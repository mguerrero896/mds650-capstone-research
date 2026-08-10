"""Acquire the causal warm-up and independent 30-session Full Tape block."""

from __future__ import annotations

import importlib
import json
from collections.abc import Mapping
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from mds650.phase5_storage import GIB, Phase5StorageConfig, sha256_file, storage_preflight
from mds650.study_design import canonical_sha256

ROOT = Path(__file__).resolve().parents[1]
WINDOW = ROOT / "artifacts" / "independent_replication" / "window_manifest.json"
METHOD_FREEZE = ROOT / "artifacts" / "independent_replication" / "method_freeze.json"
STORAGE_PREFLIGHT = ROOT / "artifacts" / "independent_replication" / "storage_preflight.json"
OUT = ROOT / "artifacts" / "independent_replication" / "acquisition_manifest.json"
INCIDENT_ROOT = ROOT / "artifacts" / "independent_replication" / "acquisition_incidents"
DATA_ROOT = Path("D:/MDS650/independent_replication_30")
CHECKPOINT_ROOT = DATA_ROOT / "manifests" / "full_tape"
MINIMUM_FREE_BYTES = 80 * GIB
PROJECTED_PEAK_BYTES = 150 * GIB
DOWNLOADER: Any = importlib.import_module("download_calibration_20d")


def _required_int(value: Any, field: str) -> int:
    """Return a numeric manifest field or fail closed."""
    if isinstance(value, bool):
        raise RuntimeError(f"ACQUISITION_FIELD_INVALID:{field}")
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        return int(value)
    raise RuntimeError(f"ACQUISITION_FIELD_INVALID:{field}")


def _required_float(value: Any, field: str) -> float:
    """Return a numeric manifest field or fail closed."""
    if isinstance(value, bool):
        raise RuntimeError(f"ACQUISITION_FIELD_INVALID:{field}")
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        return float(value)
    raise RuntimeError(f"ACQUISITION_FIELD_INVALID:{field}")


def _json(path: Path) -> dict[str, Any]:
    """Load one JSON object."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"JSON_OBJECT_REQUIRED:{path.name}")
    return payload


def _raise_if_provider_archive_blocked(
    session_date: str, incident_root: Path = INCIDENT_ROOT
) -> None:
    """Prevent automatic re-downloads of a stable corrupt provider archive.

    Parameters
    ----------
    session_date:
        ISO session date being considered for acquisition.
    incident_root:
        Directory containing sanitized provider incident manifests.

    Raises
    ------
    RuntimeError
        If a prior stable CRC failure is recorded for this date.
    """
    incident_path = incident_root / f"{session_date}_crc_failure.json"
    if not incident_path.is_file():
        return
    incident = _json(incident_path)
    if (
        incident.get("status") == "BLOCKED_PROVIDER_ARCHIVE_CORRUPT"
        and incident.get("provider_artifact_stable_across_retries") is True
    ):
        raise RuntimeError(f"REPLICATION_PROVIDER_ARCHIVE_BLOCKED:{session_date}")


def _checkpoint_valid(record: Mapping[str, Any], config: Phase5StorageConfig) -> bool:
    """Verify one checkpoint and all immutable output hashes."""
    if record.get("status") != "PASS" or record.get("secret_values_emitted") is not False:
        return False
    session_date = str(record.get("session_date"))
    raw = config.raw_root / session_date / f"full_tape_{session_date}.zip"
    if not raw.is_file() or sha256_file(raw) != record.get("raw_sha256"):
        return False
    parquet_files = record.get("parquet_files")
    if not isinstance(parquet_files, list) or not parquet_files:
        return False
    for item in parquet_files:
        if not isinstance(item, dict):
            return False
        path = config.data_root / str(item.get("relative_path", ""))
        if not path.is_file() or sha256_file(path) != item.get("sha256"):
            return False
    unsigned = {key: value for key, value in record.items() if key != "checkpoint_sha256"}
    return record.get("checkpoint_sha256") == canonical_sha256(unsigned)


def _parquet_files(day: date, config: Phase5StorageConfig) -> list[dict[str, Any]]:
    """Return hashed Parquet partitions for one completed day."""
    rows: list[dict[str, Any]] = []
    pattern = f"date={day.isoformat()}/asset=*/events.parquet"
    for path in sorted(config.event_root.glob(pattern)):
        rows.append(
            {
                "relative_path": path.relative_to(config.data_root).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    if len(rows) != 8:
        raise RuntimeError(f"REPLICATION_PARQUET_PARTITIONS_INVALID:{day}")
    return rows


def _write_manifest(
    records: list[dict[str, Any]],
    window: Mapping[str, Any],
    method_freeze: Mapping[str, Any],
) -> None:
    """Write the sanitized resumable acquisition manifest."""
    payload: dict[str, Any] = {
        "schema_version": "b2-independent-replication-acquisition-1.0",
        "status": (
            "IN_PROGRESS"
            if len(records) < int(window["warmup_count"]) + int(window["target_count"])
            else "PASS"
        ),
        "warmup_count": window["warmup_count"],
        "target_count": window["target_count"],
        "completed_count": len(records),
        "records": records,
        "raw_location": "MDS650_DATA_ROOT/independent_replication_30/raw/full_tape",
        "derived_location": "MDS650_DATA_ROOT/independent_replication_30/data/option_events",
        "window_manifest_sha256": window["manifest_sha256"],
        "method_freeze_sha256": method_freeze["manifest_sha256"],
        "secret_values_emitted": False,
        "personal_paths_emitted": False,
    }
    payload["manifest_sha256"] = canonical_sha256(payload)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    temporary = OUT.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(OUT)


def main() -> None:
    """Run or resume one-day-at-a-time acquisition with hash checkpoints."""
    window = _json(WINDOW)
    method_freeze = _json(METHOD_FREEZE)
    storage = _json(STORAGE_PREFLIGHT)
    if window.get("status") != "READY_FOR_BOUNDED_BODY_ACQUISITION":
        raise RuntimeError("REPLICATION_WINDOW_NOT_READY")
    if method_freeze.get("status") != "FROZEN_BEFORE_TARGET_OUTCOME_READ":
        raise RuntimeError("REPLICATION_METHOD_NOT_FROZEN")
    projected_peak = int(storage["projected_peak_additional_bytes"])
    if projected_peak <= 0 or storage.get("free_space_pass") is not True:
        raise RuntimeError("REPLICATION_STORAGE_PREFLIGHT_INVALID")
    dates = [date.fromisoformat(value) for value in window["all_dates"]]
    config = Phase5StorageConfig(
        sessions=tuple(dates),
        excluded_dates=frozenset(),
        data_root=DATA_ROOT,
        minimum_free_bytes=MINIMUM_FREE_BYTES,
        projected_peak_additional_bytes=max(PROJECTED_PEAK_BYTES, projected_peak),
    )
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    storage_preflight(config)
    expected_fields: set[str] | None = None
    existing: dict[str, dict[str, Any]] = {}
    if OUT.exists():
        prior = _json(OUT)
        for row in prior.get("records", []):
            if isinstance(row, dict) and isinstance(row.get("session_date"), str):
                existing[str(row["session_date"])] = row
    for session_date in dates:
        day_text = session_date.isoformat()
        _raise_if_provider_archive_blocked(day_text)
        checkpoint = CHECKPOINT_ROOT / f"{day_text}.json"
        if checkpoint.exists():
            candidate = _json(checkpoint)
            if _checkpoint_valid(candidate, config):
                existing[day_text] = candidate
                ordered = [
                    existing[item.isoformat()]
                    for item in dates
                    if item.isoformat() in existing
                ]
                _write_manifest(ordered, window, method_freeze)
                continue
            raise RuntimeError(f"REPLICATION_CHECKPOINT_INVALID:{day_text}")
        storage_preflight(config)
        raw = config.raw_root / day_text / f"full_tape_{day_text}.zip"
        if raw.exists():
            download = {
                "http_status": None,
                "attempts": 0,
                "download_seconds": 0.0,
                "bytes": raw.stat().st_size,
                "sha256": sha256_file(raw),
                "reused_raw_archive": True,
            }
        else:
            key = DOWNLOADER._secret("UNUSUALWHALES_API_KEY")
            download = DOWNLOADER._stream_download(session_date, key, raw)
            download["reused_raw_archive"] = False
        filtered = DOWNLOADER.filter_session(session_date, raw, expected_fields, config)
        if expected_fields is None:
            expected_fields = set(str(field) for field in filtered["schema_fields"])
        elif set(filtered["schema_fields"]) != expected_fields:
            raise RuntimeError(f"REPLICATION_SCHEMA_DRIFT:{day_text}")
        record: dict[str, Any] = {
            "status": "PASS",
            "session_date": day_text,
            "role": "warmup" if day_text in set(window["warmup_dates"]) else "target",
            "completed_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "raw_sha256": str(download["sha256"]),
            "raw_bytes": _required_int(download.get("bytes"), "bytes"),
            "http_status": download.get("http_status"),
            "download_attempts": _required_int(download.get("attempts"), "attempts"),
            "download_seconds": _required_float(
                download.get("download_seconds"), "download_seconds"
            ),
            "reused_raw_archive": bool(download["reused_raw_archive"]),
            "rows_seen": int(filtered["rows_seen"]),
            "rows_retained": int(filtered["rows_retained"]),
            "duplicate_event_ids": int(filtered.get("duplicate_event_ids", 0)),
            "parquet_bytes": int(filtered["parquet_bytes"]),
            "filter_seconds": float(filtered.get("filter_seconds", 0.0)),
            "schema_fields": filtered["schema_fields"],
            "schema_fingerprint": filtered.get("schema_fingerprint"),
            "parquet_files": _parquet_files(session_date, config),
            "secret_values_emitted": False,
            "personal_paths_emitted": False,
        }
        record["checkpoint_sha256"] = canonical_sha256(record)
        checkpoint.parent.mkdir(parents=True, exist_ok=True)
        checkpoint_part = checkpoint.with_suffix(checkpoint.suffix + ".part")
        checkpoint_part.write_text(
            json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        checkpoint_part.replace(checkpoint)
        existing[day_text] = record
        ordered = [existing[item.isoformat()] for item in dates if item.isoformat() in existing]
        _write_manifest(ordered, window, method_freeze)
        print(
            json.dumps(
                {
                    "session_date": day_text,
                    "completed": len(ordered),
                    "total": len(dates),
                    "secret_values_emitted": False,
                }
            )
        )
    _write_manifest([existing[item.isoformat()] for item in dates], window, method_freeze)


if __name__ == "__main__":
    main()
