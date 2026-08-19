"""Block 11b - what the forecast is worth on a contract somebody could actually trade.

Block 11 answers the economic question with a variance-carry proxy: it holds a synthetic
short-variance position, marks it at annualised implied minus realised variance, and charges
half the option spread. Its own document records the finding that it trades in 100 % of
periods, which means it is measuring unconditional variance carry rather than anything the
forecast contributed.

This block replaces the proxy with the instrument. For every evaluated origin it selects one
option contract from the local tape, prices the entry from the executable side of the quote
at that origin, holds for the forecast horizon, prices the exit from the executable side
again, and delta-hedges at the entry delta. Fees and slippage are charged per contract per
side, and the book is capped both per name and in gross.

Two disciplines matter more here than anywhere else in the programme:

* **Selection is point-in-time.** The contract is chosen at entry from what was quoted at
  entry. Requiring a contract to have an exit quote would condition the whole position on
  the future, so a contract with no newer quote is marked at its last observation and
  counted, not dropped.
* **Nothing is marked at the mid.** An entry pays the ask and an exit receives the bid. A
  mid-marked P&L is a claim about a trade nobody could have done.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import numpy.typing as npt
import polars as pl

from mds650.b1v3_confirmation import canonical_sha256
from mds650.rp2.bars import MARKET_TZ, SESSION_OPEN_MINUTE, build_session_grid, load_bar_sources
from mds650.rp2.economics import (
    DeltaHedgedLeg,
    ExecutionCosts,
    apply_portfolio_constraints,
    deflated_sharpe_ratio,
    delta_hedged_pnl,
    performance_metrics,
)
from mds650.rp2.flow import black_scholes_greeks
from mds650.rp2.ladder import LADDER
from mds650.rp2.panel import (
    B0_FEATURES,
    B1_FEATURES,
    B2_FEATURES,
    build_design,
    chronological_split,
    common_usable_rows,
    describe_information_set,
    lift_mask,
    load_merged_panel,
    session_rank,
    standardise,
)
from mds650.rp2.surface import SECONDS_PER_YEAR, annualise_intraday_variance

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "artifacts" / "rp2_block11b_forward"
INVENTORY = ROOT / "artifacts" / "rp2_block1_partition" / "inventory.jsonl"
B0_PANEL = ROOT / "artifacts" / "rp2_block4_b0" / "b0_panel.parquet"
B1_PANEL = ROOT / "artifacts" / "rp2_block5_surface" / "b1_surface_panel.parquet"
B2_PANEL = ROOT / "artifacts" / "rp2_block6_flow" / "b2_flow_panel.parquet"

CUTOFF_SECONDS = 120
HORIZON_MINUTES = 30
#: Evaluate on non-overlapping origins only; overlapping payoffs count the same move twice.
NON_OVERLAPPING_STEP = 30
LOOKBACK_SECONDS = 1800
CALENDAR_YEAR = 365.0
NY = ZoneInfo(MARKET_TZ)
DEFAULT_MODELS: tuple[str, ...] = ("log_ols", "gamma_glm", "lightgbm")
PERIODS_PER_YEAR = 252.0 * 13.0

#: A retail-plus execution assumption, stated rather than tuned.
COSTS = ExecutionCosts(
    half_spread_fraction=0.5,
    fee_per_contract=0.65,
    slippage_fraction_of_half_spread=0.25,
)
#: Book limits. Per-name first, so a concentrated book is not merely scaled down.
MAX_GROSS_CONTRACTS = 1000.0
MAX_PER_NAME_CONTRACTS = 250.0
#: The contract is picked from the expiry nearest this many days, where the surface is read.
TARGET_DTE_DAYS = 30.0

#: The nested information sets, in the layered form Block 11 uses.
INFORMATION_SETS: dict[str, list[dict[str, str]]] = {
    "B0": [B0_FEATURES],
    "B0+B1": [B0_FEATURES, B1_FEATURES],
    "B0+B1+B2": [B0_FEATURES, B1_FEATURES, B2_FEATURES],
}

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
        (pl.col("nbbo_bid") > 0.0)
        & (pl.col("nbbo_ask") > pl.col("nbbo_bid"))
        & pl.col("implied_volatility").is_between(0.01, 5.0)
        & pl.col("strike").is_not_null()
    )
    return tape.sort("created_at") if tape.height else None


def _latest_per_contract(keys: npt.NDArray[np.int64], lo: int, hi: int) -> npt.NDArray[np.int64]:
    """Row index of the most recent observation of each contract in ``[lo, hi)``."""

    if hi <= lo:
        return np.empty(0, dtype=np.int64)
    reversed_keys = keys[lo:hi][::-1]
    _, first = np.unique(reversed_keys, return_index=True)
    return hi - 1 - first


def session_legs(
    asset: str,
    session: str,
    paths: Sequence[str],
    origins: npt.NDArray[np.int64],
    closes: FloatArray,
) -> pl.DataFrame | None:
    """One tradeable contract per origin, with its entry and exit quotes.

    The contract is the one closest to at-the-money in the expiry nearest 30 days, chosen
    from what was quoted at the entry cutoff. Its exit is the last observation at or before
    the horizon, which is the entry quote itself when nothing newer arrived — a stale mark,
    counted as such rather than silently dropped.
    """

    tape = _read_tape(paths, asset)
    if tape is None or tape.height < 50:
        return None
    created = tape["created_at"].dt.replace_time_zone(None).cast(pl.Int64).to_numpy()
    strike = tape["strike"].cast(pl.Float64).to_numpy().astype(np.float64)
    expiry = tape["expiry"].cast(pl.Date).to_numpy()
    iv = tape["implied_volatility"].cast(pl.Float64).to_numpy().astype(np.float64)
    bid = tape["nbbo_bid"].cast(pl.Float64).to_numpy().astype(np.float64)
    ask = tape["nbbo_ask"].cast(pl.Float64).to_numpy().astype(np.float64)
    is_call = (tape["option_type"] == "call").to_numpy()
    expiry_days = (expiry - np.datetime64(session, "D")).astype("timedelta64[D]").astype(np.int64)
    keys = (
        expiry_days * 20_000_000 + np.round(strike * 1000.0).astype(np.int64) * 2 + is_call
    ).astype(np.int64)

    base = datetime.fromisoformat(session).replace(tzinfo=NY)
    rows: list[dict[str, object]] = []
    for minute in origins:
        entry_time = base + timedelta(minutes=int(SESSION_OPEN_MINUTE + minute))
        entry_cut = entry_time.astimezone(UTC).replace(tzinfo=None) - timedelta(
            seconds=CUTOFF_SECONDS
        )
        exit_cut = entry_cut + timedelta(minutes=HORIZON_MINUTES)
        entry_us = int(np.datetime64(entry_cut, "us").astype(np.int64))
        exit_us = int(np.datetime64(exit_cut, "us").astype(np.int64))
        window = entry_us - LOOKBACK_SECONDS * 1_000_000

        hi = int(np.searchsorted(created, entry_us, side="right"))
        lo = int(np.searchsorted(created, window, side="left"))
        picked = _latest_per_contract(keys, lo, hi)
        if picked.size < 3:
            continue
        spot = float(closes[minute])
        # Choose the expiry nearest the target, then the strike nearest the spot, using
        # only what is quoted at entry.
        days = expiry_days[picked].astype(np.float64)
        live = days > 0.0
        if not live.any():
            continue
        picked, days = picked[live], days[live]
        bucket_days = days[np.argmin(np.abs(days - TARGET_DTE_DAYS))]
        bucket = days == bucket_days
        candidates = picked[bucket]
        calls = candidates[is_call[candidates]]
        if calls.size == 0:
            continue
        chosen = int(calls[np.argmin(np.abs(strike[calls] - spot))])

        exit_hi = int(np.searchsorted(created, exit_us, side="right"))
        same = np.flatnonzero(keys[:exit_hi] == keys[chosen])
        exit_row = int(same[-1]) if same.size else chosen
        exit_minute = min(int(minute) + HORIZON_MINUTES, closes.size - 1)
        tenor_years = max(bucket_days, 1.0) / CALENDAR_YEAR
        greeks = black_scholes_greeks(
            np.array([spot]),
            np.array([strike[chosen]]),
            np.array([tenor_years]),
            np.array([iv[chosen]]),
            np.array([is_call[chosen]]),
        )
        entry_mid = 0.5 * (bid[chosen] + ask[chosen])
        exit_mid = 0.5 * (bid[exit_row] + ask[exit_row])
        rows.append(
            {
                "asset": asset,
                "session_date": session,
                "origin_minute": int(minute),
                "contract_key": int(keys[chosen]),
                "strike": float(strike[chosen]),
                "dte_days": float(bucket_days),
                "entry_option_mid": float(entry_mid),
                "exit_option_mid": float(exit_mid),
                "entry_half_spread": float(0.5 * (ask[chosen] - bid[chosen])),
                "exit_half_spread": float(0.5 * (ask[exit_row] - bid[exit_row])),
                "entry_spot": spot,
                "exit_spot": float(closes[exit_minute]),
                "entry_delta": float(greeks.delta[0]),
                "entry_iv": float(iv[chosen]),
                "exit_is_stale": float(exit_row == chosen),
                "quote_age_s": float((entry_us - created[chosen]) / 1e6),
            }
        )
    return pl.DataFrame(rows) if rows else None


def build_legs(data_root: Path, workers: int, limit_sessions: int) -> pl.DataFrame:
    """One pass over the tape producing the tradeable leg at every evaluated origin."""

    panel = pl.read_parquet(B0_PANEL, columns=["asset", "session_date", "origin_minute", "role"])
    panel = panel.filter((pl.col("origin_minute") % NON_OVERLAPPING_STEP) == 0)
    inventory = load_inventory()
    bars = load_bar_sources(data_root)
    grids: dict[tuple[str, str], FloatArray] = {}
    for (asset, session_date), group in bars.sort(["asset", "session_date", "minute"]).group_by(
        ["asset", "session_date"], maintain_order=True
    ):
        grid = build_session_grid(group, session=session_date)
        if grid.minutes:
            grids[(str(asset), str(session_date))] = grid.close

    jobs: list[tuple[str, str, list[str], npt.NDArray[np.int64], FloatArray]] = []
    for (asset, session_date), group in panel.sort(
        ["asset", "session_date", "origin_minute"]
    ).group_by(["asset", "session_date"], maintain_order=True):
        paths = inventory.get((str(session_date), str(asset)))
        closes = grids.get((str(asset), str(session_date)))
        if paths is None or closes is None or closes.size == 0:
            continue
        minutes = group["origin_minute"].to_numpy().astype(np.int64)
        minutes = minutes[minutes + HORIZON_MINUTES < closes.size]
        if minutes.size == 0:
            continue
        jobs.append((str(asset), str(session_date), paths, minutes, closes))
    if limit_sessions:
        jobs = jobs[:limit_sessions]

    frames: list[pl.DataFrame] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for index, result in enumerate(pool.map(lambda job: session_legs(*job), jobs), start=1):
            if result is not None:
                frames.append(result)
            if index % 200 == 0:
                print(f"[11b] {index}/{len(jobs)} session-assets", flush=True)
    if not frames:
        raise SystemExit("RP2_BLOCK11B_NO_LEGS")
    return pl.concat(frames, how="vertical")


def _scalar(value: object) -> float:
    """Polars aggregates are typed as anything; a summary field needs a real float."""

    return float(value) if isinstance(value, int | float) else float("nan")


def run_role(
    panel: pl.DataFrame,
    legs: pl.DataFrame,
    *,
    role: str,
    train_share: float,
    models: Sequence[str],
) -> dict[str, object]:
    """Fit each information set, sign a real position, and mark it from the quotes."""

    frame = panel.filter(pl.col("role") == role).sort(["session_date", "asset", "origin_minute"])
    target = np.asarray(frame["rv30"].to_numpy(), dtype=np.float64)
    designs: dict[str, FloatArray] = {}
    resolved: dict[str, tuple[str, ...]] = {}
    for name, maps in INFORMATION_SETS.items():
        designs[name], resolved[name] = build_design(frame, maps)
    keep = common_usable_rows(designs, target)
    information_sets = {
        name: describe_information_set((name,), resolved[name], keep)
        for name in INFORMATION_SETS
    }
    if int(keep.sum()) < 2000:
        return {
            "status": "INSUFFICIENT_ROWS",
            "rows": int(keep.sum()),
            "information_sets": information_sets,
        }

    frame = frame.filter(pl.Series(keep))
    target = target[keep]
    designs = {name: design[keep] for name, design in designs.items()}
    sessions_rank = session_rank(frame["session_date"].to_numpy())
    train, test = chronological_split(sessions_rank, train_share=train_share)
    information_sets = {
        name: describe_information_set((name,), resolved[name], lift_mask(keep, test))
        for name in INFORMATION_SETS
    }

    joined = frame.with_row_index("row").join(
        legs, on=["asset", "session_date", "origin_minute"], how="inner"
    )
    if joined.height < 200:
        return {
            "status": "INSUFFICIENT_LEGS",
            "legs": joined.height,
            "information_sets": information_sets,
        }
    rows = joined["row"].to_numpy().astype(np.int64)
    tradeable = test[rows]
    joined = joined.filter(pl.Series(tradeable))
    rows = rows[tradeable]
    if joined.height < 100:
        return {
            "status": "INSUFFICIENT_TEST_LEGS",
            "legs": int(joined.height),
            "information_sets": information_sets,
        }

    entry_iv = joined["entry_iv"].to_numpy().astype(np.float64)
    implied_variance = entry_iv**2
    names = joined["asset"].to_numpy().astype(str)
    leg_fields = {
        name: joined[name].to_numpy().astype(np.float64)
        for name in (
            "entry_option_mid",
            "exit_option_mid",
            "entry_spot",
            "exit_spot",
            "entry_delta",
            "entry_half_spread",
            "exit_half_spread",
        )
    }

    results: dict[str, object] = {
        "status": "MEASURED",
        "rows": int(frame.height),
        "train_share": train_share,
        "legs_evaluated": int(joined.height),
        "stale_exit_share": _scalar(joined["exit_is_stale"].mean()),
        "median_quote_age_s": _scalar(joined["quote_age_s"].median()),
        "median_dte_days": _scalar(joined["dte_days"].median()),
        "median_entry_half_spread": _scalar(joined["entry_half_spread"].median()),
        "information_sets": information_sets,
    }
    per_model: dict[str, object] = {}
    trials = len(models) * len(INFORMATION_SETS)
    for model_name in models:
        fitter = LADDER[model_name]
        block: dict[str, object] = {}
        for set_name in INFORMATION_SETS:
            forecast = fitter(standardise(designs[set_name], train), target, train)
            forecast_annual = np.array(
                [annualise_intraday_variance(value) for value in forecast], dtype=np.float64
            )[rows]
            # Short variance when the option is dear relative to the forecast, long when
            # cheap. The forecast decides the side; the quote decides the price.
            edge = implied_variance - forecast_annual
            raw = -np.sign(edge) * np.minimum(
                np.abs(edge) / np.maximum(implied_variance, 1e-9), 1.0
            )
            contracts = apply_portfolio_constraints(
                raw * MAX_PER_NAME_CONTRACTS,
                max_gross_contracts=MAX_GROSS_CONTRACTS,
                max_position_per_name=MAX_PER_NAME_CONTRACTS,
                names=names,
            )
            leg = DeltaHedgedLeg(contracts=contracts, **leg_fields)
            pnl = delta_hedged_pnl(leg, COSTS)
            net = pnl["net_pnl"]
            cost = pnl["spread_cost"] + pnl["fees"]
            metrics = performance_metrics(net, periods_per_year=PERIODS_PER_YEAR)
            gross = performance_metrics(pnl["gross_pnl"], periods_per_year=PERIODS_PER_YEAR)
            per_period = (
                metrics.mean / metrics.volatility if metrics.volatility > 0.0 else float("nan")
            )
            traded = float(np.mean(np.abs(contracts) > 1e-9))
            block[set_name] = {
                "net": asdict(metrics),
                "gross_sharpe": gross.sharpe_annual,
                "traded_share": traded,
                "mean_gross_contracts": float(np.mean(np.abs(contracts))),
                "total_cost": float(np.sum(cost)),
                "cost_share_of_gross": (
                    float(np.sum(cost) / np.sum(np.abs(pnl["gross_pnl"])))
                    if float(np.sum(np.abs(pnl["gross_pnl"]))) > 0.0
                    else float("nan")
                ),
                "deflated_sharpe_probability": deflated_sharpe_ratio(
                    per_period,
                    trials=trials,
                    observations=metrics.periods,
                    skewness=metrics.skewness,
                    kurtosis=metrics.kurtosis,
                ),
            }
        per_model[model_name] = block
    results["models"] = per_model
    return results


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=Path("D:/MDS650"))
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--train-share", type=float, default=0.6)
    parser.add_argument("--limit-sessions", type=int, default=0)
    parser.add_argument("--rebuild-legs", action="store_true", help="redo the tape pass")
    parser.add_argument("--models", default=",".join(DEFAULT_MODELS))
    args = parser.parse_args(argv)

    models = tuple(name.strip() for name in str(args.models).split(",") if name.strip())
    args.output_dir.mkdir(parents=True, exist_ok=True)
    cached = args.output_dir / "tradeable_legs.parquet"
    # The tape pass is the expensive half. Reuse it when it is already on disk and the
    # caller has not asked for a rebuild, so a downstream fix does not cost another hour.
    if cached.is_file() and not args.rebuild_legs:
        legs = pl.read_parquet(cached)
        print(f"[11b] reusing {legs.height} legs from {cached.name}")
    else:
        legs = build_legs(args.data_root, args.workers, args.limit_sessions)
        legs.write_parquet(cached)

    panel = load_merged_panel(B0_PANEL, B1_PANEL, B2_PANEL)
    document: dict[str, object] = {
        "block": "11b",
        "program": "docs/research_program_v2.md",
        "label": "EXPLORATORY_MECHANISM_DISCOVERY",
        "horizon_minutes": HORIZON_MINUTES,
        "cutoff_seconds": CUTOFF_SECONDS,
        "target_dte_days": TARGET_DTE_DAYS,
        "execution_costs": asdict(COSTS),
        "max_gross_contracts": MAX_GROSS_CONTRACTS,
        "max_position_per_name": MAX_PER_NAME_CONTRACTS,
        "legs_built": int(legs.height),
        "models": list(models),
    }
    for role in ("D", "V"):
        document[role] = run_role(
            panel, legs, role=role, train_share=args.train_share, models=models
        )
    document["forward_sha256"] = canonical_sha256(document)
    document["generated_at_utc"] = datetime.now(UTC).isoformat()
    (args.output_dir / "forward_economics.json").write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    for role in ("D", "V"):
        block = document[role]
        assert isinstance(block, dict)
        print(f"=== role {role}: {block.get('status')} legs={block.get('legs_evaluated')} ===")
        per_model = block.get("models")
        if isinstance(per_model, dict):
            for model_name, sets in per_model.items():
                assert isinstance(sets, dict)
                for set_name, stats in sets.items():
                    assert isinstance(stats, dict)
                    net = stats["net"]
                    assert isinstance(net, dict)
                    print(
                        f"  {model_name:<11} {set_name:<9} netSharpe={net['sharpe_annual']:+8.3f} "
                        f"traded={stats['traded_share']:.2f} "
                        f"costShare={stats['cost_share_of_gross']:.3f} "
                        f"DSR={stats['deflated_sharpe_probability']:.3f}"
                    )
    print(f"SECONDS_PER_YEAR sanity: {SECONDS_PER_YEAR:.0f}")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
