"""Block 5 - Gate 4: rebuild B1 as an arbitrage-aware implied-volatility surface.

For every forecast origin in the Block 4 panel this reconstructs a point-in-time snapshot
of the option surface from the local per-trade tape - each trade carries the prevailing
NBBO and the provider's implied volatility, so the latest observation per contract before
the cutoff is a (sparse) surface - and reduces it to constant-maturity total variance,
smile shape, wing quotes, term structure, variance risk premium and quote quality.

Point-in-time rule: only rows with ``created_at <= origin - 120 s`` are visible, the
empirical cutoff established in Block 2.  Sealed cohorts are never read.
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
from mds650.rp2.surface import (
    CONSTANT_MATURITY_DAYS,
    annualise_intraday_variance,
    black_scholes_delta,
    calendar_arbitrage_violations,
    fit_smile,
    interpolate_total_variance,
    model_free_variance,
    put_call_parity_residual,
    total_variance,
    variance_risk_premium,
    wing_quotes,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "artifacts" / "rp2_block5_surface"
INVENTORY = ROOT / "artifacts" / "rp2_block1_partition" / "inventory.jsonl"
B0_PANEL = ROOT / "artifacts" / "rp2_block4_b0" / "b0_panel.parquet"
CUTOFF_SECONDS = 120
LOOKBACK_SECONDS = 1800
CALENDAR_YEAR = 365.0
NY = ZoneInfo(MARKET_TZ)
TAPE_COLUMNS = (
    "underlying_symbol", "created_at", "nbbo_bid", "nbbo_ask",
    "implied_volatility", "expiry", "strike", "option_type",
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


def _read_tape(paths: Sequence[str], asset: str) -> pl.DataFrame | None:
    frames: list[pl.DataFrame] = []
    for path in paths:
        frame = pl.read_parquet(path, columns=list(TAPE_COLUMNS))
        frames.append(frame.filter(pl.col("underlying_symbol") == asset))
    if not frames:
        return None
    tape = pl.concat(frames, how="vertical")
    tape = tape.filter(
        (pl.col("nbbo_bid") > 0.0)
        & (pl.col("nbbo_ask") > pl.col("nbbo_bid"))
        & pl.col("implied_volatility").is_between(0.01, 5.0)
        & pl.col("strike").is_not_null()
    )
    return tape.sort("created_at") if tape.height else None


def _surface_at(
    cutoff_index: int,
    window_start: int,
    keys: npt.NDArray[np.int64],
    created: npt.NDArray[np.int64],
    strike: FloatArray,
    tenor: FloatArray,
    iv: FloatArray,
    bid: FloatArray,
    ask: FloatArray,
    is_call: npt.NDArray[np.bool_],
    spot: float,
    cutoff_us: int,
) -> dict[str, float]:
    """Reduce one point-in-time surface snapshot to features."""

    empty = {"b1_contracts": 0.0}
    if cutoff_index <= window_start:
        return empty
    span = slice(window_start, cutoff_index)
    # Latest observation per contract: first occurrence scanning backwards.
    reversed_keys = keys[span][::-1]
    _, first = np.unique(reversed_keys, return_index=True)
    picked = cutoff_index - 1 - first
    if picked.size < 3:
        return empty

    k_strike, k_tenor, k_iv = strike[picked], tenor[picked], iv[picked]
    k_bid, k_ask, k_call = bid[picked], ask[picked], is_call[picked]
    mid = 0.5 * (k_bid + k_ask)
    relative_spread = (k_ask - k_bid) / np.maximum(mid, 1e-9)
    age_seconds = (cutoff_us - created[picked]) / 1e6
    log_moneyness = np.log(np.maximum(k_strike, 1e-9) / spot)

    tenor_days = np.round(k_tenor * CALENDAR_YEAR).astype(np.int64)
    unique_tenors = np.unique(tenor_days)
    atm_tenor_years: list[float] = []
    atm_total_variance: list[float] = []
    for days in unique_tenors:
        mask = tenor_days == days
        if int(mask.sum()) < 3:
            continue
        smile = fit_smile(log_moneyness[mask], k_iv[mask])
        if not np.isfinite(smile.level) or smile.level <= 0.0:
            continue
        years = float(days) / CALENDAR_YEAR
        atm_tenor_years.append(years)
        atm_total_variance.append(float(total_variance(np.array([smile.level]),
                                                       np.array([years]))[0]))
    features: dict[str, float] = {
        "b1_contracts": float(picked.size),
        "b1_expiries": float(unique_tenors.size),
        "b1_strikes": float(np.unique(k_strike).size),
        "b1_median_quote_age_s": float(np.median(age_seconds)),
        "b1_median_relative_spread": float(np.median(relative_spread)),
        "b1_pcp_residual": float("nan"),
        "b1_calendar_violations": float("nan"),
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
    nearest = unique_tenors[np.argmin(np.abs(unique_tenors - 30))]
    bucket = tenor_days == nearest
    if int(bucket.sum()) >= 3:
        smile = fit_smile(log_moneyness[bucket], k_iv[bucket])
        features["b1_smile_slope"] = smile.slope
        features["b1_smile_curvature"] = smile.curvature
        features["b1_smile_residual"] = smile.residual_std
        delta = black_scholes_delta(spot, k_strike[bucket], k_tenor[bucket],
                                    k_iv[bucket], k_call[bucket])
        call_iv, put_iv = wing_quotes(delta, k_iv[bucket])
        features["b1_risk_reversal_25"] = call_iv - put_iv
        features["b1_butterfly_25"] = 0.5 * (call_iv + put_iv) - smile.level
        # Model-free variance over the observed strike grid, out-of-the-money side only.
        otm = bucket & np.where(k_call, k_strike >= spot, k_strike <= spot)
        features["b1_mfiv"] = model_free_variance(
            k_strike[otm], mid[otm], spot, float(nearest) / CALENDAR_YEAR
        )
        calls = bucket & k_call
        puts = bucket & ~k_call
        shared = np.intersect1d(k_strike[calls], k_strike[puts])
        if shared.size:
            call_mid = np.array([mid[calls][k_strike[calls] == s][0] for s in shared])
            put_mid = np.array([mid[puts][k_strike[puts] == s][0] for s in shared])
            features["b1_pcp_residual"] = put_call_parity_residual(
                call_mid, put_mid, shared, spot
            )
    return features


def build_session_surface(
    asset: str, session: str, paths: Sequence[str], origins: npt.NDArray[np.int64],
    closes: FloatArray, rv_back_30: FloatArray
) -> pl.DataFrame | None:
    """Surface features at every origin of one session-asset."""

    tape = _read_tape(paths, asset)
    if tape is None or tape.height < 50:
        return None
    created = tape["created_at"].dt.replace_time_zone(None).cast(pl.Int64).to_numpy()
    strike = tape["strike"].cast(pl.Float64).to_numpy().astype(np.float64)
    expiry = tape["expiry"].cast(pl.Date).to_numpy()
    session_date = np.datetime64(session, "D")
    tenor = np.maximum((expiry - session_date).astype("timedelta64[D]").astype(np.float64), 1.0)
    tenor_years = tenor / CALENDAR_YEAR
    iv = tape["implied_volatility"].cast(pl.Float64).to_numpy().astype(np.float64)
    bid = tape["nbbo_bid"].cast(pl.Float64).to_numpy().astype(np.float64)
    ask = tape["nbbo_ask"].cast(pl.Float64).to_numpy().astype(np.float64)
    is_call = (tape["option_type"] == "call").to_numpy()
    keys = (
        np.round(tenor).astype(np.int64) * 20_000_000
        + np.round(strike * 1000.0).astype(np.int64) * 2
        + is_call.astype(np.int64)
    )

    rows: list[dict[str, float]] = []
    base = datetime.fromisoformat(session).replace(tzinfo=NY)
    for position, minute in enumerate(origins):
        origin_time = base + timedelta(minutes=int(SESSION_OPEN_MINUTE + minute))
        cutoff = origin_time.astimezone(UTC).replace(tzinfo=None) - timedelta(
            seconds=CUTOFF_SECONDS
        )
        # The tape stores microsecond timestamps; every bound below is in microseconds.
        cutoff_us = int(np.datetime64(cutoff, "us").astype(np.int64))
        start_us = cutoff_us - LOOKBACK_SECONDS * 1_000_000
        hi = int(np.searchsorted(created, cutoff_us, side="right"))
        lo = int(np.searchsorted(created, start_us, side="left"))
        features = _surface_at(
            hi, lo, keys, created, strike, tenor_years, iv, bid, ask, is_call,
            float(closes[minute]), cutoff_us,
        )
        features["origin_minute"] = float(minute)
        implied = features.get("b1_iv_30d", float("nan"))
        features["b1_vrp_30d"] = variance_risk_premium(
            implied**2 if np.isfinite(implied) else float("nan"),
            annualise_intraday_variance(float(rv_back_30[position])),
        )
        rows.append(features)
    frame = pl.DataFrame(rows)
    return frame.with_columns(
        asset=pl.lit(asset), session_date=pl.lit(session),
        origin_minute=pl.col("origin_minute").cast(pl.Int64),
    )


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
        grid = build_session_grid(group)
        grids[(str(asset), str(session_date))] = grid.close

    jobs: list[tuple[str, str, list[str], npt.NDArray[np.int64], FloatArray, FloatArray]] = []
    for (asset, session_date), group in panel.sort(
        ["asset", "session_date", "origin_minute"]
    ).group_by(["asset", "session_date"], maintain_order=True):
        key = (str(session_date), str(asset))
        paths = inventory.get(key) or inventory.get((str(session_date), "__ALL__"))
        closes = grids.get((str(asset), str(session_date)))
        if paths is None or closes is None:
            continue
        jobs.append(
            (
                str(asset), str(session_date), paths,
                group["origin_minute"].to_numpy().astype(np.int64),
                closes,
                group["rv_back_30"].to_numpy().astype(np.float64),
            )
        )
    if args.limit_sessions:
        jobs = jobs[: args.limit_sessions]

    frames: list[pl.DataFrame] = []
    failures = 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for result in pool.map(lambda job: build_session_surface(*job), jobs):
            if result is None:
                failures += 1
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
        "lookback_seconds": LOOKBACK_SECONDS,
        "constant_maturities_days": list(CONSTANT_MATURITY_DAYS),
        "session_assets_requested": len(jobs),
        "session_assets_without_tape": failures,
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
