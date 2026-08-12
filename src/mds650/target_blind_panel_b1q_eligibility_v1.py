"""Fail-closed admissibility gate for a target-blind panel with unresolved B1Q.

The gate reads only the v2.4 panel manifest and the current target-free source
coverage ledger.  It never reads predictor rows, targets, forecasts, metrics,
models, OOS artefacts, or provider payloads.  A materialized target-blind panel
is therefore not accidentally treated as evaluable when its B1Q provenance is
blocked.
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
    """Minimal typed boundary over the runtime JSON Schema validator."""

    def iter_errors(self, instance: object) -> Iterable[object]:
        """Yield schema errors for one JSON object."""


class _Draft202012ValidatorFactory(Protocol):
    """Construction and schema-validation boundary."""

    def __call__(self, schema: Mapping[str, object]) -> _JsonSchemaValidator:
        """Construct a validator for one schema."""

    def check_schema(self, schema: Mapping[str, object]) -> None:
        """Raise when the schema itself is invalid."""


def _load_validator() -> _Draft202012ValidatorFactory:
    """Load jsonschema behind a narrow typed runtime boundary."""
    module = import_module("jsonschema")
    candidate = cast(object, getattr(module, "Draft202012Validator", None))
    if not callable(candidate) or not callable(getattr(candidate, "check_schema", None)):
        raise RuntimeError("B1Q_PANEL_ELIGIBILITY_JSONSCHEMA_UNAVAILABLE")
    return cast(_Draft202012ValidatorFactory, candidate)


_VALIDATOR = _load_validator()
_ROOT = Path(__file__).resolve().parents[2]
_SCHEMA_PATH = (
    _ROOT
    / "specs"
    / "001-pit-options-rv30"
    / "contracts"
    / "target-blind-panel-b1q-eligibility-v1.schema.json"
)
_SCHEMA_VERSION = "target-blind-panel-b1q-eligibility-v1.0"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MANIFEST_FILE_SHA256 = "35d19dd7b93619464d721532c6ac9b1d31fce2d90937912b401cf666f1ff0219"
_SOURCE_COVERAGE_FILE_SHA256 = "c9719cab83000e52d6dae2778fd1e65395ede0270fce1f8e7ef75140cdbfdc2b"
_MANIFEST_SELF_HASH = "e6f454799ad66bd9dcb00c0fcafaa8278ec24ffd302aeb09ca315f548858a83b"
_SOURCE_COVERAGE_SELF_HASH = "088cf2259a2d6acdb58c9651d0a43f39938e5e639069bb92960baa3e869c4d1d"
_SECRET_VALUE = re.compile(
    r"(?i)(?:api[_-]?key|authorization|password|secret)\s*(?:=|:)|bearer\s+[a-z0-9._-]+"
)
_EMAIL = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
_PERSONAL_PATH = re.compile(r"(?i)(?:(?<![a-z])[a-z]:[\\/]|/users/|/home/)")


def build_target_blind_panel_b1q_eligibility_v1(
    *, panel_manifest_path: Path, source_coverage_path: Path
) -> dict[str, object]:
    """Build the current B1Q panel-admissibility decision.

    Parameters
    ----------
    panel_manifest_path
        Existing v2.4 target-blind manifest.  Only its JSON bytes are read.
    source_coverage_path
        Current source-coverage ledger containing B1Q provenance status.

    Returns
    -------
    dict[str, object]
        A self-hashed decision.  The present registered inputs produce
        ``PANEL_NOT_ELIGIBLE_FOR_EVALUATION``.

    Raises
    ------
    ValueError
        If either input differs from its registered bytes, violates its
        fail-closed contract, or the decision cannot satisfy its schema.
    """
    manifest, manifest_file_sha256 = _read_registered_json(
        "MANIFEST", panel_manifest_path, _MANIFEST_FILE_SHA256
    )
    coverage, coverage_file_sha256 = _read_registered_json(
        "SOURCE_COVERAGE", source_coverage_path, _SOURCE_COVERAGE_FILE_SHA256
    )
    _validate_manifest(manifest)
    _validate_source_coverage(coverage)
    b1q = cast(Mapping[str, object], cast(Mapping[str, object], coverage["components"])["B1Q"])
    decision: dict[str, object] = {
        "schema_version": _SCHEMA_VERSION,
        "status": "PANEL_NOT_ELIGIBLE_FOR_EVALUATION",
        "scope": "target_blind_panel_admissibility_only_no_targets_or_metrics",
        "panel_manifest_file_sha256": manifest_file_sha256,
        "panel_manifest_sha256": _MANIFEST_SELF_HASH,
        "source_coverage_file_sha256": coverage_file_sha256,
        "source_coverage_ledger_sha256": _SOURCE_COVERAGE_SELF_HASH,
        "b1q_source_coverage_status": cast(str, b1q["status"]),
        "b1q_unresolved_origin_count": cast(int, b1q["unresolved_origin_count"]),
        "reason_codes": ["B1Q_EXOGENOUS_INPUT_PROVENANCE_UNRESOLVED"],
        "safe_to_evaluate": False,
        "safe_to_reconcile_existing_results": "NO",
        "safe_to_open_or_evaluate_oos": "NO",
        "target_or_metric_payload_read": False,
        "model_fit_performed": False,
        "provider_market_data_requests_performed": False,
        "secret_values_emitted": False,
        "personal_paths_emitted": False,
    }
    decision["semantic_self_hash"] = _canonical_sha256(decision)
    validate_target_blind_panel_b1q_eligibility_v1(decision)
    return decision


def validate_target_blind_panel_b1q_eligibility_v1(
    decision: Mapping[str, object]
) -> None:
    """Validate schema, identity and the non-upgradable B1Q policy state.

    Parameters
    ----------
    decision
        Candidate decision produced by the builder.

    Raises
    ------
    ValueError
        If the decision is malformed, rehashed into a positive state, or
        contains unsafe content.
    """
    _validate_self_hash(decision)
    _assert_sanitized(decision)
    expected = {
        "status": "PANEL_NOT_ELIGIBLE_FOR_EVALUATION",
        "scope": "target_blind_panel_admissibility_only_no_targets_or_metrics",
        "panel_manifest_file_sha256": _MANIFEST_FILE_SHA256,
        "panel_manifest_sha256": _MANIFEST_SELF_HASH,
        "source_coverage_file_sha256": _SOURCE_COVERAGE_FILE_SHA256,
        "source_coverage_ledger_sha256": _SOURCE_COVERAGE_SELF_HASH,
        "b1q_source_coverage_status": "BLOCKED",
        "b1q_unresolved_origin_count": 34080,
        "reason_codes": ["B1Q_EXOGENOUS_INPUT_PROVENANCE_UNRESOLVED"],
        "safe_to_evaluate": False,
        "safe_to_reconcile_existing_results": "NO",
        "safe_to_open_or_evaluate_oos": "NO",
        "target_or_metric_payload_read": False,
        "model_fit_performed": False,
        "provider_market_data_requests_performed": False,
        "secret_values_emitted": False,
        "personal_paths_emitted": False,
    }
    if any(decision.get(key) != value for key, value in expected.items()):
        raise ValueError("B1Q_PANEL_ELIGIBILITY_POLICY_INVALID")
    _validate_schema(decision)


def write_target_blind_panel_b1q_eligibility_v1(
    *,
    panel_manifest_path: Path,
    source_coverage_path: Path,
    output_path: Path,
) -> Path:
    """Write an immutable decision or retain a byte-identical replay.

    Parameters
    ----------
    panel_manifest_path, source_coverage_path
        Registered target-free input artifacts.
    output_path
        Repository artifact destination.

    Returns
    -------
    pathlib.Path
        The output path after an atomic write or identical replay.

    Raises
    ------
    ValueError
        If the destination conflicts or cannot be written safely.
    """
    payload = _render_json(
        build_target_blind_panel_b1q_eligibility_v1(
            panel_manifest_path=panel_manifest_path,
            source_coverage_path=source_coverage_path,
        )
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        if output_path.read_bytes() != payload:
            raise ValueError("B1Q_PANEL_ELIGIBILITY_OUTPUT_CONFLICT")
        return output_path
    temporary = output_path.with_name(f".{output_path.name}.{uuid.uuid4().hex}.part")
    try:
        temporary.write_bytes(payload)
        try:
            os.link(temporary, output_path)
        except FileExistsError:
            if output_path.read_bytes() != payload:
                raise ValueError("B1Q_PANEL_ELIGIBILITY_OUTPUT_CONFLICT") from None
    except OSError as exc:
        raise ValueError("B1Q_PANEL_ELIGIBILITY_OUTPUT_UNWRITABLE") from exc
    finally:
        temporary.unlink(missing_ok=True)
    return output_path


def _read_registered_json(
    name: str, path: Path, expected_file_sha256: str
) -> tuple[dict[str, object], str]:
    """Read one exact JSON artifact without exposing its local path."""
    try:
        payload = path.read_bytes()
        document = json.loads(payload.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"B1Q_PANEL_ELIGIBILITY_{name}_INVALID") from exc
    if not isinstance(document, dict):
        raise ValueError(f"B1Q_PANEL_ELIGIBILITY_{name}_INVALID")
    actual = hashlib.sha256(payload).hexdigest()
    if actual != expected_file_sha256:
        raise ValueError(f"B1Q_PANEL_ELIGIBILITY_{name}_INVALID")
    return cast(dict[str, object], document), actual


def _validate_manifest(document: Mapping[str, object]) -> None:
    """Require the existing panel to remain target-blind and unevaluated."""
    unsigned = dict(document)
    recorded = unsigned.pop("manifest_sha256", None)
    if recorded != _MANIFEST_SELF_HASH or _canonical_sha256_hex(unsigned) != recorded:
        raise ValueError("B1Q_PANEL_ELIGIBILITY_MANIFEST_INVALID")
    if any(
        document.get(key) != value
        for key, value in {
            "status": "PASS_TARGET_BLIND_INPUTS_RECONCILIATION_REMAINS_BLOCKED",
            "safe_to_reconcile_existing_results": "NO",
            "SAFE_TO_OPEN_OR_EVALUATE_OOS": "NO",
            "no_target_or_metric_payload_read": True,
            "model_fit_performed": False,
        }.items()
    ):
        raise ValueError("B1Q_PANEL_ELIGIBILITY_MANIFEST_INVALID")


def _validate_source_coverage(document: Mapping[str, object]) -> None:
    """Require unresolved B1Q provenance for every registered origin."""
    unsigned = dict(document)
    recorded = unsigned.pop("ledger_sha256", None)
    if recorded != _SOURCE_COVERAGE_SELF_HASH or _canonical_sha256_hex(unsigned) != recorded:
        raise ValueError("B1Q_PANEL_ELIGIBILITY_SOURCE_COVERAGE_INVALID")
    components = document.get("components")
    if not isinstance(components, Mapping):
        raise ValueError("B1Q_PANEL_ELIGIBILITY_SOURCE_COVERAGE_INVALID")
    b1q = components.get("B1Q")
    if not isinstance(b1q, Mapping) or any(
        b1q.get(key) != value
        for key, value in {
            "status": "BLOCKED",
            "unresolved_origin_count": 34080,
        }.items()
    ):
        raise ValueError("B1Q_PANEL_ELIGIBILITY_SOURCE_COVERAGE_INVALID")
    if document.get("target_binding_permitted") is not False:
        raise ValueError("B1Q_PANEL_ELIGIBILITY_SOURCE_COVERAGE_INVALID")


def _validate_schema(decision: Mapping[str, object]) -> None:
    """Validate one decision against the local Draft 2020-12 schema."""
    try:
        schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
        if not isinstance(schema, dict):
            raise ValueError("schema object required")
        _VALIDATOR.check_schema(schema)
        errors = list(_VALIDATOR(schema).iter_errors(decision))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise ValueError("B1Q_PANEL_ELIGIBILITY_SCHEMA_INVALID") from exc
    if errors:
        raise ValueError("B1Q_PANEL_ELIGIBILITY_SCHEMA_INVALID")


def _validate_self_hash(decision: Mapping[str, object]) -> None:
    """Reject a changed or malformed decision hash."""
    value = decision.get("semantic_self_hash")
    if (
        not isinstance(value, str)
        or not value.startswith("sha256:")
        or not _SHA256.fullmatch(value[7:])
    ):
        raise ValueError("B1Q_PANEL_ELIGIBILITY_SELF_HASH_INVALID")
    unsigned = dict(decision)
    unsigned.pop("semantic_self_hash", None)
    if _canonical_sha256(unsigned) != value:
        raise ValueError("B1Q_PANEL_ELIGIBILITY_SELF_HASH_INVALID")


def _canonical_sha256(document: Mapping[str, object]) -> str:
    """Return deterministic semantic SHA-256 for one JSON mapping."""
    payload = json.dumps(
        document,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _canonical_sha256_hex(document: Mapping[str, object]) -> str:
    """Return the legacy plain-hex hash used by registered source ledgers."""
    return _canonical_sha256(document)[7:]


def _render_json(document: Mapping[str, object]) -> bytes:
    """Render stable indented JSON with a fixed trailing newline."""
    return (json.dumps(document, ensure_ascii=True, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )


def _assert_sanitized(document: Mapping[str, object]) -> None:
    """Reject secrets, personal paths and email addresses from the decision."""
    rendered = json.dumps(document, allow_nan=False, ensure_ascii=True, sort_keys=True)
    if _SECRET_VALUE.search(rendered) or _EMAIL.search(rendered) or _PERSONAL_PATH.search(rendered):
        raise ValueError("B1Q_PANEL_ELIGIBILITY_UNSAFE_CONTENT")
