"""Acquire the frozen Phase 6 Full Tape sessions with resumable hash checks."""

from __future__ import annotations

import argparse
import importlib
import json
from collections.abc import Mapping
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from mds650.phase5_storage import (
    GIB,
    Phase5StorageConfig,
    sha256_file,
    storage_preflight,
)
from mds650.phase6 import phase6_sessions
from mds650.study_design import canonical_sha256

ROOT = Path(__file__).resolve().parents[1]
PREREGISTRATION = ROOT / "artifacts" / "phase6" / "preregistration.json"
CONTINUITY = ROOT / "artifacts" / "phase6" / "continuity_probe.json"
STORAGE = ROOT / "artifacts" / "phase6" / "storage_preflight.json"
OUT = ROOT / "artifacts" / "phase6" / "acquisition_manifest.json"
CHECKPOINT_ROOT = ROOT / "artifacts" / "phase6" / "acquisition_checkpoints"
DATA_ROOT = Path("D:/MDS650/phase6")
PROJECTED_PEAK_BYTES = 376 * GIB

downloader: Any = importlib.import_module("download_calibration_20d")


def _load_json(path: Path) -> dict[str, Any]:
    """Load one required JSON object."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"JSON_OBJECT_REQUIRED:{path.name}")
    return payload


def _valid_self_hash(payload: Mapping[str, object], field: str) -> bool:
    """Return whether one canonical self-hash matches."""
    expected = payload.get(field)
    unsigned = {key: value for key, value in payload.items() if key != field}
    return isinstance(expected, str) and expected == canonical_sha256(unsigned)


def _session_contract(session_date: str, preregistration_sha256: str) -> str:
    """Hash one date against the frozen preregistration."""
    return canonical_sha256(
        {
            "session_date": session_date,
            "preregistration_sha256": preregistration_sha256,
        }
    )


def _record_valid(record: Mapping[str, object], preregistration_sha256: str) -> bool:
    """Validate a completed session record without reading data files."""
    session_date = record.get("session_date")
    return bool(
        record.get("status") == "PASS"
        and isinstance(session_date, str)
        and record.get("preregistration_sha256") == preregistration_sha256
        and record.get("session_contract_sha256")
        == _session_contract(session_date, preregistration_sha256)
        and isinstance(record.get("raw_sha256"), str)
        and len(str(record["raw_sha256"])) == 64
        and record.get("secret_values_emitted") is False
        and record.get("personal_paths_emitted") is False
        and _valid_self_hash(record, "checkpoint_sha256")
    )


def pending_sessions(
    preregistration: Mapping[str, object], manifest: Mapping[str, object]
) -> list[str]:
    """Return dates lacking a valid checkpoint for the frozen contract."""
    if not _valid_self_hash(preregistration, "manifest_sha256"):
        raise RuntimeError("PHASE6_PREREGISTRATION_HASH_MISMATCH")
    rows = preregistration.get("sessions")
    records = manifest.get("sessions", [])
    if not isinstance(rows, list) or not isinstance(records, list):
        raise RuntimeError("PHASE6_ACQUISITION_MANIFEST_INVALID")
    expected = [
        str(row["session_date"])
        for row in rows
        if isinstance(row, dict) and isinstance(row.get("session_date"), str)
    ]
    by_date: dict[str, Mapping[str, object]] = {}
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("session_date"), str):
            continue
        session_date = str(record["session_date"])
        if session_date in by_date:
            raise RuntimeError("PHASE6_ACQUISITION_DUPLICATE")
        by_date[session_date] = record
    preregistration_sha256 = str(preregistration["manifest_sha256"])
    return [
        session_date
        for session_date in expected
        if not _record_valid(by_date.get(session_date, {}), preregistration_sha256)
    ]


def _checkpoint_path(session_date: str) -> Path:
    """Return the repository checkpoint path for one session."""
    return CHECKPOINT_ROOT / f"{session_date}.json"


def _verify_checkpoint_files(record: Mapping[str, object], config: Phase5StorageConfig) -> None:
    """Fail if any retained raw or Parquet hash differs."""
    session_date = str(record["session_date"])
    raw_path = config.raw_root / session_date / f"full_tape_{session_date}.zip"
    if not raw_path.is_file() or sha256_file(raw_path) != record.get("raw_sha256"):
        raise RuntimeError(f"PHASE6_RAW_HASH_MISMATCH:{session_date}")
    parquet_files = record.get("parquet_files")
    if not isinstance(parquet_files, list) or not parquet_files:
        raise RuntimeError(f"PHASE6_PARQUET_MANIFEST_INVALID:{session_date}")
    for item in parquet_files:
        if not isinstance(item, dict):
            raise RuntimeError(f"PHASE6_PARQUET_MANIFEST_INVALID:{session_date}")
        relative = item.get("relative_path")
        expected = item.get("sha256")
        if not isinstance(relative, str) or not isinstance(expected, str):
            raise RuntimeError(f"PHASE6_PARQUET_MANIFEST_INVALID:{session_date}")
        path = config.data_root / Path(relative)
        try:
            path.resolve().relative_to(config.data_root.resolve())
        except ValueError as error:
            raise RuntimeError("PHASE6_PARQUET_PATH_ESCAPE") from error
        if not path.is_file() or sha256_file(path) != expected:
            raise RuntimeError(f"PHASE6_PARQUET_HASH_MISMATCH:{session_date}")


def _expected_schema_fields() -> set[str] | None:
    """Reuse the first verified Phase 6 schema as the batch contract."""
    for path in sorted(CHECKPOINT_ROOT.glob("*.json")):
        record = _load_json(path)
        fields = record.get("schema_fields")
        if record.get("status") == "PASS" and isinstance(fields, list):
            return {str(field) for field in fields}
    return None


def _parquet_manifest(day: date, config: Phase5StorageConfig) -> list[dict[str, object]]:
    """Hash the derived per-asset partitions for one session."""
    rows: list[dict[str, object]] = []
    for path in sorted(config.event_root.glob(f"date={day.isoformat()}/asset=*/events.parquet")):
        rows.append(
            {
                "relative_path": path.relative_to(config.data_root).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    if not rows:
        raise RuntimeError(f"PHASE6_PARQUET_OUTPUT_MISSING:{day}")
    return rows


def acquire_session(session_date: str, config: Phase5StorageConfig) -> dict[str, object]:
    """Acquire or hash-verify one authorized Full Tape session."""
    day = date.fromisoformat(session_date)
    if day not in config.sessions:
        raise ValueError("PHASE6_SESSION_NOT_AUTHORIZED")
    preregistration = _load_json(PREREGISTRATION)
    if not _valid_self_hash(preregistration, "manifest_sha256"):
        raise RuntimeError("PHASE6_PREREGISTRATION_HASH_MISMATCH")
    preregistration_sha256 = str(preregistration["manifest_sha256"])
    checkpoint_path = _checkpoint_path(session_date)
    if checkpoint_path.exists():
        existing = _load_json(checkpoint_path)
        if not _record_valid(existing, preregistration_sha256):
            raise RuntimeError(f"PHASE6_CHECKPOINT_HASH_MISMATCH:{session_date}")
        _verify_checkpoint_files(existing, config)
        return {**existing, "reused_existing": True}

    storage_preflight(config)
    raw_path = config.raw_root / session_date / f"full_tape_{session_date}.zip"
    if raw_path.exists():
        raw_sha256 = sha256_file(raw_path)
        download: dict[str, object] = {
            "http_status": None,
            "attempts": 0,
            "download_seconds": 0.0,
            "bytes": raw_path.stat().st_size,
            "sha256": raw_sha256,
            "endpoint": "/api/option-trades/full-tape/{date}",
            "request_id": None,
            "reused_raw_archive": True,
        }
    else:
        key = downloader._secret("UNUSUALWHALES_API_KEY")
        download = downloader._stream_download(day, key, raw_path)
        raw_sha256 = str(download["sha256"])
        download["endpoint"] = "/api/option-trades/full-tape/{date}"
        download["reused_raw_archive"] = False

    filtered = downloader.filter_session(day, raw_path, _expected_schema_fields(), config)
    record: dict[str, object] = {
        "status": "PASS",
        "session_date": session_date,
        "completed_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "preregistration_sha256": preregistration_sha256,
        "session_contract_sha256": _session_contract(session_date, preregistration_sha256),
        "raw_sha256": raw_sha256,
        "raw_bytes": int(str(download["bytes"])),
        "http_status": download.get("http_status"),
        "request_id": download.get("request_id"),
        "request_endpoint": download["endpoint"],
        "download_attempts": int(str(download["attempts"])),
        "download_seconds": float(str(download["download_seconds"])),
        "reused_raw_archive": bool(download["reused_raw_archive"]),
        "schema_fields": filtered["schema_fields"],
        "schema_fingerprint": filtered.get("schema_fingerprint"),
        "rows_seen": int(filtered["rows_seen"]),
        "rows_retained": int(filtered["rows_retained"]),
        "duplicate_event_ids": int(filtered.get("duplicate_event_ids", 0)),
        "parquet_bytes": int(filtered["parquet_bytes"]),
        "filter_seconds": float(filtered.get("filter_seconds", 0.0)),
        "parquet_files": _parquet_manifest(day, config),
        "raw_location": "MDS650_DATA_ROOT/phase6/raw/full_tape",
        "derived_location": "MDS650_DATA_ROOT/phase6/data/option_events",
        "secret_values_emitted": False,
        "personal_paths_emitted": False,
    }
    record["checkpoint_sha256"] = canonical_sha256(record)
    downloader._atomic_json(checkpoint_path, record)
    return {**record, "reused_existing": False}


def _checkpoint_records() -> list[dict[str, Any]]:
    """Load completed checkpoints in frozen session order."""
    rows: list[dict[str, Any]] = []
    for row in phase6_sessions():
        path = _checkpoint_path(row["session_date"])
        if path.exists():
            rows.append(_load_json(path))
    return rows


def _write_manifest(preregistration: dict[str, Any]) -> dict[str, Any]:
    """Write the sanitized aggregate acquisition state atomically."""
    records = _checkpoint_records()
    pending = pending_sessions(preregistration, {"sessions": records})
    payload: dict[str, Any] = {
        "schema_version": "phase6-acquisition-manifest-1.0",
        "status": "PASS" if not pending else "IN_PROGRESS",
        "preregistration_sha256": preregistration["manifest_sha256"],
        "authorized_session_count": 180,
        "completed_session_count": len(records),
        "pending_session_count": len(pending),
        "pending_sessions": pending,
        "sessions": records,
        "raw_location": "MDS650_DATA_ROOT/phase6/raw/full_tape",
        "derived_location": "MDS650_DATA_ROOT/phase6/data/option_events",
        "full_backfill": False,
        "analytical_outcomes_read": False,
        "secret_values_emitted": False,
        "personal_paths_emitted": False,
    }
    payload["manifest_sha256"] = canonical_sha256(payload)
    downloader._atomic_json(OUT, payload)
    return payload


def _assert_prerequisites() -> dict[str, Any]:
    """Fail before network access unless all Phase 6 release gates pass."""
    preregistration = _load_json(PREREGISTRATION)
    continuity = _load_json(CONTINUITY)
    storage = _load_json(STORAGE)
    if not _valid_self_hash(preregistration, "manifest_sha256"):
        raise RuntimeError("PHASE6_PREREGISTRATION_HASH_MISMATCH")
    if preregistration.get("oos_read_count") != 0:
        raise RuntimeError("PHASE6_OOS_ALREADY_READ")
    if continuity.get("status") != "PASS_PHASE6_CONTINUITY":
        raise RuntimeError("PROVIDER_CONTINUITY_FAILURE")
    if storage.get("status") != "PASS_PHASE6_STORAGE":
        raise RuntimeError("STORAGE_FLOOR_BREACH")
    return preregistration


def run() -> dict[str, object]:
    """Resume the exact 180-session acquisition until PASS or a named blocker."""
    preregistration = _assert_prerequisites()
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    dates = tuple(date.fromisoformat(row["session_date"]) for row in phase6_sessions())
    config = Phase5StorageConfig(
        sessions=dates,
        excluded_dates=frozenset(),
        data_root=DATA_ROOT,
        minimum_free_bytes=80 * GIB,
        projected_peak_additional_bytes=PROJECTED_PEAK_BYTES,
    )
    current = _write_manifest(preregistration)
    pending = list(current["pending_sessions"])
    for index, session_date in enumerate(pending, start=1):
        record = acquire_session(session_date, config)
        current = _write_manifest(preregistration)
        print(
            json.dumps(
                {
                    "status": current["status"],
                    "session_date": session_date,
                    "completed": current["completed_session_count"],
                    "authorized": 180,
                    "reused_existing": record["reused_existing"],
                    "remaining_in_invocation": len(pending) - index,
                    "secret_values_emitted": False,
                }
            ),
            flush=True,
        )
    return {
        "status": current["status"],
        "completed_session_count": current["completed_session_count"],
        "pending_session_count": current["pending_session_count"],
        "secret_values_emitted": False,
    }


def main() -> int:
    """Parse the explicit resume flag and execute the acquisition."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resume", action="store_true", required=True)
    parser.parse_args()
    result = run()
    print(json.dumps(result, sort_keys=True))
    return int(result["status"] != "PASS")


if __name__ == "__main__":
    raise SystemExit(main())
