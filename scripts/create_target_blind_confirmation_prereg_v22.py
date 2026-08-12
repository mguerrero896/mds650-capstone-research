"""Seal the next MDS650 confirmation preflight from target-blind artefacts.

This script is intentionally not a model runner.  It binds the corrected common
predictor panel and timing contracts for a future method freeze while retaining
the explicit prohibition on sealed-result reconciliation and OOS access.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mds650.phase6 import (  # noqa: E402
    B0V2_FEATURES,
    B1V2A_FEATURES,
    B1V2B_FEATURES,
    B1V2C_FEATURES,
    B2V2_FEATURES,
)

PANEL_MANIFEST = (
    ROOT / "artifacts" / "target_blind_v22" / "target_blind_common_predictor_manifest_v22.json"
)
OUTPUT = ROOT / "artifacts" / "target_blind_v22" / "next_confirmation_preregistration_v2.json"


def canonical_sha256(value: Mapping[str, Any]) -> str:
    """Return a deterministic SHA-256 over one JSON-compatible mapping.

    Parameters
    ----------
    value:
        Mapping to encode with sorted keys and compact separators.

    Returns
    -------
    str
        Lowercase 64-character SHA-256 digest.
    """
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def build_preregistration(panel_manifest: Mapping[str, Any]) -> dict[str, Any]:
    """Build a successor preflight with no outcome or method result content.

    Parameters
    ----------
    panel_manifest:
        Validated v2.2 target-blind common-predictor manifest.

    Returns
    -------
    dict[str, Any]
        Self-hashing pre-method-freeze registration.  It names the fixed
        information sets and gates but does not select a model or report an
        evaluation result.

    Raises
    ------
    ValueError
        If the incoming manifest is not the expected target-blind, blocked
        v2.2 artefact.
    """
    _validate_panel_manifest(panel_manifest)
    preregistration: dict[str, Any] = {
        "schema_version": "target-blind-confirmation-preregistration-v2.0",
        "status": "SEALED_PRE_METHOD_FREEZE_NOT_AUTHORIZED_FOR_OOS",
        "purpose": "bind_corrected_target_blind_inputs_before_successor_method_freeze",
        "no_target_or_metric_payload_read": True,
        "model_fit_performed": False,
        "sealed_result_reconciliation": "BLOCKED",
        "safe_to_reconcile_existing_results": "NO",
        "safe_to_open_or_evaluate_oos": "NO",
        "bound_panel": {
            "panel_sha256": panel_manifest["output"]["panel_sha256"],
            "row_count": panel_manifest["output"]["row_count"],
            "common_complete_row_count": panel_manifest["output"]["common_complete_row_count"],
            "source_hashes": panel_manifest["source_hashes"],
            "builder_hashes": panel_manifest["builder_hashes"],
            "timing_rules": panel_manifest["timing_rules"],
        },
        "information_sets": {
            "B0": list(B0V2_FEATURES),
            "B1a_addition": list(B1V2A_FEATURES),
            "B1b_addition": list(B1V2B_FEATURES),
            "B1c_addition": list(B1V2C_FEATURES),
            "B2_addition": list(B2V2_FEATURES),
        },
        "fixed_claim_boundary": {
            "fmp": "TIMESTAMP_RAW_PLUS_1_MINUTE_CONSERVATIVE_STUDY_ASSUMPTION",
            "massive": "SIP_ASOF_ORIGIN_PRIMARY_WITH_60_300_SECOND_RESELECTION_SENSITIVITIES",
            "unusual_whales": (
                "CREATED_AT_OPERATIONAL_AVAILABILITY_PROXY_NOT_PUBLICATION_OR_RECEIPT"
            ),
        },
        "forbidden_before_successor_method_freeze": [
            "reconcile_or_read_pre_v22_sealed_results",
            "inspect_or_read_oos_outcomes_or_predictions",
            "fit_or_tune_a_model",
            "compute_qlike_or_any_predictive_metric",
            "change_assets_features_or_methods_for_a_favorable_sign",
            "add_rl_or_deep_learning",
            "modify_canonical_input_hashes",
        ],
        "required_before_any_oos_access": [
            "validate_bound_panel_and_source_hashes",
            "verify_zero_oos_reads_at_method_freeze",
            "freeze_temporal_splits_estimands_uncertainty_and_multiplicity_without_outcomes",
            "document_literature_evidence_by_the_literature_owner",
            "explicit_human_authorization_for_one_oos_access",
        ],
        "successor_method_freeze_minimum_contents": [
            "bound_panel_sha256",
            "temporal_train_validation_holdout_definition",
            "B1a_primary_and_B1b_B1c_robustness_role",
            "B0_B1a_and_B2_nested_contrasts",
            "QLIKE_primary_MAE_RMSE_secondary",
            "paired_day_cluster_bootstrap_and_Holm_policy",
            "MDE_estimated_from_development_only",
            "no_recalibration_no_feature_search_after_holdout_access",
        ],
        "source_commit": _git_commit(),
    }
    preregistration["preregistration_sha256"] = canonical_sha256(preregistration)
    return preregistration


def _validate_panel_manifest(panel_manifest: Mapping[str, Any]) -> None:
    """Fail closed unless the input is the expected blocked target-blind panel."""
    required = {
        "schema_version": "target-blind-common-predictor-manifest-v2.2",
        "status": "PASS_TARGET_BLIND_INPUTS_RECONCILIATION_REMAINS_BLOCKED",
        "no_target_or_metric_payload_read": True,
        "model_fit_performed": False,
        "safe_to_reconcile_existing_results": "NO",
    }
    if any(panel_manifest.get(key) != value for key, value in required.items()):
        raise ValueError("TARGET_BLIND_V22_PREREGISTRATION_PANEL_MANIFEST_INVALID")
    for nested in ("source_hashes", "builder_hashes", "timing_rules", "output"):
        if not isinstance(panel_manifest.get(nested), Mapping):
            raise ValueError("TARGET_BLIND_V22_PREREGISTRATION_PANEL_MANIFEST_INVALID")


def _git_commit() -> str:
    """Return the local Git commit without contacting a remote."""
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    """Write deterministic JSON atomically to a local repository artefact."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def main(argv: Sequence[str] | None = None) -> int:
    """Create the self-hashing, non-evaluative successor preflight."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panel-manifest", type=Path, default=PANEL_MANIFEST)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args(argv)
    try:
        panel_manifest = json.loads(args.panel_manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("TARGET_BLIND_V22_PANEL_MANIFEST_UNREADABLE") from error
    if not isinstance(panel_manifest, Mapping):
        raise ValueError("TARGET_BLIND_V22_PANEL_MANIFEST_INVALID")
    preregistration = build_preregistration(panel_manifest)
    _write_json_atomic(args.output, preregistration)
    print("TARGET_BLIND_CONFIRMATION_PREREGISTRATION=SEALED")
    print("SAFE_TO_OPEN_OR_EVALUATE_OOS=NO")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
