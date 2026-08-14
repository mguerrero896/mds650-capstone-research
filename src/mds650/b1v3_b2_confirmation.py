"""Resumable target-blind B2 construction for the frozen B1v3 confirmation sample."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Final

import polars as pl

from mds650.b1v3_confirmation import (
    canonical_sha256,
    sha256_file,
    validate_confirmation_plan_schema,
)
from mds650.b1v3_confirmation_build import B1V3_CANONICAL_ASSETS, FrozenBuildInputs
from mds650.b1v3_confirmation_panel import apply_b2_availability_sidecar
from mds650.b2_availability_v22 import build_b2_availability_sidecar
from mds650.phase5_features import add_compact_b2_features
from mds650.phase6 import aggregate_b2_activity
from mds650.provider_timing_v21 import (
    audit_b2_canonical_traceability,
    audit_uw_session_asset_incidents,
)
from mds650.study_design import B2_FEATURE_NAMES

B2_CONFIRMATION_VARIANTS: Final[Mapping[str, int]] = {
    "primary_5m_60s": 60,
    "latency_5m_120s": 120,
    "latency_5m_300s": 300,
}
_EVENT_COLUMNS: Final[tuple[str, ...]] = (
    "underlying_symbol",
    "option_chain_id",
    "executed_at",
    "created_at",
    "premium",
    "option_type",
    "tags",
    "strike",
    "expiry",
)
_FORBIDDEN_TOKENS: Final[tuple[bytes, ...]] = (
    b"c:\\users\\",
    b"c:/users/",
    b"d:\\mds650",
    b"api_key",
    b"apikey",
    b"authorization",
    b"bearer ",
)


@dataclass(frozen=True, slots=True)
class FullTapeContract:
    """Hash-bound Full Tape partitions authorized by the frozen 60/30 plan."""

    manifest_sha256: str
    session_records: Mapping[str, Mapping[str, Any]]


@dataclass(frozen=True, slots=True)
class B2ConfirmationArtifacts:
    """Paths and hashes for corrected target-blind B2 predictor artifacts."""

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


def load_full_tape_contract(
    path: Path,
    *,
    frozen_inputs: FrozenBuildInputs,
    manifest_schema_path: Path,
) -> FullTapeContract:
    """Validate the completed acquisition manifest without reading outcomes.

    Parameters
    ----------
    path:
        Immutable acquisition manifest produced by the resumable Full Tape job.
    frozen_inputs:
        Hash-bound 60/30 session contract already accepted by provider preflight.
    manifest_schema_path:
        Draft 2020-12 schema for the acquisition manifest.

    Returns
    -------
    FullTapeContract
        Validated manifest hash and one unique checkpoint per frozen session.

    Raises
    ------
    ValueError
        If schema, hashes, target-blind gates, or the exact 90-session scope fail.
    """
    document = _json_object(path, code="B1V3_B2_ACQUISITION_MANIFEST_INVALID")
    validate_confirmation_plan_schema(document, manifest_schema_path)
    stored_hash = document.get("manifest_sha256")
    unsigned = {key: value for key, value in document.items() if key != "manifest_sha256"}
    if not isinstance(stored_hash, str) or stored_hash != canonical_sha256(unsigned):
        raise ValueError("B1V3_B2_ACQUISITION_MANIFEST_HASH_INVALID")
    sessions = document.get("sessions")
    if (
        document.get("status") != "PASS"
        or document.get("target_blind") is not True
        or document.get("target_outcome_read") is not False
        or document.get("oos_read_count") != 0
        or document.get("secret_values_emitted") is not False
        or document.get("personal_paths_emitted") is not False
        or document.get("confirmation_plan_sha256") != frozen_inputs.plan_sha256
        or document.get("authorized_session_count") != 90
        or document.get("completed_session_count") != 90
        or document.get("pending_session_count") != 0
        or document.get("pending_sessions") != []
        or not isinstance(sessions, list)
    ):
        raise ValueError("B1V3_B2_ACQUISITION_GATE_INVALID")
    records: dict[str, Mapping[str, Any]] = {}
    for row in sessions:
        if not isinstance(row, dict):
            raise ValueError("B1V3_B2_ACQUISITION_SESSION_INVALID")
        day = str(row.get("session_date", ""))
        checkpoint_hash = row.get("checkpoint_sha256")
        unsigned_row = {key: value for key, value in row.items() if key != "checkpoint_sha256"}
        expected_session_contract = canonical_sha256(
            {
                "session_date": day,
                "confirmation_plan_sha256": frozen_inputs.plan_sha256,
            }
        )
        if (
            row.get("status") != "PASS"
            or row.get("target_outcome_read") is not False
            or row.get("oos_read_count") != 0
            or row.get("secret_values_emitted") is not False
            or row.get("personal_paths_emitted") is not False
            or row.get("confirmation_plan_sha256") != frozen_inputs.plan_sha256
            or row.get("session_contract_sha256") != expected_session_contract
            or not isinstance(checkpoint_hash, str)
            or checkpoint_hash != canonical_sha256(unsigned_row)
            or day in records
        ):
            raise ValueError("B1V3_B2_ACQUISITION_SESSION_INVALID")
        records[day] = row
    if tuple(sorted(records)) != tuple(sorted(frozen_inputs.all_sessions)):
        raise ValueError("B1V3_B2_ACQUISITION_SESSION_SCOPE_INVALID")
    return FullTapeContract(stored_hash, records)


def _safe_partition_path(data_root: Path, relative_path: object) -> Path:
    if not isinstance(relative_path, str):
        raise ValueError("B1V3_B2_PARTITION_PATH_INVALID")
    relative = PurePosixPath(relative_path)
    if len(relative.parts) != 5:
        raise ValueError("B1V3_B2_PARTITION_PATH_INVALID")
    if (
        relative.is_absolute()
        or ".." in relative.parts
        or relative.parts[:2] != ("data", "option_events")
        or not relative.parts[2].startswith("date=")
        or not relative.parts[3].startswith("asset=")
        or relative.parts[4] != "events.parquet"
    ):
        raise ValueError("B1V3_B2_PARTITION_PATH_INVALID")
    root = data_root.resolve()
    candidate = (root / Path(*relative.parts)).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError("B1V3_B2_PARTITION_PATH_INVALID") from exc
    if not candidate.is_file():
        raise FileNotFoundError("B1V3_B2_PARTITION_MISSING")
    return candidate


def _partition_index(
    contract: FullTapeContract,
    *,
    data_root: Path,
) -> Mapping[tuple[str, str], tuple[Path, str]]:
    index: dict[tuple[str, str], tuple[Path, str]] = {}
    for day, record in contract.session_records.items():
        files = record.get("parquet_files")
        if not isinstance(files, list):
            raise ValueError("B1V3_B2_PARTITION_MANIFEST_INVALID")
        for item in files:
            if not isinstance(item, dict):
                raise ValueError("B1V3_B2_PARTITION_MANIFEST_INVALID")
            relative = str(item.get("relative_path", ""))
            parts = PurePosixPath(relative).parts
            if len(parts) != 5 or not parts[2].startswith("date=") or not parts[3].startswith(
                "asset="
            ):
                raise ValueError("B1V3_B2_PARTITION_MANIFEST_INVALID")
            asset = parts[3].removeprefix("asset=")
            session_date = parts[2].removeprefix("date=")
            if session_date != day or asset not in B1V3_CANONICAL_ASSETS:
                continue
            path = _safe_partition_path(data_root, relative)
            expected_hash = item.get("sha256")
            if (
                not isinstance(expected_hash, str)
                or item.get("bytes") != path.stat().st_size
                or (session_date, asset) in index
            ):
                raise ValueError("B1V3_B2_PARTITION_MANIFEST_INVALID")
            index[(session_date, asset)] = (path, expected_hash)
    expected = {
        (day, asset)
        for day in contract.session_records
        for asset in B1V3_CANONICAL_ASSETS
    }
    if set(index) != expected:
        raise ValueError("B1V3_B2_PARTITION_SCOPE_INVALID")
    return index


def _write_parquet_if_identical(frame: pl.DataFrame, destination: Path) -> str:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if not pl.read_parquet(destination).equals(frame, null_equal=True):
            raise ValueError(f"B1V3_B2_OUTPUT_CONFLICT:{destination.name}")
        return sha256_file(destination)
    descriptor, name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".part", dir=destination.parent
    )
    os.close(descriptor)
    temporary = Path(name)
    try:
        frame.write_parquet(temporary, compression="zstd", statistics=True)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return sha256_file(destination)


def _write_json_if_identical(destination: Path, document: Mapping[str, Any]) -> str:
    payload = (json.dumps(document, indent=2, sort_keys=True, ensure_ascii=True) + "\n").encode()
    lowered = payload.lower()
    if any(token in lowered for token in _FORBIDDEN_TOKENS):
        raise ValueError("B1V3_B2_MANIFEST_HYGIENE_INVALID")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if destination.read_bytes() != payload:
            raise ValueError(f"B1V3_B2_OUTPUT_CONFLICT:{destination.name}")
    else:
        descriptor, name = tempfile.mkstemp(
            prefix=f".{destination.name}.", suffix=".part", dir=destination.parent
        )
        os.close(descriptor)
        temporary = Path(name)
        try:
            temporary.write_bytes(payload)
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
    return sha256_file(destination)


def _load_event_partition(
    path: Path,
    *,
    asset: str,
    session_date: str,
    expected_hash: str,
) -> pl.DataFrame:
    if sha256_file(path) != expected_hash:
        raise ValueError("B1V3_B2_PARTITION_HASH_MISMATCH")
    frame = pl.read_parquet(path, columns=list(_EVENT_COLUMNS)).with_columns(
        pl.lit(session_date).alias("session_date")
    )
    symbols = set(str(value) for value in frame["underlying_symbol"].unique().to_list())
    if frame.is_empty() or symbols != {asset}:
        raise ValueError("B1V3_B2_PARTITION_CONTENT_INVALID")
    return frame


def _build_raw_matrices(
    *,
    origins: pl.DataFrame,
    partition_index: Mapping[tuple[str, str], tuple[Path, str]],
    output_root: Path,
    sessions: Sequence[str],
) -> Mapping[str, Sequence[Path]]:
    outputs: dict[str, list[Path]] = {variant: [] for variant in B2_CONFIRMATION_VARIANTS}
    for day in sessions:
        day_origins = origins.filter(pl.col("session_date") == day)
        variant_parts: dict[str, list[pl.DataFrame]] = {
            variant: [] for variant in B2_CONFIRMATION_VARIANTS
        }
        for asset in B1V3_CANONICAL_ASSETS:
            asset_origins = day_origins.filter(pl.col("asset") == asset)
            path, expected_hash = partition_index[(day, asset)]
            trades = _load_event_partition(
                path,
                asset=asset,
                session_date=day,
                expected_hash=expected_hash,
            )
            for variant, delay_seconds in B2_CONFIRMATION_VARIANTS.items():
                activity = aggregate_b2_activity(
                    trades,
                    asset_origins,
                    window_minutes=5,
                    delay_seconds=delay_seconds,
                )
                feature_frame = add_compact_b2_features(activity)
                if feature_frame.filter(
                    pl.col("b2v2_max_created_at_utc").is_not_null()
                    & (pl.col("b2v2_max_created_at_utc") > pl.col("b2v2_cutoff_utc"))
                ).height:
                    raise ValueError("B1V3_B2_FUTURE_CREATED_AT")
                variant_parts[variant].append(feature_frame)
        for variant, parts in variant_parts.items():
            matrix = pl.concat(parts, how="vertical_relaxed").sort(
                "session_date", "forecast_origin_utc", "asset"
            )
            if (
                matrix.height != day_origins.height
                or matrix["origin_id"].n_unique() != matrix.height
            ):
                raise ValueError("B1V3_B2_RAW_ORIGIN_PRESERVATION_FAILURE")
            destination = output_root / variant / f"date={day}.parquet"
            _write_parquet_if_identical(matrix, destination)
            outputs[variant].append(destination)
    return outputs


def _write_json_records(path: Path, records: Sequence[Mapping[str, Any]]) -> str:
    document: dict[str, Any] = {"records": list(records)}
    document["records_sha256"] = canonical_sha256(document)
    return _write_json_if_identical(path, document)


def _combine_variant(
    paths: Sequence[Path],
    *,
    sidecar: pl.DataFrame,
    variant: str,
    destination: Path,
) -> tuple[pl.DataFrame, str]:
    parts = [
        apply_b2_availability_sidecar(
            pl.read_parquet(path),
            sidecar,
            canonical_variant=variant,
        )
        for path in paths
    ]
    frame = pl.concat(parts, how="vertical_relaxed").sort(
        "session_date", "forecast_origin_utc", "asset"
    )
    return frame, _write_parquet_if_identical(frame, destination)


def build_b2_confirmation_artifacts(
    *,
    frozen_inputs: FrozenBuildInputs,
    full_tape_contract: FullTapeContract,
    base_manifest_path: Path,
    origins_path: Path,
    data_root: Path,
    event_root: Path,
    output_root: Path,
    manifest_path: Path,
    manifest_schema_path: Path,
) -> B2ConfirmationArtifacts:
    """Build and seal three B2 timing variants plus the corrected PIT sidecar.

    Parameters
    ----------
    frozen_inputs:
        Provider-passed target-blind 60/30 plan and source bindings.
    full_tape_contract:
        Completed, hash-verified Full Tape acquisition contract.
    base_manifest_path, origins_path:
        Immutable base-predictor manifest and its target-free origin projection.
    data_root, event_root:
        Restricted B1v3 storage roots for hash-bound partitions and event rows.
    output_root:
        Destination for raw timing variants, corrected predictors, and ledgers.
    manifest_path, manifest_schema_path:
        Sanitized manifest destination and its Draft 2020-12 contract.

    Returns
    -------
    B2ConfirmationArtifacts
        Principal predictor, sidecar, and manifest paths plus manifest file hash.

    Raises
    ------
    ValueError
        If any source binding, PIT invariant, origin identity, schema, or
        idempotent-output check fails.
    FileNotFoundError
        If a hash-bound Full Tape partition is absent.

    Notes
    -----
    This function never reads RV30, QLIKE, predictions, models, or holdout
    outcomes. ``created_at`` remains an operational-availability proxy rather
    than a provider-proven publication timestamp.
    """
    base = _json_object(base_manifest_path, code="B1V3_B2_BASE_MANIFEST_INVALID")
    base_hash = base.get("manifest_sha256")
    if not isinstance(base_hash, str) or base_hash != canonical_sha256(
        {key: value for key, value in base.items() if key != "manifest_sha256"}
    ):
        raise ValueError("B1V3_B2_BASE_MANIFEST_HASH_INVALID")
    if (
        base.get("status") != "PASS_TARGET_BLIND_BASE_PREDICTORS"
        or base.get("plan_sha256") != frozen_inputs.plan_sha256
        or base.get("outcome_read_count") != 0
        or base.get("safe_to_read_outcomes") is not False
    ):
        raise ValueError("B1V3_B2_BASE_GATE_INVALID")
    outputs = base.get("outputs")
    if not isinstance(outputs, dict):
        raise ValueError("B1V3_B2_BASE_GATE_INVALID")
    origin_output = outputs.get("origins")
    if (
        not isinstance(origin_output, dict)
        or not origins_path.is_file()
        or origin_output.get("sha256") != sha256_file(origins_path)
    ):
        raise ValueError("B1V3_B2_ORIGIN_BINDING_INVALID")
    origins = pl.read_parquet(origins_path)
    if origins.height != 38_664 or origins["origin_id"].n_unique() != origins.height:
        raise ValueError("B1V3_B2_ORIGIN_SCOPE_INVALID")
    partitions = _partition_index(full_tape_contract, data_root=data_root)
    raw_root = output_root / "b2_raw_canonical"
    raw_paths = _build_raw_matrices(
        origins=origins,
        partition_index=partitions,
        output_root=raw_root,
        sessions=frozen_inputs.all_sessions,
    )
    incidents = audit_uw_session_asset_incidents(
        event_root=event_root,
        session_dates=frozen_inputs.all_sessions,
        assets=B1V3_CANONICAL_ASSETS,
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
            raise ValueError("B1V3_B2_CORRECTED_ORIGIN_PRESERVATION_FAILURE")
        corrected[variant] = {
            "logical_path": f"MDS650_B1V3_DATA_ROOT/predictors/{destination.name}",
            "sha256": file_hash,
            "row_count": frame.height,
            "eligible_row_count": frame.filter(pl.col("b2v2_availability_eligible")).height,
            "excluded_row_count": frame.filter(~pl.col("b2v2_availability_eligible")).height,
        }
    document: dict[str, Any] = {
        "schema_version": "1.0",
        "status": "PASS_TARGET_BLIND_B2_PREDICTORS",
        "plan_sha256": frozen_inputs.plan_sha256,
        "base_manifest_sha256": base_hash,
        "full_tape_manifest_sha256": full_tape_contract.manifest_sha256,
        "target_blind": True,
        "outcome_read_count": 0,
        "safe_to_read_outcomes": False,
        "session_count": 90,
        "asset_count": len(B1V3_CANONICAL_ASSETS),
        "origin_count": origins.height,
        "feature_count": len(B2_FEATURE_NAMES),
        "features": list(B2_FEATURE_NAMES),
        "variants": corrected,
        "availability": availability_summary,
        "legacy_zero_coding_gate": legacy_gate,
        "sidecar": {
            "logical_path": "MDS650_B1V3_DATA_ROOT/predictors/b2_availability_sidecar.parquet",
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
    validate_confirmation_plan_schema(document, manifest_schema_path)
    manifest_file_hash = _write_json_if_identical(manifest_path, document)
    return B2ConfirmationArtifacts(
        primary_path=primary_path,
        sidecar_path=sidecar_path,
        manifest_path=manifest_path,
        manifest_file_sha256=manifest_file_hash,
    )
