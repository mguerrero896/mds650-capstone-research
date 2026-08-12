"""Emit a deterministic, target-blind status record for date-level PIT preflight v2.

The status record is intentionally not an HTTP runner.  It binds the immutable
date-level plan, documented endpoint catalog and request budget, records the
positive historical-source availability separately from PIT semantics, and
fails closed before any provider call can occur.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from importlib import import_module
from pathlib import Path
from typing import Protocol, cast

from mds650.date_level_pit_preflight_v2 import (
    ContractEvidenceStatus,
    HistoricalSourceAvailability,
    NetworkGateStatus,
    OperationKind,
    OperationPlan,
    build_operation_plan,
)
from mds650.massive_contract_selection_v1 import RULE_ID as MASSIVE_CONTRACT_SELECTION_RULE_ID


class _JsonSchemaValidator(Protocol):
    """Minimal typed surface required from the untyped ``jsonschema`` runtime."""

    def iter_errors(self, instance: object) -> Iterable[object]:
        """Yield validation errors for one JSON-compatible object."""


class _Draft202012ValidatorFactory(Protocol):
    """Typed construction and validation boundary for Draft 2020-12 schemas."""

    def __call__(self, schema: Mapping[str, object]) -> _JsonSchemaValidator:
        """Create a validator for one schema mapping."""

    def check_schema(self, schema: Mapping[str, object]) -> None:
        """Raise when the supplied schema is invalid."""


def _load_draft202012_validator() -> _Draft202012ValidatorFactory:
    """Load the installed JSON-Schema runtime behind a narrow typed protocol."""
    module = import_module("jsonschema")
    candidate = cast(object, getattr(module, "Draft202012Validator", None))
    if not callable(candidate) or not callable(getattr(candidate, "check_schema", None)):
        raise RuntimeError("PREFLIGHT_V2_STATUS_JSONSCHEMA_VALIDATOR_UNAVAILABLE")
    return cast(_Draft202012ValidatorFactory, candidate)


_DRAFT202012_VALIDATOR = _load_draft202012_validator()
_ROOT = Path(__file__).resolve().parents[2]
_LEGACY_SCHEMA_PATH = (
    _ROOT
    / "specs"
    / "001-pit-options-rv30"
    / "contracts"
    / "date-level-pit-preflight-status-v2.schema.json"
)
_CURRENT_SCHEMA_PATH = (
    _ROOT
    / "specs"
    / "001-pit-options-rv30"
    / "contracts"
    / "date-level-pit-preflight-status-v2.1.schema.json"
)
_LEGACY_SCHEMA_VERSION = "date-level-pit-preflight-status-v2.0"
_CURRENT_SCHEMA_VERSION = "date-level-pit-preflight-status-v2.1"
_SCHEMA_PATH_BY_VERSION = {
    _LEGACY_SCHEMA_VERSION: _LEGACY_SCHEMA_PATH,
    _CURRENT_SCHEMA_VERSION: _CURRENT_SCHEMA_PATH,
}
_OUTPUT_FILENAME = "date_level_pit_preflight_status_v2_1_current.json"
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")
_EXPECTED_EVIDENCE_STATUSES = (
    ContractEvidenceStatus.FMP_DATE_BOUNDED_ONLY_NO_PIT_CLAIM,
    ContractEvidenceStatus.UW_FULL_TAPE_ZIP_ROUTE_DOCUMENTED_EXECUTION_GATED,
    ContractEvidenceStatus.MASSIVE_QUOTE_AS_OF_PARAMETERS_DOCUMENTED_LOCAL_SIP_CHECK_REQUIRED,
)
_LEGACY_EVIDENCE_STATUSES = (
    ContractEvidenceStatus.FMP_DATE_BOUNDED_ONLY_NO_PIT_CLAIM,
    ContractEvidenceStatus.UW_FULL_TAPE_ZIP_ROUTE_DOCUMENTED_EXECUTION_GATED,
    ContractEvidenceStatus.MASSIVE_CONTRACT_SELECTION_RULE_UNRESOLVED_NO_EXECUTION,
    ContractEvidenceStatus.MASSIVE_QUOTE_AS_OF_PARAMETERS_DOCUMENTED_LOCAL_SIP_CHECK_REQUIRED,
)


def emit_current_date_level_pit_status_v2(
    *,
    immutable_plan_path: Path,
    endpoint_catalog_path: Path,
    request_budget_path: Path,
    output_dir: Path,
    source_commit: str,
) -> Path:
    """Emit a zero-network, fail-closed current PIT-v2 status record.

    Parameters
    ----------
    immutable_plan_path
        Versioned date-level plan containing only calendar-derived sessions and
        forecast origins.
    endpoint_catalog_path
        Versioned, documentation-derived catalog. It is validated but never
        used to form a network request.
    request_budget_path
        Versioned bounded request-budget artifact. It is validated without
        reserving or sending an HTTP attempt.
    output_dir
        Destination for an immutable, write-if-identical status JSON file.
    source_commit
        Forty-character lowercase commit identity for this exact emission.

    Returns
    -------
    pathlib.Path
        The validated current status record.

    Raises
    ------
    ValueError
        If a versioned input, its schema or self-hash, the required hard
        network gate, the output schema, the output self-hash, or an existing
        output identity is invalid.

    Notes
    -----
    This function does not inspect a secret, disk space, an endpoint URL,
    provider response, target, RV30 value, metric, model, prediction or OOS
    artefact. It does not import an HTTP client and sends zero network calls.
    """
    _require_commit(source_commit, "PREFLIGHT_V2_STATUS_SOURCE_COMMIT_INVALID")
    immutable_plan = _read_json_object(immutable_plan_path, "PREFLIGHT_V2_STATUS_PLAN_UNREADABLE")
    endpoint_catalog = _read_json_object(
        endpoint_catalog_path, "PREFLIGHT_V2_STATUS_CATALOG_UNREADABLE"
    )
    request_budget = _read_json_object(request_budget_path, "PREFLIGHT_V2_STATUS_BUDGET_UNREADABLE")
    operation_plan = build_operation_plan(immutable_plan, endpoint_catalog, request_budget)
    _validate_hard_no_network_gate(operation_plan)
    document = _build_status_document(operation_plan, source_commit)
    validate_current_date_level_pit_status_v2(document)
    payload = _render_json(document)
    output_path = output_dir / _OUTPUT_FILENAME
    _assert_write_compatible(output_path, payload)
    output_dir.mkdir(parents=True, exist_ok=True)
    if not output_path.exists():
        output_path.write_bytes(payload)
    return output_path


def validate_current_date_level_pit_status_v2(document: Mapping[str, object]) -> None:
    """Validate a current PIT-v2 status record's schema, hash and hard gates.

    Parameters
    ----------
    document
        Candidate JSON-compatible status mapping.

    Raises
    ------
    ValueError
        If the semantic self-hash, schema, or zero-network fail-closed policy
        does not hold.
    """
    _validate_self_hash(
        document,
        "semantic_self_hash",
        "PREFLIGHT_V2_STATUS_SELF_HASH_INVALID",
    )
    schema_version = document.get("schema_version")
    if not isinstance(schema_version, str):
        raise ValueError("PREFLIGHT_V2_STATUS_SCHEMA_INVALID")
    schema_path = _SCHEMA_PATH_BY_VERSION.get(schema_version)
    if schema_path is None:
        raise ValueError("PREFLIGHT_V2_STATUS_SCHEMA_INVALID")
    schema = _read_json_object(schema_path, "PREFLIGHT_V2_STATUS_SCHEMA_UNREADABLE")
    try:
        _DRAFT202012_VALIDATOR.check_schema(schema)
        errors = list(_DRAFT202012_VALIDATOR(schema).iter_errors(document))
    except (TypeError, ValueError) as exc:
        raise ValueError("PREFLIGHT_V2_STATUS_SCHEMA_INVALID") from exc
    if errors:
        raise ValueError("PREFLIGHT_V2_STATUS_SCHEMA_INVALID")
    _validate_policy_literals(document, schema_version)


def _build_status_document(operation_plan: OperationPlan, source_commit: str) -> dict[str, object]:
    """Render one deterministic status mapping from a validated no-network plan."""
    availability = _historical_availability_document(operation_plan.historical_availability)
    document: dict[str, object] = {
        "schema_version": _CURRENT_SCHEMA_VERSION,
        "status": "FAILED_CLOSED",
        "scope": "target_blind_date_level_pit_compatibility_only",
        "network_permitted": False,
        "network_attempts_sent": 0,
        "safe_to_reconcile_existing_results": "NO",
        "safe_to_open_or_evaluate_oos": "NO",
        "historical_source_availability": availability,
        "contract_evidence_statuses": [status.value for status in _EXPECTED_EVIDENCE_STATUSES],
        "massive_contract_selection_rule_id": MASSIVE_CONTRACT_SELECTION_RULE_ID,
        "source_fingerprint": {
            "plan_sha256": operation_plan.source_fingerprint.plan_sha256,
            "endpoint_catalog_sha256": operation_plan.source_fingerprint.catalog_sha256,
            "request_budget_sha256": operation_plan.source_fingerprint.budget_sha256,
            "composite_sha256": operation_plan.source_fingerprint.composite_sha256,
        },
        "operation_counts": _operation_counts(operation_plan),
        "attempt_budget": {
            "logical_request_cap": operation_plan.logical_request_cap,
            "global_http_attempt_cap": operation_plan.http_attempt_cap,
            "max_attempts_per_logical_request": operation_plan.max_attempts_per_logical_request,
            "attempts_reserved": 0,
            "attempts_sent": operation_plan.network_gate.attempts_sent,
        },
        "operational_preconditions_not_evaluated": [
            "SECRET_PRESENCE",
            "D_DRIVE_FREE_SPACE",
            "COST_AUTHORIZATION",
        ],
        "required_before_network": [status.value for status in _EXPECTED_EVIDENCE_STATUSES],
        "exact_recheck_commands": [
            (
                "uv run --offline pytest -q tests/unit/test_date_level_pit_preflight_v2.py "
                "tests/unit/test_date_level_pit_preflight_status_v2.py"
            ),
            "uv run --offline python scripts/aggregate_pit_reconciliation_gate_v21.py",
        ],
        "artifact_schema": {
            "logical_path": (
                "specs/001-pit-options-rv30/contracts/"
                "date-level-pit-preflight-status-v2.1.schema.json"
            ),
            "file_sha256": _file_sha256(
                _CURRENT_SCHEMA_PATH,
                "PREFLIGHT_V2_STATUS_SCHEMA_UNREADABLE",
            ),
        },
        "builder_source_sha256": _file_sha256(
            Path(__file__), "PREFLIGHT_V2_STATUS_BUILDER_UNREADABLE"
        ),
        "source_commit": source_commit,
    }
    document["semantic_self_hash"] = _canonical_sha256(document)
    return document


def _validate_hard_no_network_gate(operation_plan: OperationPlan) -> None:
    """Reject any plan that could represent a transport authorization or sent attempt."""
    gate = operation_plan.network_gate
    if (
        gate.status is not NetworkGateStatus.NETWORK_BLOCKED
        or gate.execution_permitted
        or gate.attempts_sent != 0
        or gate.evidence_statuses != _EXPECTED_EVIDENCE_STATUSES
        or operation_plan.contract_selection_rule_id != MASSIVE_CONTRACT_SELECTION_RULE_ID
    ):
        raise ValueError("PREFLIGHT_V2_STATUS_NETWORK_GATE_INVALID")


def _historical_availability_document(
    availability: HistoricalSourceAvailability,
) -> dict[str, str]:
    """Serialize registered historical availability without upgrading PIT semantics."""
    return {
        "status": availability.status.value,
        "fmp": availability.fmp_status.value,
        "unusual_whales": availability.unusual_whales_status.value,
        "fmp_evidence_sha256": availability.fmp_evidence_sha256,
        "unusual_whales_evidence_sha256": availability.unusual_whales_evidence_sha256,
    }


def _operation_counts(operation_plan: OperationPlan) -> dict[str, int]:
    """Count exactly the target-free initial operation categories in the v2 plan."""
    counts = {
        "fmp_minute_bars": 0,
        "unusual_whales_full_tape": 0,
        "massive_contract_search": 0,
        "total_initial_operations": len(operation_plan.initial_operations),
    }
    for operation in operation_plan.initial_operations:
        if operation.kind is OperationKind.MINUTE_BARS:
            counts["fmp_minute_bars"] += 1
        elif operation.kind is OperationKind.FULL_TAPE_ZIP_DOWNLOAD:
            counts["unusual_whales_full_tape"] += 1
        elif operation.kind is OperationKind.CONTRACT_SEARCH:
            counts["massive_contract_search"] += 1
        else:
            raise ValueError("PREFLIGHT_V2_STATUS_UNEXPECTED_INITIAL_OPERATION")
    if counts != {
        "fmp_minute_bars": 56,
        "unusual_whales_full_tape": 7,
        "massive_contract_search": 56,
        "total_initial_operations": 119,
    }:
        raise ValueError("PREFLIGHT_V2_STATUS_OPERATION_COUNT_INVALID")
    return counts


def _validate_policy_literals(document: Mapping[str, object], schema_version: object) -> None:
    """Require the emitted schema-valid document to retain all current hard blocks."""
    expected = {
        "status": "FAILED_CLOSED",
        "scope": "target_blind_date_level_pit_compatibility_only",
        "network_permitted": False,
        "network_attempts_sent": 0,
        "safe_to_reconcile_existing_results": "NO",
        "safe_to_open_or_evaluate_oos": "NO",
    }
    if any(document.get(key) != value for key, value in expected.items()):
        raise ValueError("PREFLIGHT_V2_STATUS_POLICY_INVALID")
    expected_statuses = (
        _EXPECTED_EVIDENCE_STATUSES
        if schema_version == _CURRENT_SCHEMA_VERSION
        else _LEGACY_EVIDENCE_STATUSES
    )
    if document.get("contract_evidence_statuses") != [status.value for status in expected_statuses]:
        raise ValueError("PREFLIGHT_V2_STATUS_POLICY_INVALID")
    if (
        schema_version == _CURRENT_SCHEMA_VERSION
        and document.get("massive_contract_selection_rule_id") != MASSIVE_CONTRACT_SELECTION_RULE_ID
    ):
        raise ValueError("PREFLIGHT_V2_STATUS_POLICY_INVALID")


def _read_json_object(path: Path, error_code: str) -> dict[str, object]:
    """Read one JSON object without echoing a path or its content in errors."""
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(error_code) from exc
    if not isinstance(parsed, dict):
        raise ValueError(error_code)
    return cast(dict[str, object], parsed)


def _validate_self_hash(document: Mapping[str, object], field: str, error_code: str) -> None:
    """Require one ``sha256:`` self-hash over all other mapping fields."""
    value = document.get(field)
    if not isinstance(value, str) or not value.startswith("sha256:"):
        raise ValueError(error_code)
    _require_sha256(value.removeprefix("sha256:"), error_code)
    unsigned = {key: item for key, item in document.items() if key != field}
    if _canonical_sha256(unsigned) != value:
        raise ValueError(error_code)


def _require_sha256(value: str, error_code: str) -> None:
    """Validate a lowercase SHA-256 identity without its optional ``sha256:`` prefix."""
    if _SHA256_PATTERN.fullmatch(value) is None:
        raise ValueError(error_code)


def _require_commit(value: str, error_code: str) -> None:
    """Validate a lowercase forty-character Git commit identity."""
    if _COMMIT_PATTERN.fullmatch(value) is None:
        raise ValueError(error_code)


def _file_sha256(path: Path, error_code: str) -> str:
    """Return a byte SHA-256 for one readable regular file."""
    try:
        if not path.is_file():
            raise OSError("not a regular file")
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise ValueError(error_code) from exc


def _canonical_sha256(document: Mapping[str, object]) -> str:
    """Return a ``sha256:`` canonical JSON identity for one mapping."""
    rendered = json.dumps(
        document,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return "sha256:" + hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def _render_json(document: Mapping[str, object]) -> bytes:
    """Render deterministic human-readable UTF-8 JSON with one terminal newline."""
    return (
        json.dumps(document, allow_nan=False, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _assert_write_compatible(path: Path, payload: bytes) -> None:
    """Permit exact replay but reject replacing a sealed status record."""
    if path.exists() and (not path.is_file() or path.read_bytes() != payload):
        raise ValueError("PREFLIGHT_V2_STATUS_OUTPUT_CONFLICT")
