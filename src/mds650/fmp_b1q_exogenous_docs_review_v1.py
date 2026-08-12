"""Bounded documentation review for FMP B1Q rate and dividend inputs.

The review records only what the official FMP endpoint and cycle-time pages
state.  It is deliberately not a provider payload, a historical-revision log,
or an authorization to rebuild B1Q.  In particular, endpoint existence and a
nominal refresh cycle do not establish that a historical value was available to
the customer before any particular forecast origin.
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
        raise RuntimeError("FMP_B1Q_DOCS_REVIEW_JSONSCHEMA_VALIDATOR_UNAVAILABLE")
    return cast(_Draft202012ValidatorFactory, candidate)


_DRAFT202012_VALIDATOR = _load_draft202012_validator()
_ROOT = Path(__file__).resolve().parents[2]
_SCHEMA_PATH = (
    _ROOT
    / "specs"
    / "001-pit-options-rv30"
    / "contracts"
    / "fmp-b1q-exogenous-docs-review-v1.schema.json"
)
_SCHEMA_VERSION = "fmp-b1q-exogenous-docs-review-v1.0"
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_SECRET_VALUE_PATTERN = re.compile(
    r"(?i)(?:api[_-]?key|authorization|password|secret)\s*(?:=|:)|bearer\s+[a-z0-9._-]+"
)
_PERSONAL_PATH_PATTERN = re.compile(r"(?i)(?:(?<![a-z])[a-z]:[\\/]|/users/|/home/)")
_EMAIL_PATTERN = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
_REQUIRED_SUPPORT_CLAIM_IDS = (
    "FMP_TREASURY_OBSERVATION_DATE_SEMANTICS",
    "FMP_TREASURY_HISTORICAL_AVAILABILITY_OR_REVISION_SEMANTICS",
    "FMP_DIVIDEND_DECLARATION_DATE_SEMANTICS",
    "FMP_DIVIDEND_HISTORICAL_AVAILABILITY_OR_REVISION_SEMANTICS",
)


def build_fmp_b1q_exogenous_docs_review_v1() -> dict[str, object]:
    """Build a deterministic, documentation-only review of FMP B1Q inputs.

    Returns
    -------
    dict[str, object]
        Schema-valid review with fixed ``UNRESOLVED`` B1Q provenance and the
        four remaining support-claim identifiers.

    Notes
    -----
    The record is target-blind and makes no provider request.  It states only
    that FMP documents the endpoint, the dividend declaration-date field, and
    nominal refresh categories.  It intentionally does not infer original
    observation/publication/customer-availability timestamps or revision
    history from those facts.
    """
    review: dict[str, object] = {
        "schema_version": _SCHEMA_VERSION,
        "status": "DOCUMENTED_ENDPOINTS_INSUFFICIENT_FOR_B1Q_PIT",
        "scope": "official_documentation_review_only_target_blind",
        "observed_on_utc": "2026-08-12",
        "treasury_endpoint_status": "DOCUMENTED_HISTORICAL_ENDPOINT",
        "treasury_cycle_time_status": "DOCUMENTED_TWO_HOURS",
        "dividend_endpoint_status": "DOCUMENTED_DECLARATION_DATE_FIELD",
        "dividend_cycle_time_status": "DOCUMENTED_ONE_TO_TWO_HOURS",
        "sources": {
            "treasury_rates": {
                "endpoint_url": "https://financialmodelingprep.com/stable/treasury-rates",
                "documentation_url": (
                    "https://site.financialmodelingprep.com/developer/docs/stable/treasury-rates"
                ),
                "cycle_times_url": (
                    "https://site.financialmodelingprep.com/developer/docs/cycle-times-stable"
                ),
                "endpoint_scope": "LATEST_AND_HISTORICAL_TREASURY_RATES",
                "cycle_time": "TWO_HOURS",
                "observation_date_semantics_documented": False,
                "customer_available_at_documented": False,
                "historical_revision_or_backfill_behavior_documented": False,
            },
            "dividends": {
                "endpoint_url": "https://financialmodelingprep.com/stable/dividends",
                "documentation_url": (
                    "https://site.financialmodelingprep.com/developer/docs/historical-stock-dividends-api/"
                ),
                "cycle_times_url": (
                    "https://site.financialmodelingprep.com/developer/docs/cycle-times-stable"
                ),
                "endpoint_scope": "SYMBOL_DIVIDEND_HISTORY_AND_SCHEDULE",
                "declaration_date_field_documented": True,
                "cycle_time": "ONE_TO_TWO_HOURS",
                "customer_available_at_documented": False,
                "historical_revision_or_backfill_behavior_documented": False,
            },
        },
        "b1q_exogenous_input_provenance_status": "UNRESOLVED",
        "unresolved_reason_codes": [
            "FMP_TREASURY_OBSERVATION_DATE_SEMANTICS_UNDOCUMENTED",
            "FMP_TREASURY_HISTORICAL_AVAILABILITY_OR_REVISION_UNDOCUMENTED",
            "FMP_DIVIDEND_CUSTOMER_AVAILABILITY_OR_REVISION_UNDOCUMENTED",
        ],
        "required_support_claim_ids": list(_REQUIRED_SUPPORT_CLAIM_IDS),
        "permitted_conclusion": (
            "Endpoint and refresh documentation supports neither pre-origin rate/dividend "
            "provenance nor a B1Q rebuild."
        ),
        "safe_to_build_b1q": False,
        "safe_to_reconcile_existing_results": "NO",
        "safe_to_open_or_evaluate_oos": "NO",
        "provider_market_data_requests_performed": False,
        "target_or_metric_payload_read": False,
        "model_fit_performed": False,
        "secret_values_emitted": False,
        "personal_paths_emitted": False,
    }
    review["semantic_self_hash"] = _canonical_sha256(review)
    validate_fmp_b1q_exogenous_docs_review_v1(review)
    return review


def validate_fmp_b1q_exogenous_docs_review_v1(review: Mapping[str, object]) -> None:
    """Validate the review's schema, hash, hygiene, and no-upgrade boundary.

    Parameters
    ----------
    review
        Candidate B1Q documentation-review artifact.

    Raises
    ------
    ValueError
        If the document violates the schema, its self-hash, sanitation rules,
        or any invariant that prevents a documentation-only review from being
        used as a B1Q provenance or research-gate upgrade.
    """
    _validate_self_hash(review)
    _validate_schema(review)
    _assert_sanitized(review)
    expected: dict[str, object] = {
        "schema_version": _SCHEMA_VERSION,
        "status": "DOCUMENTED_ENDPOINTS_INSUFFICIENT_FOR_B1Q_PIT",
        "scope": "official_documentation_review_only_target_blind",
        "observed_on_utc": "2026-08-12",
        "treasury_endpoint_status": "DOCUMENTED_HISTORICAL_ENDPOINT",
        "treasury_cycle_time_status": "DOCUMENTED_TWO_HOURS",
        "dividend_endpoint_status": "DOCUMENTED_DECLARATION_DATE_FIELD",
        "dividend_cycle_time_status": "DOCUMENTED_ONE_TO_TWO_HOURS",
        "b1q_exogenous_input_provenance_status": "UNRESOLVED",
        "required_support_claim_ids": list(_REQUIRED_SUPPORT_CLAIM_IDS),
        "permitted_conclusion": (
            "Endpoint and refresh documentation supports neither pre-origin rate/dividend "
            "provenance nor a B1Q rebuild."
        ),
        "safe_to_build_b1q": False,
        "safe_to_reconcile_existing_results": "NO",
        "safe_to_open_or_evaluate_oos": "NO",
        "provider_market_data_requests_performed": False,
        "target_or_metric_payload_read": False,
        "model_fit_performed": False,
        "secret_values_emitted": False,
        "personal_paths_emitted": False,
    }
    if any(review.get(key) != value for key, value in expected.items()):
        raise ValueError("FMP_B1Q_DOCS_REVIEW_POLICY_INVALID")


def write_fmp_b1q_exogenous_docs_review_v1(output_path: Path) -> Path:
    """Write a deterministic review or retain a byte-identical existing copy.

    Parameters
    ----------
    output_path
        Destination for the immutable, sanitized JSON artifact.

    Returns
    -------
    pathlib.Path
        ``output_path`` after an atomic new write or an identical replay.

    Raises
    ------
    ValueError
        If a divergent record already exists or an I/O failure occurs.
    """
    payload = _render_json(build_fmp_b1q_exogenous_docs_review_v1())
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        if output_path.read_bytes() != payload:
            raise ValueError("FMP_B1Q_DOCS_REVIEW_OUTPUT_CONFLICT")
        return output_path
    temporary_path = output_path.with_name(f".{output_path.name}.{uuid.uuid4().hex}.part")
    try:
        temporary_path.write_bytes(payload)
        try:
            os.link(temporary_path, output_path)
        except FileExistsError:
            if output_path.read_bytes() != payload:
                raise ValueError("FMP_B1Q_DOCS_REVIEW_OUTPUT_CONFLICT") from None
    except OSError as exc:
        raise ValueError("FMP_B1Q_DOCS_REVIEW_OUTPUT_UNWRITABLE") from exc
    finally:
        temporary_path.unlink(missing_ok=True)
    return output_path


def _validate_schema(review: Mapping[str, object]) -> None:
    """Validate one review against the local Draft 2020-12 contract."""
    schema = _read_json_object(_SCHEMA_PATH, "FMP_B1Q_DOCS_REVIEW_SCHEMA_INVALID")
    try:
        _DRAFT202012_VALIDATOR.check_schema(schema)
        errors = list(_DRAFT202012_VALIDATOR(schema).iter_errors(review))
    except (TypeError, ValueError) as exc:
        raise ValueError("FMP_B1Q_DOCS_REVIEW_SCHEMA_INVALID") from exc
    if errors:
        raise ValueError("FMP_B1Q_DOCS_REVIEW_SCHEMA_INVALID")


def _validate_self_hash(review: Mapping[str, object]) -> None:
    """Reject a changed review before evaluating policy fields."""
    value = review.get("semantic_self_hash")
    if not isinstance(value, str) or not value.startswith("sha256:"):
        raise ValueError("FMP_B1Q_DOCS_REVIEW_SELF_HASH_INVALID")
    if _SHA256_PATTERN.fullmatch(value[7:]) is None:
        raise ValueError("FMP_B1Q_DOCS_REVIEW_SELF_HASH_INVALID")
    unsigned = dict(review)
    unsigned.pop("semantic_self_hash", None)
    if _canonical_sha256(unsigned) != value:
        raise ValueError("FMP_B1Q_DOCS_REVIEW_SELF_HASH_INVALID")


def _read_json_object(path: Path, error_code: str) -> dict[str, object]:
    """Read one local JSON object without exposing its filesystem location."""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(error_code) from exc
    if not isinstance(value, dict):
        raise ValueError(error_code)
    return cast(dict[str, object], value)


def _canonical_sha256(document: Mapping[str, object]) -> str:
    """Return the repository canonical semantic SHA-256 for one mapping."""
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
        raise ValueError("FMP_B1Q_DOCS_REVIEW_UNSAFE_CONTENT")
