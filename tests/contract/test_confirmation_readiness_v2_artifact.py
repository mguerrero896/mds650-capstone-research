"""Contract checks for the generated source-bound readiness v2 snapshot."""

from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

from mds650.study_design import canonical_sha256

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = (
    ROOT / "specs" / "001-pit-options-rv30" / "contracts" / "confirmation-readiness-v2.schema.json"
)
ARTIFACT_PATH = (
    ROOT / "artifacts" / "target_blind_v23_sourcebound_20260812" / "confirmation_readiness_v2.json"
)


def test_committed_v2_readiness_snapshot_is_hashed_schema_valid_and_fail_closed() -> None:
    """A published v2 snapshot cannot be mistaken for OOS or acquisition approval."""
    assert SCHEMA_PATH.is_file()
    assert ARTIFACT_PATH.is_file()

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    payload = json.loads(ARTIFACT_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    errors = list(Draft202012Validator(schema).iter_errors(payload))

    assert not errors, "\n".join(error.message for error in errors)
    unsigned = dict(payload)
    recorded_hash = unsigned.pop("readiness_sha256")
    assert recorded_hash == canonical_sha256(unsigned)
    assert payload["status"] == "PASS_SOURCE_BOUND_METHOD_FREEZE_PREPARATION"
    assert payload["ready_for_successor_method_freeze"] == "YES"
    assert payload["safe_to_reconcile_existing_results"] == "NO"
    assert payload["safe_to_open_or_evaluate_oos"] == "NO"
    assert payload["safe_to_acquire_new_sample"] == "NO"
    assert payload["model_fit_performed"] is False
    assert payload["provider_timing_boundary"]["status"] == "PASS_LIMITATIONS_RETAINED"
    serialized = ARTIFACT_PATH.read_text(encoding="utf-8")
    assert "C:\\Users\\" not in serialized
    assert "apiKey" not in serialized
