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
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import numpy.typing as npt
import polars as pl

from mds650.b1v3_confirmation import canonical_sha256
from mds650.rp2.bars import MARKET_TZ, SESSION_OPEN_MINUTE, build_session_grid, load_bar_sources
from mds650.rp2.flow import (
    CONTRACT_MULTIPLIER,
    HAWKES_DECAY_SECONDS,
    black_scholes_greeks,
    hawkes_intensity,
    herfindahl,
    shannon_entropy,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "artifacts" / "rp2_block6_flow"
INVENTORY = ROOT / "artifacts" / "rp2_block1_partition" / "inventory.jsonl"
B0_PANEL = ROOT / "artifacts" / "rp2_block4_b0" / "b0_panel.parquet"
CUTOFF_SECONDS = 120
WINDOWS: tuple[tuple[str, int], ...] = (("5m", 300), ("30m", 1800))
#: Concentration statistics are not prefix-summable; they are computed on this window only.
CONCENTRATION_WINDOW = "5m"
CALENDAR_YEAR = 365.0
NY = ZoneInfo(MARKET_TZ)
OTM_LOG_MONEYNESS = 0.05
SHORT_DTE_DAYS = 7.0
LONG_DTE_DAYS = 30.0
TAPE_COLUMNS = (
    "underlying_symbol", "created_at", "nbbo_bid", "nbbo_ask", "size", "premium",
    "implied_volatility", "expiry", "strike", "option_type", "tags", "report_flags",
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
    frames = [
        pl.read_parquet(path, columns=list(TAPE_COLUMNS)).filter(
            pl.col("underlying_symbol") == asset
        )
        for path in paths
    ]
    if not frames:
        return None
    tape = pl.concat(frames, how="vertical").filter(
        (pl.col("size") > 0)
        & pl.col("strike").is_not_null()
        & pl.col("implied_volatility").is_between(0.01, 5.0)
    )
    return tape.sort("created_at") if tape.height else None


def _prefix(values: FloatArray) -> FloatArray:
    out = np.zeros(values.size + 1, dtype=np.float64)
    np.cumsum(values, out=out[1:])
    return out


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
    d_mid[1:] = np.where(
        same[1:], (mid_s[1:] - mid_s[:-1]) / np.maximum(mid_s[:-1], 1e-9), 0.0
    )
    d_spread[1:] = np.where(same[1:], spread_s[1:] - spread_s[:-1], 0.0)
    inverse = np.empty(keys.size, dtype=np.int64)
    inverse[order] = np.arange(keys.size)
    return (
        d_iv[inverse], d_mid[inverse], d_spread[inverse], same[inverse].astype(np.float64)
    )


def build_session_flow(
    asset: str, session: str, paths: Sequence[str], origins: npt.NDArray[np.int64],
    closes: FloatArray
) -> pl.DataFrame | None:
    """Microstructure features at every origin of one session-asset."""

    tape = _read_tape(paths, asset)
    if tape is None or tape.height < 50:
        return None
    created = tape["created_at"].dt.replace_time_zone(None).cast(pl.Int64).to_numpy()
    strike = tape["strike"].cast(pl.Float64).to_numpy().astype(np.float64)
    expiry = tape["expiry"].cast(pl.Date).to_numpy()
    tenor_days = np.maximum(
        (expiry - np.datetime64(session, "D")).astype("timedelta64[D]").astype(np.float64), 1.0
    )
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
        tags.str.contains("ask_side").to_numpy(), 1.0,
        np.where(tags.str.contains("bid_side").to_numpy(), -1.0, 0.0),
    )
    is_sweep = tape["report_flags"].cast(pl.Utf8).fill_null("").str.contains("sweep").to_numpy()
    keys = (
        np.round(tenor_days).astype(np.int64) * 20_000_000
        + np.round(strike * 1000.0).astype(np.int64) * 2
        + is_call.astype(np.int64)
    )

    # Spot at the trade's own session minute, so Greeks use the underlying price then
    # prevailing.  The minute is measured from the real 09:30 New York open, not from the
    # first tape row, which may be a pre-open print.
    session_open = datetime.fromisoformat(session).replace(tzinfo=NY) + timedelta(
        minutes=SESSION_OPEN_MINUTE
    )
    open_us = int(
        np.datetime64(session_open.astimezone(UTC).replace(tzinfo=None), "us").astype(np.int64)
    )
    minute_of_trade = np.clip(
        ((created - open_us) // 60_000_000).astype(np.int64), 0, closes.size - 1
    )
    spot = closes[minute_of_trade]
    greeks = black_scholes_greeks(spot, strike, tenor_days / CALENDAR_YEAR, iv, is_call)
    weight = size * CONTRACT_MULTIPLIER * direction
    seconds = (created - created[0]) / 1e6
    intensity = hawkes_intensity(seconds, baseline=0.0, excitation=1.0,
                                 decay=HAWKES_DECAY_SECONDS)
    d_iv, d_mid, d_spread, has_previous = _previous_trade_deltas(
        keys, iv, mid, relative_spread
    )
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
        "vega_flow_short_dte": greeks.vega * weight * (tenor_days <= SHORT_DTE_DAYS),
        "vega_flow_long_dte": greeks.vega * weight * (tenor_days > LONG_DTE_DAYS),
        "otm_premium": premium * (np.abs(log_moneyness) > OTM_LOG_MONEYNESS),
        "buy_premium": premium * (direction > 0),
        "sell_premium": premium * (direction < 0),
        "passive_premium": premium * (direction == 0),
        "sweep_premium": premium * is_sweep,
        "d_iv_sum": d_iv,
        "d_mid_sum": d_mid,
        "d_spread_sum": d_spread,
        "has_previous": has_previous,
        "age_sum": created / 1e6,
    }
    prefixes = {name: _prefix(values) for name, values in channels.items()}

    base = datetime.fromisoformat(session).replace(tzinfo=NY)
    rows: list[dict[str, float]] = []
    for minute in origins:
        origin_time = base + timedelta(minutes=int(SESSION_OPEN_MINUTE + minute))
        cutoff = origin_time.astimezone(UTC).replace(tzinfo=None) - timedelta(
            seconds=CUTOFF_SECONDS
        )
        cutoff_us = int(np.datetime64(cutoff, "us").astype(np.int64))
        hi = int(np.searchsorted(created, cutoff_us, side="right"))
        record: dict[str, float] = {"origin_minute": float(minute)}
        for label, window_seconds in WINDOWS:
            lo = int(
                np.searchsorted(created, cutoff_us - window_seconds * 1_000_000, side="left")
            )
            record.update(
                _window_record(
                    lo, hi, label, cutoff_us=cutoff_us, prefixes=prefixes, keys=keys,
                    strike=strike, tenor_days=tenor_days, premium=premium,
                    intensity=intensity, seconds=seconds,
                )
            )
        rows.append(record)
    frame = pl.DataFrame(rows)
    return frame.with_columns(
        asset=pl.lit(asset), session_date=pl.lit(session),
        origin_minute=pl.col("origin_minute").cast(pl.Int64),
    )


def _window_record(
    lo: int, hi: int, label: str, *, cutoff_us: int, prefixes: dict[str, FloatArray],
    keys: npt.NDArray[np.int64], strike: FloatArray, tenor_days: FloatArray,
    premium: FloatArray, intensity: FloatArray, seconds: FloatArray,
) -> dict[str, float]:
    prefix = f"b2_{label}_"
    if hi <= lo:
        return {f"{prefix}trades": 0.0, f"{prefix}premium": 0.0}

    def total(name: str) -> float:
        return float(prefixes[name][hi] - prefixes[name][lo])

    trades = total("trades")
    total_premium = max(total("premium"), 1e-9)
    predecessors = max(total("has_previous"), 1.0)
    span = float(seconds[hi - 1] - seconds[lo])
    record: dict[str, float] = {
        f"{prefix}trades": trades,
        f"{prefix}contracts": float(np.unique(keys[lo:hi]).size),
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
        f"{prefix}d_iv": total("d_iv_sum") / predecessors,
        f"{prefix}d_mid_rel": total("d_mid_sum") / predecessors,
        f"{prefix}d_spread": total("d_spread_sum") / predecessors,
        f"{prefix}hawkes_last": float(intensity[hi - 1]),
        f"{prefix}hawkes_innovation": float(
            intensity[hi - 1] - np.mean(intensity[lo:hi])
        ),
        f"{prefix}rate_per_second": trades / span if span > 0.0 else float("nan"),
        f"{prefix}median_age_s": cutoff_us / 1e6 - total("age_sum") / max(trades, 1.0),
    }
    if label == CONCENTRATION_WINDOW:
        window_premium = premium[lo:hi]
        record[f"{prefix}strike_hhi"] = herfindahl(
            np.bincount(np.unique(strike[lo:hi], return_inverse=True)[1],
                        weights=window_premium).astype(np.float64)
        )
        record[f"{prefix}expiry_hhi"] = herfindahl(
            np.bincount(np.unique(tenor_days[lo:hi], return_inverse=True)[1],
                        weights=window_premium).astype(np.float64)
        )
        record[f"{prefix}contract_entropy"] = shannon_entropy(
            np.bincount(np.unique(keys[lo:hi], return_inverse=True)[1],
                        weights=window_premium).astype(np.float64)
        )
        gaps = np.diff(seconds[lo:hi])
        mean_gap = float(np.mean(gaps)) if gaps.size else float("nan")
        record[f"{prefix}interarrival_cv"] = (
            float(np.std(gaps) / mean_gap) if gaps.size and mean_gap > 0.0 else float("nan")
        )
    return record


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=Path("D:/MDS650"))
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--limit-sessions", type=int, default=0)
    args = parser.parse_args(argv)

    panel = pl.read_parquet(B0_PANEL)
    inventory = load_inventory()
    bars = load_bar_sources(args.data_root)
    grids: dict[tuple[str, str], FloatArray] = {}
    for (asset, session_date), group in bars.sort(["asset", "session_date", "minute"]).group_by(
        ["asset", "session_date"], maintain_order=True
    ):
        grids[(str(asset), str(session_date))] = build_session_grid(group).close

    jobs: list[tuple[str, str, list[str], npt.NDArray[np.int64], FloatArray]] = []
    for (asset, session_date), group in panel.sort(
        ["asset", "session_date", "origin_minute"]
    ).group_by(["asset", "session_date"], maintain_order=True):
        paths = inventory.get((str(session_date), str(asset))) or inventory.get(
            (str(session_date), "__ALL__")
        )
        closes = grids.get((str(asset), str(session_date)))
        if paths is None or closes is None:
            continue
        jobs.append(
            (str(asset), str(session_date), paths,
             group["origin_minute"].to_numpy().astype(np.int64), closes)
        )
    if args.limit_sessions:
        jobs = jobs[: args.limit_sessions]

    frames: list[pl.DataFrame] = []
    failures = 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for result in pool.map(lambda job: build_session_flow(*job), jobs):
            if result is None:
                failures += 1
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
        "hawkes_decay_seconds": HAWKES_DECAY_SECONDS,
        "session_assets_requested": len(jobs),
        "session_assets_without_tape": failures,
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
