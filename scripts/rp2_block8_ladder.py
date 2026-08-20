"""Block 8 - the model ladder over the four contrasts registered by decision 65.

Every model family is fitted on four nested information sets - B0, B0+B1, B0+B2 and
B0+B1+B2 - on identical rows, and the five estimands are formed from the resulting QLIKE
losses:

    Delta_B1        = L(B0)       - L(B0+B1)
    Delta_B2|B1     = L(B0+B1)    - L(B0+B1+B2)
    Delta_B2|B0     = L(B0)       - L(B0+B2)
    Delta_Total     = L(B0)       - L(B0+B1+B2)
    Delta_Interaction = Delta_Total - Delta_B1 - Delta_B2|B0

Selection happens only in D and V.  Every contrast is reported raw and after
Mincer-Zarnowitz recalibration of the baseline, because Block 4 showed the baseline
carries an era-dependent level bias that an added information set could otherwise appear
to repair.
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
from mds650.metrics import holm_adjust, paired_day_bootstrap, qlike_losses
from mds650.rp2.baseline import mincer_zarnowitz
from mds650.rp2.feature_registry import assert_segment_coverage, describe_coverage
from mds650.rp2.ladder import (
    INDEPENDENT_FAMILIES,
    LADDER,
    PRIMARY_MODELS,
    partial_pooling,
)
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
DEFAULT_OUTPUT = ROOT / "artifacts" / "rp2_block8_ladder"
B0_PANEL = ROOT / "artifacts" / "rp2_block4_b0" / "b0_panel.parquet"
B1_PANEL = ROOT / "artifacts" / "rp2_block5_surface" / "b1_surface_panel.parquet"
B2_PANEL = ROOT / "artifacts" / "rp2_block6_flow" / "b2_flow_panel.parquet"

INFORMATION_SETS: dict[str, list[dict[str, str]]] = {
    "B0": [B0_FEATURES],
    "B0+B1": [B0_FEATURES, B1_FEATURES],
    "B0+B2": [B0_FEATURES, B2_FEATURES],
    "B0+B1+B2": [B0_FEATURES, B1_FEATURES, B2_FEATURES],
}
CONTRASTS: dict[str, tuple[str, str]] = {
    "delta_b1": ("B0", "B0+B1"),
    "delta_b2_given_b1": ("B0+B1", "B0+B1+B2"),
    "delta_b2_given_b0": ("B0", "B0+B2"),
    "delta_total": ("B0", "B0+B1+B2"),
}

type FloatArray = npt.NDArray[np.float64]


def _recalibrate(
    forecast: FloatArray, target: FloatArray, train: npt.NDArray[np.bool_]
) -> FloatArray:
    """Apply the training-period Mincer-Zarnowitz correction to a forecast."""

    calibration = mincer_zarnowitz(target[train], forecast[train])
    corrected = np.exp(
        calibration.intercept + calibration.slope * np.log(np.maximum(forecast, 1e-12))
    )
    return np.asarray(corrected, dtype=np.float64)


def _contrast(
    losses: dict[str, FloatArray], sessions: npt.NDArray[np.str_], base: str, expanded: str
) -> dict[str, float]:
    difference = losses[base] - losses[expanded]
    frame = pl.DataFrame({"session_date": sessions, "loss_difference": difference})
    boot = paired_day_bootstrap(frame, repetitions=2000, seed=650)
    return {
        "delta": float(boot["estimate"]),
        "ci_low": float(boot["ci_low"]),
        "ci_high": float(boot["ci_high"]),
        "p_value": float(boot["p_value_two_sided"]),
        "clusters": float(boot["clusters"]),
    }


def run_role(
    panel: pl.DataFrame, *, role: str, train_share: float, models: Sequence[str]
) -> dict[str, object]:
    """Fit every family on every information set and form the five estimands."""

    frame = panel.filter(pl.col("role") == role).sort(
        ["session_date", "asset", "origin_minute"]
    )
    target = np.asarray(frame["rv30"].to_numpy(), dtype=np.float64)
    sessions_rank = session_rank(frame["session_date"].to_numpy())

    # build_design still fails closed on a registered feature the panel does not carry; its
    # matrix is discarded, because the design a fold fits is built by the preprocessor from
    # that fold's own training statistics.
    resolved: dict[str, tuple[str, ...]] = {}
    features: dict[str, list[str]] = {}
    for name, maps in INFORMATION_SETS.items():
        _, resolved[name] = build_design(frame, maps)
        features[name] = [column for mapping in maps for column in mapping]
    role_frame = frame
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

    frame = frame.filter(pl.Series(keep))
    target = target[keep]
    sessions_rank = sessions_rank[keep]
    session_labels = frame["session_date"].to_numpy()
    assets = frame["asset"].to_numpy()
    train, test = chronological_split(sessions_rank, train_share=train_share)
    # One design per information set, imputed and scaled from this fold's training rows.
    designs: dict[str, FloatArray] = {}
    preprocessors: dict[str, object] = {}
    for name in INFORMATION_SETS:
        designs[name], _, fitted = fold_design(frame, features[name], train)
        preprocessors[name] = describe_preprocessor(fitted)
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
    information_sets = {
        name: describe_information_set((name,), resolved[name], lift_mask(keep, test))
        for name in INFORMATION_SETS
    }

    results: dict[str, object] = {
        "status": "MEASURED",
        "rows": int(keep.sum()),
        "train_share": train_share,
        "train_rows": int(train.sum()),
        "test_rows": int(test.sum()),
        "sessions": int(np.unique(sessions_rank).size),
        "assets": sorted({str(a) for a in assets}),
        "design_columns": {name: designs[name].shape[1] for name in INFORMATION_SETS},
        "preprocessing": preprocessors,
        "information_sets": information_sets,
    }
    per_model: dict[str, object] = {}
    for model_name in models:
        fitter = LADDER[model_name]
        losses: dict[str, FloatArray] = {}
        losses_recalibrated: dict[str, FloatArray] = {}
        qlike_levels: dict[str, float] = {}
        for set_name in INFORMATION_SETS:
            design = designs[set_name]
            forecast = fitter(design, target, train)
            losses[set_name] = qlike_losses(target[test], forecast[test])
            recalibrated = _recalibrate(forecast, target, train)
            losses_recalibrated[set_name] = qlike_losses(target[test], recalibrated[test])
            qlike_levels[set_name] = float(np.mean(losses[set_name]))
        contrasts: dict[str, object] = {}
        raw_p: dict[str, float] = {}
        for label, (base, expanded) in CONTRASTS.items():
            stats = _contrast(losses, session_labels[test], base, expanded)
            stats_recalibrated = _contrast(
                losses_recalibrated, session_labels[test], base, expanded
            )
            contrasts[label] = {"raw": stats, "recalibrated": stats_recalibrated}
            raw_p[label] = stats["p_value"]
        interaction = (
            float(contrasts["delta_total"]["raw"]["delta"])  # type: ignore[index]
            - float(contrasts["delta_b1"]["raw"]["delta"])  # type: ignore[index]
            - float(contrasts["delta_b2_given_b0"]["raw"]["delta"])  # type: ignore[index]
        )
        per_model[model_name] = {
            "family": INDEPENDENT_FAMILIES[model_name],
            "qlike": qlike_levels,
            "contrasts": contrasts,
            "delta_interaction": interaction,
            "holm_adjusted_p": holm_adjust(raw_p),
        }
    results["models"] = per_model

    # Level 3: hierarchical partial pooling of per-asset offsets on the best smooth model.
    design = designs["B0+B1+B2"]
    forecast = LADDER["log_ols"](design, target, train)
    residual = np.log(np.maximum(target, 1e-12)) - np.log(np.maximum(forecast, 1e-12))
    asset_index = np.unique(assets, return_inverse=True)[1].astype(np.int64)
    pooled = partial_pooling(residual, asset_index, train)
    pooled_forecast = forecast * np.exp(pooled.apply(asset_index))
    results["hierarchical_partial_pooling"] = {
        "between_variance": pooled.between_variance,
        "qlike_without_pooling": float(np.mean(qlike_losses(target[test], forecast[test]))),
        "qlike_with_pooling": float(
            np.mean(qlike_losses(target[test], pooled_forecast[test]))
        ),
        "asset_offsets": {
            str(np.unique(assets)[index]): value for index, value in pooled.offsets.items()
        },
    }
    return results


def assert_primary_models(models: Sequence[str]) -> None:
    """Refuse a run that would report a ladder without one of the deciding families.

    The contract freezes three families and the programme's conclusions are read off them.
    A run that quietly dropped one would still produce an artifact, and the artifact would
    look complete.
    """

    fitted = set(models)
    for name in PRIMARY_MODELS:
        if name not in fitted:
            raise ValueError(f"RP2_BLOCK8_PRIMARY_MODEL_MISSING:{name}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--train-share", type=float, default=0.6)
    parser.add_argument("--models", default=",".join(LADDER))
    args = parser.parse_args(argv)

    models = tuple(name.strip() for name in str(args.models).split(",") if name.strip())
    assert_primary_models(models)
    panel = load_merged_panel(B0_PANEL, B1_PANEL, B2_PANEL)
    document: dict[str, object] = {
        # Which frozen sets were fitted, how complete they were, and the hash of the
        # registry that decided them. Without it an artifact records a design width and
        # nothing a reader can check that width against.
        "feature_registry": describe_coverage(panel, *CORE_SETS.values()),
        "block": 8,
        "program": "docs/research_program_v2.md",
        "label": "EXPLORATORY_MECHANISM_DISCOVERY",
        "decision": 65,
        "models": list(models),
        # The families the research contract decides on. Everything else in the ladder
        # is robustness: it can move a conclusion only by contradicting these three.
        "primary_models": list(PRIMARY_MODELS),
        "information_sets": list(INFORMATION_SETS),
        "level_4_sequence_models": "NOT_RUN: no deep-learning stack installed; also gated "
        "by the program behind a demonstrated tabular failure",
    }
    for role in ("D", "V"):
        document[role] = run_role(
            panel, role=role, train_share=args.train_share, models=models
        )
    document["ladder_sha256"] = canonical_sha256(document)
    document["generated_at_utc"] = datetime.now(UTC).isoformat()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "ladder.json").write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    for role in ("D", "V"):
        block = document[role]
        assert isinstance(block, dict)
        print(f"=== role {role} ({block.get('status')}, rows={block.get('rows')}) ===")
        per_model = block.get("models")
        if not isinstance(per_model, dict):
            continue
        for model_name, stats in per_model.items():
            assert isinstance(stats, dict)
            qlike = stats["qlike"]
            contrasts = stats["contrasts"]
            assert isinstance(qlike, dict) and isinstance(contrasts, dict)
            print(f"  {model_name:<17} B0={qlike['B0']:.5f} B0B1B2={qlike['B0+B1+B2']:.5f}")
            for label, values in contrasts.items():
                assert isinstance(values, dict)
                raw = values["raw"]
                print(
                    f"      {label:<20} {raw['delta']:+.5f} "
                    f"[{raw['ci_low']:+.5f},{raw['ci_high']:+.5f}] p={raw['p_value']:.4f}"
                )
            print(f"      delta_interaction    {stats['delta_interaction']:+.5f}")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
