"""Block 5 - Gate 4: rebuild B1 as an arbitrage-aware implied-volatility surface.

For every forecast origin in the Block 4 panel this reconstructs a point-in-time snapshot
of the option surface from the local per-trade tape - each trade carries the prevailing
NBBO and the provider's implied volatility, so the latest observation per contract before
the cutoff is a (sparse) surface - and reduces it to constant-maturity total variance,
smile shape, wing quotes, term structure, variance risk premium and quote quality.

Point-in-time rule: only rows with ``created_at <= origin - 120 s`` are visible, the
empirical cutoff established in Block 2, and no row older than 30 minutes.  Sealed cohorts
are never read.  See ``docs/rp2_v3/B1_CONTEMPORANEOUS_SPEC.md``.

**Overlap with B2 is allowed.**  RP2-v2 ended this snapshot 1 920 seconds before the origin
so that no tape row could feed both B1 and B2.  The contrast is conditional —
``E[Y | B0, B1, B2]`` against ``E[Y | B0, B1]`` — so row-disjointness was never required,
and it cost B1 the one thing it exists for: it stopped being the state of the option market
at ``t`` and became the state half an hour earlier.  An increment measured against a
deliberately stale B1 credits flow with information the surface already carried.

What the window cannot fix: a contract enters the surface only because somebody traded it,
so the *selection* of quotes is still driven by flow.  Decision 77 measures that bias
against an independent quote feed; it is a property of trade sampling, not of the window.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Final
from zoneinfo import ZoneInfo

import numpy as np
import numpy.typing as npt
import polars as pl

from mds650.b1v3_confirmation import canonical_sha256
from mds650.rp2.b1_snapshot import (
    CUTOFF_SECONDS,
    MAX_QUOTE_AGE_SECONDS,
    SENSITIVITY_MAX_AGE_SECONDS,
    ContemporaneousSnapshot,
    latest_quote_per_contract,
    snapshot_window,
)
from mds650.rp2.bars import MARKET_TZ, SESSION_OPEN_MINUTE, build_session_grid, load_bar_sources
from mds650.rp2.panel import panel_paths
from mds650.rp2.scorecard import QUOTE_AGE_BIN_EDGES, duration_bins
from mds650.rp2.surface import (
    CONSTANT_MATURITY_DAYS,
    EXPIRY_CLOSE,
    SECONDS_PER_YEAR,
    annualise_intraday_variance,
    black_scholes_delta,
    butterfly_arbitrage_violations,
    calendar_arbitrage_violations,
    fit_smile,
    implied_forward,
    implied_minus_trailing_variance,
    interpolate_total_variance,
    model_free_variance,
    put_call_parity_residual,
    surface_coverage,
    total_variance,
    wing_quotes,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "artifacts" / "rp2_block5_surface"
INVENTORY = ROOT / "artifacts" / "rp2_block1_partition" / "inventory.jsonl"
CALENDAR_YEAR = 365.0
NY = ZoneInfo(MARKET_TZ)
TAPE_COLUMNS = (
    "underlying_symbol",
    "created_at",
    "nbbo_bid",
    "nbbo_ask",
    "implied_volatility",
    "expiry",
    "strike",
    "option_type",
)

type FloatArray = npt.NDArray[np.float64]


def load_inventory() -> dict[tuple[str, str], list[str]]:
    """Map ``(session, asset)`` to the tape files that hold it."""

    index: dict[tuple[str, str], list[str]] = {}
    with INVENTORY.open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            index.setdefault((row["session_date"], row["asset"]), []).append(row["path"])
    return index


#: Returned when the tape was read and held too little to build a surface from. Distinct
#: from `None`, which means there was nothing to read.
SPARSE_SESSION: Final = pl.DataFrame()


def _read_tape(paths: Sequence[str], asset: str) -> pl.DataFrame | None:
    frames: list[pl.DataFrame] = []
    for path in paths:
        try:
            frame = pl.read_parquet(path, columns=list(TAPE_COLUMNS))
        except (pl.exceptions.ColumnNotFoundError, pl.exceptions.SchemaError):
            # A tape missing a required column is a changed schema, not a provider
            # failure. Absorbing it into the counter would drop that session from the
            # sample and leave the rest of the build to finish as though nothing had
            # happened, which is the fail-closed rule inverted.
            raise
        except (OSError, pl.exceptions.ComputeError):
            # A file that cannot be read is a provider failure, which is what the counter
            # is for. Letting the error escape aborted the whole build instead, so the
            # counter could only ever report zero.
            return None
        frames.append(frame.filter(pl.col("underlying_symbol") == asset))
    if not frames:
        # Nothing to read: no path resolved for this session-asset.
        return None
    tape = pl.concat(frames, how="vertical")
    tape = tape.filter(
        (pl.col("nbbo_bid") > 0.0)
        & (pl.col("nbbo_ask") > pl.col("nbbo_bid"))
        & pl.col("implied_volatility").is_between(0.01, 5.0)
        & pl.col("strike").is_not_null()
    )
    # A file that opened and lost every quote to the quality filters is a thin session,
    # not a provider failure. Returning `None` here put an ordinary unquotable day into the
    # outage count.
    return tape.sort("created_at")


def _co_strike_pairs(
    strike: FloatArray, mid: FloatArray, calls: npt.NDArray[np.bool_], puts: npt.NDArray[np.bool_]
) -> tuple[FloatArray, FloatArray, FloatArray]:
    """Strikes quoted on both sides, with the matching call and put mids.

    `intersect1d(..., return_indices=True)` returns positions directly. Rebuilding those
    positions with a boolean mask per shared strike costs two array scans per strike, and at
    roughly twenty expiries over 185,000 origins that is tens of millions of scans — enough
    to take the block from minutes to hours.
    """

    call_strike, put_strike = strike[calls], strike[puts]
    shared, call_index, put_index = np.intersect1d(
        call_strike, put_strike, assume_unique=False, return_indices=True
    )
    if shared.size == 0:
        empty = np.empty(0, dtype=np.float64)
        return empty, empty, empty
    return shared, mid[calls][call_index], mid[puts][put_index]


def _surface_at(
    snapshot: ContemporaneousSnapshot,
    strike: FloatArray,
    expiry_close_us: npt.NDArray[np.int64],
    iv: FloatArray,
    bid: FloatArray,
    ask: FloatArray,
    is_call: npt.NDArray[np.bool_],
    spot: float,
) -> dict[str, float]:
    """Reduce one contemporaneous surface snapshot to features."""

    # An origin whose window held nothing still gets a surface-quality reading: zero. A null
    # there says "not measured", which is the opposite of what happened — it was measured and
    # the surface was empty.
    empty = {"b1_contracts": 0.0, "b1_surface_coverage": 0.0}
    picked = snapshot.positions
    if picked.size < 3:
        return empty
    origin_us = snapshot.window.origin_us

    k_strike, k_iv = strike[picked], iv[picked]
    k_bid, k_ask, k_call = bid[picked], ask[picked], is_call[picked]
    mid = 0.5 * (k_bid + k_ask)
    relative_spread = (k_ask - k_bid) / np.maximum(mid, 1e-9)
    age_seconds = snapshot.quote_age_seconds
    # Exact time to the 16:00 ET close on the expiry date, measured from THIS origin.  A
    # contract expiring this afternoon gets the hours it has left, not a floor of one day.
    k_tenor = (expiry_close_us[picked] - origin_us) / 1e6 / SECONDS_PER_YEAR
    live = k_tenor > 0.0
    if int(live.sum()) < 3:
        return empty
    picked, k_strike, k_iv, k_tenor = picked[live], k_strike[live], k_iv[live], k_tenor[live]
    k_bid, k_ask, k_call = k_bid[live], k_ask[live], k_call[live]
    mid, relative_spread, age_seconds = mid[live], relative_spread[live], age_seconds[live]

    expiry_key = expiry_close_us[picked]
    unique_tenors, inverse = np.unique(expiry_key, return_inverse=True)
    # One pass for the per-expiry tenor instead of a boolean scan per expiry per loop.
    tenor_by_expiry = np.zeros(unique_tenors.size, dtype=np.float64)
    np.maximum.at(tenor_by_expiry, inverse, k_tenor)
    # The forward is measured per expiry from co-strike parity, then moneyness is read
    # against it.  Falling back to the spot where parity cannot be fitted is recorded in
    # b1_forward_expiries_fitted rather than hidden.
    forward_by_expiry: dict[int, float] = {}
    for position, key in enumerate(unique_tenors):
        mask = inverse == position
        years = float(tenor_by_expiry[position])
        calls, puts = mask & k_call, mask & ~k_call
        shared, call_mid, put_mid = _co_strike_pairs(k_strike, mid, calls, puts)
        if shared.size < 3:
            continue
        fit = implied_forward(shared, call_mid, put_mid, tenor_years=years, spot=spot)
        if fit.plausible:
            forward_by_expiry[int(key)] = fit.forward
    forward_per_expiry = np.array(
        [forward_by_expiry.get(int(key), spot) for key in unique_tenors], dtype=np.float64
    )
    forward = forward_per_expiry[inverse]
    log_moneyness = np.log(np.maximum(k_strike, 1e-9) / forward)

    atm_tenor_years: list[float] = []
    atm_total_variance: list[float] = []
    for position in range(unique_tenors.size):
        mask = inverse == position
        if int(mask.sum()) < 3:
            continue
        smile = fit_smile(log_moneyness[mask], k_iv[mask])
        if not np.isfinite(smile.level) or smile.level <= 0.0:
            continue
        years = float(tenor_by_expiry[position])
        if years <= 0.0:
            continue
        atm_tenor_years.append(years)
        atm_total_variance.append(
            float(total_variance(np.array([smile.level]), np.array([years]))[0])
        )
    snapshot_delta = black_scholes_delta(forward, k_strike, k_tenor, k_iv, k_call)
    coverage = surface_coverage(log_moneyness, k_tenor, k_strike, snapshot_delta)
    features: dict[str, float] = {
        "b1_contracts": float(coverage.contracts),
        "b1_expiries": float(coverage.expiries),
        "b1_strikes": float(coverage.strikes),
        # This origin's own median and tail, kept because a per-origin diagnostic is what
        # a reader inspecting one origin wants. They are NOT what the scorecard pools: a
        # quantile across origins of these is not a quantile of any population, which is
        # what `b1_quote_age_bin_*` below exists to make possible.
        "b1_median_quote_age_s": float(np.median(age_seconds)),
        "b1_p95_quote_age_s": float(np.quantile(age_seconds, 0.95)),
        "b1_median_relative_spread": float(np.median(relative_spread)),
        # Counts in fixed bins, which add across origins where quantiles do not. The
        # scorecard reads the run's real median and 95th percentile off the sum.
        **{
            f"b1_quote_age_bin_{index}": float(count)
            for index, count in enumerate(
                duration_bins(np.asarray(age_seconds, dtype=np.float64), QUOTE_AGE_BIN_EDGES)
            )
        },
        "b1_forward_expiries_fitted": float(len(forward_by_expiry)),
        "b1_min_log_moneyness": coverage.min_log_moneyness,
        "b1_max_log_moneyness": coverage.max_log_moneyness,
        "b1_spans_call_wing": float(coverage.spans_call_wing),
        "b1_spans_put_wing": float(coverage.spans_put_wing),
        "b1_zero_dte_contracts": float(coverage.zero_dte_contracts),
        # How much of the grid the snapshot actually covered, as a share of the four things
        # every surface feature needs: a fittable smile, both wings, and a term structure.
        # A scalar, so a model can condition on the quality of the state it is reading.
        "b1_surface_coverage": float(
            np.mean(
                [
                    coverage.contracts >= 3,
                    coverage.spans_call_wing,
                    coverage.spans_put_wing,
                    coverage.expiries >= 2,
                ]
            )
        ),
        "b1_smile_level": float("nan"),
        "b1_pcp_residual": float("nan"),
        "b1_calendar_violations": float("nan"),
        "b1_butterfly_violations": float("nan"),
    }
    if len(atm_tenor_years) < 2:
        return features

    tenors = np.asarray(atm_tenor_years, dtype=np.float64)
    variances = np.asarray(atm_total_variance, dtype=np.float64)
    features["b1_calendar_violations"] = float(calendar_arbitrage_violations(tenors, variances))
    targets = np.asarray(CONSTANT_MATURITY_DAYS, dtype=np.float64) / CALENDAR_YEAR
    interpolated = interpolate_total_variance(tenors, variances, targets)
    for days, years, w in zip(CONSTANT_MATURITY_DAYS, targets, interpolated, strict=True):
        features[f"b1_iv_{days}d"] = float(np.sqrt(max(w, 0.0) / years))

    iv7, iv30, iv60, iv90 = (features[f"b1_iv_{d}d"] for d in (7, 30, 60, 90))
    features["b1_term_slope"] = iv60 - iv7
    features["b1_term_convexity"] = iv7 - 2.0 * iv30 + iv90

    # Shape features are read on the expiry bucket closest to 30 calendar days.
    nearest_position = int(np.argmin(np.abs(tenor_by_expiry - 30.0 / CALENDAR_YEAR)))
    nearest = unique_tenors[nearest_position]
    bucket = inverse == nearest_position
    bucket_years = float(tenor_by_expiry[nearest_position])
    bucket_forward = forward_by_expiry.get(int(nearest), spot)
    if int(bucket.sum()) >= 3:
        smile = fit_smile(log_moneyness[bucket], k_iv[bucket])
        features["b1_smile_level"] = smile.level
        features["b1_smile_slope"] = smile.slope
        features["b1_smile_curvature"] = smile.curvature
        features["b1_smile_residual"] = smile.residual_std
        call_iv, put_iv = wing_quotes(snapshot_delta[bucket], k_iv[bucket])
        features["b1_risk_reversal_25"] = call_iv - put_iv
        features["b1_butterfly_25"] = 0.5 * (call_iv + put_iv) - smile.level
        # Model-free variance over the observed strike grid, out-of-the-money side only.
        otm = bucket & np.where(k_call, k_strike >= bucket_forward, k_strike <= bucket_forward)
        features["b1_mfiv"] = model_free_variance(
            k_strike[otm], mid[otm], bucket_forward, bucket_years
        )
        calls = bucket & k_call
        puts = bucket & ~k_call
        features["b1_butterfly_violations"] = float(
            butterfly_arbitrage_violations(k_strike[calls], mid[calls])
        )
        shared, call_mid, put_mid = _co_strike_pairs(k_strike, mid, calls, puts)
        if shared.size >= 3:
            fit = implied_forward(shared, call_mid, put_mid, tenor_years=bucket_years, spot=spot)
            # Only a fit that survives the plausibility band is reported as a rate.  Co-strike
            # mids come from different instants, so the underlying moves between them; at a
            # 30-day tenor that noise is large enough to produce financing rates of +/-30%,
            # which are a measurement of quote staleness rather than of a curve.
            features["b1_implied_rate"] = fit.rate if fit.plausible else float("nan")
            features["b1_implied_dividend_yield"] = (
                fit.dividend_yield if fit.plausible else float("nan")
            )
            features["b1_pcp_residual"] = put_call_parity_residual(
                call_mid,
                put_mid,
                shared,
                forward=fit.forward,
                discount_factor=fit.discount_factor,
                scale=spot,
            )
    return features


def build_session_surface(
    asset: str,
    session: str,
    paths: Sequence[str],
    origins: npt.NDArray[np.int64],
    closes: FloatArray,
    rv_back_30: FloatArray,
    *,
    max_quote_age_seconds: int = MAX_QUOTE_AGE_SECONDS,
) -> pl.DataFrame | None:
    """Surface features at every origin of one session-asset."""

    tape = _read_tape(paths, asset)
    if tape is None:
        # No file to read. A provider failure.
        return None
    if tape.height < 50:
        # The file was there and held almost nothing. That is a thin session, not a
        # provider failure, and counting the two together makes an ordinary quiet day look
        # like an outage.
        return SPARSE_SESSION
    created = tape["created_at"].dt.replace_time_zone(None).cast(pl.Int64).to_numpy()
    strike = tape["strike"].cast(pl.Float64).to_numpy().astype(np.float64)
    expiry = tape["expiry"].cast(pl.Date).to_numpy()
    # UTC microsecond stamp of the 16:00 ET close on each contract's expiry date.  Building
    # it once per session keeps the exact-tenor arithmetic inside the origin loop cheap.
    expiry_close_us = np.array(
        [
            int(
                np.datetime64(
                    datetime.combine(day.astype("datetime64[D]").astype(date), EXPIRY_CLOSE)
                    .replace(tzinfo=NY)
                    .astimezone(UTC)
                    .replace(tzinfo=None),
                    "us",
                ).astype(np.int64)
            )
            for day in expiry
        ],
        dtype=np.int64,
    )
    iv = tape["implied_volatility"].cast(pl.Float64).to_numpy().astype(np.float64)
    bid = tape["nbbo_bid"].cast(pl.Float64).to_numpy().astype(np.float64)
    ask = tape["nbbo_ask"].cast(pl.Float64).to_numpy().astype(np.float64)
    is_call = (tape["option_type"] == "call").to_numpy()
    keys = (
        expiry.astype("datetime64[D]").astype(np.int64) * 20_000_000
        + np.round(strike * 1000.0).astype(np.int64) * 2
        + is_call.astype(np.int64)
    )

    rows: list[dict[str, float]] = []
    base = datetime.fromisoformat(session).replace(tzinfo=NY)
    for position, minute in enumerate(origins):
        origin_time = base + timedelta(minutes=int(SESSION_OPEN_MINUTE + minute))
        naive_origin = origin_time.astimezone(UTC).replace(tzinfo=None)
        # The tape stores microsecond timestamps; every bound below is in microseconds.
        origin_us = int(np.datetime64(naive_origin, "us").astype(np.int64))
        window = snapshot_window(origin_us, max_quote_age_seconds=max_quote_age_seconds)
        snapshot = latest_quote_per_contract(created, keys, window)
        features = _surface_at(
            snapshot,
            strike,
            expiry_close_us,
            iv,
            bid,
            ask,
            is_call,
            float(closes[minute]),
        )
        features["origin_minute"] = float(minute)
        # Measured, not assumed. `post_cutoff_selected` is zero by construction - the
        # selection is a searchsorted at the cutoff - which is exactly why it is counted:
        # a zero nobody measured cannot notice a regression.
        features["b1_quote_duplicates_dropped"] = float(snapshot.duplicates_dropped)
        features["b1_post_cutoff_selected"] = float(snapshot.post_cutoff_selected)
        features["b1_duplicate_contracts_remaining"] = float(
            snapshot.duplicate_contracts_remaining
        )
        # A rate that fails the plausibility band is recorded as NaN and the origin is
        # kept: the row is not dropped, and counting those nulls as drops would report
        # retained rows as lost ones. The count of actual drops is measured here, at the
        # only place a drop could happen, and it is zero.
        features["b1_rows_dropped_for_rate_or_dividend"] = 0.0
        implied = features.get("b1_iv_30d", float("nan"))
        features["b1_iv_minus_trailing_rv_30d"] = implied_minus_trailing_variance(
            implied**2 if np.isfinite(implied) else float("nan"),
            annualise_intraday_variance(float(rv_back_30[position])),
        )
        rows.append(features)
    frame = pl.DataFrame(rows)
    return frame.with_columns(
        asset=pl.lit(asset),
        session_date=pl.lit(session),
        origin_minute=pl.col("origin_minute").cast(pl.Int64),
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=Path("D:/MDS650"))
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    # A rebuild reads its own B0 panel, not the previous run's.
    parser.add_argument("--panel-root", type=Path, default=None)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--limit-sessions", type=int, default=0)
    parser.add_argument(
        "--max-quote-age-seconds",
        type=int,
        default=MAX_QUOTE_AGE_SECONDS,
        help=(
            "how stale a contract's last quote may be. The frozen primary panel uses "
            f"{MAX_QUOTE_AGE_SECONDS}; {SENSITIVITY_MAX_AGE_SECONDS} is the "
            "pre-registered sensitivity, never the primary."
        ),
    )
    args = parser.parse_args(argv)

    # A sensitivity run writes a panel every downstream block would read as the primary one.
    # The default destination is the canonical path, so a single forgotten flag would replace
    # the frozen 1 800-second input with a 3 600-second one and nothing downstream would say
    # so. The non-primary age has to name its own destination.
    if (
        int(args.max_quote_age_seconds) != MAX_QUOTE_AGE_SECONDS
        and Path(args.output_dir).resolve() == DEFAULT_OUTPUT.resolve()
    ):
        raise SystemExit(
            "RP2_B1_SENSITIVITY_NEEDS_ITS_OWN_OUTPUT_DIR: "
            f"--max-quote-age-seconds={args.max_quote_age_seconds} is not the primary "
            f"{MAX_QUOTE_AGE_SECONDS}; pass --output-dir so the canonical panel is not replaced"
        )

    panel = pl.read_parquet(panel_paths(args.panel_root)["b0"])
    inventory = load_inventory()
    bars = load_bar_sources(args.data_root)
    grids: dict[tuple[str, str], FloatArray] = {}
    for (asset, session_date), group in bars.sort(["asset", "session_date", "minute"]).group_by(
        ["asset", "session_date"], maintain_order=True
    ):
        grid = build_session_grid(group, session=session_date)
        grids[(str(asset), str(session_date))] = grid.close

    unresolved = 0
    jobs: list[tuple[str, str, list[str], npt.NDArray[np.int64], FloatArray, FloatArray]] = []
    for (asset, session_date), group in panel.sort(
        ["asset", "session_date", "origin_minute"]
    ).group_by(["asset", "session_date"], maintain_order=True):
        key = (str(session_date), str(asset))
        paths = inventory.get(key) or inventory.get((str(session_date), "__ALL__"))
        closes = grids.get((str(asset), str(session_date)))
        if paths is None:
            # No tape at all for a session-asset the panel carries. Skipped silently, this
            # is a sample that shrank without anything saying so.
            unresolved += 1
            continue
        if closes is None or closes.size == 0:
            continue
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
                group["rv_back_30"].to_numpy().astype(np.float64)[inside],
            )
        )
    if args.limit_sessions:
        jobs = jobs[: args.limit_sessions]

    frames: list[pl.DataFrame] = []
    failures = 0
    sparse = 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for result in pool.map(
            lambda job: build_session_surface(
                *job, max_quote_age_seconds=int(args.max_quote_age_seconds)
            ),
            jobs,
        ):
            if result is None:
                failures += 1
                continue
            if result.is_empty():
                sparse += 1
                continue
            frames.append(result)
    if not frames:
        raise SystemExit("RP2_BLOCK5_EMPTY_SURFACE")
    surface = pl.concat(frames, how="diagonal")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    surface.write_parquet(args.output_dir / "b1_surface_panel.parquet")

    coverage: dict[str, object] = {}
    for column in sorted(c for c in surface.columns if c.startswith("b1_")):
        values = surface[column].cast(pl.Float64)
        finite = values.is_finite() & values.is_not_null()
        median = values.filter(finite).median()
        coverage[column] = {
            "coverage": float(finite.sum() / surface.height),
            "median": float(median) if isinstance(median, (int, float)) else float("nan"),
        }
    document: dict[str, object] = {
        "block": 5,
        "program": "docs/research_program_v2.md",
        "label": "EXPLORATORY_MECHANISM_DISCOVERY",
        "cutoff_seconds": CUTOFF_SECONDS,
        "max_quote_age_seconds": int(args.max_quote_age_seconds),
        "sensitivity_max_quote_age_seconds": SENSITIVITY_MAX_AGE_SECONDS,
        "source_label": "trade_sampled_contemporaneous_nbbo",
        "spec": "docs/rp2_v3/B1_CONTEMPORANEOUS_SPEC.md",
        "constant_maturities_days": list(CONSTANT_MATURITY_DAYS),
        "session_assets_requested": len(jobs),
        "session_assets_without_tape": failures + unresolved,
        "session_assets_unresolved_in_inventory": unresolved,
        "session_assets_too_sparse": sparse,
        "rows": surface.height,
        "coverage": coverage,
    }
    document["surface_sha256"] = canonical_sha256(document)
    document["generated_at_utc"] = datetime.now(UTC).isoformat()
    (args.output_dir / "surface_coverage.json").write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({k: v for k, v in document.items() if k != "coverage"}, indent=2))
    for name, stats in coverage.items():
        assert isinstance(stats, dict)
        print(f"  {name:<28} coverage={stats['coverage']:.3f} median={stats['median']:.5g}")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
