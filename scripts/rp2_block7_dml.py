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
from mds650.rp2.panel import (
    B0_FEATURES,
    B1_FEATURES,
    B2_FEATURES,
    VARIANCE_FLOOR,
    build_design,
    chronological_split,
    describe_information_set,
    load_merged_panel,
    session_rank,
    usable_rows,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "artifacts" / "rp2_block7_dml"
B0_PANEL = ROOT / "artifacts" / "rp2_block4_b0" / "b0_panel.parquet"
B1_PANEL = ROOT / "artifacts" / "rp2_block5_surface" / "b1_surface_panel.parquet"
B2_PANEL = ROOT / "artifacts" / "rp2_block6_flow" / "b2_flow_panel.parquet"

#: Economically distinct B2 treatments used for the primary joint test.
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
    nuisance, nuisance_names = build_design(frame, [B0_FEATURES, B1_FEATURES])
    unknown = [name for name in treatments if name not in B2_FEATURES]
    if unknown:
        raise ValueError(f"RP2_DML_UNKNOWN_TREATMENT:{','.join(sorted(unknown))}")
    treatment_map = {name: B2_FEATURES[name] for name in treatments}
    treatment_design, treatment_names = build_design(frame, [treatment_map], intercept=False)
    outcomes = _outcomes(frame)
    sessions = session_rank(frame["session_date"].to_numpy())

    keep = usable_rows(nuisance, np.exp(outcomes["log_rv30"]))
    keep &= np.isfinite(treatment_design).all(axis=1)
    information_sets = {
        "B0+B1": describe_information_set(("B0", "B1"), nuisance_names, keep),
        "B2_treatment": describe_information_set(("B2",), treatment_names, keep),
    }
    if int(keep.sum()) < 1000:
        return {
            "status": "INSUFFICIENT_ROWS",
            "rows": int(keep.sum()),
            "information_sets": information_sets,
        }

    nuisance, treatment_design = nuisance[keep], treatment_design[keep]
    sessions = sessions[keep]
    blocks = time_block_folds(sessions, folds=folds, purge_sessions=1)

    treatment_residual = np.column_stack(
        [
            cross_fitted_residuals(nuisance, treatment_design[:, index], blocks)
            for index in range(treatment_design.shape[1])
        ]
    )
    results: dict[str, object] = {
        "status": "MEASURED",
        "rows": int(keep.sum()),
        "sessions": int(np.unique(sessions).size),
        "nuisance_features": len(nuisance_names),
        "folds": len(blocks),
        "treatments": list(treatment_names),
        "information_sets": information_sets,
    }
    for outcome_name, values in outcomes.items():
        response = values[keep]
        response_residual = cross_fitted_residuals(nuisance, response, blocks)
        try:
            estimate = dml_partial_out(
                response_residual, treatment_residual, sessions, treatment_names
            )
        except ValueError as error:  # pragma: no cover - defensive
            results[outcome_name] = {"status": str(error)}
            continue
        results[outcome_name] = {
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
    parser.add_argument("--folds", type=int, default=5)
    parser.add_argument("--train-share", type=float, default=0.6)
    args = parser.parse_args(argv)

    panel = load_merged_panel(B0_PANEL, B1_PANEL, B2_PANEL)
    document: dict[str, object] = {
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
