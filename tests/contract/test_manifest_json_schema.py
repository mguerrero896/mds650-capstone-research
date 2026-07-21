"""Contract validation against the versioned provider-audit JSON Schema."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).parents[2]
SCHEMA = (
    ROOT
    / "specs"
    / "001-pit-options-rv30"
    / "contracts"
    / "provider-audit-manifest.schema.json"
)
MANIFESTS = [
    ROOT / "artifacts" / "api_audit" / "authenticated_v1j" / "provider_audit_manifest.json",
    ROOT / "artifacts" / "api_audit" / "authenticated_v1k" / "provider_audit_manifest.json",
    ROOT / "artifacts" / "api_audit" / "authenticated_v1l" / "provider_audit_manifest.json",
    ROOT / "artifacts" / "api_audit" / "authenticated_v1m" / "provider_audit_manifest.json",
    ROOT / "artifacts" / "api_audit" / "authenticated_v1q" / "provider_audit_manifest.json",
    ROOT / "artifacts" / "api_audit" / "authenticated_v1r" / "provider_audit_manifest.json",
    ROOT / "artifacts" / "api_audit" / "authenticated_v1s" / "provider_audit_manifest.json",
    ROOT / "artifacts" / "api_audit" / "authenticated_v1t" / "provider_audit_manifest.json",
    ROOT / "artifacts" / "api_audit" / "authenticated_v1u" / "provider_audit_manifest.json",
    ROOT / "artifacts" / "api_audit" / "authenticated_v1v" / "provider_audit_manifest.json",
    ROOT / "artifacts" / "api_audit" / "authenticated_v1w" / "provider_audit_manifest.json",
    ROOT / "artifacts" / "api_audit" / "authenticated_v1x" / "provider_audit_manifest.json",
]


@pytest.mark.parametrize("manifest_path", MANIFESTS, ids=lambda path: path.parent.name)
def test_authenticated_manifests_validate_against_manifest_schema(manifest_path: Path) -> None:
    """Each retained sanitized authenticated run must conform to schema version 1.1."""
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(manifest)


def test_manifest_schema_rejects_invalid_timestamp() -> None:
    """Request timestamps are RFC3339 date-times, not free-form dates."""
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    manifest = json.loads(MANIFESTS[0].read_text(encoding="utf-8"))
    manifest["provider_results"][0]["request_start"] = "not-a-timestamp"
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = list(validator.iter_errors(manifest))
    assert any(error.path[-1] == "request_start" for error in errors)
