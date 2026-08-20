"""Block 10 - the inference the program says is still missing.

Clark-West for the nested contrasts, Giacomini-White for conditional predictive ability,
and Hansen SPA / White Reality Check over the whole family of model x information-set
combinations, so that the best of many transformations has to survive its own selection.

The sequential alpha-spending budget of decision 64 is reported alongside every p-value:
a raw p-value below 0.05 is not enough when it is the k-th look at the same effect.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import numpy.typing as npt
import polars as pl

from mds650.b1v3_confirmation import canonical_sha256
from mds650.metrics import qlike_losses
from mds650.rp2.feature_registry import assert_segment_coverage, describe_coverage
from mds650.rp2.inference import (
    aggregate_by_session,
    clark_west_terms,
    clustered_mean_test,
    giacomini_white,
    hansen_spa,
    session_block_bootstrap,
)
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

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "artifacts" / "rp2_block10_inference"
B0_PANEL = ROOT / "artifacts" / "rp2_block4_b0" / "b0_panel.parquet"
B1_PANEL = ROOT / "artifacts" / "rp2_block5_surface" / "b1_surface_panel.parquet"
B2_PANEL = ROOT / "artifacts" / "rp2_block6_flow" / "b2_flow_panel.parquet"

INFORMATION_SETS: dict[str, list[dict[str, str]]] = {
    "B0": [B0_FEATURES],
    "B0+B1": [B0_FEATURES, B1_FEATURES],
    "B0+B2": [B0_FEATURES, B2_FEATURES],
    "B0+B1+B2": [B0_FEATURES, B1_FEATURES, B2_FEATURES],
}
NESTED_PAIRS: dict[str, tuple[str, str]] = {
    "b1_over_b0": ("B0", "B0+B1"),
    "b2_over_b1": ("B0+B1", "B0+B1+B2"),
    "b2_over_b0": ("B0", "B0+B2"),
    "total_over_b0": ("B0", "B0+B1+B2"),
}
DEFAULT_MODELS: tuple[str, ...] = ("log_ols", "gamma_glm", "lightgbm")
#: Families whose restricted form really is a parameter restriction of the unrestricted
#: one, which is the precondition Clark-West is derived under.
NESTED_LINEAR_FAMILIES: frozenset[str] = frozenset({"log_ols", "ridge_log"})
#: Decision 64 alpha spending, alpha_k = 0.05 / (k (k+1)); this program is one further look.
ALPHA_SPENDING_STEP = 3

type FloatArray = npt.NDArray[np.float64]


def alpha_budget(step: int) -> float:
    return 0.05 / (step * (step + 1))


def run_role(
    panel: pl.DataFrame, *, role: str, train_share: float, models: Sequence[str]
) -> dict[str, object]:
    frame = panel.filter(pl.col("role") == role).sort(["session_date", "asset", "origin_minute"])
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
    information_sets = {
        name: describe_information_set((name,), resolved[name], lift_mask(keep, test))
        for name in INFORMATION_SETS
    }
    clusters = sessions_rank[test]
    log_target = np.log(np.maximum(target, 1e-12))

    # Conditioning variables for Giacomini-White: ex-ante observable state, taken from the
    # fold-local design rather than raw. Two of the three are registered B0 features, and a
    # raw NaN would be dropped inside the test by its own finite filter — so the conditional
    # statistic would be computed on a feature-selected subsample while the unconditional
    # tests beside it used the recorded common mask. The origin minute is exact and needs no
    # imputation, but is standardised with the same fold statistics for comparability.
    conditioner_features = ["rv_back_30", "dollar_volume_30", "minutes_since_open"]
    conditioners = fold_design(frame, conditioner_features, train, intercept=False)[0][test]

    results: dict[str, object] = {
        "status": "MEASURED",
        "preprocessing": preprocessors,
        "rows": int(keep.sum()),
        "train_share": train_share,
        "test_rows": int(test.sum()),
        "clusters": int(np.unique(clusters).size),
        "information_sets": information_sets,
    }
    all_losses: dict[str, FloatArray] = {}
    per_model: dict[str, object] = {}
    for model_name in models:
        fitter = LADDER[model_name]
        forecasts: dict[str, FloatArray] = {}
        losses: dict[str, FloatArray] = {}
        for set_name in INFORMATION_SETS:
            forecast = fitter(designs[set_name], target, train)
            forecasts[set_name] = forecast[test]
            losses[set_name] = qlike_losses(target[test], forecast[test])
            all_losses[f"{model_name}|{set_name}"] = losses[set_name]
        block: dict[str, object] = {}
        for label, (base, expanded) in NESTED_PAIRS.items():
            # Clark-West is defined on squared error, so it runs on the log scale where
            # the nested models are actually linear in their extra parameters.
            # Clark-West is derived for a linear model whose restricted form is a
            # parameter restriction of the unrestricted one. A boosted tree on a larger
            # feature set is a different function class, not a nested restriction, so the
            # adjustment is not applied there.
            nested_linear = model_name in NESTED_LINEAR_FAMILIES
            if nested_linear:
                terms = clark_west_terms(
                    log_target[test],
                    np.log(np.maximum(forecasts[base], 1e-12)),
                    np.log(np.maximum(forecasts[expanded], 1e-12)),
                    nested_linear=True,
                )
                cw = clustered_mean_test(terms, clusters)
            else:
                cw = None
            difference = losses[base] - losses[expanded]
            gw = giacomini_white(difference, conditioners, clusters)
            session_means, _ = aggregate_by_session(difference, clusters)
            blocked = session_block_bootstrap(session_means)
            block[label] = {
                "clark_west_applicable": nested_linear,
                "clark_west_mean": cw.mean if cw else None,
                "clark_west_t": cw.t_statistic if cw else None,
                "clark_west_p_one_sided": cw.p_value_one_sided if cw else None,
                "session_blocked_delta": blocked["estimate"],
                "session_blocked_ci_low": blocked["ci_low"],
                "session_blocked_ci_high": blocked["ci_high"],
                "session_blocked_p": blocked["p_value_two_sided"],
                "sessions": blocked["sessions"],
                "giacomini_white_wald": gw.wald,
                "giacomini_white_p": gw.p_value,
                "unconditional_delta_qlike": float(np.mean(difference)),
            }
        per_model[model_name] = block
    results["nested_tests"] = per_model

    # SPA / Reality Check: every model x information set against the plain B0 benchmark.
    benchmark = all_losses[f"{models[0]}|B0"]
    candidates = {name: values for name, values in all_losses.items() if not name.endswith("|B0")}
    spa = hansen_spa(benchmark, candidates, repetitions=1000, seed=650)
    results["superior_predictive_ability"] = {
        "benchmark": f"{models[0]}|B0",
        "best_model": spa.best_model,
        "best_mean_delta_qlike": spa.best_mean_difference,
        "spa_p_value": spa.spa_p_value,
        "reality_check_p_value": spa.reality_check_p_value,
        "candidates": spa.candidates,
    }
    return results


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--train-share", type=float, default=0.6)
    parser.add_argument("--models", default=",".join(DEFAULT_MODELS))
    args = parser.parse_args(argv)

    models = tuple(name.strip() for name in str(args.models).split(",") if name.strip())
    panel = load_merged_panel(B0_PANEL, B1_PANEL, B2_PANEL)
    document: dict[str, object] = {
        # Which frozen sets were fitted, how complete they were, and the hash of the
        # registry that decided them. Without it an artifact records a design width and
        # nothing a reader can check that width against.
        "feature_registry": describe_coverage(panel, *CORE_SETS.values()),
        "block": 10,
        "program": "docs/research_program_v2.md",
        "label": "EXPLORATORY_MECHANISM_DISCOVERY",
        "models": list(models),
        "alpha_spending_step": ALPHA_SPENDING_STEP,
        "alpha_budget": alpha_budget(ALPHA_SPENDING_STEP),
    }
    for role in ("D", "V"):
        document[role] = run_role(panel, role=role, train_share=args.train_share, models=models)
    document["inference_sha256"] = canonical_sha256(document)
    document["generated_at_utc"] = datetime.now(UTC).isoformat()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "inference.json").write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"alpha budget at step {ALPHA_SPENDING_STEP}: {alpha_budget(ALPHA_SPENDING_STEP):.5f}")
    for role in ("D", "V"):
        block = document[role]
        assert isinstance(block, dict)
        print(f"=== role {role}: {block.get('status')} clusters={block.get('clusters')} ===")
        nested = block.get("nested_tests")
        if isinstance(nested, dict):
            for model_name, pairs in nested.items():
                assert isinstance(pairs, dict)
                for label, stats in pairs.items():
                    assert isinstance(stats, dict)
                    cw_text = (
                        f"CW t={stats['clark_west_t']:+6.2f} "
                        f"p={stats['clark_west_p_one_sided']:.4f}"
                        if stats.get("clark_west_applicable")
                        else "CW n/a (not nested linear)"
                    )
                    print(
                        f"  {model_name:<11} {label:<14} {cw_text}  "
                        f"GW p={stats['giacomini_white_p']:.4f}  "
                        f"session dQLIKE={stats['session_blocked_delta']:+.5f} "
                        f"p={stats['session_blocked_p']:.4f} n={stats['sessions']:.0f}"
                    )
        spa = block.get("superior_predictive_ability")
        if isinstance(spa, dict):
            print(
                f"  SPA best={spa['best_model']} delta={spa['best_mean_delta_qlike']:+.5f} "
                f"SPA p={spa['spa_p_value']:.4f} RC p={spa['reality_check_p_value']:.4f}"
            )
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
