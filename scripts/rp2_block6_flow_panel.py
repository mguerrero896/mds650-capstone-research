"""Block 6 - Gate 5: rebuild B2 as microstructure, not a five-minute count.

For every origin in the Block 4 panel this reads the raw option tape inside two windows
before the point-in-time cutoff and produces Greeks-weighted signed flow, activity split by
option type, moneyness and tenor, burstiness and Hawkes intensity, concentration and
entropy, and trade-to-quote impact.

Architecture note: every per-trade quantity is computed **once per session** and turned
into a prefix sum, so a window feature is one subtraction regardless of how many trades the
window contains.  The obvious per-origin implementation is O(origins x window) and is far
too slow at 1.4 billion tape rows; only the concentration statistics, which are not
prefix-summable, are evaluated on the (short) five-minute slice.

Direction comes from the tape's own per-trade side tag (``ask_side`` = buyer initiated,
``bid_side`` = seller initiated).  The provider's ``ask_vol``/``bid_vol``/``multi_vol``
columns are cumulative per contract, not per trade, and are deliberately unused.

Point-in-time rule: only rows with ``created_at <= origin - 120 s`` are visible.
``created_at`` is the operational record-creation stamp, registered as a *proxy* for
availability rather than as proven publication (docs/provider_timing_pit_contract_v22.md).
Bounding visibility with it is conservative; reading it as provider behaviour is not.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final
from zoneinfo import ZoneInfo

import numpy as np
import numpy.typing as npt
import polars as pl

from mds650.b1v3_confirmation import canonical_sha256
from mds650.rp2.bars import MARKET_TZ, SESSION_OPEN_MINUTE, build_session_grid, load_bar_sources
from mds650.rp2.flow import (
    CONTRACT_MULTIPLIER,
    DECAY_SECONDS,
    black_scholes_greeks,
    decay_intensity_at,
    herfindahl,
    shannon_entropy,
)
from mds650.rp2.option_clock import (
    OptionClocks,
    expiry_close_timestamps,
    time_to_expiry_years,
)
from mds650.rp2.panel import panel_paths

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "artifacts" / "rp2_block6_flow"
INVENTORY = ROOT / "artifacts" / "rp2_block1_partition" / "inventory.jsonl"
CUTOFF_SECONDS = 120
WINDOWS: tuple[tuple[str, int], ...] = (("5m", 300), ("30m", 1800))
#: Window used for the per-origin *counters* the scorecard sums. It matches the origin
#: spacing so the windows tile the session and no trade is counted twice.
COUNTING_WINDOW_SECONDS: Final = 300


def counting_bounds(
    created: npt.NDArray[np.int64], *, cutoff_us: int, visible: int, first: bool = False
) -> tuple[int, int]:
    """The half-open slice of one origin's counting window.

    Both edges use `side="right"`, so a trade whose record was created exactly on a
    five-minute boundary belongs to the earlier window only. Closed at both ends, adjacent
    windows share their edge and a trade sitting on it is counted twice.

    The first origin's bucket reaches back to the start of the tape rather than five
    minutes. Its own thirty-minute features already see everything visible since the open,
    so a five-minute first bucket would leave the trades of roughly the first twenty-three
    minutes able to move the fitted features while never entering the count of them.
    """

    if first:
        return 0, max(visible, 0)
    low = int(
        np.searchsorted(created, cutoff_us - COUNTING_WINDOW_SECONDS * 1_000_000, side="right")
    )
    return low, max(visible, low)


def window_count(flags: npt.NDArray[np.bool_], low: int, high: int) -> int:
    """How many flagged trades fall inside one origin's counting window."""

    if high <= low:
        return 0
    return int(np.count_nonzero(flags[low:high]))
#: Concentration statistics are not prefix-summable; they are computed on this window only.
CONCENTRATION_WINDOW = "5m"
CALENDAR_YEAR = 365.0
NY = ZoneInfo(MARKET_TZ)
OTM_LOG_MONEYNESS = 0.05
#: A session with fewer prints than this is too thin to build microstructure from. It
#: is a sparse session, not a provider failure, and the artifact says which.
MINIMUM_SESSION_PRINTS = 50
#: Every per-trade quantity the window aggregator prefix-sums. Named here so a caller — a
#: test, or a future runner — can build the prefix table without reconstructing a session.
CHANNEL_NAMES: tuple[str, ...] = (
    "trades",
    "size",
    "premium",
    "vega_flow",
    "gamma_flow",
    "delta_flow",
    "vega_flow_abs",
    "vega_flow_call",
    "vega_flow_put",
    "vega_flow_short_dte",
    "vega_flow_long_dte",
    "zero_dte_premium",
    "zero_dte_signed_premium",
    "zero_dte_trades",
    "otm_premium",
    "buy_premium",
    "sell_premium",
    "passive_premium",
    "sweep_premium",
    "multileg_size",
    "multileg_premium",
    "d_iv_sum",
    "d_mid_sum",
    "d_spread_sum",
    "has_previous",
    "age_sum",
    "latency_sum",
    "latency_over_60s",
)
SHORT_DTE_DAYS = 7.0
LONG_DTE_DAYS = 30.0
#: Exact tenors in years, so the DTE buckets compare like with like against the clock.
SHORT_DTE_YEARS = SHORT_DTE_DAYS / CALENDAR_YEAR
LONG_DTE_YEARS = LONG_DTE_DAYS / CALENDAR_YEAR
TAPE_COLUMNS = (
    "underlying_symbol",
    # Both clocks. `executed_at` is read for the latency features and must be declared
    # here: the reader projects exactly this tuple, so a column used but not listed makes
    # the block fail on its first file rather than silently degrade.
    "created_at",
    "executed_at",
    "nbbo_bid",
    "nbbo_ask",
    "size",
    "premium",
    "implied_volatility",
    "expiry",
    "strike",
    "option_type",
    "tags",
    "report_flags",
    "multi_vol",
)

type FloatArray = npt.NDArray[np.float64]


def load_inventory() -> dict[tuple[str, str], list[str]]:
    index: dict[tuple[str, str], list[str]] = {}
    with INVENTORY.open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            index.setdefault((row["session_date"], row["asset"]), []).append(row["path"])
    return index


def _read_tape(paths: Sequence[str], asset: str) -> pl.DataFrame | None:
    """The session's tape, or ``None`` when the provider's files could not be read.

    A file that will not open is the provider failure this block reports. Letting it raise
    would abort the whole rebuild over one bad file and, worse, would mean the published
    failure count could only ever be zero.

    A file that opens and holds nothing for this asset returns an **empty frame**, not
    ``None``: nobody traded is a fact about the market and must not be counted as the
    provider being broken.
    """

    try:
        frames = [
            pl.read_parquet(path, columns=list(TAPE_COLUMNS)).filter(
                pl.col("underlying_symbol") == asset
            )
            for path in paths
        ]
    except pl.exceptions.ColumnNotFoundError:
        # A partition missing a required column is a producer or schema regression, not an
        # acquisition gap. Recording it as a provider failure would hide a broken tape
        # behind ordinary coverage accounting and let the rebuild finish on partial data.
        raise
    except (OSError, pl.exceptions.ComputeError, pl.exceptions.NoDataError):
        return None
    if not frames:
        return None
    tape = pl.concat(frames, how="vertical").filter(
        (pl.col("size") > 0)
        & pl.col("strike").is_not_null()
        & pl.col("implied_volatility").is_between(0.01, 5.0)
    )
    return tape.sort("created_at")


def _in_session(
    tape: pl.DataFrame, session: str, closes: FloatArray, opens: FloatArray
) -> pl.DataFrame:
    """Keep only prints the session can price from a bar that had already closed.

    The Full Tape carries out-of-session executions (see docs/pit_field_classification.md).
    Clamping those to the first or last minute prices a pre-open trade at the open and a
    post-close trade at the close, and every Greeks-weighted total then carries a number
    that was never a market price. A minute the grid never observed is NaN, which would
    poison the prefix sums outright.

    Bars are labelled by their **start**, so ``closes[m]`` is the price at the end of minute
    ``m`` — after a trade executed inside it. A trade is marked at the close of minute
    ``m - 1``, which the market had already printed. The session's opening minute has no
    completed bar before it, and its prints are the most active of the day; dropping them
    would take trades, premium, direction, 0DTE share, latency and concentration out of the
    thirty-minute window of every early origin. They are marked at ``opens[0]`` instead,
    the session's first print, which is the earliest price that exists.
    """

    open_us = int(
        np.datetime64(
            (
                datetime.fromisoformat(session).replace(tzinfo=NY)
                + timedelta(minutes=SESSION_OPEN_MINUTE)
            )
            .astimezone(UTC)
            .replace(tzinfo=None),
            "us",
        ).astype(np.int64)
    )
    executed = tape["executed_at"].dt.replace_time_zone(None).cast(pl.Int64).to_numpy()
    minute = (executed - open_us) // 60_000_000
    inside = (minute >= 0) & (minute < closes.size)
    priced = np.zeros(tape.height, dtype=bool)
    marked = mark_price(minute[inside], closes, opens)
    priced[inside] = np.isfinite(marked) & (marked > 0.0)
    return tape.filter(pl.Series(priced))


def mark_price(minute: npt.NDArray[np.int64], closes: FloatArray, opens: FloatArray) -> FloatArray:
    """The price a trade in each minute may be marked at without reading its own future.

    The close of the preceding minute, which the market had already printed; the session's
    opening print for the opening minute, which has nothing before it.
    """

    opening = float(opens[0]) if opens.size else float("nan")
    return np.where(minute > 0, closes[np.maximum(minute - 1, 0)], opening)


def _prefix(values: FloatArray) -> FloatArray:
    out = np.zeros(values.size + 1, dtype=np.float64)
    np.cumsum(values, out=out[1:])
    return out


def _multileg_size(
    keys: npt.NDArray[np.int64], multi_vol: FloatArray, size: FloatArray
) -> FloatArray:
    """Size on each print that belonged to a multi-leg order.

    The tape reports ``multi_vol`` as a running per-contract total, so the multi-leg size of
    a single print is the increase in that total since the contract's previous print.  The
    first print of a contract inside the window has no predecessor and its running total may
    already carry earlier trades, so it contributes zero rather than its whole accumulated
    history.
    """

    order = np.lexsort((np.arange(keys.size), keys))
    sorted_keys, sorted_multi = keys[order], multi_vol[order]
    same = np.zeros(keys.size, dtype=bool)
    same[1:] = sorted_keys[1:] == sorted_keys[:-1]
    increase = np.zeros(keys.size, dtype=np.float64)
    increase[1:] = np.where(same[1:], sorted_multi[1:] - sorted_multi[:-1], 0.0)
    inverse = np.empty(keys.size, dtype=np.int64)
    inverse[order] = np.arange(keys.size)
    return np.clip(increase[inverse], 0.0, size)


def _previous_trade_deltas(
    keys: npt.NDArray[np.int64], iv: FloatArray, mid: FloatArray, spread: FloatArray
) -> tuple[FloatArray, FloatArray, FloatArray, FloatArray]:
    """Per-trade change versus the previous trade in the *same* contract.

    Returns ``(d_iv, d_mid_rel, d_spread, has_predecessor)`` in original tape order, so the
    caller can prefix-sum them and recover window means.
    """

    order = np.lexsort((np.arange(keys.size), keys))
    sorted_keys = keys[order]
    same = np.zeros(keys.size, dtype=bool)
    same[1:] = sorted_keys[1:] == sorted_keys[:-1]
    d_iv = np.zeros(keys.size, dtype=np.float64)
    d_mid = np.zeros(keys.size, dtype=np.float64)
    d_spread = np.zeros(keys.size, dtype=np.float64)
    iv_s, mid_s, spread_s = iv[order], mid[order], spread[order]
    d_iv[1:] = np.where(same[1:], iv_s[1:] - iv_s[:-1], 0.0)
    d_mid[1:] = np.where(same[1:], (mid_s[1:] - mid_s[:-1]) / np.maximum(mid_s[:-1], 1e-9), 0.0)
    d_spread[1:] = np.where(same[1:], spread_s[1:] - spread_s[:-1], 0.0)
    inverse = np.empty(keys.size, dtype=np.int64)
    inverse[order] = np.arange(keys.size)
    return (d_iv[inverse], d_mid[inverse], d_spread[inverse], same[inverse].astype(np.float64))


def build_session_flow(
    asset: str,
    session: str,
    paths: Sequence[str],
    origins: npt.NDArray[np.int64],
    closes: FloatArray,
    opens: FloatArray,
) -> tuple[pl.DataFrame | None, str]:
    """Microstructure features at every origin of one session-asset, plus why not.

    The outcome is named. A tape that could not be read is a provider failure; a tape that
    was read and held almost nothing is a sparse session, which is a fact about the market.
    Returning ``None`` for both made the published failure count measure neither.
    """

    tape = _read_tape(paths, asset)
    if tape is None:
        return None, "provider_failure"
    tape = _in_session(tape, session, closes, opens)
    if tape.height < MINIMUM_SESSION_PRINTS:
        return None, "sparse_tape"
    # Two clocks travel together. `executed_at` is when the trade happened at the
    # exchange; `created_at` is the record-creation stamp, a registered proxy for
    # availability rather than a proven publication time. Windows are
    # selected on availability, because that is what a forecaster could actually see, but
    # the exchange clock is retained so the latency between them is a feature rather than
    # an unmeasured assumption.
    created = tape["created_at"].dt.replace_time_zone(None).cast(pl.Int64).to_numpy()
    executed = tape["executed_at"].dt.replace_time_zone(None).cast(pl.Int64).to_numpy()
    clocks = OptionClocks(executed_us=executed, created_us=created)
    latency_seconds = clocks.latency_seconds
    strike = tape["strike"].cast(pl.Float64).to_numpy().astype(np.float64)
    expiry = tape["expiry"].cast(pl.Date).to_numpy()
    expiry_day = expiry.astype("datetime64[D]").astype(np.int64)
    # Exact time to the expiry close, measured from each trade's own execution stamp. The
    # producer floored this at one day, which priced a contract with four hours left as if
    # it had twenty-four and collided 0DTE with 1DTE in the contract key below.
    expiry_close_us = expiry_close_timestamps(expiry, MARKET_TZ)
    tenor_years = time_to_expiry_years(expiry_close_us, executed)
    is_zero_dte = expiry == np.datetime64(session, "D")
    iv = tape["implied_volatility"].cast(pl.Float64).to_numpy().astype(np.float64)
    size = tape["size"].cast(pl.Float64).to_numpy().astype(np.float64)
    premium = tape["premium"].cast(pl.Float64).to_numpy().astype(np.float64)
    bid = tape["nbbo_bid"].cast(pl.Float64).to_numpy().astype(np.float64)
    ask = tape["nbbo_ask"].cast(pl.Float64).to_numpy().astype(np.float64)
    mid = 0.5 * (bid + ask)
    relative_spread = (ask - bid) / np.maximum(mid, 1e-9)
    is_call = (tape["option_type"] == "call").to_numpy()
    tags = tape["tags"].cast(pl.Utf8).fill_null("")
    direction = np.where(
        tags.str.contains("ask_side").to_numpy(),
        1.0,
        np.where(tags.str.contains("bid_side").to_numpy(), -1.0, 0.0),
    )
    is_sweep = tape["report_flags"].cast(pl.Utf8).fill_null("").str.contains("sweep").to_numpy()
    keys = (
        expiry_day * 20_000_000
        + np.round(strike * 1000.0).astype(np.int64) * 2
        + is_call.astype(np.int64)
    )
    # A leg of a spread carries a side tag describing how that leg crossed the NBBO, not
    # what the trader was expressing: the short leg of a call vertical prints `bid_side`
    # while the order as a whole is bullish.  Reading direction off it manufactures signed
    # flow out of a neutral structure, so multi-leg prints are unsigned here.  They are not
    # discarded - they still count as volume, and their share is a feature of its own.
    multileg_size = _multileg_size(keys, tape["multi_vol"].cast(pl.Float64).to_numpy(), size)
    is_multileg = multileg_size > 0.0
    direction = np.where(is_multileg, 0.0, direction)

    # Spot at the trade's own session minute, so Greeks use the underlying price then
    # prevailing.  The minute is measured from the real 09:30 New York open, not from the
    # first tape row, which may be a pre-open print.
    session_open = datetime.fromisoformat(session).replace(tzinfo=NY) + timedelta(
        minutes=SESSION_OPEN_MINUTE
    )
    open_us = int(
        np.datetime64(session_open.astimezone(UTC).replace(tzinfo=None), "us").astype(np.int64)
    )
    # The exchange clock, not the availability clock: a batched print must be priced at the
    # underlying level when it happened, not when the provider got round to publishing it.
    # Out-of-session executions were removed above, so no clamp is needed and none is used:
    # a clamp here would silently price a pre-open trade at the open.
    #
    # The last *completed* bar, because bars are labelled by their start: `closes[m]` is the
    # price at the end of minute m, which for a trade inside minute m lies in that trade's
    # own future. This was never a violation of the forecast's point-in-time rule — the
    # whole window sits before the origin either way — but it mistimed the exposure of every
    # Greeks-weighted total by up to sixty seconds.
    minute_of_trade = ((executed - open_us) // 60_000_000).astype(np.int64)
    spot = mark_price(minute_of_trade, closes, opens)
    greeks = black_scholes_greeks(spot, strike, tenor_years, iv, is_call)
    weight = size * CONTRACT_MULTIPLIER * direction
    # Interarrivals and intensity are economics, so they run on the exchange clock too. On
    # the availability clock a provider flushing a backlog reads as a burst of trading.
    seconds = clocks.economic_seconds()
    d_iv, d_mid, d_spread, has_previous = _previous_trade_deltas(keys, iv, mid, relative_spread)
    log_moneyness = np.log(np.maximum(strike, 1e-9) / np.maximum(spot, 1e-9))

    channels: dict[str, FloatArray] = {
        "trades": np.ones(created.size, dtype=np.float64),
        "size": size,
        "premium": premium,
        "vega_flow": greeks.vega * weight,
        "gamma_flow": greeks.gamma * weight * spot**2,
        "delta_flow": greeks.delta * weight * spot,
        "vega_flow_abs": np.abs(greeks.vega * size * CONTRACT_MULTIPLIER),
        "vega_flow_call": greeks.vega * weight * is_call,
        "vega_flow_put": greeks.vega * weight * (~is_call),
        "vega_flow_short_dte": greeks.vega * weight * (tenor_years <= SHORT_DTE_YEARS),
        "vega_flow_long_dte": greeks.vega * weight * (tenor_years > LONG_DTE_YEARS),
        # Same-session expiries, whose whole behaviour is that they have hours left.
        "zero_dte_premium": premium * is_zero_dte,
        "zero_dte_signed_premium": premium * direction * is_zero_dte,
        "zero_dte_trades": is_zero_dte.astype(np.float64),
        # OTM is sided. abs(log_moneyness) lumps out-of-the-money calls together with
        # IN-the-money puts at the same strike distance, which is the opposite exposure.
        "otm_premium": premium
        * np.where(
            is_call,
            log_moneyness > OTM_LOG_MONEYNESS,
            log_moneyness < -OTM_LOG_MONEYNESS,
        ),
        "buy_premium": premium * (direction > 0),
        "sell_premium": premium * (direction < 0),
        "passive_premium": premium * (direction == 0),
        "sweep_premium": premium * is_sweep,
        "multileg_size": multileg_size,
        "multileg_premium": premium * is_multileg,
        "d_iv_sum": d_iv,
        "d_mid_sum": d_mid,
        "d_spread_sum": d_spread,
        "has_previous": has_previous,
        "age_sum": created / 1e6,
        "latency_sum": latency_seconds,
        "latency_over_60s": clocks.late_arrivals.astype(np.float64),
    }
    prefixes = {name: _prefix(values) for name, values in channels.items()}
    # The widest record-creation lag in this session bounds how far a stale row can sit
    # inside a window edge, so the correction above only has to scan that band.
    max_lag_us = int(max((created - executed).max(), 0)) if created.size else 0
    assert set(prefixes) == set(CHANNEL_NAMES), "CHANNEL_NAMES is out of date"

    base = datetime.fromisoformat(session).replace(tzinfo=NY)
    cutoffs_us = np.array(
        [
            int(
                np.datetime64(
                    (
                        base + timedelta(minutes=int(SESSION_OPEN_MINUTE + minute))
                    ).astimezone(UTC).replace(tzinfo=None)
                    - timedelta(seconds=CUTOFF_SECONDS),
                    "us",
                ).astype(np.int64)
            )
            for minute in origins
        ],
        dtype=np.int64,
    )
    visible = np.searchsorted(created, cutoffs_us, side="right").astype(np.int64)
    # Decay-weighted activity, evaluated at each cutoff and at each window start, over the
    # rows visible at that instant and aged on the exchange clock. Running one recursion
    # over the whole session in execution order would let a trade the provider had not
    # published yet raise the intensity of one it had; taking the window start from an
    # earlier *origin* would leave the first origins of every session undefined, which the
    # fail-closed rule turns into dropped evaluation rows.
    epoch_us = int(executed.min())
    window_starts_us = {
        label: cutoffs_us - window_seconds * 1_000_000 for label, window_seconds in WINDOWS
    }
    evaluation_us = np.concatenate([cutoffs_us, *window_starts_us.values()])
    order = np.argsort(evaluation_us, kind="stable")
    sorted_us = evaluation_us[order]
    sorted_intensity = decay_intensity_at(
        (sorted_us - epoch_us) / 1e6,
        seconds,
        np.searchsorted(created, sorted_us, side="right").astype(np.int64),
        baseline=0.0,
        excitation=1.0,
        decay=DECAY_SECONDS,
    )
    intensity_at = np.empty(evaluation_us.size, dtype=np.float64)
    intensity_at[order] = sorted_intensity
    intensity_now = intensity_at[: origins.size]
    intensity_before = {
        label: intensity_at[(index + 1) * origins.size : (index + 2) * origins.size]
        for index, label in enumerate(window_starts_us)
    }

    rows: list[dict[str, float]] = []
    for position, minute in enumerate(origins):
        cutoff_us = int(cutoffs_us[position])
        hi = int(visible[position])
        record: dict[str, float] = {"origin_minute": float(minute)}
        # Counted inside the five-minute window rather than since the open. Origins are
        # five minutes apart and the windows are anchored at the availability cutoff, so
        # the five-minute windows tile the session: summing these over origins counts each
        # trade at most once. A running total from the open, summed the same way, would
        # count the first trade of the day once for every origin that followed it.
        counting_lo, counting_hi = counting_bounds(
            created, cutoff_us=cutoff_us, visible=hi, first=position == 0
        )
        record["b2_pit_violations"] = float(
            np.count_nonzero(created[counting_lo:counting_hi] > cutoff_us)
        )
        record["b2_zero_dte_trades"] = float(
            window_count(is_zero_dte, counting_lo, counting_hi)
        )
        for label, window_seconds in WINDOWS:
            lo_us = cutoff_us - window_seconds * 1_000_000
            lo = int(np.searchsorted(created, lo_us, side="left"))
            # Membership in the window is an economic question, so the lower edge is the
            # exchange clock. `created >= executed` always holds, so selecting on `created`
            # can only over-include: a row with `created < lo_us` also has
            # `executed < lo_us`. The rows to remove are therefore those whose record was
            # created inside the window while the trade happened before it, and they all
            # sit within one record-creation lag of the edge.
            band = int(np.searchsorted(created, lo_us + max_lag_us, side="right"))
            stale = lo + np.flatnonzero(executed[lo : min(band, hi)] < lo_us)
            # The innovation is the rise in intensity across the window: the same measure
            # at the cutoff and at the window start, each over the rows visible at its own
            # instant, so neither can see the other's future and both are always defined.
            record.update(
                _window_record(
                    lo,
                    hi,
                    label,
                    window_seconds=window_seconds,
                    cutoff_us=cutoff_us,
                    prefixes=prefixes,
                    channels=channels,
                    stale=stale,
                    keys=keys,
                    strike=strike,
                    expiry_day=expiry_day,
                    premium=premium,
                    seconds=seconds,
                    latency=latency_seconds,
                    intensity_now=float(intensity_now[position]),
                    intensity_before=float(intensity_before[label][position]),
                )
            )
        rows.append(record)
    frame = pl.DataFrame(rows)
    return (
        frame.with_columns(
            asset=pl.lit(asset),
            session_date=pl.lit(session),
            origin_minute=pl.col("origin_minute").cast(pl.Int64),
        ),
        "measured",
    )


def _window_quantile(
    values: FloatArray, lo: int, hi: int, stale: npt.NDArray[np.int64], quantile: float
) -> float:
    """A quantile over one window's own observations, with the stale rows removed.

    The stale rows are those whose record was created inside the window while the trade
    happened before it; they are excluded from every other window statistic and are
    excluded here for the same reason.
    """

    if hi <= lo:
        return 0.0
    inside = np.ones(hi - lo, dtype=bool)
    if stale.size:
        inside[stale - lo] = False
    selected = values[lo:hi][inside]
    return float(np.quantile(selected, quantile)) if selected.size else 0.0


def _window_record(
    lo: int,
    hi: int,
    label: str,
    *,
    window_seconds: int,
    cutoff_us: int,
    prefixes: dict[str, FloatArray],
    channels: dict[str, FloatArray],
    stale: npt.NDArray[np.int64],
    keys: npt.NDArray[np.int64],
    strike: FloatArray,
    expiry_day: npt.NDArray[np.int64],
    premium: FloatArray,
    seconds: FloatArray,
    latency: FloatArray,
    intensity_now: float,
    intensity_before: float,
) -> dict[str, float]:
    prefix = f"b2_{label}_"
    empty = hi <= lo

    def total(name: str) -> float:
        raw = float(prefixes[name][hi] - prefixes[name][lo])
        return raw - float(channels[name][stale].sum()) if stale.size else raw

    trades = total("trades")
    total_premium = max(total("premium"), 1e-9)
    predecessors = max(total("has_previous"), 1.0)
    # The same economic membership the totals use. A row created inside the window but
    # executed before it is not in the window, and it must be out of the sliced statistics
    # too — otherwise the concentration, the span and the interarrivals would still treat an
    # old execution as recent activity while the trade count no longer does.
    selected = np.ones(max(hi - lo, 0), dtype=bool)
    if stale.size:
        selected[stale - lo] = False
    window = seconds[lo:hi][selected]
    empty = empty or not selected.any()
    span = float(window.max() - window.min()) if not empty else 0.0
    record: dict[str, float] = {
        f"{prefix}trades": trades,
        f"{prefix}contracts": float(np.unique(keys[lo:hi][selected]).size),
        f"{prefix}size": total("size"),
        f"{prefix}premium": total("premium"),
        f"{prefix}vega_flow": total("vega_flow"),
        f"{prefix}gamma_flow": total("gamma_flow"),
        f"{prefix}delta_flow": total("delta_flow"),
        f"{prefix}vega_flow_abs": total("vega_flow_abs"),
        f"{prefix}vega_flow_call": total("vega_flow_call"),
        f"{prefix}vega_flow_put": total("vega_flow_put"),
        f"{prefix}vega_flow_short_dte": total("vega_flow_short_dte"),
        f"{prefix}vega_flow_long_dte": total("vega_flow_long_dte"),
        f"{prefix}otm_premium_share": total("otm_premium") / total_premium,
        f"{prefix}buy_premium_share": total("buy_premium") / total_premium,
        f"{prefix}sell_premium_share": total("sell_premium") / total_premium,
        f"{prefix}passive_premium_share": total("passive_premium") / total_premium,
        f"{prefix}sweep_premium_share": total("sweep_premium") / total_premium,
        # Share of the window that was spread legs, whose side tags carry no direction.
        f"{prefix}multileg_size_share": total("multileg_size") / max(total("size"), 1e-9),
        f"{prefix}multileg_premium_share": total("multileg_premium") / total_premium,
        f"{prefix}d_iv": total("d_iv_sum") / predecessors,
        f"{prefix}d_mid_rel": total("d_mid_sum") / predecessors,
        f"{prefix}d_spread": total("d_spread_sum") / predecessors,
        f"{prefix}decay_intensity_last": intensity_now,
        f"{prefix}decay_intensity_innovation": intensity_now - intensity_before,
        # Trades per second of the window, not per second of the observed span. A window
        # holding one print — or several stamped at the same instant — has a span of zero
        # and would otherwise report positive flow as a rate of nothing.
        f"{prefix}rate_per_second": trades / window_seconds,
        f"{prefix}observed_span_s": span,
        # A mean, and now named one. It was called a median for the whole programme. A mean
        # over nothing is not zero, it is undefined, and the three per-trade averages say so.
        # A mean over no trades is not zero; it is unmeasured. Rather than leave a NaN that
        # the fail-closed mask would turn into a dropped origin, the window says so: the
        # indicator is 1 and the three per-trade averages are 0, which the model reads
        # together. This is an explicit encoding of one enumerable state, not imputation —
        # fold-local imputation of the general case is its own gate.
        f"{prefix}is_empty_window": 1.0 if empty else 0.0,
        f"{prefix}mean_age_s": (
            cutoff_us / 1e6 - total("age_sum") / trades if trades else 0.0
        ),
        # `created_at - executed_at`. The master plan names this feature
        # `mean_provider_latency_s`, and the name is kept, but it does not assert provider
        # delivery behaviour: docs/provider_timing_pit_contract_v22.md establishes
        # `created_at` as an operational record-creation proxy, not a proven publication or
        # receipt time. What is measured is the lag between the exchange stamp and the
        # record stamp; using it as an availability bound is conservative, and reading it as
        # a measurement of the provider's pipe is not supported by this dataset.
        f"{prefix}mean_provider_latency_s": (
            total("latency_sum") / trades if trades else 0.0
        ),
        f"{prefix}late_arrival_share": (
            total("latency_over_60s") / trades if trades else 0.0
        ),
        # The tail, taken over the individual lags inside this window. A quantile of
        # per-window means, computed later, would be a statistic about typical windows:
        # averaging first suppresses exactly the slow records the tail is asked about.
        f"{prefix}p95_provider_latency_s": _window_quantile(latency, lo, hi, stale, 0.95),
        f"{prefix}zero_dte_premium_share": total("zero_dte_premium") / total_premium,
        f"{prefix}zero_dte_signed_premium": total("zero_dte_signed_premium"),
        f"{prefix}zero_dte_trade_share": total("zero_dte_trades") / max(trades, 1.0),
    }
    if empty:
        # Concentration over no trades is not a number, but leaving it out puts a null into
        # four registered features and the fail-closed mask then removes the origin from
        # every contrast — for the sake of a window in which nobody traded. They are zero
        # here, and `is_empty_window` is what tells a model those zeros are an absence. The
        # intensity is not zero: earlier visible trades still support it.
        if label == CONCENTRATION_WINDOW:
            record.update(
                {
                    f"{prefix}strike_hhi": 0.0,
                    f"{prefix}expiry_hhi": 0.0,
                    f"{prefix}contract_entropy": 0.0,
                    f"{prefix}interarrival_cv": 0.0,
                }
            )
        return record
    if label == CONCENTRATION_WINDOW:
        window_premium = premium[lo:hi][selected]
        record[f"{prefix}strike_hhi"] = herfindahl(
            np.bincount(
                np.unique(strike[lo:hi][selected], return_inverse=True)[1],
                weights=window_premium,
            ).astype(np.float64)
        )
        record[f"{prefix}expiry_hhi"] = herfindahl(
            np.bincount(
                np.unique(expiry_day[lo:hi][selected], return_inverse=True)[1],
                weights=window_premium,
            ).astype(np.float64)
        )
        record[f"{prefix}contract_entropy"] = shannon_entropy(
            np.bincount(
                np.unique(keys[lo:hi][selected], return_inverse=True)[1],
                weights=window_premium,
            ).astype(np.float64)
        )
        gaps = np.diff(np.sort(window))
        mean_gap = float(np.mean(gaps)) if gaps.size else float("nan")
        record[f"{prefix}interarrival_cv"] = (
            float(np.std(gaps) / mean_gap) if gaps.size and mean_gap > 0.0 else float("nan")
        )
    return record


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=Path("D:/MDS650"))
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    # A rebuild reads its own B0 panel, not the previous run's.
    parser.add_argument("--panel-root", type=Path, default=None)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--limit-sessions", type=int, default=0)
    args = parser.parse_args(argv)

    panel = pl.read_parquet(panel_paths(args.panel_root)["b0"])
    inventory = load_inventory()
    bars = load_bar_sources(args.data_root)
    grids: dict[tuple[str, str], tuple[FloatArray, FloatArray]] = {}
    for (asset, session_date), group in bars.sort(["asset", "session_date", "minute"]).group_by(
        ["asset", "session_date"], maintain_order=True
    ):
        grid = build_session_grid(group, session=session_date)
        grids[(str(asset), str(session_date))] = (grid.close, grid.open)

    jobs: list[
        tuple[str, str, list[str], npt.NDArray[np.int64], FloatArray, FloatArray]
    ] = []
    # A session-asset the B0 panel carries but the tape inventory or the bar grid does not
    # is an incomplete acquisition. Skipping it silently made every coverage number in this
    # artifact describe only the part of the study that happened to be complete.
    missing_tape_inventory: list[dict[str, str]] = []
    missing_bar_grid: list[dict[str, str]] = []
    for (asset, session_date), group in panel.sort(
        ["asset", "session_date", "origin_minute"]
    ).group_by(["asset", "session_date"], maintain_order=True):
        paths = inventory.get((str(session_date), str(asset))) or inventory.get(
            (str(session_date), "__ALL__")
        )
        grid_pair = grids.get((str(asset), str(session_date)))
        if paths is None:
            missing_tape_inventory.append({"asset": str(asset), "session_date": str(session_date)})
            continue
        if grid_pair is None or grid_pair[0].size == 0:
            missing_bar_grid.append({"asset": str(asset), "session_date": str(session_date)})
            continue
        closes, opens = grid_pair
        # Origins come from the B0 panel, which is built on each session's real length.
        # A holiday now yields an empty grid and an early close a 210-minute one, so an
        # origin is only usable if the grid actually holds that minute — indexing past it
        # would read whatever `closes[-1]` happens to be, silently.
        origin_minutes = group["origin_minute"].to_numpy().astype(np.int64)
        inside = origin_minutes < closes.size
        if not inside.any():
            continue
        jobs.append(
            (
                str(asset),
                str(session_date),
                paths,
                origin_minutes[inside],
                closes,
                opens,
            )
        )
    # The accounting below covers the whole B0 panel. A limited run attempts a prefix of
    # it, so both numbers are published: a document that reported only one of them would
    # describe neither the sample nor the study.
    session_assets_in_panel = len(jobs) + len(missing_tape_inventory) + len(missing_bar_grid)
    if args.limit_sessions:
        jobs = jobs[: args.limit_sessions]

    frames: list[pl.DataFrame] = []
    # A tape that could not be read is a provider failure. A tape that was read and held
    # almost nothing is a sparse session. A window in which nobody traded is a fact about
    # the market. All three would otherwise arrive downstream as "no flow", and only the
    # last is evidence about flow, so each is named separately.
    provider_failures: list[dict[str, str]] = []
    sparse_sessions: list[dict[str, str]] = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = pool.map(lambda job: build_session_flow(*job), jobs)
        for job, (result, outcome) in zip(jobs, results, strict=True):
            if result is None:
                entry = {"asset": job[0], "session_date": job[1]}
                if outcome == "provider_failure":
                    provider_failures.append(entry)
                else:
                    sparse_sessions.append(entry)
                continue
            frames.append(result)
    if not frames:
        raise SystemExit("RP2_BLOCK6_EMPTY_FLOW")
    flow = pl.concat(frames, how="diagonal")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    flow.write_parquet(args.output_dir / "b2_flow_panel.parquet")

    coverage: dict[str, object] = {}
    for column in sorted(c for c in flow.columns if c.startswith("b2_")):
        values = flow[column].cast(pl.Float64)
        finite = values.is_finite() & values.is_not_null()
        median = values.filter(finite).median()
        coverage[column] = {
            "coverage": float(finite.sum() / flow.height),
            "median": float(median) if isinstance(median, (int, float)) else float("nan"),
        }
    document: dict[str, object] = {
        "block": 6,
        "program": "docs/research_program_v2.md",
        "label": "EXPLORATORY_MECHANISM_DISCOVERY",
        "cutoff_seconds": CUTOFF_SECONDS,
        "windows_seconds": dict(WINDOWS),
        "concentration_window": CONCENTRATION_WINDOW,
        "decay_seconds": DECAY_SECONDS,
        "session_assets_requested": len(jobs),
        "session_assets_without_tape": len(provider_failures),
        "provider_failures": provider_failures,
        "minimum_session_prints": MINIMUM_SESSION_PRINTS,
        "sparse_sessions": sparse_sessions,
        "session_assets_in_b0_panel": session_assets_in_panel,
        "session_assets_attempted": len(jobs),
        "limit_sessions": int(args.limit_sessions),
        "missing_tape_inventory": missing_tape_inventory,
        "missing_bar_grid": missing_bar_grid,
        "empty_window_share_5m": float(
            (flow["b2_5m_trades"].fill_null(0.0) == 0.0).sum() / flow.height
        ),
        "empty_window_share_30m": float(
            (flow["b2_30m_trades"].fill_null(0.0) == 0.0).sum() / flow.height
        ),
        "rows": flow.height,
        "feature_count": len(coverage),
        "coverage": coverage,
    }
    document["flow_sha256"] = canonical_sha256(document)
    document["generated_at_utc"] = datetime.now(UTC).isoformat()
    (args.output_dir / "flow_coverage.json").write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({k: v for k, v in document.items() if k != "coverage"}, indent=2))
    for name, stats in coverage.items():
        assert isinstance(stats, dict)
        print(f"  {name:<34} coverage={stats['coverage']:.3f} median={stats['median']:.5g}")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
