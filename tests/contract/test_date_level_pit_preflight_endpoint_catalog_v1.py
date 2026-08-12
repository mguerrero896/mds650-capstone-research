from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from mds650.date_level_pit_preflight_v1 import (
    PreflightError,
    load_endpoint_descriptors,
    run_date_level_pit_preflight,
)

ROOT = Path(__file__).resolve().parents[2]
CATALOG_PATH = ROOT / "config/date_level_pit_preflight_endpoint_catalog_v1.json"
SCHEMA_PATH = (
    ROOT / "specs/001-pit-options-rv30/contracts/"
    "date-level-pit-preflight-endpoint-catalog-v1.schema.json"
)
PLAN_PATH = ROOT / "artifacts/preflight/date_level_pit_preflight_plan_v1.json"
MIN_D_DRIVE_FREE_BYTES = 80 * 1024**3


def _plan() -> dict[str, object]:
    return json.loads(PLAN_PATH.read_text(encoding="utf-8"))


def _all_keys_present() -> dict[str, bool]:
    return {
        "FMP_API_KEY": True,
        "UNUSUALWHALES_API_KEY": True,
        "MASSIVE_API_KEY": True,
    }


def test_missing_endpoint_catalog_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(PreflightError, match="ENDPOINT_CATALOG_READ_FAILED"):
        load_endpoint_descriptors(tmp_path / "missing-catalog.json")


def test_invalid_endpoint_catalog_fails_closed(tmp_path: Path) -> None:
    invalid_catalog = tmp_path / "invalid-catalog.json"
    invalid_catalog.write_text('{"artifact_type":"wrong"}', encoding="utf-8")

    with pytest.raises(PreflightError, match="ENDPOINT_CATALOG_SCHEMA_INVALID"):
        load_endpoint_descriptors(invalid_catalog)


def test_valid_catalog_matches_schema_and_has_only_safe_declarative_targets() -> None:
    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    endpoints = {entry["provider"]: entry for entry in catalog["endpoints"]}
    catalog_text = CATALOG_PATH.read_text(encoding="utf-8")

    assert list(Draft202012Validator(schema).iter_errors(catalog)) == []
    assert endpoints["fmp"]["request_target"] == "/stable/historical-chart/1min"
    assert endpoints["unusual_whales"]["metadata_only"] is True
    assert endpoints["unusual_whales"]["range_probe"] == {
        "dataset": "full_tape_historical",
        "mode": "metadata_only",
    }
    assert endpoints["massive"]["routes"][1]["parameters"] == {
        "timestamp.lte": "{as_of_timestamp_ns}",
        "sort": "timestamp",
        "order": "desc",
        "limit": 1,
    }
    assert endpoints["massive"]["routes"][1]["timestamp_unit"] == "nanoseconds"
    assert catalog["execution_requirements"] == {
        "authorization_required": True,
        "zero_incremental_spend_assertion_required": True,
        "minimum_d_drive_free_bytes": MIN_D_DRIVE_FREE_BYTES,
        "network_transport_required": True,
    }
    assert re.search(r"(?i)(?:[a-z]:\\users\\|/users/)", catalog_text) is None
    assert "apiKey=" not in catalog_text
    assert "apikey=" not in catalog_text


def test_catalog_load_is_idempotent() -> None:
    assert load_endpoint_descriptors(CATALOG_PATH) == load_endpoint_descriptors(CATALOG_PATH)


def test_catalog_configures_all_providers_but_does_not_enable_network() -> None:
    plan = _plan()
    descriptors = load_endpoint_descriptors(CATALOG_PATH)
    dry_run = run_date_level_pit_preflight(
        plan,
        execute=False,
        secret_presence=_all_keys_present(),
        endpoint_descriptors=descriptors,
    )
    execution = run_date_level_pit_preflight(
        plan,
        execute=True,
        approved_plan_semantic_hash=plan["semantic_self_hash"],
        zero_incremental_spend_asserted=True,
        d_drive_free_bytes=MIN_D_DRIVE_FREE_BYTES,
        secret_presence=_all_keys_present(),
        endpoint_descriptors=descriptors,
    )

    assert dry_run["status"] == "DRY_RUN_NETWORK_BLOCKED"
    assert dry_run["gates"]["endpoint_configuration"] == {
        "fmp": "CONFIGURED",
        "unusual_whales": "CONFIGURED",
        "massive": "CONFIGURED",
    }
    assert execution["status"] == "FAILED_CLOSED"
    assert execution["blocking_reasons"] == ["NETWORK_TRANSPORT_UNCONFIGURED"]
    assert execution["gates"]["transport"] == "NOT_EVALUATED"
