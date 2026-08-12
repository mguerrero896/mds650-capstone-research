"""Seal the v4 target-blind confirmation protocol and readiness package.

This is an offline metadata-only sealer.  It consumes three source-bound JSON
contracts, validates their schemas and semantic hashes, then emits two
write-if-identical records.  It does not open predictor matrices, target
values, result artefacts, provider services, or model runtimes.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import re
from collections.abc import Iterable, Mapping
from copy import deepcopy
from pathlib import Path
from typing import Protocol, cast

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_CONTRACTS_ROOT = _REPOSITORY_ROOT / "specs" / "001-pit-options-rv30" / "contracts"
_V24_INPUT_SCHEMA = _CONTRACTS_ROOT / "target-blind-common-predictor-manifest-v24.schema.json"
_POLICY_INPUT_SCHEMA = _CONTRACTS_ROOT / "provider-timing-evidence-policy-gate-v1.schema.json"
_V3_INPUT_SCHEMA = _CONTRACTS_ROOT / "target-blind-confirmation-preregistration-v3.schema.json"
_V4_OUTPUT_SCHEMA = _CONTRACTS_ROOT / "target-blind-confirmation-preregistration-v4.schema.json"
_READINESS_OUTPUT_SCHEMA = _CONTRACTS_ROOT / "confirmation-readiness-v3.schema.json"
_DEFAULT_V24_MANIFEST = (
    _REPOSITORY_ROOT
    / "artifacts"
    / "target_blind_v24_sourcebound_20260812"
    / "target_blind_common_predictor_manifest_v24.json"
)
_DEFAULT_POLICY_GATE = (
    _REPOSITORY_ROOT
    / "artifacts"
    / "provider_timing_v22"
    / "provider_timing_evidence_policy_gate_v1_20260812.json"
)
_DEFAULT_V3_PREREGISTRATION = (
    _REPOSITORY_ROOT
    / "artifacts"
    / "target_blind_v23_sourcebound_20260812"
    / "next_confirmation_preregistration_v3.json"
)
_DEFAULT_OUTPUT_DIRECTORY = _REPOSITORY_ROOT / "artifacts" / "target_blind_v24_sourcebound_20260812"
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
_COMMIT_PATTERN = re.compile(r"[0-9a-f]{40}")
_FROZEN_B2_FEATURES = [
    "b2v2_z_log_trade_count",
    "b2v2_z_unique_contract_share",
    "b2v2_z_log_mean_trade_premium",
    "b2v2_z_log_max_trade_premium",
    "b2v2_deviation_call_put_premium_imbalance",
    "b2v2_deviation_execution_side_premium_imbalance",
    "b2v2_z_repeated_contract_premium_share",
    "b2v2_z_strike_concentration",
    "b2v2_z_expiry_concentration",
]
_FORBIDDEN_RUNTIME_ACTIONS = [
    "OOS_ACCESS",
    "SEALED_RESULT_RECONCILIATION",
    "NEW_HISTORICAL_ACQUISITION",
    "PROSPECTIVE_CAPTURE_START",
    "MODEL_FIT",
    "METRIC_EVALUATION",
    "PROVIDER_NETWORK_CALL",
]
_PREFLIGHT_NOT_AUTHORIZATION = [
    "OOS_ACCESS",
    "SEALED_RESULT_RECONCILIATION",
    "MODEL_FIT",
    "METRIC_EVALUATION",
]


class _JsonSchemaValidator(Protocol):
    """Typed surface consumed from the untyped jsonschema package runtime."""

    def iter_errors(self, instance: object) -> Iterable[object]:
        """Yield schema violations for one JSON-compatible instance."""


class _Draft202012ValidatorFactory(Protocol):
    """Typed boundary for the Draft 2020-12 operations used by this sealer."""

    def __call__(self, schema: Mapping[str, object]) -> _JsonSchemaValidator:
        """Construct one validator from a JSON Schema mapping."""

    def check_schema(self, schema: Mapping[str, object]) -> None:
        """Raise if a supplied JSON Schema is invalid."""


def _load_draft202012_validator() -> _Draft202012ValidatorFactory:
    """Load jsonschema once through a small, documented typed boundary."""
    try:
        module = importlib.import_module("jsonschema")
        candidate = module.Draft202012Validator
    except (ImportError, AttributeError) as exc:
        raise RuntimeError("CONFIRMATION_V4_JSONSCHEMA_UNAVAILABLE") from exc
    if not callable(candidate) or not callable(getattr(candidate, "check_schema", None)):
        raise RuntimeError("CONFIRMATION_V4_JSONSCHEMA_INTERFACE_INVALID")
    return cast(_Draft202012ValidatorFactory, candidate)


_DRAFT202012_VALIDATOR = _load_draft202012_validator()


def _read_json_mapping(path: Path, error_prefix: str) -> dict[str, object]:
    """Read one JSON object and reject non-object or malformed content."""
    try:
        decoded: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{error_prefix}_UNREADABLE") from exc
    if not isinstance(decoded, dict):
        raise ValueError(f"{error_prefix}_NOT_OBJECT")
    document: dict[str, object] = {}
    for key, value in decoded.items():
        if not isinstance(key, str):
            raise ValueError(f"{error_prefix}_NON_STRING_KEY")
        document[key] = value
    return document


def _canonical_sha256(document: Mapping[str, object]) -> str:
    """Return the repository's semantic JSON hash for a mapping without its self-hash."""
    rendered = json.dumps(
        dict(document),
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def _file_sha256(path: Path, error_prefix: str) -> str:
    """Return a byte SHA-256 without interpreting the source payload."""
    if not path.is_file():
        raise ValueError(f"{error_prefix}_MISSING")
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise ValueError(f"{error_prefix}_UNREADABLE") from exc
    return digest.hexdigest()


def _render_json(document: Mapping[str, object]) -> bytes:
    """Render canonical, human-auditable artifact bytes deterministically."""
    return (json.dumps(dict(document), allow_nan=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )


def _require_sha256(value: object, error_code: str) -> str:
    if not isinstance(value, str) or _SHA256_PATTERN.fullmatch(value) is None:
        raise ValueError(error_code)
    return value


def _require_commit(value: object, error_code: str) -> str:
    if not isinstance(value, str) or _COMMIT_PATTERN.fullmatch(value) is None:
        raise ValueError(error_code)
    return value


def _require_mapping(value: object, error_code: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise ValueError(error_code)
    mapping: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise ValueError(error_code)
        mapping[key] = item
    return mapping


def _require_string_list(value: object, error_code: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(error_code)
    return [item for item in value if isinstance(item, str)]


def _validate_schema(document: Mapping[str, object], schema_path: Path, error_prefix: str) -> None:
    """Validate one document against one local Draft 2020-12 schema."""
    schema = _read_json_mapping(schema_path, f"{error_prefix}_SCHEMA")
    try:
        _DRAFT202012_VALIDATOR.check_schema(schema)
        violations = list(_DRAFT202012_VALIDATOR(schema).iter_errors(document))
    except Exception as exc:
        raise ValueError(f"{error_prefix}_SCHEMA_INVALID") from exc
    if violations:
        raise ValueError(f"{error_prefix}_SCHEMA_VIOLATION")


def _validate_self_hash(document: Mapping[str, object], field: str, error_prefix: str) -> str:
    """Require a correct semantic self-hash while leaving the source immutable."""
    recorded = _require_sha256(document.get(field), f"{error_prefix}_SELF_HASH_INVALID")
    unsigned = dict(document)
    unsigned.pop(field, None)
    if _canonical_sha256(unsigned) != recorded:
        raise ValueError(f"{error_prefix}_SELF_HASH_MISMATCH")
    return recorded


def _require_values(
    document: Mapping[str, object], expected: Mapping[str, object], error_prefix: str
) -> None:
    if any(document.get(key) != value for key, value in expected.items()):
        raise ValueError(f"{error_prefix}_GATE_INVALID")


def _validate_v24_manifest(document: Mapping[str, object]) -> Mapping[str, object]:
    _validate_schema(document, _V24_INPUT_SCHEMA, "CONFIRMATION_V4_V24")
    _validate_self_hash(document, "manifest_sha256", "CONFIRMATION_V4_V24")
    _require_values(
        document,
        {
            "schema_version": "target-blind-common-predictor-manifest-v2.4",
            "status": "PASS_TARGET_BLIND_INPUTS_RECONCILIATION_REMAINS_BLOCKED",
            "model_fit_performed": False,
            "no_target_or_metric_payload_read": True,
            "SAFE_TO_OPEN_OR_EVALUATE_OOS": "NO",
            "safe_to_reconcile_existing_results": "NO",
        },
        "CONFIRMATION_V4_V24",
    )
    _require_commit(document.get("source_commit"), "CONFIRMATION_V4_V24_SOURCE_COMMIT_INVALID")
    source_hashes = _require_mapping(
        document.get("source_hashes"), "CONFIRMATION_V4_V24_SOURCE_HASHES_INVALID"
    )
    for key in (
        "b2_availability_sidecar_sha256",
        "b2_availability_manifest_v22_sha256",
        "massive_reselection_recomputed_v21_sha256",
        "pit_reconciliation_gate_v21_sha256",
    ):
        _require_sha256(source_hashes.get(key), "CONFIRMATION_V4_V24_SOURCE_HASH_INVALID")
    return source_hashes


def _evidence_by_role(policy: Mapping[str, object]) -> dict[str, Mapping[str, object]]:
    raw_records = policy.get("source_evidence")
    if not isinstance(raw_records, list):
        raise ValueError("CONFIRMATION_V4_POLICY_EVIDENCE_INVALID")
    result: dict[str, Mapping[str, object]] = {}
    for item in raw_records:
        mapping = _require_mapping(item, "CONFIRMATION_V4_POLICY_EVIDENCE_RECORD_INVALID")
        role = mapping.get("role")
        if not isinstance(role, str) or role in result:
            raise ValueError("CONFIRMATION_V4_POLICY_EVIDENCE_ROLE_INVALID")
        result[role] = mapping
    return result


def _validate_policy_gate(document: Mapping[str, object]) -> dict[str, Mapping[str, object]]:
    _validate_schema(document, _POLICY_INPUT_SCHEMA, "CONFIRMATION_V4_POLICY")
    _validate_self_hash(document, "policy_sha256", "CONFIRMATION_V4_POLICY")
    _require_values(
        document,
        {
            "schema_version": "provider-timing-evidence-policy-gate-v1.0",
            "status": "PASS_EVIDENCE_SCOPED_POLICY_FAIL_CLOSED",
            "policy_resolution": (
                "LITERAL_RECONCILIATION_NO_REMAINS_CURRENT_FOR_SEALED_PRE_V22_RESULTS"
            ),
            "model_fit_performed": False,
            "no_target_or_metric_payload_read": True,
            "no_oos_or_predictive_artifacts_read": True,
            "no_provider_http_requests_performed": True,
        },
        "CONFIRMATION_V4_POLICY",
    )
    _require_values(
        _require_mapping(
            document.get("existing_sealed_result_reconciliation"),
            "CONFIRMATION_V4_POLICY_SEALED_GATE_INVALID",
        ),
        {"safe_to_reconcile_existing_results": "NO", "status": "BLOCKED"},
        "CONFIRMATION_V4_POLICY_SEALED",
    )
    _require_values(
        _require_mapping(document.get("oos_access"), "CONFIRMATION_V4_POLICY_OOS_GATE_INVALID"),
        {"safe_to_open_or_evaluate_oos": "NO", "status": "BLOCKED"},
        "CONFIRMATION_V4_POLICY_OOS",
    )
    _require_values(
        _require_mapping(
            document.get("new_historical_acquisition"),
            "CONFIRMATION_V4_POLICY_HISTORICAL_GATE_INVALID",
        ),
        {
            "current_authorization": "NO",
            "status": "GO_AFTER_DATE_LEVEL_PIT_PREFLIGHT",
            "timing_precondition": "DATE_LEVEL_PIT_PREFLIGHT",
        },
        "CONFIRMATION_V4_POLICY_HISTORICAL",
    )
    _require_values(
        _require_mapping(
            document.get("prospective_capture"),
            "CONFIRMATION_V4_POLICY_PROSPECTIVE_GATE_INVALID",
        ),
        {
            "current_authorization": "NO",
            "status": "GO_AFTER_RECEIPT_LOGGER_VALIDATED",
            "timing_precondition": "VALIDATED_RECEIPT_LOGGER",
        },
        "CONFIRMATION_V4_POLICY_PROSPECTIVE",
    )
    return _evidence_by_role(document)


def _validate_v3_preregistration(document: Mapping[str, object]) -> Mapping[str, object]:
    _validate_schema(document, _V3_INPUT_SCHEMA, "CONFIRMATION_V4_V3")
    _validate_self_hash(document, "preregistration_sha256", "CONFIRMATION_V4_V3")
    _require_values(
        document,
        {
            "schema_version": "target-blind-confirmation-preregistration-v3.0",
            "status": "SEALED_SOURCE_BOUND_PRE_METHOD_FREEZE_NOT_AUTHORIZED_FOR_OOS",
            "model_fit_performed": False,
            "no_target_or_metric_payload_read": True,
            "safe_to_reconcile_existing_results": "NO",
            "safe_to_open_or_evaluate_oos": "NO",
        },
        "CONFIRMATION_V4_V3",
    )
    _require_commit(document.get("source_commit"), "CONFIRMATION_V4_V3_SOURCE_COMMIT_INVALID")
    information_sets = _require_mapping(
        document.get("information_sets"), "CONFIRMATION_V4_V3_INFORMATION_SETS_INVALID"
    )
    for key in ("B0", "B1a_addition", "B1b_addition", "B1c_addition"):
        _require_string_list(
            information_sets.get(key), "CONFIRMATION_V4_V3_INFORMATION_SET_INVALID"
        )
    if (
        _require_string_list(information_sets.get("B2_addition"), "CONFIRMATION_V4_V3_B2_INVALID")
        != _FROZEN_B2_FEATURES
    ):
        raise ValueError("CONFIRMATION_V4_V3_B2_FROZEN_CONTRACT_INVALID")
    return information_sets


def _evidence_hash(
    evidence: Mapping[str, Mapping[str, object]], role: str, field: str, error_code: str
) -> str:
    record = evidence.get(role)
    if record is None:
        raise ValueError(error_code)
    return _require_sha256(record.get(field), error_code)


def _validate_cross_bindings(
    source_hashes: Mapping[str, object], evidence: Mapping[str, Mapping[str, object]]
) -> None:
    """Bridge the v2.4 predictor-only manifest to the independent policy evidence."""
    comparisons = (
        (
            "pit_reconciliation_gate_v21_sha256",
            "PIT_RECONCILIATION_GATE_V21",
            "file_sha256",
            "CONFIRMATION_V4_PIT_GATE_POLICY_BINDING_INVALID",
        ),
        (
            "massive_reselection_recomputed_v21_sha256",
            "MASSIVE_RESELECTION_V21",
            "file_sha256",
            "CONFIRMATION_V4_MASSIVE_POLICY_BINDING_INVALID",
        ),
        (
            "b2_availability_manifest_v22_sha256",
            "B2_AVAILABILITY_MANIFEST_V22",
            "file_sha256",
            "CONFIRMATION_V4_B2_MANIFEST_POLICY_BINDING_INVALID",
        ),
        (
            "b2_availability_sidecar_sha256",
            "B2_AVAILABILITY_MANIFEST_V22",
            "semantic_sha256",
            "CONFIRMATION_V4_B2_SIDECAR_POLICY_BINDING_INVALID",
        ),
    )
    for v24_key, role, evidence_field, error_code in comparisons:
        if _require_sha256(source_hashes.get(v24_key), error_code) != _evidence_hash(
            evidence, role, evidence_field, error_code
        ):
            raise ValueError(error_code)


def _preflight_workflow() -> dict[str, object]:
    """Declare the next preflight without executing or authorizing it."""
    return {
        "execution_status": "NOT_EXECUTED",
        "historical_acquisition_gate": "GO_AFTER_DATE_LEVEL_PIT_PREFLIGHT",
        "prospective_capture_gate": "GO_AFTER_RECEIPT_LOGGER_VALIDATED",
        "exact_recheck_command": "uv run python scripts/aggregate_pit_reconciliation_gate_v21.py",
        "required_human_inputs": [
            "APPROVED_DATE_LEVEL_SESSION_PLAN_WITH_SHA256",
            "APPROVED_STORAGE_AND_COST_BOUNDARY",
            "SEPARATE_EXPLICIT_HUMAN_AUTHORIZATION",
        ],
        "workflow": [
            "Record an approved exact session plan and its SHA256 before any acquisition request.",
            "Run the exact recheck command only in the isolated PIT preflight stage.",
            (
                "Record date-level timing evidence under the registered contract without OOS "
                "or metric payloads."
            ),
            (
                "Obtain separate authorization before acquisition; no preflight outcome "
                "authorizes OOS, reconciliation, fitting, or metric evaluation."
            ),
        ],
        "not_authorization": list(_PREFLIGHT_NOT_AUTHORIZATION),
    }


def _source_binding(
    *,
    v24_manifest_path: Path,
    v24_manifest: Mapping[str, object],
    policy_gate_path: Path,
    policy_gate: Mapping[str, object],
    preregistration_v3_path: Path,
    preregistration_v3: Mapping[str, object],
) -> dict[str, object]:
    return {
        "v24_predictor_only_manifest": {
            "logical_path": (
                "artifacts/target_blind_v24_sourcebound_20260812/"
                "target_blind_common_predictor_manifest_v24.json"
            ),
            "file_sha256": _file_sha256(v24_manifest_path, "CONFIRMATION_V4_V24_MANIFEST"),
            "manifest_sha256": _require_sha256(
                v24_manifest.get("manifest_sha256"), "CONFIRMATION_V4_V24_SELF_HASH_INVALID"
            ),
            "schema_version": "target-blind-common-predictor-manifest-v2.4",
            "source_commit": _require_commit(
                v24_manifest.get("source_commit"), "CONFIRMATION_V4_V24_SOURCE_COMMIT_INVALID"
            ),
        },
        "provider_timing_evidence_policy_gate_v1": {
            "logical_path": (
                "artifacts/provider_timing_v22/"
                "provider_timing_evidence_policy_gate_v1_20260812.json"
            ),
            "file_sha256": _file_sha256(policy_gate_path, "CONFIRMATION_V4_POLICY_GATE"),
            "policy_sha256": _require_sha256(
                policy_gate.get("policy_sha256"), "CONFIRMATION_V4_POLICY_SELF_HASH_INVALID"
            ),
            "schema_version": "provider-timing-evidence-policy-gate-v1.0",
        },
        "prior_preregistration_v3": {
            "logical_path": (
                "artifacts/target_blind_v23_sourcebound_20260812/"
                "next_confirmation_preregistration_v3.json"
            ),
            "file_sha256": _file_sha256(
                preregistration_v3_path, "CONFIRMATION_V4_PRIOR_PREREGISTRATION"
            ),
            "preregistration_sha256": _require_sha256(
                preregistration_v3.get("preregistration_sha256"),
                "CONFIRMATION_V4_V3_SELF_HASH_INVALID",
            ),
            "schema_version": "target-blind-confirmation-preregistration-v3.0",
            "source_commit": _require_commit(
                preregistration_v3.get("source_commit"), "CONFIRMATION_V4_V3_SOURCE_COMMIT_INVALID"
            ),
        },
    }


def _build_preregistration(
    *,
    information_sets: Mapping[str, object],
    source_binding: Mapping[str, object],
    source_commit: str,
) -> dict[str, object]:
    """Build the sealed v4 method freeze from already validated metadata only."""
    document: dict[str, object] = {
        "schema_version": "target-blind-confirmation-preregistration-v4.0",
        "status": "SEALED_METHOD_FROZEN_TARGET_BLIND_READY_FUTURE_GATES_CLOSED",
        "scope": "offline_source_bound_target_blind_method_freeze_only",
        "purpose": "freeze_successor_confirmation_method_without_target_or_oos_access",
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
        "information_sets": deepcopy(dict(information_sets)),
        "confirmatory_model": {
            "family": "Gamma",
            "estimator": "GLM",
            "link": "log",
            "role": "CONFIRMATORY_FIXED",
        },
        "robustness_model": {
            "estimator": "LightGBM",
            "role": "FIXED_ROBUSTNESS",
            "tuning": "NONE",
        },
        "metrics": {"primary": "QLIKE", "secondary": ["MAE", "RMSE"]},
        "inference": {
            "resampling": "PAIRED_DAY_CLUSTER_BOOTSTRAP",
            "cluster_unit": "TRADING_DAY",
            "multiplicity": "HOLM",
            "selection_by_sign": "PROHIBITED",
        },
        "preflight_workflow": _preflight_workflow(),
        "forbidden_runtime_actions": list(_FORBIDDEN_RUNTIME_ACTIONS),
        "bound_sources": deepcopy(dict(source_binding)),
        "artifact_schema": {
            "logical_path": (
                "specs/001-pit-options-rv30/contracts/"
                "target-blind-confirmation-preregistration-v4.schema.json"
            ),
            "file_sha256": _file_sha256(_V4_OUTPUT_SCHEMA, "CONFIRMATION_V4_OUTPUT_SCHEMA"),
        },
        "builder_script_sha256": _file_sha256(Path(__file__), "CONFIRMATION_V4_BUILDER_SCRIPT"),
        "source_commit": source_commit,
    }
    document["preregistration_sha256"] = _canonical_sha256(document)
    return document


def _build_readiness(
    *,
    preregistration: Mapping[str, object],
    source_binding: Mapping[str, object],
    source_commit: str,
) -> dict[str, object]:
    """Build the reproducible readiness package that retains all closed gates."""
    v24 = _require_mapping(
        source_binding.get("v24_predictor_only_manifest"), "CONFIRMATION_V4_SOURCE_BINDING_INVALID"
    )
    policy = _require_mapping(
        source_binding.get("provider_timing_evidence_policy_gate_v1"),
        "CONFIRMATION_V4_SOURCE_BINDING_INVALID",
    )
    preregistration_bytes = _render_json(preregistration)
    document: dict[str, object] = {
        "schema_version": "confirmation-readiness-v3.0",
        "status": "PASS_METHOD_FROZEN_TARGET_BLIND_READY_FUTURE_GATES_CLOSED",
        "scope": "offline_source_bound_target_blind_readiness_only",
        "method_freeze_status": "FROZEN_TARGET_BLIND_ONLY",
        "target_blind_ready": "YES",
        "no_target_or_metric_payload_read": True,
        "model_fit_performed": False,
        "no_provider_network_calls_performed": True,
        "claim_boundary": "NO_PREDICTIVE_OR_COMPARATIVE_CLAIM",
        "safe_to_reconcile_existing_results": "NO",
        "safe_to_open_or_evaluate_oos": "NO",
        "safe_to_acquire_new_historical_sample": "NO",
        "safe_to_start_prospective_capture": "NO",
        "gate_statuses": {
            "existing_sealed_result_reconciliation": "BLOCKED_LITERAL_NO_REMAINS_CURRENT",
            "oos_access": "BLOCKED_NO",
            "new_historical_acquisition": "NO_UNTIL_DATE_LEVEL_PIT_PREFLIGHT",
            "prospective_capture": "NO_UNTIL_RECEIPT_LOGGER_VALIDATED",
        },
        "bound_artifact_integrity": {
            "status": "PASS",
            "v24_predictor_only_manifest": {
                "file_sha256": v24["file_sha256"],
                "manifest_sha256": v24["manifest_sha256"],
            },
            "provider_timing_evidence_policy_gate_v1": {
                "file_sha256": policy["file_sha256"],
                "policy_sha256": policy["policy_sha256"],
            },
            "preregistration_v4": {
                "file_sha256": hashlib.sha256(preregistration_bytes).hexdigest(),
                "preregistration_sha256": preregistration["preregistration_sha256"],
            },
        },
        "preflight_workflow": _preflight_workflow(),
        "required_before_any_oos_access": [
            "FROZEN_V4_METHOD_REVIEW",
            "SEPARATE_EXPLICIT_HUMAN_AUTHORIZATION",
            "DATE_LEVEL_PIT_PREFLIGHT_IF_NEW_HISTORICAL_ACQUISITION",
            "VALIDATED_RECEIPT_LOGGER_IF_PROSPECTIVE_CAPTURE",
        ],
        "forbidden_runtime_actions": list(_FORBIDDEN_RUNTIME_ACTIONS),
        "artifact_schema": {
            "logical_path": (
                "specs/001-pit-options-rv30/contracts/confirmation-readiness-v3.schema.json"
            ),
            "file_sha256": _file_sha256(
                _READINESS_OUTPUT_SCHEMA, "CONFIRMATION_V4_READINESS_SCHEMA"
            ),
        },
        "builder_script_sha256": _file_sha256(Path(__file__), "CONFIRMATION_V4_BUILDER_SCRIPT"),
        "source_commit": source_commit,
    }
    document["readiness_sha256"] = _canonical_sha256(document)
    return document


def _assert_write_compatible(path: Path, payload: bytes) -> None:
    """Fail closed rather than replace an existing sealed artifact."""
    if path.exists() and (not path.is_file() or path.read_bytes() != payload):
        raise ValueError(f"CONFIRMATION_V4_OUTPUT_CONFLICT:{path.name}")


def _write_if_identical(path: Path, payload: bytes) -> None:
    """Write one missing artifact after all output conflicts were preflighted."""
    if path.exists():
        return
    path.write_bytes(payload)


def seal_confirmation_package(
    *,
    v24_manifest_path: Path,
    policy_gate_path: Path,
    preregistration_v3_path: Path,
    output_dir: Path,
    source_commit: str,
) -> dict[str, Path]:
    """Seal a deterministic method freeze and readiness package from JSON metadata.

    The function validates all source schemas, self-hashes, closed gates, and
    policy-to-v2.4 evidence bindings before it emits either output.  Existing
    equal bytes are retained; divergent bytes cause a fail-closed conflict.
    """
    _require_commit(source_commit, "CONFIRMATION_V4_SOURCE_COMMIT_INVALID")
    v24_manifest = _read_json_mapping(v24_manifest_path, "CONFIRMATION_V4_V24")
    policy_gate = _read_json_mapping(policy_gate_path, "CONFIRMATION_V4_POLICY")
    preregistration_v3 = _read_json_mapping(preregistration_v3_path, "CONFIRMATION_V4_V3")

    source_hashes = _validate_v24_manifest(v24_manifest)
    evidence = _validate_policy_gate(policy_gate)
    information_sets = _validate_v3_preregistration(preregistration_v3)
    _validate_cross_bindings(source_hashes, evidence)

    source_binding = _source_binding(
        v24_manifest_path=v24_manifest_path,
        v24_manifest=v24_manifest,
        policy_gate_path=policy_gate_path,
        policy_gate=policy_gate,
        preregistration_v3_path=preregistration_v3_path,
        preregistration_v3=preregistration_v3,
    )
    preregistration = _build_preregistration(
        information_sets=information_sets,
        source_binding=source_binding,
        source_commit=source_commit,
    )
    _validate_schema(preregistration, _V4_OUTPUT_SCHEMA, "CONFIRMATION_V4_OUTPUT")
    _validate_self_hash(preregistration, "preregistration_sha256", "CONFIRMATION_V4_OUTPUT")
    readiness = _build_readiness(
        preregistration=preregistration,
        source_binding=source_binding,
        source_commit=source_commit,
    )
    _validate_schema(readiness, _READINESS_OUTPUT_SCHEMA, "CONFIRMATION_V4_READINESS")
    _validate_self_hash(readiness, "readiness_sha256", "CONFIRMATION_V4_READINESS")

    preregistration_path = output_dir / "next_confirmation_preregistration_v4.json"
    readiness_path = output_dir / "confirmation_readiness_v3.json"
    preregistration_bytes = _render_json(preregistration)
    readiness_bytes = _render_json(readiness)
    _assert_write_compatible(preregistration_path, preregistration_bytes)
    _assert_write_compatible(readiness_path, readiness_bytes)
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_if_identical(preregistration_path, preregistration_bytes)
    _write_if_identical(readiness_path, readiness_bytes)
    return {"preregistration": preregistration_path, "readiness": readiness_path}


def _parse_arguments(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Seal the target-blind v4 confirmation package from source-bound JSON only."
    )
    parser.add_argument("--v24-manifest", type=Path, default=_DEFAULT_V24_MANIFEST)
    parser.add_argument("--policy-gate", type=Path, default=_DEFAULT_POLICY_GATE)
    parser.add_argument("--preregistration-v3", type=Path, default=_DEFAULT_V3_PREREGISTRATION)
    parser.add_argument("--output-dir", type=Path, default=_DEFAULT_OUTPUT_DIRECTORY)
    parser.add_argument("--source-commit", required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Run the metadata-only sealer; callers supply the exact source commit."""
    arguments = _parse_arguments(argv)
    sealed = seal_confirmation_package(
        v24_manifest_path=arguments.v24_manifest,
        policy_gate_path=arguments.policy_gate,
        preregistration_v3_path=arguments.preregistration_v3,
        output_dir=arguments.output_dir,
        source_commit=arguments.source_commit,
    )
    for label in ("preregistration", "readiness"):
        path = sealed[label]
        print(f"{label}={path.as_posix()}")
        print(f"{label}_file_sha256={_file_sha256(path, 'CONFIRMATION_V4_OUTPUT')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
