"""Seal the source-bound v2.3 predictor contract before method freeze."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from mds650.provider_timing_v21 import canonical_sha256

_PANEL_SCHEMA_VERSION = "target-blind-common-predictor-manifest-v2.3"
_PANEL_STATUS = "PASS_TARGET_BLIND_INPUTS_RECONCILIATION_REMAINS_BLOCKED"
_TEMPLATE_SCHEMA_VERSION = "target-blind-confirmation-preregistration-v2.0"
_TEMPLATE_STATUS = "SEALED_PRE_METHOD_FREEZE_NOT_AUTHORIZED_FOR_OOS"
_OUTPUT_SCHEMA_VERSION = "target-blind-confirmation-preregistration-v3.0"
_OUTPUT_STATUS = "SEALED_SOURCE_BOUND_PRE_METHOD_FREEZE_NOT_AUTHORIZED_FOR_OOS"
_EXPECTED_CLAIM_BOUNDARY = {
    "fmp": "TIMESTAMP_RAW_PLUS_1_MINUTE_CONSERVATIVE_STUDY_ASSUMPTION",
    "massive": "SIP_ASOF_ORIGIN_PRIMARY_WITH_60_300_SECOND_RESELECTION_SENSITIVITIES",
    "unusual_whales": "CREATED_AT_OPERATIONAL_AVAILABILITY_PROXY_NOT_PUBLICATION_OR_RECEIPT",
}


def build_sourcebound_preregistration_v3(
    *,
    panel_manifest: Mapping[str, Any],
    template_preregistration: Mapping[str, Any],
    panel_manifest_file_sha256: str,
    template_file_sha256: str,
    source_commit: str,
) -> dict[str, Any]:
    """Build an immutable, target-blind v3 successor-method preregistration.

    Parameters
    ----------
    panel_manifest:
        Parsed v2.3 source-bound predictor manifest. It must retain closed
        reconciliation and OOS gates.
    template_preregistration:
        Parsed, self-hashed v2.0 method-design template. Its methods and nine
        B2 features are copied verbatim; this function does not choose them.
    panel_manifest_file_sha256:
        Byte SHA-256 of the source-bound panel manifest.
    template_file_sha256:
        Byte SHA-256 of the v2.0 template file.
    source_commit:
        Forty-character commit identity of the local sealer source history.

    Returns
    -------
    dict[str, Any]
        Self-hashing v3 preregistration with closed OOS and reconciliation
        gates, a source-bound panel identity, and the unchanged method design.

    Raises
    ------
    ValueError
        If either supplied contract is malformed, changes a closed safety gate,
        has an invalid self-hash, lacks an exact nine-feature B2 definition, or
        receives an invalid identity hash.

    Notes
    -----
    The function consumes metadata only. It never opens predictor Parquet,
    targets, outcomes, predictions, metrics, models, or OOS artefacts.
    """
    _require_sha256(panel_manifest_file_sha256, "TARGET_BLIND_V3_PANEL_MANIFEST_HASH_INVALID")
    _require_sha256(template_file_sha256, "TARGET_BLIND_V3_TEMPLATE_FILE_HASH_INVALID")
    _require_commit(source_commit, "TARGET_BLIND_V3_SOURCE_COMMIT_INVALID")
    _validate_panel_manifest(panel_manifest)
    _validate_template(template_preregistration)

    output = panel_manifest.get("output")
    source_hashes = panel_manifest.get("source_hashes")
    builder_hashes = panel_manifest.get("builder_hashes")
    timing_rules = panel_manifest.get("timing_rules")
    input_provenance = panel_manifest.get("input_provenance")
    assert isinstance(output, Mapping)
    assert isinstance(source_hashes, Mapping)
    assert isinstance(builder_hashes, Mapping)
    assert isinstance(timing_rules, Mapping)
    assert isinstance(input_provenance, Mapping)

    preregistration: dict[str, Any] = {
        "schema_version": _OUTPUT_SCHEMA_VERSION,
        "status": _OUTPUT_STATUS,
        "purpose": "bind_source_bound_target_blind_inputs_before_successor_method_freeze",
        "no_target_or_metric_payload_read": True,
        "model_fit_performed": False,
        "sealed_result_reconciliation": "BLOCKED",
        "safe_to_reconcile_existing_results": "NO",
        "safe_to_open_or_evaluate_oos": "NO",
        "bound_panel": {
            "panel_manifest_sha256": panel_manifest_file_sha256,
            "panel_sha256": output["panel_sha256"],
            "common_complete_sha256": output["common_complete_sha256"],
            "row_count": output["row_count"],
            "common_complete_row_count": output["common_complete_row_count"],
            "source_hashes": deepcopy(dict(source_hashes)),
            "builder_hashes": deepcopy(dict(builder_hashes)),
            "timing_rules": deepcopy(dict(timing_rules)),
            "input_provenance": deepcopy(dict(input_provenance)),
            "panel_builder_source_commit": panel_manifest["source_commit"],
        },
        "method_template_v22_sha256": template_file_sha256,
        "method_template_v22_preregistration_sha256": template_preregistration[
            "preregistration_sha256"
        ],
        "method_template_v22_source_commit": template_preregistration["source_commit"],
        "information_sets": deepcopy(template_preregistration["information_sets"]),
        "fixed_claim_boundary": deepcopy(template_preregistration["fixed_claim_boundary"]),
        "forbidden_before_successor_method_freeze": deepcopy(
            template_preregistration["forbidden_before_successor_method_freeze"]
        ),
        "required_before_any_oos_access": deepcopy(
            template_preregistration["required_before_any_oos_access"]
        ),
        "successor_method_freeze_minimum_contents": deepcopy(
            template_preregistration["successor_method_freeze_minimum_contents"]
        ),
        "source_commit": source_commit,
    }
    preregistration["preregistration_sha256"] = canonical_sha256(preregistration)
    return preregistration


def _validate_panel_manifest(panel_manifest: Mapping[str, Any]) -> None:
    """Require the source-bound manifest to preserve all closed evaluation gates."""
    required = {
        "schema_version": _PANEL_SCHEMA_VERSION,
        "status": _PANEL_STATUS,
        "no_target_or_metric_payload_read": True,
        "model_fit_performed": False,
        "safe_to_reconcile_existing_results": "NO",
        "SAFE_TO_OPEN_OR_EVALUATE_OOS": "NO",
    }
    if any(panel_manifest.get(key) != value for key, value in required.items()):
        raise ValueError("TARGET_BLIND_V3_PANEL_GATE_INVALID")
    for key in ("output", "source_hashes", "builder_hashes", "timing_rules", "input_provenance"):
        if not isinstance(panel_manifest.get(key), Mapping):
            raise ValueError("TARGET_BLIND_V3_PANEL_STRUCTURE_INVALID")
    output = panel_manifest["output"]
    assert isinstance(output, Mapping)
    for key in ("panel_sha256", "common_complete_sha256"):
        value = output.get(key)
        if not isinstance(value, str) or len(value) != 64:
            raise ValueError("TARGET_BLIND_V3_PANEL_OUTPUT_HASH_INVALID")
    for key in ("row_count", "common_complete_row_count"):
        if not isinstance(output.get(key), int) or output[key] <= 0:
            raise ValueError("TARGET_BLIND_V3_PANEL_ROW_COUNT_INVALID")
    if output["common_complete_row_count"] > output["row_count"]:
        raise ValueError("TARGET_BLIND_V3_PANEL_ROW_COUNT_INVALID")
    panel_source_commit = panel_manifest.get("source_commit")
    if not isinstance(panel_source_commit, str):
        raise ValueError("TARGET_BLIND_V3_PANEL_SOURCE_COMMIT_INVALID")
    _require_commit(panel_source_commit, "TARGET_BLIND_V3_PANEL_SOURCE_COMMIT_INVALID")


def _validate_template(template: Mapping[str, Any]) -> None:
    """Require the prior, target-blind method definition to be self-consistent."""
    required = {
        "schema_version": _TEMPLATE_SCHEMA_VERSION,
        "status": _TEMPLATE_STATUS,
        "no_target_or_metric_payload_read": True,
        "model_fit_performed": False,
        "sealed_result_reconciliation": "BLOCKED",
        "safe_to_reconcile_existing_results": "NO",
        "safe_to_open_or_evaluate_oos": "NO",
    }
    if any(template.get(key) != value for key, value in required.items()):
        raise ValueError("TARGET_BLIND_V3_TEMPLATE_GATE_INVALID")
    recorded_hash = template.get("preregistration_sha256")
    unsigned = {key: value for key, value in template.items() if key != "preregistration_sha256"}
    if not isinstance(recorded_hash, str) or canonical_sha256(unsigned) != recorded_hash:
        raise ValueError("TARGET_BLIND_V3_TEMPLATE_SELF_HASH_INVALID")
    information_sets = template.get("information_sets")
    fixed_claim_boundary = template.get("fixed_claim_boundary")
    if (
        not isinstance(information_sets, Mapping)
        or not isinstance(fixed_claim_boundary, Mapping)
        or not isinstance(template.get("bound_panel"), Mapping)
    ):
        raise ValueError("TARGET_BLIND_V3_TEMPLATE_STRUCTURE_INVALID")
    if fixed_claim_boundary != _EXPECTED_CLAIM_BOUNDARY:
        raise ValueError("TARGET_BLIND_V3_TEMPLATE_CLAIM_BOUNDARY_INVALID")
    b2_features = information_sets.get("B2_addition")
    if (
        not isinstance(b2_features, list)
        or len(b2_features) != 9
        or any(not isinstance(feature, str) for feature in b2_features)
        or len(set(b2_features)) != 9
    ):
        raise ValueError("TARGET_BLIND_V3_TEMPLATE_B2_FEATURES_INVALID")
    for key in ("B0", "B1a_addition", "B1b_addition", "B1c_addition"):
        values = information_sets.get(key)
        if (
            not isinstance(values, list)
            or not values
            or any(not isinstance(value, str) for value in values)
        ):
            raise ValueError("TARGET_BLIND_V3_TEMPLATE_INFORMATION_SETS_INVALID")
    template_source_commit = template.get("source_commit")
    if not isinstance(template_source_commit, str):
        raise ValueError("TARGET_BLIND_V3_TEMPLATE_SOURCE_COMMIT_INVALID")
    _require_commit(template_source_commit, "TARGET_BLIND_V3_TEMPLATE_SOURCE_COMMIT_INVALID")


def _require_sha256(value: str, error_code: str) -> None:
    """Reject an invalid lowercase SHA-256 identity."""
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(error_code)


def _require_commit(value: str, error_code: str) -> None:
    """Reject an invalid lowercase forty-character Git commit identity."""
    if len(value) != 40 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(error_code)
