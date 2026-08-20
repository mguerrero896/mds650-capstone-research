"""Block 11 - is any of this economic value?

Runs bridge B (a variance-risk strategy that only trades when the estimated edge clears the
option spread) and bridge C (risk-management utility: volatility targeting, VaR breaches,
certainty equivalent) for the B0 forecast and the full B0+B1+B2 forecast, and asks whether
adding option information changes anything a practitioner would notice.

Transaction cost comes from the measured option relative spread at the origin, not from an
assumption: half the round-trip spread of the surface snapshot, converted to variance units.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import numpy.typing as npt
import polars as pl

from mds650.b1v3_confirmation import canonical_sha256
from mds650.rp2.economics import (
    PERIODS_PER_YEAR,
    break_even_cost,
    deflated_sharpe_ratio,
    performance_metrics,
    risk_management_utility,
    variance_risk_strategy,
)
from mds650.rp2.feature_registry import assert_segment_coverage, describe_coverage
from mds650.rp2.ladder import LADDER
from mds650.rp2.panel import (
    B0_FEATURES,
    B1_FEATURES,
    B2_FEATURES,
    CORE_SETS,
    build_design,
    chronological_split,
    common_evaluation_mask,
    describe_information_set,
    lift_mask,
    load_merged_panel,
    session_rank,
)
from mds650.rp2.preprocessing import describe_preprocessor, fold_design
from mds650.rp2.surface import annualise_intraday_variance

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "artifacts" / "rp2_block11_economics"
B0_PANEL = ROOT / "artifacts" / "rp2_block4_b0" / "b0_panel.parquet"
B1_PANEL = ROOT / "artifacts" / "rp2_block5_surface" / "b1_surface_panel.parquet"
B2_PANEL = ROOT / "artifacts" / "rp2_block6_flow" / "b2_flow_panel.parquet"

INFORMATION_SETS: dict[str, list[dict[str, str]]] = {
    "B0": [B0_FEATURES],
    "B0+B1+B2": [B0_FEATURES, B1_FEATURES, B2_FEATURES],
}
DEFAULT_MODELS: tuple[str, ...] = ("log_ols", "gamma_glm", "lightgbm")
#: Non-overlapping evaluation: one 30-minute window per half hour, no double counting.
NON_OVERLAPPING_STEP = 30

type FloatArray = npt.NDArray[np.float64]


def run_role(
    panel: pl.DataFrame, *, role: str, train_share: float, models: Sequence[str],
    buffer: float
) -> dict[str, object]:
    frame = panel.filter(pl.col("role") == role).sort(
        ["session_date", "asset", "origin_minute"]
    )
    target = np.asarray(frame["rv30"].to_numpy(), dtype=np.float64)
    # build_design still fails closed on a registered feature the panel does not carry; its
    # matrix is discarded, because the design a fold fits is built by the preprocessor from
    # that fold's own training statistics.
    resolved: dict[str, tuple[str, ...]] = {}
    features: dict[str, list[str]] = {}
    for name, maps in INFORMATION_SETS.items():
        _, resolved[name] = build_design(frame, maps)
        features[name] = [column for mapping in maps for column in mapping]
    keep = common_evaluation_mask(frame, target)
    # The economics needs a quote it can trade against, so two surface columns join the
    # usable-row rule. The provenance is built after them: a record made before the filter
    # would report the filtered row count and hash the wider sample.
    keep &= np.isfinite(frame["b1_iv_30d"].to_numpy()) if "b1_iv_30d" in frame.columns else keep
    keep &= np.isfinite(frame["b1_median_relative_spread"].to_numpy())
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

    role_frame = frame
    frame = frame.filter(pl.Series(keep))
    target = target[keep]
    sessions_rank = session_rank(frame["session_date"].to_numpy())
    train, test = chronological_split(sessions_rank, train_share=train_share)
    # The floor holds on the panel and on this role; it also has to hold on the two
    # segments this run fits and scores, which is where a held-out tail with a gap in it
    # would otherwise become a result. The masks are lifted back onto the unfiltered role
    # frame: checking them on the frame the common mask has already pruned would be
    # checking that the rows which survived are the rows which survived.
    assert_segment_coverage(
        role_frame,
        {"train": lift_mask(keep, train), "test": lift_mask(keep, test)},
        *CORE_SETS.values(),
    )
    # One design per information set, imputed and scaled from this fold's training rows.
    designs: dict[str, FloatArray] = {}
    preprocessors: dict[str, object] = {}
    for name in INFORMATION_SETS:
        designs[name], _, fitted = fold_design(frame, features[name], train)
        preprocessors[name] = describe_preprocessor(fitted)
    minutes = frame["origin_minute"].to_numpy().astype(np.int64)
    # Evaluate on non-overlapping origins only: overlapping 30-minute payoffs would count
    # the same variance six times and inflate every Sharpe by roughly sqrt(6).
    evaluate = test & ((minutes % NON_OVERLAPPING_STEP) == 0)
    information_sets = {
        name: describe_information_set((name,), resolved[name], lift_mask(keep, evaluate))
        for name in INFORMATION_SETS
    }

    implied_variance = np.asarray(frame["b1_iv_30d"].to_numpy(), dtype=np.float64) ** 2
    realized_annual = np.array(
        [annualise_intraday_variance(value) for value in target], dtype=np.float64
    )
    # Half the round-trip option spread, expressed on the annualised variance scale.
    relative_spread = np.asarray(
        frame["b1_median_relative_spread"].to_numpy(), dtype=np.float64
    )
    cost = 0.5 * relative_spread * implied_variance
    returns = np.asarray(frame["ret_30"].to_numpy(), dtype=np.float64)

    results: dict[str, object] = {
        "status": "MEASURED",
        "preprocessing": preprocessors,
        "rows": int(keep.sum()),
        "train_share": train_share,
        "evaluated_rows": int(evaluate.sum()),
        "median_cost_variance_units": float(np.median(cost[evaluate])),
        "median_implied_variance": float(np.median(implied_variance[evaluate])),
        "median_realized_variance": float(np.median(realized_annual[evaluate])),
        "information_sets": information_sets,
    }
    per_model: dict[str, object] = {}
    trials = len(models) * len(INFORMATION_SETS)
    for model_name in models:
        fitter = LADDER[model_name]
        block: dict[str, object] = {}
        for set_name in INFORMATION_SETS:
            forecast = fitter(designs[set_name], target, train)
            forecast_annual = np.array(
                [annualise_intraday_variance(value) for value in forecast], dtype=np.float64
            )
            run = variance_risk_strategy(
                implied_variance[evaluate],
                forecast_annual[evaluate],
                realized_annual[evaluate],
                cost_per_unit=cost[evaluate],
                buffer=buffer,
            )
            metrics = performance_metrics(run.net_pnl, periods_per_year=PERIODS_PER_YEAR)
            gross = performance_metrics(run.gross_pnl, periods_per_year=PERIODS_PER_YEAR)
            per_period_sharpe = (
                metrics.mean / metrics.volatility if metrics.volatility > 0.0 else float("nan")
            )
            utility = risk_management_utility(
                forecast[evaluate],
                target[evaluate],
                returns[evaluate],
                target_variance=float(np.mean(target[train])),
            )
            block[set_name] = {
                "strategy_net": asdict(metrics),
                "strategy_gross_sharpe": gross.sharpe_annual,
                "traded_share": run.traded_share,
                "turnover": run.turnover,
                "break_even_cost": break_even_cost(run.gross_pnl, run.turnover),
                "deflated_sharpe_probability": deflated_sharpe_ratio(
                    per_period_sharpe,
                    trials=trials,
                    observations=metrics.periods,
                    skewness=metrics.skewness,
                    kurtosis=metrics.kurtosis,
                ),
                "risk_utility": asdict(utility),
            }
        per_model[model_name] = block
    results["models"] = per_model
    return results


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--train-share", type=float, default=0.6)
    parser.add_argument("--models", default=",".join(DEFAULT_MODELS))
    parser.add_argument("--buffer", type=float, default=0.0)
    args = parser.parse_args(argv)

    models = tuple(name.strip() for name in str(args.models).split(",") if name.strip())
    panel = load_merged_panel(B0_PANEL, B1_PANEL, B2_PANEL)
    document: dict[str, object] = {
        # Which frozen sets were fitted, how complete they were, and the hash of the
        # registry that decided them. Without it an artifact records a design width and
        # nothing a reader can check that width against.
        "feature_registry": describe_coverage(panel, *CORE_SETS.values()),
        "block": 11,
        "program": "docs/research_program_v2.md",
        "label": "EXPLORATORY_MECHANISM_DISCOVERY",
        "models": list(models),
        "bridge_a_delta_hedged": "NOT_IMPLEMENTED: needs a full quote book through the "
        "holding period; the local tape carries NBBO only at trade instants",
        "non_overlapping_step_minutes": NON_OVERLAPPING_STEP,
        "buffer": args.buffer,
    }
    for role in ("D", "V"):
        document[role] = run_role(
            panel, role=role, train_share=args.train_share, models=models,
            buffer=args.buffer,
        )
    document["economics_sha256"] = canonical_sha256(document)
    document["generated_at_utc"] = datetime.now(UTC).isoformat()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "economics.json").write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    for role in ("D", "V"):
        block = document[role]
        assert isinstance(block, dict)
        print(f"=== role {role}: {block.get('status')} rows={block.get('evaluated_rows')} ===")
        per_model = block.get("models")
        if not isinstance(per_model, dict):
            continue
        for model_name, sets in per_model.items():
            assert isinstance(sets, dict)
            for set_name, stats in sets.items():
                assert isinstance(stats, dict)
                net = stats["strategy_net"]
                utility = stats["risk_utility"]
                assert isinstance(net, dict) and isinstance(utility, dict)
                print(
                    f"  {model_name:<11} {set_name:<9} netSharpe={net['sharpe_annual']:+7.3f} "
                    f"grossSharpe={stats['strategy_gross_sharpe']:+7.3f} "
                    f"traded={stats['traded_share']:.2f} "
                    f"DSR={stats['deflated_sharpe_probability']:.3f} "
                    f"volTE={utility['target_volatility_tracking_error']:.3f} "
                    f"VaR={utility['var_breach_rate']:.3f}"
                )
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
