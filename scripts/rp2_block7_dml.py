"""Block 7 - the decisive experiment: does B2 survive orthogonalisation against B0+B1?

Partialling-out double machine learning on the merged panel.  Both nuisance functions are
cross-fitted over contiguous time blocks with a one-session purge, and inference is
clustered by session because five-minute origins share overlapping 30-minute targets.

Three outcomes are tested, matching the program's hypotheses:
``log RV30`` (primary), ``log jump30`` (H_B2,J) and ``Delta log RV30`` (H_B2,DeltaRV).
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
from mds650.rp2.dml import cross_fitted_residuals, dml_partial_out, time_block_folds
from mds650.rp2.feature_registry import describe_features, feature_map
from mds650.rp2.panel import (
    B0_FEATURES,
    B1_FEATURES,
    B2_FEATURES,
    VARIANCE_FLOOR,
    build_design,
    chronological_split,
    common_evaluation_mask,
    describe_information_set,
    lift_mask,
    load_merged_panel,
    mask_sha256,
    panel_paths,
    session_rank,
)
from mds650.rp2.preprocessing import describe_preprocessor, fold_design

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "artifacts" / "rp2_block7_dml"

#: Economically distinct B2 treatments used for the primary joint test.
#: The sets this block actually fits: the nuisance is B0+B1 core, and two of the ten
#: treatments are B2-rich, so the provenance has to cover both or it omits a fitted
#: variable.
FITTED_SETS: tuple[str, ...] = ("B0_CORE", "B1_CORE", "B2_CORE", "B2_RICH")

CORE_TREATMENTS: tuple[str, ...] = (
    "b2_5m_vega_flow",
    "b2_5m_gamma_flow",
    "b2_5m_delta_flow",
    "b2_5m_premium",
    "b2_5m_trades",
    "b2_5m_decay_intensity_innovation",
    "b2_5m_d_iv",
    "b2_5m_buy_premium_share",
    "b2_5m_strike_hhi",
    "b2_5m_otm_premium_share",
)


def _outcomes(panel: pl.DataFrame) -> dict[str, npt.NDArray[np.float64]]:
    rv30 = np.asarray(panel["rv30"].to_numpy(), dtype=np.float64)
    jump30 = np.asarray(panel["jump30"].to_numpy(), dtype=np.float64)
    back30 = np.asarray(panel["rv_back_30"].to_numpy(), dtype=np.float64)
    log_rv = np.log(np.maximum(rv30, VARIANCE_FLOOR))
    return {
        "log_rv30": log_rv,
        "log_jump30": np.log(np.maximum(jump30, VARIANCE_FLOOR)),
        "delta_log_rv30": log_rv - np.log(np.maximum(back30, VARIANCE_FLOOR)),
    }


def run_role(
    panel: pl.DataFrame, *, role: str, folds: int, treatments: Sequence[str]
) -> dict[str, object]:
    """Full DML pass for one partition role."""

    frame = panel.filter(pl.col("role") == role).sort(["session_date", "asset", "origin_minute"])
    # build_design still fails closed on a registered feature the panel does not carry.
    # Its matrix is discarded: the design a cross-fit block projects on is imputed and
    # scaled from that block's own training rows.
    _, nuisance_names = build_design(frame, [B0_FEATURES, B1_FEATURES])
    nuisance_features = [*B0_FEATURES, *B1_FEATURES]
    # The DML treatment battery is a set of mechanisms to partial out, not a primary
    # information set, so it resolves against the whole registry: two of its ten channels
    # are B2-rich, and rich means out of the primary contrasts, not out of existence.
    available = feature_map("B2_CORE", "B2_RICH")
    unknown = [name for name in treatments if name not in available]
    if unknown:
        raise ValueError(f"RP2_DML_UNKNOWN_TREATMENT:{','.join(sorted(unknown))}")
    treatment_map = {name: available[name] for name in treatments}
    _, treatment_names = build_design(frame, [treatment_map], intercept=False)
    outcomes = _outcomes(frame)
    sessions = session_rank(frame["session_date"].to_numpy())

    # Target, keys and availability — not "every design column is finite", which made the
    # decisive experiment a complete-case study and dropped exactly the origins a missing
    # secondary feature touched.
    keep = common_evaluation_mask(frame, np.exp(outcomes["log_rv30"]))
    information_sets = {
        "B0+B1": describe_information_set(("B0", "B1"), nuisance_names, keep),
        "B2_treatment": describe_information_set(("B2_treatment",), treatment_names, keep),
    }
    if int(keep.sum()) < 1000:
        return {
            "status": "INSUFFICIENT_ROWS",
            "rows": int(keep.sum()),
            "information_sets": information_sets,
        }

    kept_frame = frame.filter(pl.Series(keep))
    sessions = sessions[keep]
    blocks = time_block_folds(sessions, folds=folds, purge_sessions=1)

    # Imputation and scaling are nuisance parameters too, so both designs are rebuilt from
    # each cross-fit block's own training rows rather than once over the whole sample.
    def nuisance_for(train: npt.NDArray[np.bool_]) -> npt.NDArray[np.float64]:
        return fold_design(kept_frame, nuisance_features, train)[0]

    def treatment_for(train: npt.NDArray[np.bool_]) -> npt.NDArray[np.float64]:
        return fold_design(
            kept_frame, list(treatment_map), train, intercept=False
        )[0]

    # A shape only: the projections below rebuild the design per cross-fit block, and the
    # statistics that produced each of them are recorded per outcome and per block. A
    # full-sample fit here would be an artifact nothing used.
    seed = np.ones(int(keep.sum()), dtype=bool)
    nuisance = nuisance_for(seed)
    treatment_design = treatment_for(seed)
    preprocessing: dict[str, object] = {}

    results: dict[str, object] = {
        "status": "MEASURED",
        "rows": int(keep.sum()),
        "sessions": int(np.unique(sessions).size),
        "nuisance_design_columns": len(nuisance_names),
        "folds": len(blocks),
        "treatments": list(treatment_names),
        "preprocessing": preprocessing,
        "information_sets": information_sets,
    }
    for outcome_name, values in outcomes.items():
        response = values[keep]
        # An outcome can be missing where the design is not: delta_log_rv30 needs a trailing
        # realized variance the coverage floor permits to be absent. A NaN response makes the
        # fold coefficients NaN and the whole estimate collapses, so each outcome is
        # residualised on its own finite rows and the artifact records how many that was.
        finite = np.isfinite(response)
        if int(finite.sum()) < 1000:
            results[outcome_name] = {
                "status": "INSUFFICIENT_FINITE_OUTCOME",
                "rows": int(finite.sum()),
                "evaluation_mask_sha256": mask_sha256(lift_mask(keep, finite)),
                "information_sets": information_sets,
            }
            continue
        outcome_blocks = time_block_folds(sessions[finite], folds=folds, purge_sessions=1)
        outcome_frame = kept_frame.filter(pl.Series(finite))

        fold_statistics: list[dict[str, object]] = []

        def outcome_nuisance(
            train: npt.NDArray[np.bool_],
            _frame: pl.DataFrame = outcome_frame,
            _record: list[dict[str, object]] = fold_statistics,
        ) -> npt.NDArray[np.float64]:
            design, _, fitted = fold_design(_frame, nuisance_features, train)
            _record.append(
                {"train_rows": int(train.sum()), **describe_preprocessor(fitted)}
            )
            return design

        response_residual = cross_fitted_residuals(
            nuisance[finite], response[finite], outcome_blocks, design_builder=outcome_nuisance
        )
        outcome_treatment = np.column_stack(
            [
                cross_fitted_residuals(
                    nuisance[finite],
                    treatment_design[finite, index],
                    outcome_blocks,
                    design_builder=outcome_nuisance,
                )
                for index in range(treatment_design.shape[1])
            ]
        )
        try:
            estimate = dml_partial_out(
                response_residual, outcome_treatment, sessions[finite], treatment_names
            )
        except ValueError as error:  # pragma: no cover - defensive
            results[outcome_name] = {"status": str(error)}
            continue
        # Every cross-fit block appears once per residualised column, so the distinct
        # training masks are what identify the folds.
        preprocessing[outcome_name] = [
            record
            for index, record in enumerate(fold_statistics)
            if record["train_rows"] not in [r["train_rows"] for r in fold_statistics[:index]]
        ]
        results[outcome_name] = {
            "evaluation_mask_sha256": mask_sha256(lift_mask(keep, finite)),
            "preprocessing": preprocessing[outcome_name],
            "joint_wald": estimate.joint_statistic,
            "joint_p_value": estimate.joint_p_value,
            "clusters": estimate.clusters,
            "rows": estimate.rows,
            "coefficients": {
                name: {
                    "theta": float(estimate.theta[index]),
                    "standard_error": float(estimate.standard_error[index]),
                    "t": float(estimate.t_statistic[index]),
                    "p": float(estimate.p_value[index]),
                }
                for index, name in enumerate(estimate.treatment_names)
            },
        }
    return results


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    # A rebuild writes its panels into its own run directory; without this the
    # block would silently read the previous run's panels and label the result
    # with the new run id.
    parser.add_argument("--panel-root", type=Path, default=None)
    parser.add_argument("--folds", type=int, default=5)
    parser.add_argument("--train-share", type=float, default=0.6)
    args = parser.parse_args(argv)

    panels = panel_paths(args.panel_root)
    panel = load_merged_panel(panels["b0"], panels["b1"], panels["b2"])
    document: dict[str, object] = {
        # Which frozen sets were fitted, how complete they were, and the hash of the
        # registry that decided them. Without it an artifact records a design width and
        # nothing a reader can check that width against.
        "feature_registry": describe_features(
            panel,
            [*feature_map("B0_CORE", "B1_CORE", "B2_CORE"), *CORE_TREATMENTS],
            sets=FITTED_SETS,
        ),
        "block": 7,
        "program": "docs/research_program_v2.md",
        "label": "EXPLORATORY_MECHANISM_DISCOVERY",
        "panel_rows": panel.height,
        "core_treatments": list(CORE_TREATMENTS),
        "full_b2_treatment_count": len(B2_FEATURES),
    }
    for role in ("D", "V"):
        document[f"core_{role}"] = run_role(
            panel, role=role, folds=args.folds, treatments=CORE_TREATMENTS
        )
        document[f"full_{role}"] = run_role(
            panel, role=role, folds=args.folds, treatments=tuple(B2_FEATURES)
        )

    # A split marker so downstream blocks can reproduce the same chronological boundary.
    sessions = session_rank(panel["session_date"].to_numpy())
    train, test = chronological_split(sessions, train_share=args.train_share)
    document["split"] = {"train_rows": int(train.sum()), "test_rows": int(test.sum())}
    document["dml_sha256"] = canonical_sha256(document)
    document["generated_at_utc"] = datetime.now(UTC).isoformat()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "dml.json").write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    for key in ("core_D", "core_V", "full_D", "full_V"):
        block = document[key]
        assert isinstance(block, dict)
        print(f"=== {key}: {block.get('status')} rows={block.get('rows')} ===")
        for outcome in ("log_rv30", "log_jump30", "delta_log_rv30"):
            stats = block.get(outcome)
            if not isinstance(stats, dict) or "joint_p_value" not in stats:
                continue
            print(
                f"  {outcome:<16} joint Wald={stats['joint_wald']:10.3f} "
                f"p={stats['joint_p_value']:.3e} clusters={stats['clusters']}"
            )
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
