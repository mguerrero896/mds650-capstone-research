"""Fail-closed provenance binding for the target-blind predictor panel v2.3."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

from mds650.provider_timing_v21 import canonical_sha256

MASSIVE_LOGICAL_PATH = (
    "artifacts/provider_timing_v21/massive_reselection_sensitivity_v21_recomputed_20260812.json"
)
UW_AVAILABILITY_MANIFEST_LOGICAL_PATH = (
    "artifacts/provider_timing_v22/b2_availability_manifest_v22.json"
)
MASSIVE_SELECTION_RULE = "last_quote_by_sip_timestamp_then_sequence_at_or_before_origin_minus_delay"


def validate_target_blind_provenance_v23(
    *,
    availability_manifest_path: Path,
    availability_manifest_schema_path: Path,
    availability_sidecar_path: Path,
    massive_reselection_path: Path,
    origins_path: Path,
    reconciliation_gate_path: Path,
    reconciliation_gate_schema_path: Path,
) -> dict[str, str]:
    """Validate immutable source identities before reading predictor payloads.

    Parameters
    ----------
    availability_manifest_path:
        Sanitized v2.2 manifest describing the immutable B2 availability
        sidecar.
    availability_manifest_schema_path:
        Draft 2020-12 JSON Schema for ``availability_manifest_path``.
    availability_sidecar_path:
        Derived Parquet sidecar whose bytes must match the v2.2 manifest.
    massive_reselection_path:
        Promoted, target-free Massive v2.1 recomputation record.
    origins_path:
        Target-free canonical origin grid whose bytes must match the v2.2
        manifest.
    reconciliation_gate_path:
        Promoted v2.1 aggregate gate that binds the Massive record and v2.2
        manifest.
    reconciliation_gate_schema_path:
        Draft 2020-12 JSON Schema for ``reconciliation_gate_path``.

    Returns
    -------
    dict[str, str]
        Stable SHA-256 identities for the five bound input records.  The map
        contains no filesystem paths or predictor values.

    Raises
    ------
    FileNotFoundError
        If any local evidence file or schema is absent.
    ValueError
        If a schema, self-hash, provider-timing claim, or cross-record binding
        is inconsistent.

    Notes
    -----
    This function reads only compact provenance JSON and file bytes needed for
    hashing.  It does not read predictor payloads, targets, models, metrics,
    or OOS artefacts.
    """
    for label, path in {
        "AVAILABILITY_MANIFEST": availability_manifest_path,
        "AVAILABILITY_MANIFEST_SCHEMA": availability_manifest_schema_path,
        "AVAILABILITY_SIDECAR": availability_sidecar_path,
        "MASSIVE_RESELECTION": massive_reselection_path,
        "ORIGINS": origins_path,
        "RECONCILIATION_GATE": reconciliation_gate_path,
        "RECONCILIATION_GATE_SCHEMA": reconciliation_gate_schema_path,
    }.items():
        if not path.is_file():
            raise FileNotFoundError(f"TARGET_BLIND_V23_{label}_MISSING")

    availability_manifest = _read_json_object(
        availability_manifest_path, "TARGET_BLIND_V23_AVAILABILITY_MANIFEST"
    )
    reconciliation_gate = _read_json_object(
        reconciliation_gate_path, "TARGET_BLIND_V23_RECONCILIATION_GATE"
    )
    massive_reselection = _read_json_object(
        massive_reselection_path, "TARGET_BLIND_V23_MASSIVE_RESELECTION"
    )
    _validate_json_schema(
        availability_manifest,
        availability_manifest_schema_path,
        "TARGET_BLIND_V23_AVAILABILITY_MANIFEST_SCHEMA",
    )
    _validate_json_schema(
        reconciliation_gate,
        reconciliation_gate_schema_path,
        "TARGET_BLIND_V23_RECONCILIATION_GATE_SCHEMA",
    )

    hashes = {
        "origins_sha256": _sha256_file(origins_path),
        "b2_availability_sidecar_sha256": _sha256_file(availability_sidecar_path),
        "massive_reselection_recomputed_v21_sha256": _sha256_file(massive_reselection_path),
        "b2_availability_manifest_v22_sha256": _sha256_file(availability_manifest_path),
        "pit_reconciliation_gate_v21_sha256": _sha256_file(reconciliation_gate_path),
    }
    _validate_availability_manifest(availability_manifest, hashes)
    _validate_massive_reselection(massive_reselection)
    _validate_reconciliation_gate(reconciliation_gate, hashes)
    return hashes


def _read_json_object(path: Path, error_prefix: str) -> dict[str, Any]:
    """Read one UTF-8 JSON object or raise a stable, fail-closed error."""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{error_prefix}_INVALID_JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{error_prefix}_NOT_OBJECT")
    return value


def _validate_json_schema(
    document: Mapping[str, Any], schema_path: Path, error_prefix: str
) -> None:
    """Validate one compact evidence document against its pinned JSON Schema."""
    schema = _read_json_object(schema_path, error_prefix)
    try:
        Draft202012Validator.check_schema(schema)
        errors = sorted(
            Draft202012Validator(schema).iter_errors(document),
            key=lambda error: list(error.absolute_path),
        )
    except Exception as exc:  # pragma: no cover - jsonschema internal failure
        raise ValueError(f"{error_prefix}_INVALID") from exc
    if errors:
        raise ValueError(f"{error_prefix}_VIOLATION")


def _validate_availability_manifest(document: Mapping[str, Any], hashes: Mapping[str, str]) -> None:
    """Require the sidecar and origin bytes recorded by the v2.2 manifest."""
    if document.get("expected_origins_sha256") != hashes["origins_sha256"]:
        raise ValueError("TARGET_BLIND_V23_ORIGIN_HASH_MISMATCH")
    if document.get("sidecar_sha256") != hashes["b2_availability_sidecar_sha256"]:
        raise ValueError("TARGET_BLIND_V23_SIDECAR_HASH_MISMATCH")


def _validate_massive_reselection(document: Mapping[str, Any]) -> None:
    """Require the promoted target-free Massive recomputation identity."""
    recorded_hash = document.get("recomputed_result_sha256")
    if not isinstance(recorded_hash, str):
        raise ValueError("TARGET_BLIND_V23_MASSIVE_SELF_HASH_INVALID")
    unsigned = dict(document)
    unsigned.pop("recomputed_result_sha256", None)
    if canonical_sha256(unsigned) != recorded_hash:
        raise ValueError("TARGET_BLIND_V23_MASSIVE_SELF_HASH_MISMATCH")
    required = {
        "schema_version": "provider-timing-v2.1",
        "status": "PASS",
        "no_provider_http_requests_performed": True,
        "no_targets_or_predictive_metrics_read": True,
        "selection_rule": MASSIVE_SELECTION_RULE,
    }
    if any(document.get(key) != value for key, value in required.items()):
        raise ValueError("TARGET_BLIND_V23_MASSIVE_CONTRACT_INVALID")


def _validate_reconciliation_gate(document: Mapping[str, Any], hashes: Mapping[str, str]) -> None:
    """Require a self-consistent closed gate that binds both promoted records."""
    recorded_hash = document.get("aggregation_sha256")
    if not isinstance(recorded_hash, str):
        raise ValueError("TARGET_BLIND_V23_GATE_SELF_HASH_INVALID")
    unsigned = dict(document)
    unsigned.pop("aggregation_sha256", None)
    if canonical_sha256(unsigned) != recorded_hash:
        raise ValueError("TARGET_BLIND_V23_GATE_SELF_HASH_MISMATCH")
    required = {
        "schema_version": "pit-reconciliation-gate-v2.1",
        "status": "CONDITIONAL_NOT_CLOSED",
        "SAFE_TO_RECONCILE_EXISTING_RESULTS": "NO",
        "SAFE_TO_OPEN_OR_EVALUATE_OOS": "NO",
        "edge_conclusion": "NOT_EVALUATED_TARGET_BLIND",
        "no_provider_http_requests_performed": True,
        "no_targets_or_predictive_metrics_read": True,
        "no_oos_or_predictive_artifacts_read": True,
    }
    if any(document.get(key) != value for key, value in required.items()):
        raise ValueError("TARGET_BLIND_V23_GATE_CONTRACT_INVALID")
    evidence = document.get("source_evidence")
    if not isinstance(evidence, list):
        raise ValueError("TARGET_BLIND_V23_GATE_EVIDENCE_INVALID")
    _assert_single_binding(
        evidence,
        role="MASSIVE_RESELECTION",
        logical_path=MASSIVE_LOGICAL_PATH,
        expected_hash=hashes["massive_reselection_recomputed_v21_sha256"],
        error_code="TARGET_BLIND_V23_GATE_MASSIVE_HASH_MISMATCH",
    )
    _assert_single_binding(
        evidence,
        role="UW_AVAILABILITY_MANIFEST_V22",
        logical_path=UW_AVAILABILITY_MANIFEST_LOGICAL_PATH,
        expected_hash=hashes["b2_availability_manifest_v22_sha256"],
        error_code="TARGET_BLIND_V23_GATE_B2_MANIFEST_HASH_MISMATCH",
    )


def _assert_single_binding(
    evidence: list[Any],
    *,
    role: str,
    logical_path: str,
    expected_hash: str,
    error_code: str,
) -> None:
    """Require exactly one named source record with an exact byte identity."""
    matches = [
        item
        for item in evidence
        if isinstance(item, Mapping)
        and item.get("role") == role
        and item.get("logical_path") == logical_path
    ]
    if len(matches) != 1 or matches[0].get("file_sha256") != expected_hash:
        raise ValueError(error_code)


def _sha256_file(path: Path) -> str:
    """Return the SHA-256 of one local file without parsing its payload."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
