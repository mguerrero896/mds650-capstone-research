"""Seal the target-blind B0/B1a/B2 primary-comparison contract.

This module consumes a metadata-only v4 method freeze and produces a separate,
self-hashing comparison record.  It never opens predictor panels, RV30 values,
outcomes, metrics, fitted models, OOS artefacts, or provider credentials.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from copy import deepcopy
from importlib import import_module
from pathlib import Path
from typing import Protocol, cast


class _JsonSchemaValidator(Protocol):
    """Minimal typed surface required from the untyped ``jsonschema`` package."""

    def iter_errors(self, instance: object) -> Iterable[object]:
        """Yield validation errors for one JSON-compatible object."""


class _Draft202012ValidatorFactory(Protocol):
    """Typed boundary for Draft 2020-12 validation used by this contract."""

    def __call__(self, schema: Mapping[str, object]) -> _JsonSchemaValidator:
        """Create a validator for ``schema``."""

    def check_schema(self, schema: Mapping[str, object]) -> None:
        """Raise when ``schema`` is not a valid JSON Schema."""


def _load_draft202012_validator() -> _Draft202012ValidatorFactory:
    """Load ``jsonschema`` through an explicit narrow runtime type boundary."""
    module = import_module("jsonschema")
    candidate = cast(object, getattr(module, "Draft202012Validator", None))
    if not callable(candidate) or not callable(getattr(candidate, "check_schema", None)):
        raise RuntimeError("COMPARISON_CONTRACT_V1_JSONSCHEMA_VALIDATOR_UNAVAILABLE")
    return cast(_Draft202012ValidatorFactory, candidate)


_DRAFT202012_VALIDATOR = _load_draft202012_validator()
_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_SCHEMA_PATH = (
    _REPOSITORY_ROOT
    / "specs"
    / "001-pit-options-rv30"
    / "contracts"
    / "target-blind-comparison-contract-v1.schema.json"
)
_OUTPUT_FILENAME = "target_blind_comparison_contract_v1.json"
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")
_FROZEN_B2_FEATURES = (
    "b2v2_z_log_trade_count",
    "b2v2_z_unique_contract_share",
    "b2v2_z_log_mean_trade_premium",
    "b2v2_z_log_max_trade_premium",
    "b2v2_deviation_call_put_premium_imbalance",
    "b2v2_deviation_execution_side_premium_imbalance",
    "b2v2_z_repeated_contract_premium_share",
    "b2v2_z_strike_concentration",
    "b2v2_z_expiry_concentration",
)
_EXPECTED_PARENT_FIELDS: dict[str, object] = {
    "schema_version": "target-blind-confirmation-preregistration-v4.0",
    "status": "SEALED_METHOD_FROZEN_TARGET_BLIND_READY_FUTURE_GATES_CLOSED",
    "method_freeze_status": "FROZEN_TARGET_BLIND_ONLY",
    "target_blind_ready": "YES",
    "no_target_or_metric_payload_read": True,
    "model_fit_performed": False,
    "claim_boundary": "NO_PREDICTIVE_OR_COMPARATIVE_CLAIM",
    "sealed_result_reconciliation": "BLOCKED",
    "safe_to_reconcile_existing_results": "NO",
    "safe_to_open_or_evaluate_oos": "NO",
    "safe_to_acquire_new_historical_sample": "NO",
    "safe_to_start_prospective_capture": "NO",
    "target_definition": "RV30",
}
_EXPECTED_METRICS: dict[str, object] = {"primary": "QLIKE", "secondary": ["MAE", "RMSE"]}
_EXPECTED_INFERENCE: dict[str, object] = {
    "resampling": "PAIRED_DAY_CLUSTER_BOOTSTRAP",
    "cluster_unit": "TRADING_DAY",
    "multiplicity": "HOLM",
    "selection_by_sign": "PROHIBITED",
}


def seal_target_blind_comparison_contract(
    *, preregistration_v4_path: Path, output_dir: Path, source_commit: str
) -> Path:
    """Seal the pre-approved B1a-versus-B0 and B2-versus-B1a comparisons.

    Parameters
    ----------
    preregistration_v4_path
        Path to the metadata-only v4 method freeze.  Its self-hash, closed
        gates, target, metric, inference plan, and information sets are
        validated before any output is constructed.
    output_dir
        Directory for the immutable JSON record.  An existing non-identical
        output is rejected rather than overwritten.
    source_commit
        Forty-character lowercase Git commit identity for this sealing run.

    Returns
    -------
    pathlib.Path
        The deterministic, JSON-Schema-validated comparison contract.

    Raises
    ------
    ValueError
        If the parent is malformed, opens a closed gate, changes the fixed
        method, does not produce strict nested information sets, fails a JSON
        Schema validation, or conflicts with an existing output.

    Notes
    -----
    ``QLIKE`` appears only as a pre-specified estimand name.  The function
    does not read or compute a QLIKE value, RV30 target, prediction, model, or
    out-of-sample result.
    """
    _require_commit(source_commit, "COMPARISON_CONTRACT_V1_SOURCE_COMMIT_INVALID")
    parent = _read_json_object(preregistration_v4_path, "COMPARISON_CONTRACT_V1_PARENT_UNREADABLE")
    information_sets = _validate_parent_preregistration(parent)
    parent_file_sha256 = _file_sha256(
        preregistration_v4_path, "COMPARISON_CONTRACT_V1_PARENT_UNREADABLE"
    )
    contract = _build_contract(
        parent=parent,
        information_sets=information_sets,
        parent_file_sha256=parent_file_sha256,
        source_commit=source_commit,
    )
    _validate_output_schema(contract)
    payload = _render_json(contract)
    output_path = output_dir / _OUTPUT_FILENAME
    _assert_write_compatible(output_path, payload)
    output_dir.mkdir(parents=True, exist_ok=True)
    if not output_path.exists():
        output_path.write_bytes(payload)
    return output_path


def _validate_parent_preregistration(parent: Mapping[str, object]) -> dict[str, list[str]]:
    """Require a self-hashed v4 parent and strict B0/B1a/B2 information nesting."""
    if any(parent.get(key) != value for key, value in _EXPECTED_PARENT_FIELDS.items()):
        raise ValueError("COMPARISON_CONTRACT_V1_PARENT_GATE_INVALID")
    _require_commit(
        _require_string(
            parent.get("source_commit"), "COMPARISON_CONTRACT_V1_PARENT_COMMIT_INVALID"
        ),
        "COMPARISON_CONTRACT_V1_PARENT_COMMIT_INVALID",
    )
    _validate_self_hash(
        parent,
        "preregistration_sha256",
        "COMPARISON_CONTRACT_V1_PARENT_HASH_INVALID",
    )

    metrics = _require_mapping(
        parent.get("metrics"), "COMPARISON_CONTRACT_V1_PARENT_METHOD_INVALID"
    )
    inference = _require_mapping(
        parent.get("inference"), "COMPARISON_CONTRACT_V1_PARENT_METHOD_INVALID"
    )
    if dict(metrics) != _EXPECTED_METRICS or dict(inference) != _EXPECTED_INFERENCE:
        raise ValueError("COMPARISON_CONTRACT_V1_PARENT_METHOD_INVALID")

    raw_information_sets = _require_mapping(
        parent.get("information_sets"), "COMPARISON_CONTRACT_V1_INFORMATION_SETS_INVALID"
    )
    expected_keys = {"B0", "B1a_addition", "B1b_addition", "B1c_addition", "B2_addition"}
    if set(raw_information_sets) != expected_keys:
        raise ValueError("COMPARISON_CONTRACT_V1_INFORMATION_SETS_INVALID")
    information_sets = {
        key: _require_distinct_string_list(
            raw_information_sets.get(key), "COMPARISON_CONTRACT_V1_INFORMATION_SETS_INVALID"
        )
        for key in expected_keys
    }
    if tuple(information_sets["B2_addition"]) != _FROZEN_B2_FEATURES:
        raise ValueError("COMPARISON_CONTRACT_V1_B2_FEATURES_INVALID")
    b0 = set(information_sets["B0"])
    b1a_addition = set(information_sets["B1a_addition"])
    b2_addition = set(information_sets["B2_addition"])
    if b0 & b1a_addition:
        raise ValueError("COMPARISON_CONTRACT_V1_B1A_NOT_STRICT_INCREMENT")
    if (b0 | b1a_addition) & b2_addition:
        raise ValueError("COMPARISON_CONTRACT_V1_B2_NOT_STRICT_INCREMENT")
    return information_sets


def _build_contract(
    *,
    parent: Mapping[str, object],
    information_sets: Mapping[str, list[str]],
    parent_file_sha256: str,
    source_commit: str,
) -> dict[str, object]:
    """Construct the exact nested information sets and pre-approved estimands."""
    b0 = list(information_sets["B0"])
    b1a = [*b0, *information_sets["B1a_addition"]]
    b2 = [*b1a, *information_sets["B2_addition"]]
    document: dict[str, object] = {
        "schema_version": "target-blind-comparison-contract-v1.0",
        "status": "SEALED_PRIMARY_COMPARISONS_TARGET_BLIND_NO_EVALUATION",
        "scope": "offline_metadata_only_primary_comparison_freeze",
        "purpose": "freeze_nested_b0_b1a_b2_comparisons_before_rv30_or_qlike_access",
        "target_definition": "RV30",
        "no_target_or_metric_payload_read": True,
        "model_fit_performed": False,
        "metric_evaluation_performed": False,
        "safe_to_reconcile_existing_results": "NO",
        "safe_to_open_or_evaluate_oos": "NO",
        "safe_to_acquire_new_historical_sample": "NO",
        "safe_to_start_prospective_capture": "NO",
        "parent_preregistration": {
            "logical_path": (
                "artifacts/target_blind_v24_sourcebound_20260812/"
                "next_confirmation_preregistration_v4.json"
            ),
            "file_sha256": parent_file_sha256,
            "preregistration_sha256": parent["preregistration_sha256"],
            "schema_version": parent["schema_version"],
            "source_commit": parent["source_commit"],
        },
        "model_information_sets": {"B0": b0, "B1a": b1a, "B2": b2},
        "primary_b1_level": "B1a",
        "primary_benchmark_substitution": "PROHIBITED",
        "b1b_b1c_role": "PRE_SPECIFIED_ROBUSTNESS_ONLY",
        "primary_comparisons": [
            {
                "comparison_id": "B1A_VS_B0",
                "benchmark": "B0",
                "challenger": "B1a",
                "estimand": "MEAN_DAILY_QLIKE_B0_MINUS_B1A",
                "positive_direction": "FAVORS_B1A",
            },
            {
                "comparison_id": "B2_VS_B1A",
                "benchmark": "B1a",
                "challenger": "B2",
                "estimand": "MEAN_DAILY_QLIKE_B1A_MINUS_B2",
                "positive_direction": "FAVORS_B2",
            },
        ],
        "inference": deepcopy(_EXPECTED_INFERENCE),
        "selection_controls": {
            "feature_selection_by_rv30_or_qlike": "PROHIBITED",
            "model_selection_by_sign": "PROHIBITED",
            "asset_selection_by_predictive_result": "PROHIBITED",
            "primary_comparison_switching": "PROHIBITED",
        },
        "forbidden_runtime_actions": [
            "RV30_ACCESS",
            "QLIKE_EVALUATION",
            "MODEL_FIT",
            "OOS_ACCESS",
            "SEALED_RESULT_RECONCILIATION",
            "NEW_HISTORICAL_ACQUISITION",
            "PROSPECTIVE_CAPTURE_START",
        ],
        "artifact_schema": {
            "logical_path": (
                "specs/001-pit-options-rv30/contracts/"
                "target-blind-comparison-contract-v1.schema.json"
            ),
            "file_sha256": _file_sha256(_SCHEMA_PATH, "COMPARISON_CONTRACT_V1_SCHEMA_UNREADABLE"),
        },
        "builder_source_sha256": _file_sha256(
            Path(__file__), "COMPARISON_CONTRACT_V1_BUILDER_UNREADABLE"
        ),
        "source_commit": source_commit,
    }
    document["comparison_contract_sha256"] = _canonical_sha256(document)
    return document


def _validate_output_schema(document: Mapping[str, object]) -> None:
    """Validate the generated record against the versioned local JSON Schema."""
    schema = _read_json_object(_SCHEMA_PATH, "COMPARISON_CONTRACT_V1_SCHEMA_UNREADABLE")
    try:
        _DRAFT202012_VALIDATOR.check_schema(schema)
        errors = list(_DRAFT202012_VALIDATOR(schema).iter_errors(document))
    except (ValueError, TypeError) as exc:
        raise ValueError("COMPARISON_CONTRACT_V1_SCHEMA_INVALID") from exc
    if errors:
        raise ValueError("COMPARISON_CONTRACT_V1_OUTPUT_SCHEMA_INVALID")


def _read_json_object(path: Path, error_code: str) -> dict[str, object]:
    """Read one JSON object without reflecting its content in diagnostics."""
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(error_code) from exc
    if not isinstance(parsed, dict):
        raise ValueError(error_code)
    return cast(dict[str, object], parsed)


def _validate_self_hash(document: Mapping[str, object], field: str, error_code: str) -> None:
    """Require ``field`` to equal the canonical hash of all other fields."""
    recorded = _require_string(document.get(field), error_code)
    _require_sha256(recorded, error_code)
    unsigned = {key: value for key, value in document.items() if key != field}
    if _canonical_sha256(unsigned) != recorded:
        raise ValueError(error_code)


def _require_mapping(value: object, error_code: str) -> Mapping[str, object]:
    """Return a string-keyed mapping or raise the supplied fail-closed code."""
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise ValueError(error_code)
    return cast(Mapping[str, object], value)


def _require_distinct_string_list(value: object, error_code: str) -> list[str]:
    """Return a non-empty, duplicate-free list of non-blank feature names."""
    if (
        not isinstance(value, list)
        or not value
        or any(not isinstance(item, str) or not item for item in value)
        or len(set(value)) != len(value)
    ):
        raise ValueError(error_code)
    return cast(list[str], value)


def _require_string(value: object, error_code: str) -> str:
    """Return a non-empty string or raise ``error_code``."""
    if not isinstance(value, str) or not value:
        raise ValueError(error_code)
    return value


def _require_sha256(value: str, error_code: str) -> None:
    """Validate one lowercase SHA-256 identifier."""
    if _SHA256_PATTERN.fullmatch(value) is None:
        raise ValueError(error_code)


def _require_commit(value: str, error_code: str) -> None:
    """Validate one lowercase forty-character Git commit identifier."""
    if _COMMIT_PATTERN.fullmatch(value) is None:
        raise ValueError(error_code)


def _file_sha256(path: Path, error_code: str) -> str:
    """Return the byte SHA-256 of a readable regular file."""
    try:
        if not path.is_file():
            raise OSError("not a regular file")
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise ValueError(error_code) from exc


def _canonical_sha256(document: Mapping[str, object]) -> str:
    """Return the repository canonical SHA-256 for one JSON mapping."""
    rendered = json.dumps(
        document,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def _render_json(document: Mapping[str, object], *, trailing_newline: bool = True) -> bytes:
    """Render deterministic UTF-8 JSON, optionally ending in one newline."""
    rendered = json.dumps(
        document,
        allow_nan=False,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    suffix = "\n" if trailing_newline else ""
    return (rendered + suffix).encode("utf-8")


def _assert_write_compatible(path: Path, payload: bytes) -> None:
    """Reject replacement of an existing non-identical immutable contract."""
    if path.exists() and (not path.is_file() or path.read_bytes() != payload):
        raise ValueError("COMPARISON_CONTRACT_V1_OUTPUT_CONFLICT")
