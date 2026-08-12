"""Fail-closed readiness checks bound to MDS650 target-blind v2.3 inputs.

This module admits only target-blind predictor artefacts, their provenance and
provider-timing limitations. It cannot read realised variance, predictions,
losses, QLIKE, model parameters, or sealed OOS data.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import polars as pl

from mds650.study_design import canonical_sha256

_FORBIDDEN_EXACT = frozenset({"rv30", "qlike", "target", "prediction", "outcome", "loss", "metric"})
_FORBIDDEN_PREFIXES = (
    "rv30_",
    "target_",
    "prediction_",
    "outcome_",
    "loss_",
    "metric_",
)


@dataclass(frozen=True)
class SourceBoundConfirmationReadinessV2Config:
    """Describe one v2.3 source-bound, target-blind readiness assessment.

    Parameters
    ----------
    panel_manifest, preregistration, provider_docs_audit:
        Parsed, sanitized v2.3/v3/provider-documentation records. Each must
        match its corresponding local file exactly.
    panel_manifest_path, provider_docs_audit_path:
        JSON files whose hashes are checked without emitting local paths.
    panel_path, common_path, availability_sidecar_path:
        Target-blind parquet files and the B2 availability sidecar bound by the
        manifest and preregistration.

    Notes
    -----
    This configuration does not contain target values or provider credentials.
    Passing the gate only prepares a successor method freeze; it never permits
    acquisition, model fitting, reconciliation, or out-of-sample access.
    """

    panel_manifest: Mapping[str, Any]
    panel_manifest_path: Path
    preregistration: Mapping[str, Any]
    provider_docs_audit: Mapping[str, Any]
    provider_docs_audit_path: Path
    panel_path: Path
    common_path: Path
    availability_sidecar_path: Path


def build_source_bound_confirmation_readiness_v2(
    config: SourceBoundConfirmationReadinessV2Config,
) -> dict[str, Any]:
    """Build a self-hashed readiness snapshot for source-bound v2.3 inputs.

    Parameters
    ----------
    config:
        Sanitized target-blind files and parsed payloads to validate.

    Returns
    -------
    dict[str, Any]
        A deterministic readiness report. The three safety gates for existing
        reconciliation, OOS access and acquisition are always ``"NO"``.

    Notes
    -----
    A passing report confirms only internal provenance, predictor-only column
    scope and the registered provider-timing limitations. It is not evidence of
    predictive edge, provider delivery latency or a fitted model.
    """
    bound_artifacts = _validate_bound_artifact_integrity(config)
    common_subset = _validate_common_subset(config)
    provider_timing = _validate_provider_timing_boundary(config)
    core_pass = (
        bound_artifacts["status"] == "PASS"
        and common_subset["status"] == "PASS"
        and provider_timing["status"] == "PASS_LIMITATIONS_RETAINED"
    )
    report: dict[str, Any] = {
        "schema_version": "confirmation-readiness-v2.0",
        "status": (
            "PASS_SOURCE_BOUND_METHOD_FREEZE_PREPARATION"
            if core_pass
            else "FAIL_SOURCE_BOUND_READINESS"
        ),
        "scope": "offline_source_bound_target_blind_readiness_only",
        "no_target_or_metric_payload_read": True,
        "model_fit_performed": False,
        "safe_to_reconcile_existing_results": "NO",
        "safe_to_open_or_evaluate_oos": "NO",
        "safe_to_acquire_new_sample": "NO",
        "ready_for_successor_method_freeze": "YES" if core_pass else "NO",
        "bound_artifact_integrity": bound_artifacts,
        "common_subset_validation": common_subset,
        "provider_timing_boundary": provider_timing,
        "required_before_any_oos_access": [
            "successor_method_freeze_bound_to_this_v2_readiness_snapshot",
            "independent_provider_evidence_or_prospectively_operated_receipt_logger",
            "zero_oos_read_access_ledger_at_method_freeze",
            "explicit_human_authorization_for_one_oos_access",
        ],
    }
    report["readiness_sha256"] = canonical_sha256(report)
    return report


def _validate_bound_artifact_integrity(
    config: SourceBoundConfirmationReadinessV2Config,
) -> dict[str, Any]:
    """Validate file hashes and v2.3/v3 provenance bindings without outcomes."""
    manifest = config.panel_manifest
    preregistration = config.preregistration
    failures: list[str] = []
    manifest_path_payload = _read_json_object(config.panel_manifest_path)
    docs_path_payload = _read_json_object(config.provider_docs_audit_path)
    manifest_file_hash = _safe_sha256(config.panel_manifest_path)
    panel_hash = _safe_sha256(config.panel_path)
    common_hash = _safe_sha256(config.common_path)
    sidecar_hash = _safe_sha256(config.availability_sidecar_path)

    if manifest_path_payload != dict(manifest):
        failures.append("PANEL_MANIFEST_PATH_PAYLOAD_MISMATCH")
    if docs_path_payload != dict(config.provider_docs_audit):
        failures.append("PROVIDER_DOCS_AUDIT_PATH_PAYLOAD_MISMATCH")
    _append_manifest_failures(manifest, failures)
    _append_preregistration_failures(preregistration, failures)

    bound_panel = _mapping(preregistration.get("bound_panel"))
    output = _mapping(manifest.get("output"))
    if _string(bound_panel.get("panel_manifest_sha256")) != manifest_file_hash:
        failures.append("PREREGISTRATION_MANIFEST_FILE_HASH_MISMATCH")
    if _string(output.get("panel_sha256")) != panel_hash:
        failures.append("PANEL_FILE_HASH_MISMATCH")
    if _string(output.get("common_complete_sha256")) != common_hash:
        failures.append("COMMON_FILE_HASH_MISMATCH")
    source_hashes = _mapping(manifest.get("source_hashes"))
    if _string(source_hashes.get("b2_availability_sidecar_sha256")) != sidecar_hash:
        failures.append("B2_AVAILABILITY_SIDECAR_HASH_MISMATCH")
    if _string(bound_panel.get("panel_sha256")) != _string(output.get("panel_sha256")):
        failures.append("PREREGISTRATION_PANEL_HASH_BINDING_MISMATCH")
    if _string(bound_panel.get("common_complete_sha256")) != _string(
        output.get("common_complete_sha256")
    ):
        failures.append("PREREGISTRATION_COMMON_HASH_BINDING_MISMATCH")
    if bound_panel.get("row_count") != output.get("row_count"):
        failures.append("PREREGISTRATION_PANEL_ROW_COUNT_BINDING_MISMATCH")
    if bound_panel.get("common_complete_row_count") != output.get("common_complete_row_count"):
        failures.append("PREREGISTRATION_COMMON_ROW_COUNT_BINDING_MISMATCH")
    for key in ("source_hashes", "builder_hashes", "timing_rules", "input_provenance"):
        if bound_panel.get(key) != manifest.get(key):
            failures.append(f"PREREGISTRATION_{key.upper()}_BINDING_MISMATCH")
    if bound_panel.get("panel_builder_source_commit") != manifest.get("source_commit"):
        failures.append("PREREGISTRATION_PANEL_SOURCE_COMMIT_BINDING_MISMATCH")

    return {
        "status": "PASS" if not failures else "FAIL",
        "failure_codes": failures,
        "panel_manifest_sha256_observed": manifest_file_hash,
        "panel_sha256_observed": panel_hash,
        "common_complete_sha256_observed": common_hash,
        "availability_sidecar_sha256_observed": sidecar_hash,
    }


def _append_manifest_failures(payload: Mapping[str, Any], failures: list[str]) -> None:
    """Append explicit failure codes for the v2.3 target-blind manifest boundary."""
    expected = {
        "schema_version": "target-blind-common-predictor-manifest-v2.3",
        "status": "PASS_TARGET_BLIND_INPUTS_RECONCILIATION_REMAINS_BLOCKED",
        "SAFE_TO_OPEN_OR_EVALUATE_OOS": "NO",
        "safe_to_reconcile_existing_results": "NO",
        "model_fit_performed": False,
        "no_target_or_metric_payload_read": True,
    }
    for key, value in expected.items():
        if payload.get(key) != value:
            failures.append(f"PANEL_MANIFEST_{key.upper()}_INVALID")


def _append_preregistration_failures(payload: Mapping[str, Any], failures: list[str]) -> None:
    """Append explicit failure codes for the sealed v3 preregistration boundary."""
    expected = {
        "schema_version": "target-blind-confirmation-preregistration-v3.0",
        "status": "SEALED_SOURCE_BOUND_PRE_METHOD_FREEZE_NOT_AUTHORIZED_FOR_OOS",
        "safe_to_reconcile_existing_results": "NO",
        "safe_to_open_or_evaluate_oos": "NO",
        "model_fit_performed": False,
        "no_target_or_metric_payload_read": True,
        "sealed_result_reconciliation": "BLOCKED",
    }
    for key, value in expected.items():
        if payload.get(key) != value:
            failures.append(f"PREREGISTRATION_{key.upper()}_INVALID")
    recorded_hash = _string(payload.get("preregistration_sha256"))
    unsigned = {key: value for key, value in payload.items() if key != "preregistration_sha256"}
    if recorded_hash != canonical_sha256(unsigned):
        failures.append("PREREGISTRATION_SELF_HASH_INVALID")


def _validate_common_subset(
    config: SourceBoundConfirmationReadinessV2Config,
) -> dict[str, Any]:
    """Require the common file to be the exact complete subset of the panel."""
    failures: list[str] = []
    try:
        panel = pl.read_parquet(config.panel_path)
        common = pl.read_parquet(config.common_path)
    except (OSError, pl.exceptions.PolarsError):
        return {
            "status": "FAIL",
            "failure_codes": ["TARGET_BLIND_PARQUET_UNREADABLE"],
            "panel_row_count": None,
            "common_complete_row_count": None,
        }
    if _contains_outcome_like_columns(panel.columns) or _contains_outcome_like_columns(
        common.columns
    ):
        failures.append("TARGET_BLIND_OUTCOME_LIKE_COLUMN_PRESENT")
    required_columns = {"origin_id", "common_predictor_complete"}
    if not required_columns <= set(panel.columns) or not required_columns <= set(common.columns):
        failures.append("TARGET_BLIND_COMMON_REQUIRED_COLUMNS_MISSING")

    output = _mapping(config.panel_manifest.get("output"))
    if output.get("row_count") != panel.height:
        failures.append("TARGET_BLIND_PANEL_ROW_COUNT_MISMATCH")
    if output.get("common_complete_row_count") != common.height:
        failures.append("TARGET_BLIND_COMMON_ROW_COUNT_MISMATCH")
    if "origin_id" in panel.columns and panel.get_column("origin_id").n_unique() != panel.height:
        failures.append("TARGET_BLIND_PANEL_ORIGIN_ID_DUPLICATE")
    if "origin_id" in common.columns and common.get_column("origin_id").n_unique() != common.height:
        failures.append("TARGET_BLIND_COMMON_ORIGIN_ID_DUPLICATE")
    if not failures:
        if not common.get_column("common_predictor_complete").all():
            failures.append("TARGET_BLIND_COMMON_COMPLETENESS_FLAG_FALSE")
        expected = panel.filter(pl.col("common_predictor_complete")).sort("origin_id")
        observed = common.sort("origin_id")
        if not expected.equals(observed):
            failures.append("TARGET_BLIND_COMMON_NOT_EXACT_SUBSET")
    return {
        "status": "PASS" if not failures else "FAIL",
        "failure_codes": failures,
        "panel_row_count": panel.height,
        "common_complete_row_count": common.height,
    }


def _validate_provider_timing_boundary(
    config: SourceBoundConfirmationReadinessV2Config,
) -> dict[str, Any]:
    """Require the documented limitations rather than upgrading them by inference."""
    audit = config.provider_docs_audit
    failures: list[str] = []
    expected = {
        "schema_version": "provider-timing-official-docs-audit-v1.0",
        "status": "PASS_LIMITATIONS_RECORDED_NO_PIT_SEMANTICS_UPGRADE",
        "SAFE_TO_RECONCILE_EXISTING_RESULTS": "NO",
        "SAFE_TO_OPEN_OR_EVALUATE_OOS": "NO",
        "no_provider_data_requests_performed": True,
        "no_targets_or_predictive_artifacts_read": True,
    }
    for key, value in expected.items():
        if audit.get(key) != value:
            failures.append(f"PROVIDER_DOCS_AUDIT_{key.upper()}_INVALID")
    if _nested_string(audit, "fmp", "provider_semantics_status") != "UNVERIFIED":
        failures.append("FMP_PROVIDER_SEMANTICS_BOUNDARY_INVALID")
    if _nested_string(audit, "unusual_whales", "created_at_status") != "PROXY_ONLY":
        failures.append("UW_CREATED_AT_BOUNDARY_INVALID")
    if _nested_string(audit, "massive", "sip_timestamp_status") != "EVENT_TIME_TECHNICAL_ONLY":
        failures.append("MASSIVE_SIP_TIMESTAMP_BOUNDARY_INVALID")
    historical_availability = _mapping(audit.get("historical_source_availability"))
    if historical_availability.get("status") != "PASS_SEPARATE_FROM_PIT_TIMESTAMP_SEMANTICS":
        failures.append("HISTORICAL_SOURCE_AVAILABILITY_SEPARATION_INVALID")
    fmp_history = _mapping(historical_availability.get("fmp"))
    if (
        fmp_history.get("historical_availability_status") != "PASS_90_OF_90_SESSIONS"
        or fmp_history.get("session_count") != 90
        or fmp_history.get("evidence_sha256")
        != "97c3b57707a953629ff57e485cde918e52ecdd1777a246e84072b5c4150771dc"
    ):
        failures.append("FMP_HISTORICAL_SOURCE_AVAILABILITY_BOUNDARY_INVALID")
    uw_history = _mapping(historical_availability.get("unusual_whales"))
    if (
        uw_history.get("historical_availability_status") != "PASS_90_OF_90_FILE_METADATA"
        or uw_history.get("session_count") != 90
        or uw_history.get("row_level_pit_claim") is not False
        or uw_history.get("evidence_sha256")
        != "244690e15054f518e5d12083e6b81d2bcbfcd8f5f009304f4127cbb5c1c4a3f3"
    ):
        failures.append("UW_HISTORICAL_SOURCE_AVAILABILITY_BOUNDARY_INVALID")
    recorded_hash = _string(audit.get("manifest_sha256"))
    unsigned = {key: value for key, value in audit.items() if key != "manifest_sha256"}
    if recorded_hash != canonical_sha256(unsigned):
        failures.append("PROVIDER_DOCS_AUDIT_SELF_HASH_INVALID")
    return {
        "status": "PASS_LIMITATIONS_RETAINED" if not failures else "FAIL",
        "failure_codes": failures,
        "provider_docs_audit_sha256": recorded_hash,
    }


def _read_json_object(path: Path) -> dict[str, Any] | None:
    """Read one JSON object or return ``None`` without leaking a local path."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _safe_sha256(path: Path) -> str | None:
    """Hash one file incrementally, returning ``None`` for unreadable inputs."""
    try:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return None
    return digest.hexdigest()


def _mapping(value: object) -> Mapping[str, Any]:
    """Return a string-keyed mapping or an empty mapping for invalid input."""
    return value if isinstance(value, Mapping) else {}


def _string(value: object) -> str | None:
    """Return a string only when the supplied value has the expected type."""
    return value if isinstance(value, str) else None


def _nested_string(payload: Mapping[str, Any], key: str, nested_key: str) -> str | None:
    """Return a string from one nested mapping only when both types are valid."""
    return _string(_mapping(payload.get(key)).get(nested_key))


def _contains_outcome_like_columns(columns: list[str]) -> bool:
    """Return whether a target-like field escaped into a target-blind table."""
    return any(
        column.casefold() in _FORBIDDEN_EXACT or column.casefold().startswith(_FORBIDDEN_PREFIXES)
        for column in columns
    )
