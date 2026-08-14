"""Contract checks for the immutable target-blind B1v3 base manifest."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from mds650.b1v3_confirmation import canonical_sha256

ROOT = Path(__file__).resolve().parents[2]
ARTIFACT = ROOT / "artifacts/b1v3_confirmation_panel/base_predictor_manifest.json"
SCHEMA = (
    ROOT
    / "specs/001-pit-options-rv30/contracts/"
    "b1v3-confirmation-base-predictors-v1.schema.json"
)


def test_base_predictor_manifest_is_schema_valid_self_hashed_and_sanitized() -> None:
    document = json.loads(ARTIFACT.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.validate(document, schema)
    stored_hash = document.pop("manifest_sha256")

    assert stored_hash == canonical_sha256(document)
    assert document["origin_count"] == 38_664
    assert document["fmp"]["bar_count"] == 279_360
    assert document["b0"]["complete_row_count"] == 35_424
    assert document["b0"]["missing_row_count"] == 3_240
    assert document["outcome_read_count"] == 0
    assert document["safe_to_read_outcomes"] is False
    serialized = ARTIFACT.read_text(encoding="utf-8").lower()
    assert "c:\\users\\" not in serialized
    assert "d:\\mds650" not in serialized
    assert "api_key" not in serialized
    assert "authorization" not in serialized
