"""Acquire two disjoint, metadata-authorized Unusual Whales confirmation blocks.

The script is intentionally limited to the two 30-session blocks frozen by
``new_blocks_availability_probe_v2.json``. It writes immutable ZIP archives and
filtered Parquet to ``D:/MDS650/b2_confirmation`` and maintains a self-hashed,
resumable manifest under ``artifacts/methodology``. It never reads outcomes or
starts model evaluation.
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from collections.abc import Mapping
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from mds650.phase5_storage import GIB, Phase5StorageConfig, sha256_file, storage_preflight
from mds650.study_design import canonical_sha256

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
PROBE = ROOT / "artifacts" / "api_audit" / "new_blocks_availability_probe_v2.json"
OUT = ROOT / "artifacts" / "methodology" / "b2_confirmation_acquisition_manifest_v1.json"
CHECKPOINT_ROOT = Path("D:/MDS650/b2_confirmation/manifests/full_tape")
DATA_ROOT = Path("D:/MDS650/b2_confirmation")
MINIMUM_FREE_BYTES = 80 * GIB
PROJECTED_PEAK_BYTES = 140 * GIB
DOWNLOADER: Any = importlib.import_module("download_calibration_20d")


def _json(path: Path) -> dict[str, Any]:
    """Load one JSON object and reject non-object payloads."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"JSON_OBJECT_REQUIRED:{path.name}")
    return payload


def _block_dates(probe: Mapping[str, Any]) -> dict[str, tuple[date, ...]]:
    """Return the exact two disjoint 30-session allow-lists from the probe."""
    if probe.get("status") != "METADATA_ONLY_NO_FULL_TAPE_DOWNLOAD":
        raise RuntimeError("B2_CONFIRMATION_AVAILABILITY_STATUS_INVALID")
    if probe.get("full_tape_downloaded") is not False or probe.get("pit_claim") is not False:
        raise RuntimeError("B2_CONFIRMATION_PROBE_MUST_REMAIN_METADATA_ONLY")
    blocks = probe.get("blocks")
    if not isinstance(blocks, Mapping) or set(blocks) != {
        "block_a_2024_08_02_2024_09_13",
        "block_b_2024_10_01_2024_11_11",
    }:
        raise RuntimeError("B2_CONFIRMATION_BLOCK_ALLOWLIST_INVALID")
    result: dict[str, tuple[date, ...]] = {}
    for block_id, values in blocks.items():
        if not isinstance(values, list):
            raise RuntimeError(f"B2_CONFIRMATION_DATES_INVALID:{block_id}")
        parsed = tuple(date.fromisoformat(str(value)) for value in values)
        if len(parsed) != 30 or tuple(sorted(set(parsed))) != parsed:
            raise RuntimeError(f"B2_CONFIRMATION_BLOCK_COUNT_OR_ORDER_INVALID:{block_id}")
        result[str(block_id)] = parsed
    all_dates = set(result[next(iter(result))])
    other_dates = set(result[next(reversed(result))])
    if all_dates & other_dates:
        raise RuntimeError("B2_CONFIRMATION_BLOCKS_OVERLAP")
    return result


def _validate_probe_records(probe: Mapping[str, Any], dates: set[date]) -> None:
    """Require every allow-listed date to have a successful UW metadata probe."""
    records = probe.get("records")
    if not isinstance(records, list) or len(records) != 60:
        raise RuntimeError("B2_CONFIRMATION_PROBE_RECORD_COUNT_INVALID")
    seen: set[date] = set()
    for record in records:
        if not isinstance(record, Mapping):
            raise RuntimeError("B2_CONFIRMATION_PROBE_RECORD_INVALID")
        day = date.fromisoformat(str(record.get("date")))
        if day in seen or day not in dates:
            raise RuntimeError(f"B2_CONFIRMATION_PROBE_DATE_INVALID:{day}")
        seen.add(day)
        uw = record.get("uw")
        if not isinstance(uw, Mapping) or uw.get("http_status") != 206:
            raise RuntimeError(f"B2_CONFIRMATION_UW_METADATA_INVALID:{day}")
        if uw.get("content_range_present") is not True or int(uw.get("bytes_total", 0)) <= 0:
            raise RuntimeError(f"B2_CONFIRMATION_UW_RANGE_INVALID:{day}")
        if uw.get("full_tape_downloaded") is not False or uw.get("pit_claim") is not False:
            raise RuntimeError(f"B2_CONFIRMATION_UW_METADATA_SCOPE_INVALID:{day}")


def _checkpoint_valid(record: Mapping[str, Any], config: Phase5StorageConfig) -> bool:
    """Verify a completed date and all hashed Parquet partitions."""
    if record.get("status") != "PASS" or record.get("secret_values_emitted") is not False:
        return False
    day_text = str(record.get("session_date"))
    raw = config.raw_root / day_text / f"full_tape_{day_text}.zip"
    if not raw.is_file() or sha256_file(raw) != record.get("raw_sha256"):
        return False
    parquet_files = record.get("parquet_files")
    if not isinstance(parquet_files, list) or len(parquet_files) != 8:
        return False
    for item in parquet_files:
        if not isinstance(item, Mapping):
            return False
        path = config.data_root / str(item.get("relative_path", ""))
        if not path.is_file() or sha256_file(path) != item.get("sha256"):
            return False
    unsigned = {key: value for key, value in record.items() if key != "checkpoint_sha256"}
    return record.get("checkpoint_sha256") == canonical_sha256(unsigned)


def _parquet_files(day: date, config: Phase5StorageConfig) -> list[dict[str, Any]]:
    """Return the eight hashed asset partitions for one date."""
    rows: list[dict[str, Any]] = []
    for path in sorted(config.event_root.glob(f"date={day.isoformat()}/asset=*/events.parquet")):
        rows.append({
            "relative_path": path.relative_to(config.data_root).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        })
    if len(rows) != 8:
        raise RuntimeError(f"B2_CONFIRMATION_PARQUET_PARTITIONS_INVALID:{day}")
    return rows


def _write_manifest(
    records: list[dict[str, Any]],
    block_dates: Mapping[str, tuple[date, ...]],
    preflight: Mapping[str, Any],
) -> None:
    """Write a sanitized self-hashed resumable acquisition manifest."""
    expected = {day.isoformat() for values in block_dates.values() for day in values}
    present = {str(row["session_date"]) for row in records}
    if not present <= expected:
        raise RuntimeError("B2_CONFIRMATION_MANIFEST_OUT_OF_ALLOWLIST")
    payload: dict[str, Any] = {
        "schema_version": "b2-confirmation-acquisition-1.0",
        "status": "PASS" if present == expected else "IN_PROGRESS",
        "block_counts": {key: len(values) for key, values in block_dates.items()},
        "authorized_sessions": sorted(expected),
        "completed_count": len(records),
        "records": records,
        "raw_location": "MDS650_DATA_ROOT/b2_confirmation/raw/full_tape",
        "derived_location": "MDS650_DATA_ROOT/b2_confirmation/data/option_events",
        "storage_preflight": dict(preflight),
        "oos_read_count": 0,
        "target_outcome_read": False,
        "independent_samples_read": False,
        "secret_values_emitted": False,
        "personal_paths_emitted": False,
    }
    payload["manifest_sha256"] = canonical_sha256(payload)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    temporary = OUT.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(OUT)


def main() -> None:
    """Run or resume acquisition one immutable session at a time."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true", help="Validate allow-list and storage only."
    )
    args = parser.parse_args()
    probe = _json(PROBE)
    blocks = _block_dates(probe)
    all_dates = tuple(sorted(day for values in blocks.values() for day in values))
    _validate_probe_records(probe, set(all_dates))
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    config = Phase5StorageConfig(
        sessions=all_dates,
        excluded_dates=frozenset(),
        data_root=DATA_ROOT,
        minimum_free_bytes=MINIMUM_FREE_BYTES,
        projected_peak_additional_bytes=PROJECTED_PEAK_BYTES,
    )
    preflight = storage_preflight(config)
    if args.dry_run:
        print(
            json.dumps(
                {"status": "DRY_RUN_PASS", "sessions": len(all_dates), "storage": preflight}
            )
        )
        return
    expected_fields: set[str] | None = None
    existing: dict[str, dict[str, Any]] = {}
    if OUT.exists():
        prior = _json(OUT)
        unsigned = {key: value for key, value in prior.items() if key != "manifest_sha256"}
        if prior.get("manifest_sha256") != canonical_sha256(unsigned):
            raise RuntimeError("B2_CONFIRMATION_MANIFEST_HASH_INVALID")
        for row in prior.get("records", []):
            if isinstance(row, Mapping):
                existing[str(row.get("session_date"))] = dict(row)
                fields = row.get("schema_fields")
                if isinstance(fields, list):
                    expected_fields = {str(field) for field in fields}
    for checkpoint in sorted(CHECKPOINT_ROOT.glob("*.json")):
        candidate = _json(checkpoint)
        day_text = str(candidate.get("session_date"))
        if day_text not in {day.isoformat() for day in all_dates}:
            continue
        if _checkpoint_valid(candidate, config):
            existing[day_text] = candidate
            if expected_fields is None and isinstance(candidate.get("schema_fields"), list):
                expected_fields = {str(field) for field in candidate["schema_fields"]}
    _write_manifest(
        [existing[day.isoformat()] for day in all_dates if day.isoformat() in existing],
        blocks,
        preflight,
    )
    for day in all_dates:
        day_text = day.isoformat()
        if day_text in existing:
            continue
        storage_preflight(config)
        raw = config.raw_root / day_text / f"full_tape_{day_text}.zip"
        download: dict[str, Any]
        if raw.is_file():
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
            download = DOWNLOADER._stream_download(day, key, raw)
            download["reused_raw_archive"] = False
        filtered = DOWNLOADER.filter_session(day, raw, expected_fields, config)
        fields = {str(field) for field in filtered["schema_fields"]}
        if expected_fields is None:
            expected_fields = fields
        elif fields != expected_fields:
            raise RuntimeError(f"B2_CONFIRMATION_SCHEMA_DRIFT:{day_text}")
        block_id = next(key for key, values in blocks.items() if day in values)
        record: dict[str, Any] = {
            "status": "PASS",
            "block_id": block_id,
            "session_date": day_text,
            "completed_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "raw_sha256": str(download["sha256"]),
            "raw_bytes": int(download["bytes"]),
            "http_status": download.get("http_status"),
            "download_attempts": int(download.get("attempts", 0)),
            "download_seconds": float(download.get("download_seconds", 0.0)),
            "reused_raw_archive": bool(download["reused_raw_archive"]),
            "rows_seen": int(filtered["rows_seen"]),
            "rows_retained": int(filtered["rows_retained"]),
            "duplicate_event_ids": int(filtered.get("duplicate_event_ids", 0)),
            "parquet_bytes": int(filtered["parquet_bytes"]),
            "filter_seconds": float(filtered.get("filter_seconds", 0.0)),
            "schema_fields": filtered["schema_fields"],
            "schema_fingerprint": filtered.get("schema_fingerprint"),
            "parquet_files": _parquet_files(day, config),
            "secret_values_emitted": False,
            "personal_paths_emitted": False,
        }
        record["checkpoint_sha256"] = canonical_sha256(record)
        checkpoint = CHECKPOINT_ROOT / f"{day_text}.json"
        checkpoint.parent.mkdir(parents=True, exist_ok=True)
        temporary = checkpoint.with_suffix(".tmp")
        temporary.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temporary.replace(checkpoint)
        existing[day_text] = record
        _write_manifest(
            [existing[item.isoformat()] for item in all_dates if item.isoformat() in existing],
            blocks,
            preflight,
        )
        print(
            json.dumps(
                {"session_date": day_text, "completed": len(existing), "total": len(all_dates)}
            ),
            flush=True,
        )


if __name__ == "__main__":
    main()
