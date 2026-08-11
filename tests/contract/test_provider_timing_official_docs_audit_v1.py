"""Contract checks for the source-bound official provider-documentation audit."""

from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

from mds650.study_design import canonical_sha256

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = (
    ROOT
    / "specs"
    / "001-pit-options-rv30"
    / "contracts"
    / "provider-timing-official-docs-audit-v1.schema.json"
)
ARTIFACT_PATH = ROOT / "artifacts" / "provider_timing_v21" / "official_docs_audit_v1_20260812.json"
ADDENDUM_PATH = ROOT / "docs" / "provider_timing_official_docs_audit_v1_20260812.md"
FMP_PROBE_PATH = ROOT / "artifacts" / "api_audit" / "b2_replication_90_common_probe.json"
UW_PROBE_PATH = ROOT / "artifacts" / "api_audit" / "b2_replication_90_uw_metadata_probe.json"


def test_official_docs_audit_is_hashed_schema_valid_and_does_not_upgrade_pit() -> None:
    """Official documentation may strengthen field meaning, never infer delivery timing."""
    assert SCHEMA_PATH.is_file()
    assert ARTIFACT_PATH.is_file()
    assert ADDENDUM_PATH.is_file()

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    payload = json.loads(ARTIFACT_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    errors = list(Draft202012Validator(schema).iter_errors(payload))

    assert not errors, "\n".join(error.message for error in errors)
    unsigned = dict(payload)
    recorded_hash = unsigned.pop("manifest_sha256")
    assert recorded_hash == canonical_sha256(unsigned)
    assert payload["status"] == "PASS_LIMITATIONS_RECORDED_NO_PIT_SEMANTICS_UPGRADE"
    assert payload["SAFE_TO_RECONCILE_EXISTING_RESULTS"] == "NO"
    assert payload["SAFE_TO_OPEN_OR_EVALUATE_OOS"] == "NO"
    assert payload["fmp"]["provider_semantics_status"] == "UNVERIFIED"
    assert payload["unusual_whales"]["created_at_status"] == "PROXY_ONLY"
    assert payload["massive"]["sip_timestamp_status"] == "EVENT_TIME_TECHNICAL_ONLY"
    availability = payload["historical_source_availability"]
    assert availability["status"] == "PASS_SEPARATE_FROM_PIT_TIMESTAMP_SEMANTICS"
    assert availability["fmp"]["historical_availability_status"] == "PASS_90_OF_90_SESSIONS"
    assert (
        availability["unusual_whales"]["historical_availability_status"]
        == "PASS_90_OF_90_FILE_METADATA"
    )
    assert availability["unusual_whales"]["row_level_pit_claim"] is False
    assert availability["fmp"]["evidence_sha256"] == (
        "97c3b57707a953629ff57e485cde918e52ecdd1777a246e84072b5c4150771dc"
    )
    assert availability["unusual_whales"]["evidence_sha256"] == (
        "244690e15054f518e5d12083e6b81d2bcbfcd8f5f009304f4127cbb5c1c4a3f3"
    )
    assert FMP_PROBE_PATH.is_file()
    assert UW_PROBE_PATH.is_file()
    assert payload["no_targets_or_predictive_artifacts_read"] is True
    assert payload["no_provider_data_requests_performed"] is True
    serialized = ARTIFACT_PATH.read_text(encoding="utf-8")
    assert "C:\\Users\\" not in serialized
    assert "apiKey" not in serialized
    assert recorded_hash in ADDENDUM_PATH.read_text(encoding="utf-8")
