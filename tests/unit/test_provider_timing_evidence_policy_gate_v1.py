"""Target-blind tests for the evidence-scoped provider-timing policy gate."""

from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from mds650.provider_timing_evidence_policy_gate_v1 import (
    ProviderTimingEvidencePolicyGateV1Config,
    build_provider_timing_evidence_policy_gate_v1,
    write_provider_timing_evidence_policy_gate_v1,
)

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = (
    ROOT
    / "specs"
    / "001-pit-options-rv30"
    / "contracts"
    / "provider-timing-evidence-policy-gate-v1.schema.json"
)
ARTIFACT_PATH = (
    ROOT
    / "artifacts"
    / "provider_timing_v22"
    / "provider_timing_evidence_policy_gate_v1_20260812.json"
)


def _config(
    *, readiness_path: Path | None = None, preregistration_path: Path | None = None
) -> ProviderTimingEvidencePolicyGateV1Config:
    """Return the complete, explicitly allowlisted target-blind source set."""
    return ProviderTimingEvidencePolicyGateV1Config(
        provider_timing_gate_amendment_path=ROOT / "docs" / "provider_timing_gate_amendment_v1.md",
        methodology_decisions_path=ROOT / "docs" / "methodology_decisions.md",
        pit_reconciliation_addendum_path=(
            ROOT / "docs" / "pit_reconciliation_gate_v21_addendum_20260812.md"
        ),
        confirmation_protocol_path=ROOT / "docs" / "confirmation_protocol_v2_sourcebound.md",
        pit_contract_v22_path=ROOT / "docs" / "provider_timing_pit_contract_v22.md",
        pit_v22_decision_ledger_path=ROOT / "docs" / "pit_v22_decision_ledger.md",
        pit_reconciliation_gate_v21_path=(
            ROOT / "artifacts" / "provider_timing_v21" / "pit_reconciliation_gate_v21_20260812.json"
        ),
        massive_reselection_path=(
            ROOT
            / "artifacts"
            / "provider_timing_v21"
            / "massive_reselection_sensitivity_v21_recomputed_20260812.json"
        ),
        uw_anomaly_path=(
            ROOT / "artifacts" / "provider_timing_v21" / "uw_anomaly_evidence_v21.json"
        ),
        official_docs_audit_path=(
            ROOT / "artifacts" / "provider_timing_v21" / "official_docs_audit_v1_20260812.json"
        ),
        b2_availability_manifest_v22_path=(
            ROOT / "artifacts" / "provider_timing_v22" / "b2_availability_manifest_v22.json"
        ),
        target_blind_manifest_v23_path=(
            ROOT
            / "artifacts"
            / "target_blind_v23_sourcebound_20260812"
            / "target_blind_common_predictor_manifest_v23.json"
        ),
        preregistration_v3_path=(
            preregistration_path
            if preregistration_path is not None
            else ROOT
            / "artifacts"
            / "target_blind_v23_sourcebound_20260812"
            / "next_confirmation_preregistration_v3.json"
        ),
        confirmation_readiness_v2_path=(
            readiness_path
            if readiness_path is not None
            else ROOT
            / "artifacts"
            / "target_blind_v23_sourcebound_20260812"
            / "confirmation_readiness_v2.json"
        ),
    )


def test_build_policy_keeps_sealed_reconciliation_and_oos_closed() -> None:
    """A corrected sidecar and v2.3 panel must not upgrade legacy/OOS authority."""
    document = build_provider_timing_evidence_policy_gate_v1(_config())

    assert document["status"] == "PASS_EVIDENCE_SCOPED_POLICY_FAIL_CLOSED"
    assert document["policy_resolution"] == (
        "LITERAL_RECONCILIATION_NO_REMAINS_CURRENT_FOR_SEALED_PRE_V22_RESULTS"
    )
    assert document["existing_evidence_under_registered_assumptions"] == {
        "does_not_authorize_sealed_result_reconciliation": True,
        "interpretation_scope": "FROZEN_CANONICAL_EVIDENCE_ONLY",
        "status": "VALID_UNDER_REGISTERED_TIMING_ASSUMPTIONS",
    }
    assert document["existing_sealed_result_reconciliation"] == {
        "reason_codes": [
            "V22_SIDECAR_REQUIRES_NEW_TARGET_BLIND_PANEL",
            "V23_SOURCE_BOUND_PANEL_DOES_NOT_RECONCILE_SEALED_LEGACY_RESULTS",
        ],
        "safe_to_reconcile_existing_results": "NO",
        "status": "BLOCKED",
    }
    assert document["oos_access"]["safe_to_open_or_evaluate_oos"] == "NO"
    assert document["new_historical_acquisition"] == {
        "current_authorization": "NO",
        "not_oos_authorization": True,
        "status": "GO_AFTER_DATE_LEVEL_PIT_PREFLIGHT",
        "timing_precondition": "DATE_LEVEL_PIT_PREFLIGHT",
    }
    assert document["prospective_capture"] == {
        "current_authorization": "NO",
        "not_oos_authorization": True,
        "status": "GO_AFTER_RECEIPT_LOGGER_VALIDATED",
        "timing_precondition": "VALIDATED_RECEIPT_LOGGER",
    }
    assert document["no_provider_http_requests_performed"] is True
    assert document["no_target_or_metric_payload_read"] is True
    assert document["model_fit_performed"] is False
    assert _canonical_sha256_without(document, "policy_sha256") == document["policy_sha256"]
    _assert_schema_valid(document)


def test_build_policy_rejects_an_oos_upgrade_even_when_preregistration_is_rehashed(
    tmp_path: Path,
) -> None:
    """A syntactically valid rehash cannot elevate the OOS gate to YES."""
    preregistration_path = tmp_path / "preregistration.json"
    _rewrite_hashed_payload(
        source=(
            ROOT
            / "artifacts"
            / "target_blind_v23_sourcebound_20260812"
            / "next_confirmation_preregistration_v3.json"
        ),
        destination=preregistration_path,
        hash_field="preregistration_sha256",
        updates={"safe_to_open_or_evaluate_oos": "YES"},
    )

    with pytest.raises(ValueError, match="POLICY_PREREGISTRATION_OOS_GATE_INVALID"):
        build_provider_timing_evidence_policy_gate_v1(
            _config(preregistration_path=preregistration_path)
        )


def test_build_policy_rejects_new_acquisition_upgrade_even_when_readiness_is_rehashed(
    tmp_path: Path,
) -> None:
    """A readiness snapshot cannot turn the historical-acquisition gate into YES."""
    readiness_path = tmp_path / "readiness.json"
    _rewrite_hashed_payload(
        source=(
            ROOT
            / "artifacts"
            / "target_blind_v23_sourcebound_20260812"
            / "confirmation_readiness_v2.json"
        ),
        destination=readiness_path,
        hash_field="readiness_sha256",
        updates={"safe_to_acquire_new_sample": "YES"},
    )

    with pytest.raises(ValueError, match="POLICY_READINESS_NEW_ACQUISITION_GATE_INVALID"):
        build_provider_timing_evidence_policy_gate_v1(_config(readiness_path=readiness_path))


def test_write_policy_is_deterministic_and_refuses_different_existing_bytes(tmp_path: Path) -> None:
    """A policy artifact is idempotent but never overwrites conflicting state."""
    output_path = tmp_path / "policy.json"

    first = write_provider_timing_evidence_policy_gate_v1(config=_config(), output_path=output_path)
    second = write_provider_timing_evidence_policy_gate_v1(
        config=_config(), output_path=output_path
    )

    assert first == second
    output_path.write_bytes(b"conflicting-bytes")
    with pytest.raises(FileExistsError, match="POLICY_OUTPUT_EXISTS_WITH_DIFFERENT_BYTES"):
        write_provider_timing_evidence_policy_gate_v1(config=_config(), output_path=output_path)


def test_committed_policy_artifact_is_schema_valid_hashed_and_sanitized() -> None:
    """The promoted target-blind policy snapshot must remain portable and fail-closed."""
    payload = json.loads(ARTIFACT_PATH.read_text(encoding="utf-8"))

    _assert_schema_valid(payload)
    assert _canonical_sha256_without(payload, "policy_sha256") == payload["policy_sha256"]
    rendered = json.dumps(payload, sort_keys=True, ensure_ascii=True)
    assert (
        re.search(r"(?i)(api[_-]?key|authorization|bearer|password|secret)\s*[:=]", rendered)
        is None
    )
    assert re.search(r"(?i)(?:[a-z]:[\\/]|/users/|/home/)", rendered) is None


def _assert_schema_valid(document: dict[str, object]) -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    errors = sorted(
        Draft202012Validator(schema).iter_errors(document), key=lambda error: list(error.path)
    )
    assert not errors, [error.message for error in errors]


def _rewrite_hashed_payload(
    *, source: Path, destination: Path, hash_field: str, updates: dict[str, object]
) -> None:
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload.update(deepcopy(updates))
    payload.pop(hash_field)
    payload[hash_field] = _canonical_sha256(payload)
    destination.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")


def _canonical_sha256_without(payload: dict[str, object], hash_field: str) -> str:
    unsigned = dict(payload)
    unsigned.pop(hash_field)
    return _canonical_sha256(unsigned)


def _canonical_sha256(payload: dict[str, object]) -> str:
    rendered = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()
