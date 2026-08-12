"""Regression tests for the documented, non-executable provider contract v2."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
CATALOG_PATH = ROOT / "config/date_level_pit_preflight_endpoint_catalog_v2.json"
SCHEMA_PATH = (
    ROOT / "specs/001-pit-options-rv30/contracts/"
    "date-level-pit-preflight-endpoint-catalog-v2.schema.json"
)


def _mapping(path: Path) -> dict[str, object]:
    """Load one local JSON contract fixture."""
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return cast(dict[str, object], value)


def test_uw_contract_uses_documented_zip_download_and_never_an_undocumented_range_probe() -> None:
    """UW v2 must represent only the documented date-addressed ZIP route."""
    catalog = _mapping(CATALOG_PATH)
    endpoints = catalog["endpoints"]
    assert isinstance(endpoints, list)
    unusual_whales = next(
        endpoint
        for endpoint in endpoints
        if isinstance(endpoint, dict) and endpoint.get("provider") == "unusual_whales"
    )

    assert unusual_whales["endpoint_id"] == "uw-full-tape-zip-download"
    assert unusual_whales["method"] == "GET"
    assert unusual_whales["request_target"] == "/api/option-trades/full-tape/{session_date}"
    assert unusual_whales["expected_content_type"] == "application/zip"
    assert unusual_whales["range_transport_status"] == "NOT_DOCUMENTED_NOT_USED"
    assert "range_probe" not in unusual_whales


def test_v2_catalog_validates_against_its_versioned_schema() -> None:
    """The documented route contract must be machine-validatable before use."""
    catalog = _mapping(CATALOG_PATH)
    schema = _mapping(SCHEMA_PATH)

    assert list(Draft202012Validator(schema).iter_errors(catalog)) == []
