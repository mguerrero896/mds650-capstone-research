"""Fail-closed, target-blind provider-timing policy reconciliation.

This module consumes only the registered timing contracts and target-blind
sidecars named by :class:`ProviderTimingEvidencePolicyGateV1Config`.  It does
not inspect targets, outcomes, predictions, metrics, model artefacts, sealed
results, or OOS payloads, and it makes no provider request.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

POLICY_SCHEMA_VERSION = "provider-timing-evidence-policy-gate-v1.0"
_SECRET_VALUE_PATTERN = re.compile(r"(?i)(api[_-]?key|authorization|bearer|password|secret)\s*[:=]")
_PERSONAL_PATH_PATTERN = re.compile(r"(?i)(?:[a-z]:[\\/]|/users/|/home/)")
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class ProviderTimingEvidencePolicyGateV1Config:
    """Bind the explicit, target-blind evidence set for policy reconciliation.

    Every input is a pre-existing documentation record or target-blind timing
    artefact.  The resulting gate distinguishes registered-assumption evidence
    from authorization to reconcile sealed results, open OOS, acquire a new
    historical sample, or operate a prospective receipt logger.
    """

    provider_timing_gate_amendment_path: Path
    methodology_decisions_path: Path
    pit_reconciliation_addendum_path: Path
    confirmation_protocol_path: Path
    pit_contract_v22_path: Path
    pit_v22_decision_ledger_path: Path
    pit_reconciliation_gate_v21_path: Path
    massive_reselection_path: Path
    uw_anomaly_path: Path
    official_docs_audit_path: Path
    b2_availability_manifest_v22_path: Path
    target_blind_manifest_v23_path: Path
    preregistration_v3_path: Path
    confirmation_readiness_v2_path: Path


def build_provider_timing_evidence_policy_gate_v1(
    config: ProviderTimingEvidencePolicyGateV1Config,
) -> dict[str, Any]:
    """Build the deterministic evidence-scoped policy gate.

    The v1 amendment makes frozen canonical timing evidence interpretable under
    registered conservative assumptions.  The later v2.1/v2.2/v2.3 evidence
    does not, however, authorize reconciliation of sealed pre-v2.2 results.
    This function therefore always preserves literal ``NO`` for existing sealed
    result reconciliation and OOS access.  Acquisition and prospective capture
    retain their independent, unmet timing preconditions.

    Raises
    ------
    FileNotFoundError
        If a required explicitly configured evidence input is unavailable.
    ValueError
        If an input hash, schema, safety gate, source binding, or documentary
        boundary is inconsistent.  Error messages intentionally contain only
        stable reason codes, never local paths or file content.
    """
    texts = {
        "amendment": _read_text(config.provider_timing_gate_amendment_path, "POLICY_AMENDMENT"),
        "methodology": _read_text(
            config.methodology_decisions_path, "POLICY_METHODOLOGY_DECISIONS"
        ),
        "addendum": _read_text(
            config.pit_reconciliation_addendum_path, "POLICY_RECONCILIATION_ADDENDUM"
        ),
        "confirmation_protocol": _read_text(
            config.confirmation_protocol_path, "POLICY_CONFIRMATION_PROTOCOL"
        ),
        "contract_v22": _read_text(config.pit_contract_v22_path, "POLICY_PIT_CONTRACT_V22"),
        "ledger_v22": _read_text(
            config.pit_v22_decision_ledger_path, "POLICY_PIT_V22_DECISION_LEDGER"
        ),
    }
    _validate_documentary_boundaries(texts)

    pit_gate = _read_json_object(
        config.pit_reconciliation_gate_v21_path, "POLICY_PIT_RECONCILIATION_GATE_V21"
    )
    massive = _read_json_object(config.massive_reselection_path, "POLICY_MASSIVE_RESELECTION")
    uw = _read_json_object(config.uw_anomaly_path, "POLICY_UW_ANOMALY")
    docs_audit = _read_json_object(config.official_docs_audit_path, "POLICY_OFFICIAL_DOCS_AUDIT")
    b2_manifest = _read_json_object(
        config.b2_availability_manifest_v22_path, "POLICY_B2_AVAILABILITY_MANIFEST_V22"
    )
    target_blind_manifest = _read_json_object(
        config.target_blind_manifest_v23_path, "POLICY_TARGET_BLIND_MANIFEST_V23"
    )
    preregistration = _read_json_object(config.preregistration_v3_path, "POLICY_PREREGISTRATION")
    readiness = _read_json_object(config.confirmation_readiness_v2_path, "POLICY_READINESS")

    pit_gate_hash = _validate_pit_reconciliation_gate(pit_gate)
    massive_hash = _validate_massive_reselection(massive)
    uw_hash = _validate_uw_anomaly(uw)
    docs_audit_hash = _validate_official_docs_audit(docs_audit)
    b2_sidecar_hash = _validate_b2_availability_manifest(b2_manifest)
    _validate_target_blind_manifest(
        target_blind_manifest=target_blind_manifest,
        pit_gate_file_sha256=_file_sha256(
            config.pit_reconciliation_gate_v21_path, "POLICY_PIT_RECONCILIATION_GATE_V21"
        ),
        massive_file_sha256=_file_sha256(
            config.massive_reselection_path, "POLICY_MASSIVE_RESELECTION"
        ),
        b2_manifest_file_sha256=_file_sha256(
            config.b2_availability_manifest_v22_path, "POLICY_B2_AVAILABILITY_MANIFEST_V22"
        ),
    )
    _validate_preregistration(
        preregistration=preregistration,
        target_blind_manifest=target_blind_manifest,
        target_blind_manifest_file_sha256=_file_sha256(
            config.target_blind_manifest_v23_path, "POLICY_TARGET_BLIND_MANIFEST_V23"
        ),
    )
    _validate_readiness(readiness=readiness, docs_audit_hash=docs_audit_hash)

    document: dict[str, Any] = {
        "schema_version": POLICY_SCHEMA_VERSION,
        "status": "PASS_EVIDENCE_SCOPED_POLICY_FAIL_CLOSED",
        "scope": "offline_target_blind_provider_timing_policy_only",
        "policy_resolution": (
            "LITERAL_RECONCILIATION_NO_REMAINS_CURRENT_FOR_SEALED_PRE_V22_RESULTS"
        ),
        "existing_evidence_under_registered_assumptions": {
            "status": "VALID_UNDER_REGISTERED_TIMING_ASSUMPTIONS",
            "interpretation_scope": "FROZEN_CANONICAL_EVIDENCE_ONLY",
            "does_not_authorize_sealed_result_reconciliation": True,
        },
        "existing_sealed_result_reconciliation": {
            "status": "BLOCKED",
            "safe_to_reconcile_existing_results": "NO",
            "reason_codes": [
                "V22_SIDECAR_REQUIRES_NEW_TARGET_BLIND_PANEL",
                "V23_SOURCE_BOUND_PANEL_DOES_NOT_RECONCILE_SEALED_LEGACY_RESULTS",
            ],
        },
        "oos_access": {
            "status": "BLOCKED",
            "safe_to_open_or_evaluate_oos": "NO",
            "required_before_any_access": "SEPARATE_METHOD_FREEZE_AND_EXPLICIT_HUMAN_AUTHORIZATION",
        },
        "new_historical_acquisition": {
            "status": "GO_AFTER_DATE_LEVEL_PIT_PREFLIGHT",
            "current_authorization": "NO",
            "timing_precondition": "DATE_LEVEL_PIT_PREFLIGHT",
            "not_oos_authorization": True,
        },
        "prospective_capture": {
            "status": "GO_AFTER_RECEIPT_LOGGER_VALIDATED",
            "current_authorization": "NO",
            "timing_precondition": "VALIDATED_RECEIPT_LOGGER",
            "not_oos_authorization": True,
        },
        "timing_claim_boundary": {
            "fmp": "REGISTERED_PLUS_1_MINUTE_WITH_PLUS_2_MINUTE_SENSITIVITY",
            "massive": "SIP_EVENT_TIME_TECHNICAL_ONLY",
            "unusual_whales": "CREATED_AT_PROXY_ONLY",
            "universal_provider_latency_claim": "NOT_SUPPORTED",
        },
        "no_provider_http_requests_performed": True,
        "no_target_or_metric_payload_read": True,
        "no_oos_or_predictive_artifacts_read": True,
        "model_fit_performed": False,
        "secret_values_emitted": False,
        "personal_paths_emitted": False,
        "source_evidence": [
            _evidence_record(
                role="PROVIDER_TIMING_GATE_AMENDMENT_V1",
                logical_path="docs/provider_timing_gate_amendment_v1.md",
                source_path=config.provider_timing_gate_amendment_path,
                semantic_sha256=None,
            ),
            _evidence_record(
                role="METHODOLOGY_DECISIONS",
                logical_path="docs/methodology_decisions.md",
                source_path=config.methodology_decisions_path,
                semantic_sha256=None,
            ),
            _evidence_record(
                role="PIT_RECONCILIATION_ADDENDUM_V21",
                logical_path="docs/pit_reconciliation_gate_v21_addendum_20260812.md",
                source_path=config.pit_reconciliation_addendum_path,
                semantic_sha256=None,
            ),
            _evidence_record(
                role="CONFIRMATION_PROTOCOL_V2_SOURCEBOUND",
                logical_path="docs/confirmation_protocol_v2_sourcebound.md",
                source_path=config.confirmation_protocol_path,
                semantic_sha256=None,
            ),
            _evidence_record(
                role="PIT_CONTRACT_V22",
                logical_path="docs/provider_timing_pit_contract_v22.md",
                source_path=config.pit_contract_v22_path,
                semantic_sha256=None,
            ),
            _evidence_record(
                role="PIT_V22_DECISION_LEDGER",
                logical_path="docs/pit_v22_decision_ledger.md",
                source_path=config.pit_v22_decision_ledger_path,
                semantic_sha256=None,
            ),
            _evidence_record(
                role="PIT_RECONCILIATION_GATE_V21",
                logical_path=(
                    "artifacts/provider_timing_v21/pit_reconciliation_gate_v21_20260812.json"
                ),
                source_path=config.pit_reconciliation_gate_v21_path,
                semantic_sha256=pit_gate_hash,
            ),
            _evidence_record(
                role="MASSIVE_RESELECTION_V21",
                logical_path=(
                    "artifacts/provider_timing_v21/"
                    "massive_reselection_sensitivity_v21_recomputed_20260812.json"
                ),
                source_path=config.massive_reselection_path,
                semantic_sha256=massive_hash,
            ),
            _evidence_record(
                role="UW_ANOMALY_V21",
                logical_path="artifacts/provider_timing_v21/uw_anomaly_evidence_v21.json",
                source_path=config.uw_anomaly_path,
                semantic_sha256=uw_hash,
            ),
            _evidence_record(
                role="OFFICIAL_DOCS_AUDIT_V1",
                logical_path=("artifacts/provider_timing_v21/official_docs_audit_v1_20260812.json"),
                source_path=config.official_docs_audit_path,
                semantic_sha256=docs_audit_hash,
            ),
            _evidence_record(
                role="B2_AVAILABILITY_MANIFEST_V22",
                logical_path="artifacts/provider_timing_v22/b2_availability_manifest_v22.json",
                source_path=config.b2_availability_manifest_v22_path,
                semantic_sha256=b2_sidecar_hash,
            ),
            _evidence_record(
                role="TARGET_BLIND_MANIFEST_V23",
                logical_path=(
                    "artifacts/target_blind_v23_sourcebound_20260812/"
                    "target_blind_common_predictor_manifest_v23.json"
                ),
                source_path=config.target_blind_manifest_v23_path,
                semantic_sha256=None,
            ),
            _evidence_record(
                role="CONFIRMATION_PREREGISTRATION_V3",
                logical_path=(
                    "artifacts/target_blind_v23_sourcebound_20260812/"
                    "next_confirmation_preregistration_v3.json"
                ),
                source_path=config.preregistration_v3_path,
                semantic_sha256=_string(preregistration.get("preregistration_sha256")),
            ),
            _evidence_record(
                role="CONFIRMATION_READINESS_V2",
                logical_path=(
                    "artifacts/target_blind_v23_sourcebound_20260812/confirmation_readiness_v2.json"
                ),
                source_path=config.confirmation_readiness_v2_path,
                semantic_sha256=_string(readiness.get("readiness_sha256")),
            ),
        ],
    }
    _assert_sanitized(document)
    document["policy_sha256"] = _canonical_sha256(document)
    return document


def write_provider_timing_evidence_policy_gate_v1(
    *, config: ProviderTimingEvidencePolicyGateV1Config, output_path: Path
) -> dict[str, Any]:
    """Write the policy gate atomically without overwriting divergent bytes."""
    document = build_provider_timing_evidence_policy_gate_v1(config)
    rendered = (json.dumps(document, indent=2, sort_keys=True, ensure_ascii=True) + "\n").encode(
        "utf-8"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        if output_path.read_bytes() != rendered:
            raise FileExistsError("POLICY_OUTPUT_EXISTS_WITH_DIFFERENT_BYTES")
        return document

    temporary_path = output_path.with_name(f".{output_path.name}.{uuid.uuid4().hex}.part")
    try:
        temporary_path.write_bytes(rendered)
        try:
            os.link(temporary_path, output_path)
        except FileExistsError:
            if output_path.read_bytes() != rendered:
                raise FileExistsError("POLICY_OUTPUT_EXISTS_WITH_DIFFERENT_BYTES") from None
    finally:
        temporary_path.unlink(missing_ok=True)
    return document


def _validate_documentary_boundaries(texts: Mapping[str, str]) -> None:
    """Require the documentary basis for each scope without reading any outcomes."""
    _require_texts(
        texts["amendment"],
        (
            "VALID_UNDER_REGISTERED_TIMING_ASSUMPTIONS",
            "EXISTING_SCIENTIFIC_RECONCILIATION",
            "CONDITIONAL_GO_NOW",
            "GO_AFTER_DATE_LEVEL_PIT_PREFLIGHT",
            "GO_AFTER_RECEIPT_LOGGER_VALIDATED",
            "UNIVERSAL_PROVIDER_LATENCY_CLAIM",
            "NOT_SUPPORTED",
        ),
        "POLICY_AMENDMENT_BOUNDARY_MISSING",
    )
    _require_texts(
        texts["methodology"],
        (
            "Provider timing gate amendment v1",
            "Provider timing gate amendment v2.1",
            "SAFE_TO_RECONCILE_EXISTING_RESULTS=NO",
            "FAIL_ZERO_ACTIVITY_NOT_DISAMBIGUATED",
        ),
        "POLICY_METHODOLOGY_BOUNDARY_MISSING",
    )
    _require_texts(
        texts["addendum"],
        (
            "PASS_MASK_READY_REQUIRES_NEW_TARGET_BLIND_PANEL_BUILD",
            "SAFE_TO_RECONCILE_EXISTING_RESULTS=NO",
            "SAFE_TO_OPEN_OR_EVALUATE_OOS=NO",
            "mask for a new target-blind common panel",
        ),
        "POLICY_RECONCILIATION_ADDENDUM_BOUNDARY_MISSING",
    )
    _require_texts(
        texts["confirmation_protocol"],
        (
            "SAFE_TO_RECONCILE_EXISTING_RESULTS=NO",
            "SAFE_TO_OPEN_OR_EVALUATE_OOS=NO",
            "does not authorize acquisition, model fitting, QLIKE,",
            "explicit human authorization for exactly one OOS access",
        ),
        "POLICY_CONFIRMATION_PROTOCOL_BOUNDARY_MISSING",
    )
    _require_texts(
        texts["contract_v22"],
        (
            "B2_AVAILABILITY_SIDECAR = PASS_WITH_EXCLUSIONS",
            "SAFE_TO_RECONCILE_EXISTING_RESULTS = NO",
            "The result does **not** authorize reconciliation of sealed result artefacts",
            "new target-blind common B0/B1/B2 panel",
        ),
        "POLICY_PIT_V22_CONTRACT_BOUNDARY_MISSING",
    )
    _require_texts(
        texts["ledger_v22"],
        (
            "Decision 43",
            "does not reconcile any sealed legacy result",
            "SAFE_TO_RECONCILE_EXISTING_RESULTS=NO",
            "SAFE_TO_OPEN_OR_EVALUATE_OOS=NO",
            "SAFE_TO_ACQUIRE_NEW_SAMPLE=NO",
        ),
        "POLICY_PIT_V22_LEDGER_BOUNDARY_MISSING",
    )


def _validate_pit_reconciliation_gate(document: Mapping[str, Any]) -> str:
    _validate_self_hash(
        document=document,
        hash_field="aggregation_sha256",
        error_prefix="POLICY_PIT_RECONCILIATION_GATE_V21",
    )
    _require_values(
        document,
        {
            "schema_version": "pit-reconciliation-gate-v2.1",
            "status": "CONDITIONAL_NOT_CLOSED",
            "SAFE_TO_RECONCILE_EXISTING_RESULTS": "NO",
            "SAFE_TO_OPEN_OR_EVALUATE_OOS": "NO",
            "no_provider_http_requests_performed": True,
            "no_targets_or_predictive_metrics_read": True,
            "no_oos_or_predictive_artifacts_read": True,
        },
        "POLICY_PIT_RECONCILIATION_GATE_V21",
    )
    return _required_hash(document, "aggregation_sha256", "POLICY_PIT_RECONCILIATION_GATE_V21")


def _validate_massive_reselection(document: Mapping[str, Any]) -> str:
    _validate_self_hash(
        document=document,
        hash_field="recomputed_result_sha256",
        error_prefix="POLICY_MASSIVE_RESELECTION",
    )
    _require_values(
        document,
        {
            "schema_version": "provider-timing-v2.1",
            "status": "PASS",
            "selection_rule": (
                "last_quote_by_sip_timestamp_then_sequence_at_or_before_origin_minus_delay"
            ),
            "no_provider_http_requests_performed": True,
            "no_targets_or_predictive_metrics_read": True,
        },
        "POLICY_MASSIVE_RESELECTION",
    )
    return _required_hash(document, "recomputed_result_sha256", "POLICY_MASSIVE_RESELECTION")


def _validate_uw_anomaly(document: Mapping[str, Any]) -> str:
    _validate_self_hash(
        document=document,
        hash_field="artifact_sha256",
        error_prefix="POLICY_UW_ANOMALY",
    )
    _require_values(
        document,
        {
            "schema_version": "uw-anomaly-evidence-v2.1",
            "activity_availability_gate": "FAIL",
            "activity_availability_gate_reasons": ["ZERO_CONFOUNDED_BY_OBSERVED_CREATED_AT_DELAY"],
            "no_model_or_oos_artifacts_read": True,
            "no_provider_http_requests_performed": True,
            "no_targets_or_predictive_metrics_read": True,
        },
        "POLICY_UW_ANOMALY",
    )
    return _required_hash(document, "artifact_sha256", "POLICY_UW_ANOMALY")


def _validate_official_docs_audit(document: Mapping[str, Any]) -> str:
    _validate_self_hash(
        document=document,
        hash_field="manifest_sha256",
        error_prefix="POLICY_OFFICIAL_DOCS_AUDIT",
    )
    _require_values(
        document,
        {
            "schema_version": "provider-timing-official-docs-audit-v1.0",
            "status": "PASS_LIMITATIONS_RECORDED_NO_PIT_SEMANTICS_UPGRADE",
            "SAFE_TO_RECONCILE_EXISTING_RESULTS": "NO",
            "SAFE_TO_OPEN_OR_EVALUATE_OOS": "NO",
            "no_provider_data_requests_performed": True,
            "no_targets_or_predictive_artifacts_read": True,
        },
        "POLICY_OFFICIAL_DOCS_AUDIT",
    )
    _require_nested_values(
        document,
        {
            ("fmp", "provider_semantics_status"): "UNVERIFIED",
            ("massive", "sip_timestamp_status"): "EVENT_TIME_TECHNICAL_ONLY",
            ("unusual_whales", "created_at_status"): "PROXY_ONLY",
            ("historical_source_availability", "status"): (
                "PASS_SEPARATE_FROM_PIT_TIMESTAMP_SEMANTICS"
            ),
        },
        "POLICY_OFFICIAL_DOCS_AUDIT",
    )
    return _required_hash(document, "manifest_sha256", "POLICY_OFFICIAL_DOCS_AUDIT")


def _validate_b2_availability_manifest(document: Mapping[str, Any]) -> str:
    _require_values(
        document,
        {
            "schema_version": "2.2",
            "b2_availability_sidecar_status": "PASS_WITH_EXCLUSIONS",
            "corrected_pit_panel_preparation": (
                "PASS_MASK_READY_REQUIRES_NEW_TARGET_BLIND_PANEL_BUILD"
            ),
            "generation_mode": "deterministic_target_blind_rebuild",
            "safe_to_reconcile_existing_results": "NO",
            "sealed_result_reconciliation": "BLOCKED",
            "model_or_metric_payload_read": False,
            "oos_payload_read": False,
        },
        "POLICY_B2_AVAILABILITY_MANIFEST_V22",
    )
    summary = _mapping(document.get("summary"))
    if summary.get("primary_delayed_raw_zero_exclusion_count") != 451:
        raise ValueError("POLICY_B2_AVAILABILITY_MANIFEST_V22_EXCLUSION_COUNT_INVALID")
    return _required_hash(document, "sidecar_sha256", "POLICY_B2_AVAILABILITY_MANIFEST_V22")


def _validate_target_blind_manifest(
    *,
    target_blind_manifest: Mapping[str, Any],
    pit_gate_file_sha256: str,
    massive_file_sha256: str,
    b2_manifest_file_sha256: str,
) -> None:
    _require_values(
        target_blind_manifest,
        {
            "schema_version": "target-blind-common-predictor-manifest-v2.3",
            "status": "PASS_TARGET_BLIND_INPUTS_RECONCILIATION_REMAINS_BLOCKED",
            "scope": "offline_target_blind_predictor_construction_only",
            "SAFE_TO_OPEN_OR_EVALUATE_OOS": "NO",
            "safe_to_reconcile_existing_results": "NO",
            "model_fit_performed": False,
            "no_target_or_metric_payload_read": True,
        },
        "POLICY_TARGET_BLIND_MANIFEST_V23",
    )
    source_hashes = _mapping(target_blind_manifest.get("source_hashes"))
    if source_hashes.get("pit_reconciliation_gate_v21_sha256") != pit_gate_file_sha256:
        raise ValueError("POLICY_TARGET_BLIND_MANIFEST_V23_PIT_GATE_BINDING_INVALID")
    if source_hashes.get("massive_reselection_recomputed_v21_sha256") != massive_file_sha256:
        raise ValueError("POLICY_TARGET_BLIND_MANIFEST_V23_MASSIVE_BINDING_INVALID")
    if source_hashes.get("b2_availability_manifest_v22_sha256") != b2_manifest_file_sha256:
        raise ValueError("POLICY_TARGET_BLIND_MANIFEST_V23_B2_MANIFEST_BINDING_INVALID")


def _validate_preregistration(
    *,
    preregistration: Mapping[str, Any],
    target_blind_manifest: Mapping[str, Any],
    target_blind_manifest_file_sha256: str,
) -> None:
    _validate_self_hash(
        document=preregistration,
        hash_field="preregistration_sha256",
        error_prefix="POLICY_PREREGISTRATION",
    )
    if preregistration.get("safe_to_open_or_evaluate_oos") != "NO":
        raise ValueError("POLICY_PREREGISTRATION_OOS_GATE_INVALID")
    _require_values(
        preregistration,
        {
            "schema_version": "target-blind-confirmation-preregistration-v3.0",
            "status": "SEALED_SOURCE_BOUND_PRE_METHOD_FREEZE_NOT_AUTHORIZED_FOR_OOS",
            "safe_to_reconcile_existing_results": "NO",
            "sealed_result_reconciliation": "BLOCKED",
            "model_fit_performed": False,
            "no_target_or_metric_payload_read": True,
        },
        "POLICY_PREREGISTRATION",
    )
    bound_panel = _mapping(preregistration.get("bound_panel"))
    if bound_panel.get("panel_manifest_sha256") != target_blind_manifest_file_sha256:
        raise ValueError("POLICY_PREREGISTRATION_PANEL_MANIFEST_BINDING_INVALID")
    if bound_panel.get("source_hashes") != target_blind_manifest.get("source_hashes"):
        raise ValueError("POLICY_PREREGISTRATION_SOURCE_HASH_BINDING_INVALID")
    _require_nested_values(
        preregistration,
        {
            ("bound_panel", "input_provenance"): {
                "availability_sidecar_status": "PASS_WITH_EXCLUSIONS",
                "edge_conclusion": "NOT_EVALUATED_TARGET_BLIND",
                "primary_excluded_row_count": 451,
                "reconciliation_gate_status": "CONDITIONAL_NOT_CLOSED",
            }
        },
        "POLICY_PREREGISTRATION",
    )


def _validate_readiness(*, readiness: Mapping[str, Any], docs_audit_hash: str) -> None:
    _validate_self_hash(
        document=readiness,
        hash_field="readiness_sha256",
        error_prefix="POLICY_READINESS",
    )
    if readiness.get("safe_to_acquire_new_sample") != "NO":
        raise ValueError("POLICY_READINESS_NEW_ACQUISITION_GATE_INVALID")
    _require_values(
        readiness,
        {
            "schema_version": "confirmation-readiness-v2.0",
            "status": "PASS_SOURCE_BOUND_METHOD_FREEZE_PREPARATION",
            "scope": "offline_source_bound_target_blind_readiness_only",
            "ready_for_successor_method_freeze": "YES",
            "safe_to_reconcile_existing_results": "NO",
            "safe_to_open_or_evaluate_oos": "NO",
            "model_fit_performed": False,
            "no_target_or_metric_payload_read": True,
        },
        "POLICY_READINESS",
    )
    _require_nested_values(
        readiness,
        {
            ("bound_artifact_integrity", "status"): "PASS",
            ("common_subset_validation", "status"): "PASS",
            ("provider_timing_boundary", "status"): "PASS_LIMITATIONS_RETAINED",
            ("provider_timing_boundary", "provider_docs_audit_sha256"): docs_audit_hash,
        },
        "POLICY_READINESS",
    )


def _read_json_object(path: Path, source_name: str) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"{source_name}_MISSING")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{source_name}_INVALID_JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{source_name}_NOT_OBJECT")
    return value


def _read_text(path: Path, source_name: str) -> str:
    if not path.is_file():
        raise FileNotFoundError(f"{source_name}_MISSING")
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ValueError(f"{source_name}_UNREADABLE") from exc


def _require_texts(text: str, fragments: tuple[str, ...], error_code: str) -> None:
    if any(fragment not in text for fragment in fragments):
        raise ValueError(error_code)


def _validate_self_hash(*, document: Mapping[str, Any], hash_field: str, error_prefix: str) -> None:
    recorded = _required_hash(document, hash_field, error_prefix)
    unsigned = dict(document)
    unsigned.pop(hash_field)
    if _canonical_sha256(unsigned) != recorded:
        raise ValueError(f"{error_prefix}_SELF_HASH_MISMATCH")


def _required_hash(document: Mapping[str, Any], key: str, error_prefix: str) -> str:
    value = _string(document.get(key))
    if value is None or _SHA256_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{error_prefix}_SELF_HASH_INVALID")
    return value


def _require_values(
    document: Mapping[str, Any], expected: Mapping[str, object], error_prefix: str
) -> None:
    for key, value in expected.items():
        if document.get(key) != value:
            raise ValueError(f"{error_prefix}_{key.upper()}_INVALID")


def _require_nested_values(
    document: Mapping[str, Any],
    expected: Mapping[tuple[str, str], object],
    error_prefix: str,
) -> None:
    for (outer_key, inner_key), value in expected.items():
        if _mapping(document.get(outer_key)).get(inner_key) != value:
            raise ValueError(f"{error_prefix}_{outer_key.upper()}_{inner_key.upper()}_INVALID")


def _evidence_record(
    *, role: str, logical_path: str, source_path: Path, semantic_sha256: str | None
) -> dict[str, str | None]:
    return {
        "role": role,
        "logical_path": logical_path,
        "file_sha256": _file_sha256(source_path, f"POLICY_{role}"),
        "semantic_sha256": semantic_sha256,
    }


def _file_sha256(path: Path, source_name: str) -> str:
    if not path.is_file():
        raise FileNotFoundError(f"{source_name}_MISSING")
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise ValueError(f"{source_name}_UNREADABLE") from exc
    return digest.hexdigest()


def _canonical_sha256(payload: Mapping[str, Any]) -> str:
    rendered = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _string(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _assert_sanitized(document: Mapping[str, Any]) -> None:
    rendered = json.dumps(document, sort_keys=True, ensure_ascii=True, allow_nan=False)
    if _SECRET_VALUE_PATTERN.search(rendered):
        raise ValueError("POLICY_OUTPUT_SECRET_LIKE_CONTENT")
    if _PERSONAL_PATH_PATTERN.search(rendered):
        raise ValueError("POLICY_OUTPUT_PERSONAL_PATH")
