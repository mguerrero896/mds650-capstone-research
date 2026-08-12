"""Regression coverage for the current no-network date-level PIT status record."""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Protocol, cast

import pytest

ROOT = Path(__file__).resolve().parents[2]
PLAN_PATH = ROOT / "artifacts/preflight/date_level_pit_preflight_plan_v1.json"
CATALOG_PATH = ROOT / "config/date_level_pit_preflight_endpoint_catalog_v2.json"
BUDGET_PATH = ROOT / "artifacts/preflight/date_level_pit_preflight_request_budget_v2.json"
MODULE_NAME = "mds650.date_level_pit_preflight_status_v2"
_SOURCE_COMMIT = "a" * 40


class _StatusEmitter(Protocol):
    """Public target-blind status-emitter surface used by this test module."""

    def emit_current_date_level_pit_status_v2(
        self,
        *,
        immutable_plan_path: Path,
        endpoint_catalog_path: Path,
        request_budget_path: Path,
        output_dir: Path,
        source_commit: str,
    ) -> Path:
        """Write one deterministic current status record without network transport."""

    def validate_current_date_level_pit_status_v2(self, document: Mapping[str, object]) -> None:
        """Reject a malformed or self-hash-invalid status record."""


def _module() -> _StatusEmitter:
    """Load the expected status emitter without importing data or model modules."""
    assert importlib.util.find_spec(MODULE_NAME) is not None, (
        "date-level PIT v2 status emitter is required"
    )
    return cast(_StatusEmitter, importlib.import_module(MODULE_NAME))


def _read_json(path: Path) -> dict[str, object]:
    """Read a JSON object from a metadata-only test output."""
    document = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return cast(dict[str, object], document)


def _canonical_sha256(document: Mapping[str, object]) -> str:
    """Compute the repository's canonical self-hash independently of the emitter."""
    rendered = json.dumps(
        document,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return "sha256:" + hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def _emit(emitter: _StatusEmitter, output_dir: Path, source_commit: str = _SOURCE_COMMIT) -> Path:
    """Emit one record from the three real versioned metadata inputs."""
    return emitter.emit_current_date_level_pit_status_v2(
        immutable_plan_path=PLAN_PATH,
        endpoint_catalog_path=CATALOG_PATH,
        request_budget_path=BUDGET_PATH,
        output_dir=output_dir,
        source_commit=source_commit,
    )


def test_status_record_preserves_history_but_hard_blocks_network(
    tmp_path: Path,
) -> None:
    """Removing the hard block would make this test fail before any provider call."""
    emitter = _module()
    output_path = _emit(emitter, tmp_path / "output")
    document = _read_json(output_path)

    assert document["schema_version"] == "date-level-pit-preflight-status-v2.0"
    assert document["status"] == "FAILED_CLOSED"
    assert document["network_permitted"] is False
    assert document["network_attempts_sent"] == 0
    assert document["safe_to_reconcile_existing_results"] == "NO"
    assert document["safe_to_open_or_evaluate_oos"] == "NO"
    assert document["historical_source_availability"] == {
        "status": "PASS_SEPARATE_FROM_PIT_TIMESTAMP_SEMANTICS",
        "fmp": "PASS_90_OF_90_SESSIONS",
        "unusual_whales": "PASS_90_OF_90_FILE_METADATA",
        "fmp_evidence_sha256": "97c3b57707a953629ff57e485cde918e52ecdd1777a246e84072b5c4150771dc",
        "unusual_whales_evidence_sha256": (
            "244690e15054f518e5d12083e6b81d2bcbfcd8f5f009304f4127cbb5c1c4a3f3"
        ),
    }
    assert document["operation_counts"] == {
        "fmp_minute_bars": 56,
        "unusual_whales_full_tape": 7,
        "massive_contract_search": 56,
        "total_initial_operations": 119,
    }
    assert document["attempt_budget"] == {
        "logical_request_cap": 343,
        "global_http_attempt_cap": 343,
        "max_attempts_per_logical_request": 3,
        "attempts_reserved": 0,
        "attempts_sent": 0,
    }
    assert document["contract_evidence_statuses"] == [
        "FMP_DATE_BOUNDED_ONLY_NO_PIT_CLAIM",
        "UW_FULL_TAPE_ZIP_ROUTE_DOCUMENTED_EXECUTION_GATED",
        "MASSIVE_CONTRACT_SELECTION_RULE_UNRESOLVED_NO_EXECUTION",
        "MASSIVE_QUOTE_AS_OF_PARAMETERS_DOCUMENTED_LOCAL_SIP_CHECK_REQUIRED",
    ]
    assert document["semantic_self_hash"] == _canonical_sha256(
        {key: value for key, value in document.items() if key != "semantic_self_hash"}
    )


def test_status_record_is_idempotent_and_rejects_replacement(tmp_path: Path) -> None:
    """Changing a sealed source commit must not silently overwrite the status record."""
    emitter = _module()
    output_dir = tmp_path / "output"
    first = _emit(emitter, output_dir)
    expected = first.read_bytes()
    assert _emit(emitter, output_dir) == first
    assert first.read_bytes() == expected

    with pytest.raises(ValueError, match="PREFLIGHT_V2_STATUS_OUTPUT_CONFLICT"):
        _emit(emitter, output_dir, source_commit="b" * 40)


def test_status_validator_rejects_a_self_hash_invalid_record(tmp_path: Path) -> None:
    """Changing an emitted gate after the fact must make its self-hash invalid."""
    emitter = _module()
    document = _read_json(_emit(emitter, tmp_path / "output"))
    document["network_attempts_sent"] = 1

    with pytest.raises(ValueError, match="PREFLIGHT_V2_STATUS_SELF_HASH_INVALID"):
        emitter.validate_current_date_level_pit_status_v2(document)
