"""Block 6 - Gate 5: rebuild B2 as microstructure, not a five-minute count.

For every origin in the Block 4 panel this reads the raw option tape inside two windows
before the point-in-time cutoff and produces Greeks-weighted signed flow, activity split by
option type, moneyness and tenor, burstiness and Hawkes intensity, concentration and
entropy, and trade-to-quote impact.

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
    HAWKES_DECAY_SECONDS,
    black_scholes_greeks,
    burstiness,
    hawkes_intensity,
    herfindahl,
    shannon_entropy,
    signed_exposure,
    trade_to_quote_impact,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "artifacts" / "rp2_block6_flow"
INVENTORY = ROOT / "artifacts" / "rp2_block1_partition" / "inventory.jsonl"
B0_PANEL = ROOT / "artifacts" / "rp2_block4_b0" / "b0_panel.parquet"
CUTOFF_SECONDS = 120
WINDOWS: tuple[tuple[str, int], ...] = (("5m", 300), ("30m", 1800))
CALENDAR_YEAR = 365.0
NY = ZoneInfo(MARKET_TZ)
OTM_LOG_MONEYNESS = 0.05
SHORT_DTE_DAYS = 7.0
LONG_DTE_DAYS = 30.0
TAPE_COLUMNS = (
    "underlying_symbol", "created_at", "nbbo_bid", "nbbo_ask", "price", "size", "premium",
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


def _window_features(
    lo: int, hi: int, label: str, *, spot: float, cutoff_us: int,
    created: npt.NDArray[np.int64], strike: FloatArray, tenor_days: FloatArray,
    iv: FloatArray, size: FloatArray, premium: FloatArray, mid: FloatArray,
    relative_spread: FloatArray, direction: FloatArray, is_call: npt.NDArray[np.bool_],
    is_sweep: npt.NDArray[np.bool_], keys: npt.NDArray[np.int64],
) -> dict[str, float]:
    """Reduce one pre-cutoff window of trades to microstructure features."""

    prefix = f"b2_{label}_"
    if hi <= lo:
        return {f"{prefix}trades": 0.0, f"{prefix}premium": 0.0}
    span = slice(lo, hi)
    w_strike, w_tenor, w_iv = strike[span], tenor_days[span], iv[span]
    w_size, w_premium, w_direction = size[span], premium[span], direction[span]
    w_call, w_sweep, w_keys = is_call[span], is_sweep[span], keys[span]
    spot_vector = np.full(w_strike.size, spot, dtype=np.float64)
    greeks = black_scholes_greeks(spot_vector, w_strike, w_tenor / CALENDAR_YEAR, w_iv, w_call)
    log_moneyness = np.log(np.maximum(w_strike, 1e-9) / spot)

    seconds = (created[span] - created[span][0]) / 1e6
    intensity = hawkes_intensity(seconds, baseline=0.0, excitation=1.0,
                                 decay=HAWKES_DECAY_SECONDS)
    gaps = burstiness(seconds)
    impact = trade_to_quote_impact(w_keys, w_iv, mid[span], relative_spread[span])

    def exposure(sensitivity: FloatArray, mask: npt.NDArray[np.bool_] | None = None,
                 scale: FloatArray | None = None) -> float:
        if mask is None:
            return signed_exposure(sensitivity, w_size, w_direction, scale=scale)
        if not mask.any():
            return 0.0
        return signed_exposure(
            sensitivity[mask], w_size[mask], w_direction[mask],
            scale=None if scale is None else scale[mask],
        )

    short_dte = w_tenor <= SHORT_DTE_DAYS
    long_dte = w_tenor > LONG_DTE_DAYS
    total_premium = max(float(np.sum(w_premium)), 1e-9)
    features: dict[str, float] = {
        f"{prefix}trades": float(w_size.size),
        f"{prefix}contracts": float(np.unique(w_keys).size),
        f"{prefix}size": float(np.sum(w_size)),
        f"{prefix}premium": float(np.sum(w_premium)),
        f"{prefix}vega_flow": exposure(greeks.vega),
        f"{prefix}gamma_flow": exposure(greeks.gamma, scale=spot_vector**2),
        f"{prefix}delta_flow": exposure(greeks.delta, scale=spot_vector),
        f"{prefix}vega_flow_abs": float(
            np.sum(np.abs(greeks.vega * w_size * np.abs(w_direction)))
        ),
        f"{prefix}vega_flow_call": exposure(greeks.vega, w_call),
        f"{prefix}vega_flow_put": exposure(greeks.vega, ~w_call),
        f"{prefix}vega_flow_short_dte": exposure(greeks.vega, short_dte),
        f"{prefix}vega_flow_long_dte": exposure(greeks.vega, long_dte),
        f"{prefix}otm_premium_share": float(
            np.sum(w_premium[np.abs(log_moneyness) > OTM_LOG_MONEYNESS]) / total_premium
        ),
        f"{prefix}buy_premium_share": float(
            np.sum(w_premium[w_direction > 0]) / total_premium
        ),
        f"{prefix}sell_premium_share": float(
            np.sum(w_premium[w_direction < 0]) / total_premium
        ),
        f"{prefix}passive_premium_share": float(
            np.sum(w_premium[w_direction == 0]) / total_premium
        ),
        f"{prefix}sweep_premium_share": float(
            np.sum(w_premium[w_sweep]) / total_premium
        ),
        f"{prefix}strike_hhi": herfindahl(
            np.bincount(np.unique(w_strike, return_inverse=True)[1],
                        weights=w_premium).astype(np.float64)
        ),
        f"{prefix}expiry_hhi": herfindahl(
            np.bincount(np.unique(w_tenor, return_inverse=True)[1],
                        weights=w_premium).astype(np.float64)
        ),
        f"{prefix}contract_entropy": shannon_entropy(
            np.bincount(np.unique(w_keys, return_inverse=True)[1],
                        weights=w_premium).astype(np.float64)
        ),
        f"{prefix}hawkes_last": float(intensity[-1]),
        f"{prefix}hawkes_innovation": float(intensity[-1] - np.mean(intensity)),
        f"{prefix}rate_per_second": gaps["rate_per_second"],
        f"{prefix}interarrival_cv": gaps["interarrival_cv"],
        f"{prefix}d_iv": impact["d_iv"],
        f"{prefix}d_mid_rel": impact["d_mid_rel"],
        f"{prefix}d_spread": impact["d_spread"],
        f"{prefix}median_age_s": float(np.median((cutoff_us - created[span]) / 1e6)),
    }
    return features


def build_session_flow(
    asset: str, session: str, paths: Sequence[str], origins: npt.NDArray[np.int64],
    closes: FloatArray
) -> pl.DataFrame | None:
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
    is_sweep = (
        tape["report_flags"].cast(pl.Utf8).fill_null("").str.contains("sweep").to_numpy()
    )
    keys = (
        np.round(tenor_days).astype(np.int64) * 20_000_000
        + np.round(strike * 1000.0).astype(np.int64) * 2
        + is_call.astype(np.int64)
    )

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
        for label, seconds in WINDOWS:
            lo = int(np.searchsorted(created, cutoff_us - seconds * 1_000_000, side="left"))
            record.update(
                _window_features(
                    lo, hi, label, spot=float(closes[minute]), cutoff_us=cutoff_us,
                    created=created, strike=strike, tenor_days=tenor_days, iv=iv, size=size,
                    premium=premium, mid=mid, relative_spread=relative_spread,
                    direction=direction, is_call=is_call, is_sweep=is_sweep, keys=keys,
                )
            )
        rows.append(record)
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
        "windows_seconds": {label: seconds for label, seconds in WINDOWS},
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
