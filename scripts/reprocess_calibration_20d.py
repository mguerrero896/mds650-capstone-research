"""Rebuild calibration Parquet partitions from already validated raw ZIPs.

This recovery utility is intentionally network-free.  It exists to repair derived
partitions after a local writer failure while preserving the immutable raw archive
and its SHA-256 hash.  It is bounded to the frozen twenty-session allow-list.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any

import download_calibration_20d as downloader

ROOT = downloader.ROOT
OUT = downloader.OUT
EVENT_ROOT = downloader.EVENT_ROOT


def _remove_day_partitions(day: date) -> int:
    """Remove only derived Parquet files for one authorized session."""
    day_root = (EVENT_ROOT / f"date={day.isoformat()}").resolve()
    event_root = EVENT_ROOT.resolve()
    if not day_root.is_relative_to(event_root):
        raise RuntimeError("CALIBRATION_PARTITION_PATH_ESCAPE")
    removed = 0
    if not day_root.exists():
        return removed
    for path in day_root.glob("asset=*/events.parquet"):
        if not path.resolve().is_relative_to(day_root):
            raise RuntimeError("CALIBRATION_PARTITION_PATH_ESCAPE")
        path.unlink()
        removed += 1
    return removed


def _record_for_session(day: date, old: dict[str, Any]) -> dict[str, Any]:
    """Rebuild one session from its immutable raw ZIP and return a checkpoint."""
    day_text = day.isoformat()
    zip_path = (OUT / "raw" / "full_tape" / day_text / f"full_tape_{day_text}.zip").resolve()
    raw_root = (OUT / "raw" / "full_tape").resolve()
    if not zip_path.is_relative_to(raw_root) or not zip_path.exists():
        raise RuntimeError(f"CALIBRATION_RAW_MISSING:{day_text}")
    raw_hash = downloader._sha256_file(zip_path)
    if raw_hash != old.get("sha256"):
        raise RuntimeError(f"CALIBRATION_RAW_HASH_MISMATCH:{day_text}")
    _remove_day_partitions(day)
    filtered = downloader.filter_session(day, zip_path, set(old["schema_fields"]))
    return {
        "status": "PASS",
        "http_status": old.get("http_status"),
        "attempts": old.get("attempts", 0),
        "download_seconds": old.get("download_seconds", 0.0),
        "download_time_observed": bool(old.get("download_time_observed", False)),
        "bytes": zip_path.stat().st_size,
        "sha256": raw_hash,
        "endpoint": old.get("endpoint"),
        "request_id": None,
        "reused_raw_archive": True,
        **filtered,
        "raw_path": zip_path.relative_to(ROOT).as_posix(),
        "schema_fields": sorted(filtered["schema_fields"]),
        "legacy_cache_status": "LEGACY_CACHE_READ_ONLY",
        "active_cache_status": "ACTIVE_CALIBRATION_CACHE_V2_ONLY",
        "reused_existing": True,
        "reprocessed_existing": True,
        "secret_values_emitted": False,
        "personal_paths_emitted": False,
    }


def main() -> None:
    """Repair every authorized derived partition without making network calls."""
    root_path = OUT / "download_manifest.json"
    root = json.loads(root_path.read_text(encoding="utf-8"))
    if root.get("status") != "PASS" or root.get("session_count") != len(downloader.SESSIONS):
        raise RuntimeError("CALIBRATION_DOWNLOAD_NOT_COMPLETE")
    expected = [day.isoformat() for day in downloader.SESSIONS]
    rows = list(root.get("sessions", []))
    if [str(row.get("session_date")) for row in rows] != expected:
        raise RuntimeError("CALIBRATION_SESSION_ORDER_OR_DUPLICATE_FAILURE")
    root["status"] = "IN_PROGRESS"
    root["reprocessing_existing"] = True
    downloader._atomic_json(root_path, root)
    repaired: list[dict[str, Any]] = []
    for index, day in enumerate(downloader.SESSIONS, start=1):
        old = rows[index - 1]
        record = _record_for_session(day, old)
        rows[index - 1] = record
        downloader._atomic_json(
            OUT / "manifests" / f"{day.isoformat()}.json", record
        )
        root["sessions"] = rows
        root["session_count"] = index
        downloader._atomic_json(root_path, root)
        repaired.append(record)
        print(
            json.dumps(
                {
                    "status": "IN_PROGRESS",
                    "session": day.isoformat(),
                    "completed": index,
                    "authorized": len(downloader.SESSIONS),
                    "working_set_bytes": record.get("python_peak_working_set_bytes"),
                    "secret_values_emitted": False,
                }
            ),
            flush=True,
        )
    root.update(
        {
            "status": "PASS",
            "sessions": repaired,
            "session_count": len(repaired),
            "authorized_session_count": len(downloader.SESSIONS),
            "network_calls_started": False,
            "secret_values_emitted": False,
            "personal_paths_emitted": False,
        }
    )
    downloader._atomic_json(root_path, root)
    print(
        json.dumps(
            {
                "status": "PASS",
                "sessions": len(repaired),
                "network_calls_started": False,
                "secret_values_emitted": False,
            }
        )
    )


if __name__ == "__main__":
    main()
