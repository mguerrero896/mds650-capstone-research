"""Fail-closed intake for external provider-timing semantics evidence.

This module assesses only the completeness and hygiene of a sanitized provider
document or support-response submission.  A complete intake is reviewable; it
does not by itself verify the truth of a provider assertion, change a PIT gate,
permit network access, reconcile sealed results, or authorize OOS access.
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
    """Load the JSON-Schema runtime behind a narrow typed protocol."""
    module = import_module("jsonschema")
    candidate = cast(object, getattr(module, "Draft202012Validator", None))
    if not callable(candidate) or not callable(getattr(candidate, "check_schema", None)):
        raise RuntimeError("PIT_EVIDENCE_INTAKE_JSONSCHEMA_VALIDATOR_UNAVAILABLE")
    return cast(_Draft202012ValidatorFactory, candidate)


_DRAFT202012_VALIDATOR = _load_draft202012_validator()
_ROOT = Path(__file__).resolve().parents[2]
_CONTRACT_DIR = _ROOT / "specs" / "001-pit-options-rv30" / "contracts"
_SUBMISSION_SCHEMA_PATH = (
    _CONTRACT_DIR / "provider-timing-semantics-evidence-submission-v1.schema.json"
)
_ASSESSMENT_SCHEMA_PATH = (
    _CONTRACT_DIR / "provider-timing-semantics-evidence-assessment-v1.schema.json"
)
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_UTC_TIMESTAMP_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_SECRET_VALUE_PATTERN = re.compile(
    r"(?i)(?:api[_-]?key|authorization|password|secret)\s*(?:=|:)|bearer\s+[a-z0-9._-]+"
)
_PERSONAL_PATH_PATTERN = re.compile(r"(?i)(?:(?<![a-z])[a-z]:[\\/]|/users/|/home/)")
_EMAIL_PATTERN = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
_SAFE_SUPPORT_CASE_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{1,31}-[A-Za-z0-9_-]{3,127}$")

_REQUIRED_CLAIMS: dict[str, tuple[str, ...]] = {
    "FMP_DATE_BOUNDED_ONLY_NO_PIT_CLAIM": (
        "FMP_RESPONSE_TIMESTAMP_TIMEZONE",
        "FMP_BAR_INTERVAL_LABEL",
        "FMP_REST_AVAILABILITY_LATENCY",
        "FMP_HISTORICAL_CORRECTION_BEHAVIOR",
    ),
    "UW_FULL_TAPE_ZIP_ROUTE_DOCUMENTED_EXECUTION_GATED": (
        "UW_EXECUTED_AT_SEMANTICS",
        "UW_CREATED_AT_SEMANTICS",
        "UW_CUSTOMER_VISIBLE_AVAILABILITY",
        "UW_ARCHIVE_CORRECTION_BEHAVIOR",
        "UW_STABLE_EVENT_IDENTIFIER",
    ),
    "MASSIVE_CONTRACT_SELECTION_RULE_UNRESOLVED_NO_EXECUTION": (
        "MASSIVE_CONTRACT_AS_OF_SEMANTICS",
        "MASSIVE_CONTRACT_PAGINATION_SEMANTICS",
        "MASSIVE_CONTRACT_CORRECTION_BEHAVIOR",
        "MASSIVE_CONTRACT_SELECTION_RULE",
    ),
    "MASSIVE_QUOTE_AS_OF_PARAMETERS_DOCUMENTED_LOCAL_SIP_CHECK_REQUIRED": (
        "MASSIVE_QUOTE_LTE_WIRE_FORMAT",
        "MASSIVE_QUOTE_LTE_INCLUSIVITY",
        "MASSIVE_QUOTE_ORDERING_TIE_BREAK",
        "MASSIVE_SIP_TIMESTAMP_SEMANTICS",
    ),
}
_BLOCK_PROVIDER = {
    "FMP_DATE_BOUNDED_ONLY_NO_PIT_CLAIM": "FMP",
    "UW_FULL_TAPE_ZIP_ROUTE_DOCUMENTED_EXECUTION_GATED": "UNUSUAL_WHALES",
    "MASSIVE_CONTRACT_SELECTION_RULE_UNRESOLVED_NO_EXECUTION": "MASSIVE",
    "MASSIVE_QUOTE_AS_OF_PARAMETERS_DOCUMENTED_LOCAL_SIP_CHECK_REQUIRED": "MASSIVE",
}
_OFFICIAL_DOMAINS = {
    "FMP": "site.financialmodelingprep.com",
    "UNUSUAL_WHALES": "api.unusualwhales.com",
    "MASSIVE": "massive.com",
}


def assess_provider_timing_semantics_evidence_submission_v1(
    submission: Mapping[str, object],
) -> dict[str, object]:
    """Assess one sanitized evidence submission without changing any research gate.

    Parameters
    ----------
    submission
        A schema-valid record identifying one unresolved provider-timing block,
        a versioned official source or sanitized support case, and structured
        claims with locators and concise statements.

    Returns
    -------
    dict[str, object]
        Deterministic review-intake assessment.  A complete submission has
        status ``EVIDENCE_COMPLETE_REQUIRES_INDEPENDENT_TECHNICAL_REVIEW``;
        both outcomes retain every network, reconciliation, and OOS gate as
        ``False`` or ``NO``.

    Raises
    ------
    ValueError
        If the input schema, provider-block relationship, source identity,
        timestamp, claim uniqueness, or sanitization boundary is invalid.

    Notes
    -----
    This function makes no provider request and does not inspect secrets,
    target values, RV30, metrics, models, predictions, OOS artefacts, or raw
    market payloads.  It does not adjudicate the truth of any provider claim.
    """
    _validate_submission_schema(submission)
    _assert_sanitized(submission)
    provider = _required_string(submission, "provider", "PIT_EVIDENCE_INTAKE_PROVIDER_INVALID")
    blocking_status = _required_string(
        submission, "blocking_status", "PIT_EVIDENCE_INTAKE_BLOCKING_STATUS_INVALID"
    )
    _validate_provider_block(provider, blocking_status)
    source = _required_mapping(submission, "source", "PIT_EVIDENCE_INTAKE_SOURCE_INVALID")
    _validate_source(provider, source)
    claim_ids = _claim_ids(submission)
    required_claim_ids = _REQUIRED_CLAIMS[blocking_status]
    missing_claim_ids = [claim_id for claim_id in required_claim_ids if claim_id not in claim_ids]
    status = (
        "EVIDENCE_COMPLETE_REQUIRES_INDEPENDENT_TECHNICAL_REVIEW"
        if not missing_claim_ids
        else "EVIDENCE_INSUFFICIENT"
    )
    document: dict[str, object] = {
        "schema_version": "provider-timing-semantics-evidence-assessment-v1.0",
        "status": status,
        "scope": "target_blind_provider_timing_evidence_intake_only",
        "provider": provider,
        "blocking_status": blocking_status,
        "source": _normalized_source(source),
        "required_claim_ids": list(required_claim_ids),
        "submitted_claim_ids": [
            claim_id for claim_id in required_claim_ids if claim_id in claim_ids
        ],
        "missing_claim_ids": missing_claim_ids,
        "acceptance_boundary": (
            "COMPLETENESS_AND_HYGIENE_ONLY_PROVIDER_CLAIM_TRUTH_REQUIRES_INDEPENDENT_REVIEW"
        ),
        "hard_gate_action": "NONE",
        "network_permitted": False,
        "safe_to_reconcile_existing_results": "NO",
        "safe_to_open_or_evaluate_oos": "NO",
        "no_provider_http_requests_performed": True,
        "no_target_or_metric_payload_read": True,
        "no_oos_or_predictive_artifacts_read": True,
        "model_fit_performed": False,
        "secret_values_emitted": False,
        "personal_paths_emitted": False,
    }
    document["semantic_self_hash"] = _canonical_sha256(document)
    validate_provider_timing_semantics_evidence_assessment_v1(document)
    return document


def validate_provider_timing_semantics_evidence_assessment_v1(
    assessment: Mapping[str, object],
) -> None:
    """Validate an assessment's schema, self-hash, and non-authorizing policy.

    Parameters
    ----------
    assessment
        Candidate assessment produced by
        :func:`assess_provider_timing_semantics_evidence_submission_v1`.

    Raises
    ------
    ValueError
        If the self-hash, JSON Schema contract, sanitization boundary, or
        fail-closed policy literals are invalid.
    """
    _validate_self_hash(assessment)
    _validate_assessment_schema(assessment)
    _assert_sanitized(assessment)
    _validate_claim_state(assessment)
    expected = {
        "hard_gate_action": "NONE",
        "network_permitted": False,
        "safe_to_reconcile_existing_results": "NO",
        "safe_to_open_or_evaluate_oos": "NO",
        "no_provider_http_requests_performed": True,
        "no_target_or_metric_payload_read": True,
        "no_oos_or_predictive_artifacts_read": True,
        "model_fit_performed": False,
        "secret_values_emitted": False,
        "personal_paths_emitted": False,
    }
    if any(assessment.get(key) != value for key, value in expected.items()):
        raise ValueError("PIT_EVIDENCE_ASSESSMENT_FAIL_CLOSED_POLICY_INVALID")


def write_provider_timing_semantics_evidence_assessment_v1(
    *, submission_path: Path, output_path: Path
) -> Path:
    """Write one deterministic assessment without replacing divergent evidence.

    Parameters
    ----------
    submission_path
        Path to one sanitized JSON evidence submission that follows the local
        input contract.
    output_path
        Path for the immutable, canonical assessment JSON.

    Returns
    -------
    pathlib.Path
        ``output_path`` after an atomic write or byte-identical replay.

    Raises
    ------
    ValueError
        If the submission is unreadable or invalid, or if an existing output
        differs from the deterministic assessment for that submission.

    Notes
    -----
    The write is local only.  It neither sends a provider request nor alters
    any network, sealed-result, OOS, or model-fitting gate.
    """
    submission = _read_json_object(submission_path, "PIT_EVIDENCE_INTAKE_SUBMISSION_UNREADABLE")
    assessment = assess_provider_timing_semantics_evidence_submission_v1(submission)
    payload = _render_json(assessment)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        if output_path.read_bytes() != payload:
            raise ValueError("PIT_EVIDENCE_ASSESSMENT_OUTPUT_CONFLICT")
        return output_path

    temporary_path = output_path.with_name(f".{output_path.name}.{uuid.uuid4().hex}.part")
    try:
        temporary_path.write_bytes(payload)
        try:
            os.link(temporary_path, output_path)
        except FileExistsError:
            if output_path.read_bytes() != payload:
                raise ValueError("PIT_EVIDENCE_ASSESSMENT_OUTPUT_CONFLICT") from None
    finally:
        temporary_path.unlink(missing_ok=True)
    return output_path


def _validate_submission_schema(submission: Mapping[str, object]) -> None:
    """Validate the public submission envelope before contextual inspection."""
    _validate_against_schema(
        submission,
        _SUBMISSION_SCHEMA_PATH,
        "PIT_EVIDENCE_INTAKE_SUBMISSION_SCHEMA_INVALID",
    )


def _validate_assessment_schema(assessment: Mapping[str, object]) -> None:
    """Validate the public assessment envelope after its self-hash check."""
    _validate_against_schema(
        assessment,
        _ASSESSMENT_SCHEMA_PATH,
        "PIT_EVIDENCE_ASSESSMENT_SCHEMA_INVALID",
    )


def _validate_claim_state(assessment: Mapping[str, object]) -> None:
    """Require claim lists and review status to describe one coherent state."""
    required = _claim_id_list(
        assessment, "required_claim_ids", "PIT_EVIDENCE_ASSESSMENT_CLAIM_STATE_INVALID"
    )
    submitted = _claim_id_list(
        assessment, "submitted_claim_ids", "PIT_EVIDENCE_ASSESSMENT_CLAIM_STATE_INVALID"
    )
    missing = _claim_id_list(
        assessment, "missing_claim_ids", "PIT_EVIDENCE_ASSESSMENT_CLAIM_STATE_INVALID"
    )
    if len(set(required)) != len(required) or len(set(submitted)) != len(submitted):
        raise ValueError("PIT_EVIDENCE_ASSESSMENT_CLAIM_STATE_INVALID")
    expected_submitted = [claim_id for claim_id in required if claim_id in submitted]
    expected_missing = [claim_id for claim_id in required if claim_id not in submitted]
    if submitted != expected_submitted or missing != expected_missing:
        raise ValueError("PIT_EVIDENCE_ASSESSMENT_CLAIM_STATE_INVALID")
    status = _required_string(assessment, "status", "PIT_EVIDENCE_ASSESSMENT_CLAIM_STATE_INVALID")
    if (status == "EVIDENCE_COMPLETE_REQUIRES_INDEPENDENT_TECHNICAL_REVIEW" and missing) or (
        status == "EVIDENCE_INSUFFICIENT" and not missing
    ):
        raise ValueError("PIT_EVIDENCE_ASSESSMENT_CLAIM_STATE_INVALID")


def _validate_against_schema(
    document: Mapping[str, object], schema_path: Path, error_code: str
) -> None:
    """Validate one JSON-compatible mapping against a local Draft 2020-12 schema."""
    schema = _read_json_object(schema_path, error_code)
    try:
        _DRAFT202012_VALIDATOR.check_schema(schema)
        errors = list(_DRAFT202012_VALIDATOR(schema).iter_errors(document))
    except (TypeError, ValueError) as exc:
        raise ValueError(error_code) from exc
    if errors:
        raise ValueError(error_code)


def _validate_provider_block(provider: str, blocking_status: str) -> None:
    """Require one known unresolved hard block for its responsible provider."""
    expected_provider = _BLOCK_PROVIDER.get(blocking_status)
    if expected_provider is None or expected_provider != provider:
        raise ValueError("PIT_EVIDENCE_INTAKE_PROVIDER_BLOCK_MISMATCH")


def _validate_source(provider: str, source: Mapping[str, object]) -> None:
    """Validate one source's immutable identity without evaluating its truth."""
    source_type = _required_string(source, "source_type", "PIT_EVIDENCE_INTAKE_SOURCE_INVALID")
    reference = _required_string(source, "reference", "PIT_EVIDENCE_INTAKE_SOURCE_INVALID")
    source_version = _required_string(
        source, "source_version", "PIT_EVIDENCE_INTAKE_SOURCE_INVALID"
    )
    captured_at_utc = _required_string(
        source, "captured_at_utc", "PIT_EVIDENCE_INTAKE_SOURCE_INVALID"
    )
    content_sha256 = _required_string(
        source, "source_content_sha256", "PIT_EVIDENCE_INTAKE_SOURCE_INVALID"
    )
    if not source_version.strip() or _UTC_TIMESTAMP_PATTERN.fullmatch(captured_at_utc) is None:
        raise ValueError("PIT_EVIDENCE_INTAKE_SOURCE_INVALID")
    if _SHA256_PATTERN.fullmatch(content_sha256) is None:
        raise ValueError("PIT_EVIDENCE_INTAKE_SOURCE_INVALID")
    if source_type == "OFFICIAL_VERSIONED_SPECIFICATION":
        expected_domain = _OFFICIAL_DOMAINS[provider]
        if not reference.startswith(f"https://{expected_domain}/") or "?" in reference:
            raise ValueError("PIT_EVIDENCE_INTAKE_SOURCE_REFERENCE_INVALID")
    elif source_type == "PROVIDER_SUPPORT_CASE_RESPONSE":
        if _SAFE_SUPPORT_CASE_PATTERN.fullmatch(reference) is None:
            raise ValueError("PIT_EVIDENCE_INTAKE_SOURCE_REFERENCE_INVALID")
    else:
        raise ValueError("PIT_EVIDENCE_INTAKE_SOURCE_INVALID")


def _claim_ids(submission: Mapping[str, object]) -> set[str]:
    """Validate structured claims and return their distinct identifiers."""
    claims = submission.get("claims")
    if not isinstance(claims, list) or not claims:
        raise ValueError("PIT_EVIDENCE_INTAKE_CLAIMS_INVALID")
    provider = _required_string(submission, "provider", "PIT_EVIDENCE_INTAKE_PROVIDER_INVALID")
    allowed_claim_ids = {
        claim_id
        for blocking_status, claim_ids in _REQUIRED_CLAIMS.items()
        if _BLOCK_PROVIDER[blocking_status] == provider
        for claim_id in claim_ids
    }
    observed: set[str] = set()
    for claim in claims:
        if not isinstance(claim, Mapping):
            raise ValueError("PIT_EVIDENCE_INTAKE_CLAIMS_INVALID")
        claim_id = _required_string(claim, "claim_id", "PIT_EVIDENCE_INTAKE_CLAIMS_INVALID")
        locator = _required_string(claim, "locator", "PIT_EVIDENCE_INTAKE_CLAIMS_INVALID")
        statement = _required_string(claim, "statement", "PIT_EVIDENCE_INTAKE_CLAIMS_INVALID")
        if claim_id not in allowed_claim_ids:
            raise ValueError("PIT_EVIDENCE_INTAKE_CLAIM_NOT_ALLOWED")
        if claim_id in observed:
            raise ValueError("PIT_EVIDENCE_INTAKE_DUPLICATE_CLAIM")
        if not locator.strip() or len(statement.strip()) < 20:
            raise ValueError("PIT_EVIDENCE_INTAKE_CLAIMS_INVALID")
        observed.add(claim_id)
    return observed


def _normalized_source(source: Mapping[str, object]) -> dict[str, str]:
    """Copy the immutable source identity in deterministic key order."""
    return {
        "source_type": _required_string(
            source, "source_type", "PIT_EVIDENCE_INTAKE_SOURCE_INVALID"
        ),
        "reference": _required_string(source, "reference", "PIT_EVIDENCE_INTAKE_SOURCE_INVALID"),
        "source_version": _required_string(
            source, "source_version", "PIT_EVIDENCE_INTAKE_SOURCE_INVALID"
        ),
        "captured_at_utc": _required_string(
            source, "captured_at_utc", "PIT_EVIDENCE_INTAKE_SOURCE_INVALID"
        ),
        "source_content_sha256": _required_string(
            source, "source_content_sha256", "PIT_EVIDENCE_INTAKE_SOURCE_INVALID"
        ),
    }


def _claim_id_list(assessment: Mapping[str, object], key: str, error_code: str) -> list[str]:
    """Return one schema-validated claim-ID list with a stable failure code."""
    value = assessment.get(key)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(error_code)
    return cast(list[str], value)


def _validate_self_hash(assessment: Mapping[str, object]) -> None:
    """Reject changed assessment content before applying policy validation."""
    recorded = _required_string(
        assessment, "semantic_self_hash", "PIT_EVIDENCE_ASSESSMENT_SELF_HASH_INVALID"
    )
    if not recorded.startswith("sha256:") or _SHA256_PATTERN.fullmatch(recorded[7:]) is None:
        raise ValueError("PIT_EVIDENCE_ASSESSMENT_SELF_HASH_INVALID")
    unsigned = dict(assessment)
    unsigned.pop("semantic_self_hash", None)
    if _canonical_sha256(unsigned) != recorded:
        raise ValueError("PIT_EVIDENCE_ASSESSMENT_SELF_HASH_INVALID")


def _read_json_object(path: Path, error_code: str) -> dict[str, object]:
    """Read one local JSON object without disclosing its path in exceptions."""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(error_code) from exc
    if not isinstance(value, dict):
        raise ValueError(error_code)
    return cast(dict[str, object], value)


def _required_mapping(
    mapping: Mapping[str, object], key: str, error_code: str
) -> Mapping[str, object]:
    """Return one required object-valued field with a stable failure code."""
    value = mapping.get(key)
    if not isinstance(value, Mapping):
        raise ValueError(error_code)
    return cast(Mapping[str, object], value)


def _required_string(mapping: Mapping[str, object], key: str, error_code: str) -> str:
    """Return one required non-empty string field with a stable failure code."""
    value = mapping.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(error_code)
    return value


def _canonical_sha256(document: Mapping[str, object]) -> str:
    """Compute the repository canonical SHA-256 self-hash for one document."""
    rendered = json.dumps(
        document,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return "sha256:" + hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def _render_json(document: Mapping[str, object]) -> bytes:
    """Render canonical persisted JSON with a platform-independent newline."""
    rendered = json.dumps(document, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    return rendered.encode("utf-8")


def _assert_sanitized(document: Mapping[str, object]) -> None:
    """Reject credentials, personal paths, and email addresses before retention."""
    rendered = json.dumps(document, allow_nan=False, ensure_ascii=True, sort_keys=True)
    if (
        _SECRET_VALUE_PATTERN.search(rendered)
        or _PERSONAL_PATH_PATTERN.search(rendered)
        or _EMAIL_PATTERN.search(rendered)
    ):
        raise ValueError("PIT_EVIDENCE_INTAKE_UNSAFE_CONTENT")
