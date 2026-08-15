"""Target-blind B2 construction for the 30-session independent replication."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import polars as pl

from mds650.b1_replication_build import CANONICAL_ASSETS
from mds650.b1v3_b2_confirmation import (
    FullTapeContract,
    _build_raw_matrices,
    _combine_variant,
    _partition_index,
    _write_json_records,
    _write_parquet_if_identical,
)
from mds650.b1v3_confirmation import canonical_sha256, sha256_file
from mds650.b1v3_provider_preflight_v2 import validate_json_schema
from mds650.b2_availability_v22 import build_b2_availability_sidecar
from mds650.provider_timing_v21 import (
    audit_b2_canonical_traceability,
    audit_uw_session_asset_incidents,
)
from mds650.study_design import B2_FEATURE_NAMES


@dataclass(frozen=True, slots=True)
class ReplicationB2Artifacts:
    """Paths and hashes for corrected target-blind B2 replication artifacts."""

    primary_path: Path
    sidecar_path: Path
    manifest_path: Path
    manifest_file_sha256: str


def _json_object(path: Path, *, code: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(code) from exc
    if not isinstance(value, dict):
        raise ValueError(code)
    return value


def validate_full_tape_document(
    document: Mapping[str, object],
    *,
    preregistration_sha256: str,
    provider_report_sha256: str,
    sessions: Sequence[str],
) -> FullTapeContract:
    """Validate every daily checkpoint against the frozen replication hashes."""
    stored_hash = document.get("manifest_sha256")
    unsigned = {key: value for key, value in document.items() if key != "manifest_sha256"}
    expected_sessions = tuple(str(value) for value in sessions)
    raw_records = document.get("sessions")
    if (
        not isinstance(stored_hash, str)
        or stored_hash != canonical_sha256(unsigned)
        or document.get("status") != "PASS"
        or document.get("target_blind") is not True
        or document.get("preregistration_sha256") != preregistration_sha256
        or document.get("provider_report_sha256") != provider_report_sha256
        or document.get("authorized_session_count") != len(expected_sessions)
        or document.get("completed_session_count") != len(expected_sessions)
        or document.get("pending_session_count") != 0
        or document.get("pending_sessions") != []
        or document.get("target_outcome_read") is not False
        or document.get("outcome_read_count") != 0
        or document.get("secret_values_emitted") is not False
        or document.get("personal_paths_emitted") is not False
        or not isinstance(raw_records, list)
    ):
        raise ValueError("REPLICATION_B2_ACQUISITION_GATE_INVALID")
    records: dict[str, Mapping[str, Any]] = {}
    for raw in raw_records:
        if not isinstance(raw, Mapping):
            raise ValueError("REPLICATION_B2_ACQUISITION_SESSION_INVALID")
        day = str(raw.get("session_date", ""))
        checkpoint_hash = raw.get("checkpoint_sha256")
        unsigned_row = {key: value for key, value in raw.items() if key != "checkpoint_sha256"}
        expected_contract = canonical_sha256(
            {
                "session_date": day,
                "preregistration_sha256": preregistration_sha256,
                "provider_report_sha256": provider_report_sha256,
            }
        )
        if (
            raw.get("status") != "PASS"
            or raw.get("preregistration_sha256") != preregistration_sha256
            or raw.get("provider_report_sha256") != provider_report_sha256
            or raw.get("session_contract_sha256") != expected_contract
            or raw.get("target_outcome_read") is not False
            or raw.get("outcome_read_count") != 0
            or raw.get("secret_values_emitted") is not False
            or raw.get("personal_paths_emitted") is not False
            or not isinstance(checkpoint_hash, str)
            or checkpoint_hash != canonical_sha256(unsigned_row)
            or day in records
        ):
            raise ValueError("REPLICATION_B2_ACQUISITION_SESSION_INVALID")
        records[day] = raw
    if tuple(records) != expected_sessions:
        raise ValueError("REPLICATION_B2_ACQUISITION_SESSION_SCOPE_INVALID")
    return FullTapeContract(stored_hash, records)


def load_replication_full_tape_contract(
    path: Path,
    *,
    schema_path: Path,
    preregistration_sha256: str,
    provider_report_sha256: str,
    sessions: Sequence[str],
) -> FullTapeContract:
    """Load and JSON-Schema validate the completed Full Tape manifest."""
    document = _json_object(path, code="REPLICATION_B2_ACQUISITION_MANIFEST_INVALID")
    validate_json_schema(
        document,
        schema_path=schema_path,
        error_code="REPLICATION_B2_ACQUISITION_MANIFEST",
    )
    return validate_full_tape_document(
        document,
        preregistration_sha256=preregistration_sha256,
        provider_report_sha256=provider_report_sha256,
        sessions=sessions,
    )


def _write_manifest(path: Path, document: Mapping[str, Any]) -> str:
    payload = (json.dumps(document, indent=2, sort_keys=True, ensure_ascii=True) + "\n").encode()
    lowered = payload.lower()
    forbidden = (
        b"c:\\users\\",
        b"c:/users/",
        b"d:\\mds650",
        b"api_key",
        b"authorization",
        b"bearer ",
    )
    if any(token in lowered for token in forbidden):
        raise ValueError("REPLICATION_B2_MANIFEST_HYGIENE_INVALID")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != payload:
            raise ValueError("REPLICATION_B2_MANIFEST_OUTPUT_CONFLICT")
    else:
        path.write_bytes(payload)
    return sha256_file(path)


def build_replication_b2_artifacts(
    *,
    preregistration_sha256: str,
    full_tape_contract: FullTapeContract,
    base_manifest_path: Path,
    origins_path: Path,
    sessions: Sequence[str],
    data_root: Path,
    event_root: Path,
    output_root: Path,
    manifest_path: Path,
    manifest_schema_path: Path,
) -> ReplicationB2Artifacts:
    """Build three latency variants and mask delayed UW rows as unavailable."""
    base = _json_object(base_manifest_path, code="REPLICATION_B2_BASE_MANIFEST_INVALID")
    base_hash = base.get("manifest_sha256")
    unsigned_base = {key: value for key, value in base.items() if key != "manifest_sha256"}
    if (
        not isinstance(base_hash, str)
        or base_hash != canonical_sha256(unsigned_base)
        or base.get("status") != "PASS_TARGET_BLIND_BASE_PREDICTORS"
        or base.get("preregistration_sha256") != preregistration_sha256
        or base.get("target_blind") is not True
        or base.get("outcome_read_count") != 0
        or base.get("safe_to_read_outcomes") is not False
    ):
        raise ValueError("REPLICATION_B2_BASE_GATE_INVALID")
    outputs = base.get("outputs")
    origin_output = outputs.get("origins") if isinstance(outputs, Mapping) else None
    if (
        not isinstance(origin_output, Mapping)
        or not origins_path.is_file()
        or origin_output.get("sha256") != sha256_file(origins_path)
    ):
        raise ValueError("REPLICATION_B2_ORIGIN_BINDING_INVALID")
    origins = pl.read_parquet(origins_path)
    if origins.height != 12_744 or origins["origin_id"].n_unique() != origins.height:
        raise ValueError("REPLICATION_B2_ORIGIN_SCOPE_INVALID")
    frozen_sessions = tuple(str(value) for value in sessions)
    partitions = _partition_index(full_tape_contract, data_root=data_root)
    raw_root = output_root / "b2_raw_canonical"
    raw_paths = _build_raw_matrices(
        origins=origins,
        partition_index=partitions,
        output_root=raw_root,
        sessions=frozen_sessions,
    )
    incidents = audit_uw_session_asset_incidents(
        event_root=event_root,
        session_dates=frozen_sessions,
        assets=CANONICAL_ASSETS,
    )
    traceability, legacy_gate = audit_b2_canonical_traceability(
        matrix_root=raw_root,
        incidents=incidents,
        expected_origins_path=origins_path,
    )
    sidecar, availability_summary = build_b2_availability_sidecar(
        event_root=event_root,
        matrix_root=raw_root,
        expected_origins_path=origins_path,
        traceability_rows=traceability,
    )
    sidecar_path = output_root / "b2_availability_sidecar.parquet"
    sidecar_hash = _write_parquet_if_identical(sidecar, sidecar_path)
    incident_hash = _write_json_records(output_root / "uw_incidents.json", incidents)
    traceability_hash = _write_json_records(
        output_root / "b2_traceability.json", traceability
    )
    corrected: dict[str, dict[str, Any]] = {}
    primary_path = output_root / "b2_primary_target_blind.parquet"
    for variant, paths in raw_paths.items():
        destination = (
            primary_path
            if variant == "primary_5m_60s"
            else output_root / f"b2_{variant}_target_blind.parquet"
        )
        frame, file_hash = _combine_variant(
            paths,
            sidecar=sidecar,
            variant=variant,
            destination=destination,
        )
        if frame.height != origins.height or frame["origin_id"].n_unique() != frame.height:
            raise ValueError("REPLICATION_B2_CORRECTED_ORIGIN_PRESERVATION_FAILURE")
        corrected[variant] = {
            "logical_path": (
                f"MDS650_B1_REPLICATION_DATA_ROOT/predictors/{destination.name}"
            ),
            "sha256": file_hash,
            "row_count": frame.height,
            "eligible_row_count": frame.filter(
                pl.col("b2v2_availability_eligible")
            ).height,
            "excluded_row_count": frame.filter(
                ~pl.col("b2v2_availability_eligible")
            ).height,
        }
    document: dict[str, Any] = {
        "schema_version": "b1-independent-replication-b2-1.0",
        "status": "PASS_TARGET_BLIND_B2_PREDICTORS",
        "preregistration_sha256": preregistration_sha256,
        "base_manifest_sha256": base_hash,
        "full_tape_manifest_sha256": full_tape_contract.manifest_sha256,
        "target_blind": True,
        "outcome_read_count": 0,
        "safe_to_read_outcomes": False,
        "session_count": len(frozen_sessions),
        "asset_count": len(CANONICAL_ASSETS),
        "origin_count": origins.height,
        "feature_count": len(B2_FEATURE_NAMES),
        "features": list(B2_FEATURE_NAMES),
        "variants": corrected,
        "availability": availability_summary,
        "legacy_zero_coding_gate": legacy_gate,
        "sidecar": {
            "logical_path": (
                "MDS650_B1_REPLICATION_DATA_ROOT/predictors/"
                "b2_availability_sidecar.parquet"
            ),
            "sha256": sidecar_hash,
            "row_count": sidecar.height,
        },
        "evidence": {
            "incident_ledger_sha256": incident_hash,
            "traceability_ledger_sha256": traceability_hash,
        },
        "security": {
            "secret_values_emitted": False,
            "personal_paths_emitted": False,
        },
    }
    document["manifest_sha256"] = canonical_sha256(document)
    validate_json_schema(
        document,
        schema_path=manifest_schema_path,
        error_code="REPLICATION_B2_MANIFEST",
    )
    file_hash = _write_manifest(manifest_path, document)
    return ReplicationB2Artifacts(
        primary_path=primary_path,
        sidecar_path=sidecar_path,
        manifest_path=manifest_path,
        manifest_file_sha256=file_hash,
    )
