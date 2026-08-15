"""Full Tape source-binding tests for replication B2 predictors."""

from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

from mds650.b1_replication_b2 import validate_full_tape_document
from mds650.b1v3_confirmation import canonical_sha256

ROOT = Path(__file__).resolve().parents[2]


def test_full_tape_document_is_bound_to_preregistration_and_provider_report() -> None:
    preregistration_hash = "a" * 64
    provider_report_hash = "b" * 64
    session = "2024-12-10"
    record: dict[str, object] = {
        "status": "PASS",
        "session_date": session,
        "preregistration_sha256": preregistration_hash,
        "provider_report_sha256": provider_report_hash,
        "session_contract_sha256": canonical_sha256(
            {
                "session_date": session,
                "preregistration_sha256": preregistration_hash,
                "provider_report_sha256": provider_report_hash,
            }
        ),
        "target_outcome_read": False,
        "outcome_read_count": 0,
        "secret_values_emitted": False,
        "personal_paths_emitted": False,
        "parquet_files": [],
    }
    record["checkpoint_sha256"] = canonical_sha256(record)
    document: dict[str, object] = {
        "status": "PASS",
        "target_blind": True,
        "preregistration_sha256": preregistration_hash,
        "provider_report_sha256": provider_report_hash,
        "authorized_session_count": 1,
        "completed_session_count": 1,
        "pending_session_count": 0,
        "pending_sessions": [],
        "sessions": [record],
        "target_outcome_read": False,
        "outcome_read_count": 0,
        "secret_values_emitted": False,
        "personal_paths_emitted": False,
    }
    document["manifest_sha256"] = canonical_sha256(document)

    contract = validate_full_tape_document(
        document,
        preregistration_sha256=preregistration_hash,
        provider_report_sha256=provider_report_hash,
        sessions=(session,),
    )

    assert contract.manifest_sha256 == document["manifest_sha256"]
    assert tuple(contract.session_records) == (session,)


def test_replication_b2_schema_encodes_three_variant_sidecar_contract() -> None:
    """The sidecar has one row per origin and latency variant, not per origin."""
    schema = json.loads(
        (
            ROOT / "specs/001-pit-options-rv30/contracts/"
            "b1-independent-replication-b2-v1.schema.json"
        ).read_text(encoding="utf-8")
    )
    Draft202012Validator.check_schema(schema)

    assert schema["$defs"]["sidecar"]["properties"]["row_count"] == {"const": 38_232}
    assert schema["$defs"]["variant"]["properties"]["row_count"] == {"const": 12_744}
    assert (
        "PASS_NO_CONFOUNDED_ZERO_OBSERVED"
        in schema["properties"]["legacy_zero_coding_gate"]["enum"]
    )
