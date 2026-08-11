"""Deterministic, target-blind consolidation of PIT v2.1 timing evidence."""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from mds650.provider_timing_v21 import canonical_sha256

GATE_SCHEMA_VERSION = "pit-reconciliation-gate-v2.1"
MASSIVE_SCHEMA_VERSION = "provider-timing-v2.1"
UW_SCHEMA_VERSION = "uw-anomaly-evidence-v2.1"
MASSIVE_SELECTION_RULE = "last_quote_by_sip_timestamp_then_sequence_at_or_before_origin_minus_delay"
UW_FAILURE_REASON = "ZERO_CONFOUNDED_BY_OBSERVED_CREATED_AT_DELAY"

_SECRET_VALUE_PATTERN = re.compile(r"(?i)(api[_-]?key|authorization|bearer|password|secret)\s*[:=]")
_PERSONAL_PATH_PATTERN = re.compile(r"(?i)(?:[a-z]:[\\/]|/users/|/home/)")


def build_pit_reconciliation_gate_v21(
    *,
    massive_artifact_path: Path,
    uw_artifact_path: Path,
    pit_contract_path: Path,
    decision_ledger_path: Path,
    b2_availability_manifest_v22_path: Path,
    pit_contract_v22_path: Path,
) -> dict[str, Any]:
    """Build a fail-closed aggregate from existing target-blind PIT evidence.

    Parameters
    ----------
    massive_artifact_path:
        Existing Massive reselection aggregate containing only technical,
        target-free quote-selection evidence.
    uw_artifact_path:
        Existing Unusual Whales B2 availability aggregate.
    pit_contract_path:
        Existing PIT v2.1 contract that records the FMP ``+1 minute`` study
        convention and unresolved provider timing semantics.
    decision_ledger_path:
        Existing PIT v2.1 decision ledger that keeps reconciliation closed.
    b2_availability_manifest_v22_path:
        Existing v2.2 B2 sidecar manifest. Its ``PASS_WITH_EXCLUSIONS`` state
        requires a new target-blind panel and does not reopen sealed results.
    pit_contract_v22_path:
        Existing v2.2 sidecar contract that records the same boundary.

    Returns
    -------
    dict[str, Any]
        Sanitized reconciliation gate with a deterministic self-hash. It always
        keeps existing-result reconciliation and OOS evaluation closed.

    Raises
    ------
    FileNotFoundError
        If a required pre-existing evidence file is unavailable.
    ValueError
        If an input artifact self-hash, schema version, timing state, or binding
        contract is inconsistent.

    Notes
    -----
    ``timestamp_raw + 2 minutes`` is reported only as a conservative study
    sensitivity. It is not represented as confirmed FMP bar semantics.
    """
    massive = _read_json_object(massive_artifact_path, "PIT_V21_MASSIVE_ARTIFACT")
    uw = _read_json_object(uw_artifact_path, "PIT_V21_UW_ARTIFACT")
    contract_text = _read_text(pit_contract_path, "PIT_V21_PIT_CONTRACT")
    ledger_text = _read_text(decision_ledger_path, "PIT_V21_DECISION_LEDGER")
    b2_availability_manifest_v22 = _read_json_object(
        b2_availability_manifest_v22_path, "PIT_V21_B2_AVAILABILITY_MANIFEST_V22"
    )
    contract_v22_text = _read_text(pit_contract_v22_path, "PIT_V21_PIT_CONTRACT_V22")

    massive_self_hash = _validate_massive(massive)
    uw_self_hash = _validate_uw(uw)
    _validate_fmp_contract(contract_text)
    _validate_decision_ledger(ledger_text)
    _validate_b2_availability_manifest_v22(b2_availability_manifest_v22)
    _validate_v22_contract(contract_v22_text)

    evidence = [
        _evidence_record(
            role="MASSIVE_RESELECTION",
            logical_path=(
                "artifacts/provider_timing_v21/"
                "massive_reselection_sensitivity_v21_recomputed_20260812.json"
            ),
            source_path=massive_artifact_path,
            semantic_sha256=massive_self_hash,
        ),
        _evidence_record(
            role="UW_ANOMALY",
            logical_path="artifacts/provider_timing_v21/uw_anomaly_evidence_v21.json",
            source_path=uw_artifact_path,
            semantic_sha256=uw_self_hash,
        ),
        _evidence_record(
            role="PIT_CONTRACT",
            logical_path="docs/provider_timing_pit_contract_v21.md",
            source_path=pit_contract_path,
            semantic_sha256=None,
        ),
        _evidence_record(
            role="PIT_DECISION_LEDGER",
            logical_path="docs/pit_v21_decision_ledger.md",
            source_path=decision_ledger_path,
            semantic_sha256=None,
        ),
        _evidence_record(
            role="UW_AVAILABILITY_MANIFEST_V22",
            logical_path="artifacts/provider_timing_v22/b2_availability_manifest_v22.json",
            source_path=b2_availability_manifest_v22_path,
            semantic_sha256=None,
        ),
        _evidence_record(
            role="PIT_CONTRACT_V22",
            logical_path="docs/provider_timing_pit_contract_v22.md",
            source_path=pit_contract_v22_path,
            semantic_sha256=None,
        ),
    ]
    document: dict[str, Any] = {
        "schema_version": GATE_SCHEMA_VERSION,
        "status": "CONDITIONAL_NOT_CLOSED",
        "PIT_V21": "CONDITIONAL_NOT_CLOSED",
        "SAFE_TO_RECONCILE_EXISTING_RESULTS": "NO",
        "SAFE_TO_OPEN_OR_EVALUATE_OOS": "NO",
        "edge_conclusion": "NOT_EVALUATED_TARGET_BLIND",
        "fmp_bar_availability": {
            "baseline_study_rule": "timestamp_raw_plus_1_minute",
            "sensitivity_study_rule": "timestamp_raw_plus_2_minutes",
            "provider_semantics_status": "UNVERIFIED",
            "conclusion": "CONSERVATIVE_STUDY_ASSUMPTION_NOT_PROVIDER_CONFIRMATION",
        },
        "massive_b1q_reselection": {
            "status": "PASS_TECHNICAL_TARGET_FREE",
            "source_status": "PASS",
            "selection_rule": MASSIVE_SELECTION_RULE,
            "conclusion": "TECHNICAL_CACHE_RESELECTION_PASS_NOT_HISTORICAL_DELIVERY_LATENCY_PROOF",
        },
        "legacy_uw_b2_raw_diagnostic": {
            "status": "FAIL_ZERO_CONFOUNDED_BY_OBSERVED_CREATED_AT_DELAY",
            "source_gate": "FAIL",
            "failure_reason": UW_FAILURE_REASON,
            "conclusion": "B2_ZERO_CANNOT_BE_INTERPRETED_AS_CONFIRMED_NO_ACTIVITY",
        },
        "corrected_uw_b2_availability_sidecar_v22": {
            "status": "PASS_WITH_EXCLUSIONS",
            "primary_excluded_row_count": 451,
            "corrected_panel_preparation": "PASS_MASK_READY_REQUIRES_NEW_TARGET_BLIND_PANEL_BUILD",
            "conclusion": "SIDE_CAR_MASK_READY_NEW_TARGET_BLIND_PANEL_REQUIRED",
        },
        "blocking_reasons": [
            "SEALED_RESULTS_RECONCILIATION_PROHIBITED",
            "NEW_TARGET_BLIND_COMMON_PANEL_REQUIRED",
        ],
        "source_evidence": evidence,
        "no_provider_http_requests_performed": True,
        "no_targets_or_predictive_metrics_read": True,
        "no_oos_or_predictive_artifacts_read": True,
        "secret_values_emitted": False,
        "personal_paths_emitted": False,
    }
    _assert_sanitized(document)
    document["aggregation_sha256"] = canonical_sha256(document)
    return document


def write_pit_reconciliation_gate_v21(
    *,
    massive_artifact_path: Path,
    uw_artifact_path: Path,
    pit_contract_path: Path,
    decision_ledger_path: Path,
    b2_availability_manifest_v22_path: Path,
    pit_contract_v22_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    """Write a deterministic, non-overwriting PIT v2.1 gate artifact.

    Parameters
    ----------
    massive_artifact_path, uw_artifact_path, pit_contract_path, decision_ledger_path,
    b2_availability_manifest_v22_path, pit_contract_v22_path:
        Evidence paths accepted by :func:`build_pit_reconciliation_gate_v21`.
    output_path:
        Destination for the new aggregate. An existing byte-identical artifact
        is retained; differing pre-existing bytes cause a fail-closed error.

    Returns
    -------
    dict[str, Any]
        The same aggregate represented by ``output_path``.

    Raises
    ------
    FileExistsError
        If ``output_path`` exists with bytes that differ from a deterministic
        recomputation.
    OSError
        If the artifact cannot be written atomically.
    """
    document = build_pit_reconciliation_gate_v21(
        massive_artifact_path=massive_artifact_path,
        uw_artifact_path=uw_artifact_path,
        pit_contract_path=pit_contract_path,
        decision_ledger_path=decision_ledger_path,
        b2_availability_manifest_v22_path=b2_availability_manifest_v22_path,
        pit_contract_v22_path=pit_contract_v22_path,
    )
    rendered = (json.dumps(document, indent=2, sort_keys=True, ensure_ascii=True) + "\n").encode(
        "utf-8"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        if output_path.read_bytes() != rendered:
            raise FileExistsError("PIT_V21_OUTPUT_EXISTS_WITH_DIFFERENT_BYTES")
        return document

    temporary_path = output_path.with_name(f".{output_path.name}.{uuid.uuid4().hex}.part")
    try:
        temporary_path.write_bytes(rendered)
        try:
            os.link(temporary_path, output_path)
        except FileExistsError:
            if output_path.read_bytes() != rendered:
                raise FileExistsError("PIT_V21_OUTPUT_EXISTS_WITH_DIFFERENT_BYTES") from None
    finally:
        temporary_path.unlink(missing_ok=True)
    return document


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


def _validate_massive(document: Mapping[str, Any]) -> str:
    self_hash = _validate_self_hash(
        document=document,
        hash_field="recomputed_result_sha256",
        error_prefix="PIT_V21_MASSIVE",
    )
    if document.get("schema_version") != MASSIVE_SCHEMA_VERSION:
        raise ValueError("PIT_V21_MASSIVE_SCHEMA_VERSION_INVALID")
    if document.get("status") != "PASS":
        raise ValueError("PIT_V21_MASSIVE_STATUS_NOT_TECHNICAL_PASS")
    if document.get("no_provider_http_requests_performed") is not True:
        raise ValueError("PIT_V21_MASSIVE_PROVIDER_HTTP_ASSERTION_INVALID")
    if document.get("no_targets_or_predictive_metrics_read") is not True:
        raise ValueError("PIT_V21_MASSIVE_TARGET_BLIND_ASSERTION_INVALID")
    if document.get("selection_rule") != MASSIVE_SELECTION_RULE:
        raise ValueError("PIT_V21_MASSIVE_SELECTION_RULE_INVALID")
    return self_hash


def _validate_uw(document: Mapping[str, Any]) -> str:
    self_hash = _validate_self_hash(
        document=document,
        hash_field="artifact_sha256",
        error_prefix="PIT_V21_UW",
    )
    if document.get("schema_version") != UW_SCHEMA_VERSION:
        raise ValueError("PIT_V21_UW_SCHEMA_VERSION_INVALID")
    if document.get("activity_availability_gate") != "FAIL":
        raise ValueError("PIT_V21_UW_GATE_NOT_FAIL_CLOSED")
    reasons = document.get("activity_availability_gate_reasons")
    if reasons != [UW_FAILURE_REASON]:
        raise ValueError("PIT_V21_UW_REASON_NOT_CANONICAL")
    if document.get("no_model_or_oos_artifacts_read") is not True:
        raise ValueError("PIT_V21_UW_OOS_ASSERTION_INVALID")
    if document.get("no_provider_http_requests_performed") is not True:
        raise ValueError("PIT_V21_UW_PROVIDER_HTTP_ASSERTION_INVALID")
    if document.get("no_targets_or_predictive_metrics_read") is not True:
        raise ValueError("PIT_V21_UW_TARGET_BLIND_ASSERTION_INVALID")
    return self_hash


def _validate_self_hash(*, document: Mapping[str, Any], hash_field: str, error_prefix: str) -> str:
    recorded = document.get(hash_field)
    if not isinstance(recorded, str) or re.fullmatch(r"[0-9a-f]{64}", recorded) is None:
        raise ValueError(f"{error_prefix}_SELF_HASH_INVALID")
    unsigned = dict(document)
    unsigned.pop(hash_field)
    if canonical_sha256(unsigned) != recorded:
        raise ValueError(f"{error_prefix}_SELF_HASH_MISMATCH")
    return recorded


def _validate_fmp_contract(contract_text: str) -> None:
    if "timestamp_raw + 1 minute" not in contract_text:
        raise ValueError("PIT_V21_FMP_BASELINE_RULE_MISSING")
    if "unresolved provider facts" not in contract_text.lower():
        raise ValueError("PIT_V21_FMP_SEMANTICS_BOUNDARY_MISSING")


def _validate_decision_ledger(ledger_text: str) -> None:
    if "PIT_V21=CONDITIONAL_NOT_CLOSED" not in ledger_text:
        raise ValueError("PIT_V21_LEDGER_STATUS_MISSING")
    if "SAFE_TO_RECONCILE_EXISTING_RESULTS=NO" not in ledger_text:
        raise ValueError("PIT_V21_LEDGER_RECONCILIATION_GATE_MISSING")


def _validate_b2_availability_manifest_v22(document: Mapping[str, Any]) -> None:
    if document.get("schema_version") != "2.2":
        raise ValueError("PIT_V21_B2_V22_SCHEMA_VERSION_INVALID")
    if document.get("b2_availability_sidecar_status") != "PASS_WITH_EXCLUSIONS":
        raise ValueError("PIT_V21_B2_V22_STATUS_INVALID")
    if (
        document.get("corrected_pit_panel_preparation")
        != "PASS_MASK_READY_REQUIRES_NEW_TARGET_BLIND_PANEL_BUILD"
    ):
        raise ValueError("PIT_V21_B2_V22_PANEL_PREPARATION_INVALID")
    if document.get("generation_mode") != "deterministic_target_blind_rebuild":
        raise ValueError("PIT_V21_B2_V22_GENERATION_MODE_INVALID")
    if document.get("safe_to_reconcile_existing_results") != "NO":
        raise ValueError("PIT_V21_B2_V22_RECONCILIATION_GATE_INVALID")
    if document.get("sealed_result_reconciliation") != "BLOCKED":
        raise ValueError("PIT_V21_B2_V22_SEALED_RESULT_GATE_INVALID")
    if document.get("model_or_metric_payload_read") is not False:
        raise ValueError("PIT_V21_B2_V22_MODEL_ASSERTION_INVALID")
    if document.get("oos_payload_read") is not False:
        raise ValueError("PIT_V21_B2_V22_OOS_ASSERTION_INVALID")
    summary = document.get("summary")
    if not isinstance(summary, Mapping):
        raise ValueError("PIT_V21_B2_V22_SUMMARY_INVALID")
    if summary.get("primary_delayed_raw_zero_exclusion_count") != 451:
        raise ValueError("PIT_V21_B2_V22_PRIMARY_EXCLUSION_COUNT_INVALID")


def _validate_v22_contract(contract_text: str) -> None:
    if re.search(r"B2_AVAILABILITY_SIDECAR\s*=\s*PASS_WITH_EXCLUSIONS", contract_text) is None:
        raise ValueError("PIT_V21_B2_V22_CONTRACT_STATUS_MISSING")
    if re.search(r"SAFE_TO_RECONCILE_EXISTING_RESULTS\s*=\s*NO", contract_text) is None:
        raise ValueError("PIT_V21_B2_V22_CONTRACT_RECONCILIATION_GATE_MISSING")
    if "new target-blind common b0/b1/b2 panel" not in contract_text.lower():
        raise ValueError("PIT_V21_B2_V22_CONTRACT_NEW_PANEL_BOUNDARY_MISSING")


def _evidence_record(
    *, role: str, logical_path: str, source_path: Path, semantic_sha256: str | None
) -> dict[str, str | None]:
    return {
        "role": role,
        "logical_path": logical_path,
        "file_sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
        "semantic_sha256": semantic_sha256,
    }


def _assert_sanitized(document: Mapping[str, Any]) -> None:
    rendered = json.dumps(document, sort_keys=True, ensure_ascii=True, allow_nan=False)
    if _SECRET_VALUE_PATTERN.search(rendered):
        raise ValueError("PIT_V21_OUTPUT_SECRET_LIKE_CONTENT")
    if _PERSONAL_PATH_PATTERN.search(rendered):
        raise ValueError("PIT_V21_OUTPUT_PERSONAL_PATH")
