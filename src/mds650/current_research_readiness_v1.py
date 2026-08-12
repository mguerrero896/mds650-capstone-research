"""Bind current target-blind MDS650 evidence into one fail-closed readiness ledger.

This module deliberately distinguishes observed historical availability from
point-in-time (PIT) timing proof.  It does not load targets, predictions,
model outputs, or provider payloads; it binds only five sanitized local
evidence artifacts by their exact byte identity.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from collections.abc import Iterable, Mapping
from importlib import import_module
from pathlib import Path
from typing import Protocol, cast


class _JsonSchemaValidator(Protocol):
    """Small typed boundary over the runtime JSON Schema validator."""

    def iter_errors(self, instance: object) -> Iterable[object]:
        """Yield validation errors for one JSON-compatible object."""


class _Draft202012ValidatorFactory(Protocol):
    """Construction and schema-validation boundary for Draft 2020-12."""

    def __call__(self, schema: Mapping[str, object]) -> _JsonSchemaValidator:
        """Construct a validator for one JSON Schema mapping."""

    def check_schema(self, schema: Mapping[str, object]) -> None:
        """Raise when a JSON Schema mapping is invalid."""


def _load_draft202012_validator() -> _Draft202012ValidatorFactory:
    """Load the untyped JSON Schema runtime behind a narrow protocol."""
    module = import_module("jsonschema")
    candidate = cast(object, getattr(module, "Draft202012Validator", None))
    if not callable(candidate) or not callable(getattr(candidate, "check_schema", None)):
        raise RuntimeError("CURRENT_RESEARCH_READINESS_JSONSCHEMA_VALIDATOR_UNAVAILABLE")
    return cast(_Draft202012ValidatorFactory, candidate)


_DRAFT202012_VALIDATOR = _load_draft202012_validator()
_ROOT = Path(__file__).resolve().parents[2]
_SCHEMA_PATH = (
    _ROOT
    / "specs"
    / "001-pit-options-rv30"
    / "contracts"
    / "current-research-readiness-v1.schema.json"
)
_SCHEMA_VERSION = "current-research-readiness-v1.0"
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_SECRET_VALUE_PATTERN = re.compile(
    r"(?i)(?:api[_-]?key|authorization|password|secret)\s*(?:=|:)|bearer\s+[a-z0-9._-]+"
)
_PERSONAL_PATH_PATTERN = re.compile(r"(?i)(?:(?<![a-z])[a-z]:[\\/]|/users/|/home/)")
_EMAIL_PATTERN = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
_EXPECTED_INPUT_NAMES = (
    "policy_gate",
    "preflight",
    "source_coverage",
    "fmp_docs_review",
    "confirmation_readiness",
)
_EXPECTED_FILE_SHA256 = {
    "policy_gate": "a37560470159cee24a80bc2d0f93883eab02264aa6fd880d88f69a8df2744f79",
    "preflight": "9e246c6a167fc0a5ed5cb61cf83e6a747e6dee74901a4aa52f2ad76ab579e6db",
    "source_coverage": "c9719cab83000e52d6dae2778fd1e65395ede0270fce1f8e7ef75140cdbfdc2b",
    "fmp_docs_review": "debf59a05d062c1b2f3b16b98e40f8df61ec363f7a79ce23a6659680e3aa225a",
    "confirmation_readiness": "fc04acc0d466b25a176f3f2e599fad516a69c3a74251469178a7406d00826095",
}
_SOURCE_ROLES = {
    "policy_gate": "PROVIDER_TIMING_POLICY_GATE_V1",
    "preflight": "DATE_LEVEL_PIT_PREFLIGHT_STATUS_V2_1",
    "source_coverage": "CORRECTED_DEVELOPMENT_SOURCE_COVERAGE_V1",
    "fmp_docs_review": "FMP_B1Q_EXOGENOUS_DOCS_REVIEW_V1",
    "confirmation_readiness": "CONFIRMATION_READINESS_V3",
}
_SOURCE_IDENTITIES = {
    "policy_gate": "05da11e4f24c73d1cb8f01fee6daf6da75040a6ae0399f8bcc9cbb03647933a7",
    "preflight": "a866b52ab7e6b8bbee38c6041c3935eb7fb329a7e1006674816d4008a71f6112",
    "source_coverage": "088cf2259a2d6acdb58c9651d0a43f39938e5e639069bb92960baa3e869c4d1d",
    "fmp_docs_review": "e460e2e22c2c5105b86fc97909da64d98184f3060bb52767c8ffeb53211f89ad",
    "confirmation_readiness": "5a2cd9996ec2ff0017bf5f84de9871cffce2b19780b7592d9efa4e8a08719cf3",
}
_SOURCE_STATUSES = {
    "policy_gate": "PASS_EVIDENCE_SCOPED_POLICY_FAIL_CLOSED",
    "preflight": "FAILED_CLOSED",
    "source_coverage": "BLOCKED_SOURCE_COVERAGE",
    "fmp_docs_review": "DOCUMENTED_ENDPOINTS_INSUFFICIENT_FOR_B1Q_PIT",
    "confirmation_readiness": "PASS_METHOD_FROZEN_TARGET_BLIND_READY_FUTURE_GATES_CLOSED",
}
_CURRENT_BLOCKERS = [
    "B1Q_EXOGENOUS_INPUT_PROVENANCE_UNRESOLVED",
    "DATE_LEVEL_PIT_PREFLIGHT_FAILED_CLOSED",
    "SAFE_TO_RECONCILE_EXISTING_RESULTS_NO",
    "SAFE_TO_OPEN_OR_EVALUATE_OOS_NO",
]


def build_current_research_readiness_v1(*, input_paths: Mapping[str, Path]) -> dict[str, object]:
    """Bind the registered target-blind evidence into the current readiness state.

    Parameters
    ----------
    input_paths
        Exact local paths for the policy gate, date-level preflight status,
        source-coverage ledger, FMP B1Q documentation review, and confirmation
        readiness record.  Byte identities must match the registered snapshot.

    Returns
    -------
    dict[str, object]
        Deterministic, schema-valid readiness ledger.  It states that FMP and
        Unusual Whales historical sources are observed as available while B1Q
        provenance and date-level PIT preflight remain unresolved.

    Raises
    ------
    ValueError
        If an input is absent, differs from its registered bytes, violates its
        fail-closed state, or the constructed ledger violates its contract.

    Notes
    -----
    The function does not read target, metric, prediction, model, OOS, raw
    provider-payload, secret, or personal-path data.
    """
    _validate_input_keys(input_paths)
    sources: dict[str, dict[str, str]] = {}
    for name in _EXPECTED_INPUT_NAMES:
        document, file_sha256 = _read_registered_source(name, input_paths[name])
        _validate_source_document(name, document)
        sources[name] = {
            "role": _SOURCE_ROLES[name],
            "file_sha256": file_sha256,
            "status": _SOURCE_STATUSES[name],
            "artifact_identity": _SOURCE_IDENTITIES[name],
        }

    ledger: dict[str, object] = {
        "schema_version": _SCHEMA_VERSION,
        "status": "READY_FOR_CONFIRMATION_WITH_BLOCKERS",
        "scope": "offline_target_blind_current_readiness_only",
        "observed_on_utc": "2026-08-12",
        "method_freeze_status": "FROZEN_TARGET_BLIND_ONLY",
        "historical_source_availability": {
            "fmp": "PASS_90_OF_90_SESSIONS",
            "unusual_whales": "PASS_90_OF_90_FILE_METADATA",
            "interpretation": "AVAILABLE_HISTORY_NOT_PIT_TIMESTAMP_PROOF",
        },
        "b1q_exogenous_input_provenance": "UNRESOLVED",
        "date_level_pit_preflight": "FAILED_CLOSED",
        "safe_to_build_b0_b1_b2_evaluation": False,
        "safe_to_reconcile_existing_results": "NO",
        "safe_to_open_or_evaluate_oos": "NO",
        "safe_to_acquire_new_historical_sample": "NO",
        "current_blockers": list(_CURRENT_BLOCKERS),
        "bound_sources": sources,
        "provider_market_data_requests_performed": False,
        "target_or_metric_payload_read": False,
        "model_fit_performed": False,
        "secret_values_emitted": False,
        "personal_paths_emitted": False,
    }
    ledger["semantic_self_hash"] = _canonical_sha256(ledger)
    validate_current_research_readiness_v1(ledger)
    return ledger


def validate_current_research_readiness_v1(ledger: Mapping[str, object]) -> None:
    """Validate the current readiness ledger's integrity and fail-closed policy.

    Parameters
    ----------
    ledger
        Candidate ledger produced by :func:`build_current_research_readiness_v1`.

    Raises
    ------
    ValueError
        If the JSON Schema, self-hash, source bindings, hygiene checks, or
        invariant blocking evaluation and OOS access is violated.
    """
    _validate_self_hash(ledger)
    _validate_schema(ledger)
    _assert_sanitized(ledger)


def write_current_research_readiness_v1(
    *, input_paths: Mapping[str, Path], output_path: Path
) -> Path:
    """Write the immutable current readiness ledger or retain an identical replay.

    Parameters
    ----------
    input_paths
        Registered target-blind source artifacts accepted by the builder.
    output_path
        Destination for the generated JSON ledger.

    Returns
    -------
    pathlib.Path
        ``output_path`` after an atomic new write or a byte-identical replay.

    Raises
    ------
    ValueError
        If an existing destination differs, the input evidence is invalid, or
        the output cannot be written safely.
    """
    payload = _render_json(build_current_research_readiness_v1(input_paths=input_paths))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        if output_path.read_bytes() != payload:
            raise ValueError("CURRENT_RESEARCH_READINESS_OUTPUT_CONFLICT")
        return output_path
    temporary_path = output_path.with_name(f".{output_path.name}.{uuid.uuid4().hex}.part")
    try:
        temporary_path.write_bytes(payload)
        try:
            os.link(temporary_path, output_path)
        except FileExistsError:
            if output_path.read_bytes() != payload:
                raise ValueError("CURRENT_RESEARCH_READINESS_OUTPUT_CONFLICT") from None
    except OSError as exc:
        raise ValueError("CURRENT_RESEARCH_READINESS_OUTPUT_UNWRITABLE") from exc
    finally:
        temporary_path.unlink(missing_ok=True)
    return output_path


def _validate_input_keys(input_paths: Mapping[str, Path]) -> None:
    """Fail closed unless exactly the five registered evidence names are present."""
    if set(input_paths) != set(_EXPECTED_INPUT_NAMES):
        raise ValueError("CURRENT_RESEARCH_READINESS_INPUT_SET_INVALID")


def _read_registered_source(name: str, path: Path) -> tuple[dict[str, object], str]:
    """Read one fixed-byte source artifact without emitting its path."""
    error_code = f"CURRENT_RESEARCH_READINESS_{name.upper()}_INVALID"
    try:
        payload = path.read_bytes()
        document = json.loads(payload.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(error_code) from exc
    if not isinstance(document, dict):
        raise ValueError(error_code)
    file_sha256 = hashlib.sha256(payload).hexdigest()
    if file_sha256 != _EXPECTED_FILE_SHA256[name]:
        raise ValueError(error_code)
    return cast(dict[str, object], document), file_sha256


def _validate_source_document(name: str, document: Mapping[str, object]) -> None:
    """Confirm that each registered artifact still states its declared boundary."""
    error_code = f"CURRENT_RESEARCH_READINESS_{name.upper()}_INVALID"
    if document.get("status") != _SOURCE_STATUSES[name]:
        raise ValueError(error_code)
    if name == "policy_gate":
        reconciliation = document.get("existing_sealed_result_reconciliation")
        oos_access = document.get("oos_access")
        if (
            not isinstance(reconciliation, Mapping)
            or reconciliation.get("safe_to_reconcile_existing_results") != "NO"
            or not isinstance(oos_access, Mapping)
            or oos_access.get("safe_to_open_or_evaluate_oos") != "NO"
            or document.get("policy_sha256") != _SOURCE_IDENTITIES[name]
        ):
            raise ValueError(error_code)
        return
    if name == "preflight":
        availability = document.get("historical_source_availability")
        if (
            document.get("network_attempts_sent") != 0
            or document.get("safe_to_reconcile_existing_results") != "NO"
            or document.get("safe_to_open_or_evaluate_oos") != "NO"
            or document.get("semantic_self_hash") != f"sha256:{_SOURCE_IDENTITIES[name]}"
            or not isinstance(availability, Mapping)
            or availability.get("fmp") != "PASS_90_OF_90_SESSIONS"
            or availability.get("unusual_whales") != "PASS_90_OF_90_FILE_METADATA"
        ):
            raise ValueError(error_code)
        return
    if name == "source_coverage":
        components = document.get("components")
        if not isinstance(components, Mapping):
            raise ValueError(error_code)
        b1q = components.get("B1Q")
        if (
            not isinstance(b1q, Mapping)
            or b1q.get("status") != "BLOCKED"
            or b1q.get("unresolved_origin_count") != 34080
            or document.get("target_binding_permitted") is not False
            or document.get("safe_to_open_or_evaluate_oos") != "NO"
            or document.get("ledger_sha256") != _SOURCE_IDENTITIES[name]
        ):
            raise ValueError(error_code)
        return
    if name == "fmp_docs_review":
        if (
            document.get("b1q_exogenous_input_provenance_status") != "UNRESOLVED"
            or document.get("safe_to_build_b1q") is not False
            or document.get("safe_to_reconcile_existing_results") != "NO"
            or document.get("safe_to_open_or_evaluate_oos") != "NO"
            or document.get("semantic_self_hash") != f"sha256:{_SOURCE_IDENTITIES[name]}"
        ):
            raise ValueError(error_code)
        return
    if (
        document.get("method_freeze_status") != "FROZEN_TARGET_BLIND_ONLY"
        or document.get("safe_to_acquire_new_historical_sample") != "NO"
        or document.get("safe_to_reconcile_existing_results") != "NO"
        or document.get("safe_to_open_or_evaluate_oos") != "NO"
        or document.get("readiness_sha256") != _SOURCE_IDENTITIES[name]
    ):
        raise ValueError(error_code)


def _validate_schema(ledger: Mapping[str, object]) -> None:
    """Validate one ledger against the local Draft 2020-12 contract."""
    schema = _read_json_object(_SCHEMA_PATH, "CURRENT_RESEARCH_READINESS_SCHEMA_INVALID")
    try:
        _DRAFT202012_VALIDATOR.check_schema(schema)
        errors = list(_DRAFT202012_VALIDATOR(schema).iter_errors(ledger))
    except (TypeError, ValueError) as exc:
        raise ValueError("CURRENT_RESEARCH_READINESS_SCHEMA_INVALID") from exc
    if errors:
        raise ValueError("CURRENT_RESEARCH_READINESS_SCHEMA_INVALID")


def _validate_self_hash(ledger: Mapping[str, object]) -> None:
    """Reject a changed ledger before evaluating its fail-closed policy fields."""
    value = ledger.get("semantic_self_hash")
    if not isinstance(value, str) or not value.startswith("sha256:"):
        raise ValueError("CURRENT_RESEARCH_READINESS_SELF_HASH_INVALID")
    if _SHA256_PATTERN.fullmatch(value[7:]) is None:
        raise ValueError("CURRENT_RESEARCH_READINESS_SELF_HASH_INVALID")
    unsigned = dict(ledger)
    unsigned.pop("semantic_self_hash", None)
    if _canonical_sha256(unsigned) != value:
        raise ValueError("CURRENT_RESEARCH_READINESS_SELF_HASH_INVALID")


def _read_json_object(path: Path, error_code: str) -> dict[str, object]:
    """Read a JSON object without including a local path in any error output."""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(error_code) from exc
    if not isinstance(value, dict):
        raise ValueError(error_code)
    return cast(dict[str, object], value)


def _canonical_sha256(document: Mapping[str, object]) -> str:
    """Return the deterministic semantic SHA-256 for one JSON-compatible mapping."""
    rendered = json.dumps(
        document,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return "sha256:" + hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def _render_json(document: Mapping[str, object]) -> bytes:
    """Render stable indented JSON with a platform-independent trailing newline."""
    rendered = json.dumps(document, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    return rendered.encode("utf-8")


def _assert_sanitized(document: Mapping[str, object]) -> None:
    """Reject credentials, email addresses, and personal filesystem paths."""
    rendered = json.dumps(document, allow_nan=False, ensure_ascii=True, sort_keys=True)
    if (
        _SECRET_VALUE_PATTERN.search(rendered)
        or _PERSONAL_PATH_PATTERN.search(rendered)
        or _EMAIL_PATTERN.search(rendered)
    ):
        raise ValueError("CURRENT_RESEARCH_READINESS_UNSAFE_CONTENT")
