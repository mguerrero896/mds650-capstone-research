"""Copy retained Phase 5 evidence to the Samsung SSD without deleting sources."""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import date
from pathlib import Path
from typing import Any

from mds650.phase5_storage import (
    GIB,
    build_phase5_storage_config,
    copy_verified_file,
    sha256_file,
    storage_preflight,
)
from mds650.study_design import canonical_sha256, freeze_json

ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = Path("D:/MDS650")
PHASE5 = ROOT / "artifacts" / "phase5"
SESSION_MANIFEST = PHASE5 / "study_sessions_90.json"
REUSED_MANIFEST = PHASE5 / "reused_25_session_manifest.json"
MIGRATION_MANIFEST = PHASE5 / "storage_migration_manifest.json"
PROJECTED_PENDING_PEAK_BYTES = 150 * GIB


def _relative(path: Path, base: Path) -> str:
    return path.resolve().relative_to(base.resolve()).as_posix()


def _self_hash(payload: dict[str, Any]) -> dict[str, Any]:
    payload["manifest_sha256"] = canonical_sha256(payload)
    return payload


def _raw_sources() -> list[dict[str, Any]]:
    calibration_path = ROOT / "artifacts" / "calibration_20d" / "download_manifest.json"
    pilot_path = ROOT / "artifacts" / "pilot" / "pilot_manifest.json"
    calibration = json.loads(calibration_path.read_text(encoding="utf-8"))
    pilot = json.loads(pilot_path.read_text(encoding="utf-8"))
    records: list[dict[str, Any]] = []
    for row in calibration["sessions"]:
        day = str(row["session_date"])
        records.append(
            {
                "session_date": day,
                "source": ROOT / str(row["raw_path"]),
                "sha256": str(row["sha256"]),
                "bytes": int(row["bytes"]),
                "source_manifest": calibration_path,
                "schema_fingerprint": row.get("schema_fingerprint"),
            }
        )
    for row in pilot["raw_full_tape"]:
        day = str(row["date"])
        records.append(
            {
                "session_date": day,
                "source": (
                    ROOT
                    / "artifacts"
                    / "raw"
                    / "full_tape"
                    / day
                    / f"full_tape_{day}.zip"
                ),
                "sha256": str(row["raw_sha256"]),
                "bytes": int(row["raw_bytes"]),
                "source_manifest": pilot_path,
                "schema_fingerprint": None,
            }
        )
    return sorted(records, key=lambda item: str(item["session_date"]))


def _copy_raw(records: list[dict[str, Any]]) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    for row in records:
        day = str(row["session_date"])
        source = Path(row["source"])
        destination = DATA_ROOT / "raw" / "full_tape" / day / f"full_tape_{day}.zip"
        if source.stat().st_size != row["bytes"]:
            raise RuntimeError(f"REUSABLE_RAW_SIZE_MISMATCH:{day}")
        copy_verified_file(source, destination, str(row["sha256"]))
        day_manifest = _self_hash(
            {
                "schema_version": "phase5-reused-full-tape-1.0",
                "status": "PASS",
                "session_date": day,
                "bytes": row["bytes"],
                "sha256": row["sha256"],
                "raw_path": _relative(destination, DATA_ROOT),
                "source_manifest": _relative(Path(row["source_manifest"]), ROOT),
                "source_manifest_sha256": sha256_file(Path(row["source_manifest"])),
                "schema_fingerprint": row["schema_fingerprint"],
                "source_preserved": True,
                "reused_for_phase5": True,
            }
        )
        freeze_json(
            DATA_ROOT / "manifests" / "full_tape" / f"{day}.json",
            day_manifest,
        )
        entries.append(
            {
                "session_date": day,
                "source": _relative(source, ROOT),
                "destination": _relative(destination, DATA_ROOT),
                "bytes": row["bytes"],
                "sha256": row["sha256"],
                "source_manifest": _relative(Path(row["source_manifest"]), ROOT),
                "destination_verified": True,
            }
        )
    hashes = [str(row["sha256"]) for row in entries]
    if len(entries) != 25 or len(set(hashes)) != 25:
        raise RuntimeError("REUSED_25_RAW_SET_INVALID")
    return _self_hash(
        {
            "schema_version": "phase5-reused-25-sessions-1.0",
            "status": "PASS",
            "session_count": len(entries),
            "sessions": [str(row["session_date"]) for row in entries],
            "entries": entries,
            "all_source_hashes_match": True,
            "all_destination_hashes_match": True,
            "unique_raw_hashes": True,
            "source_preserved": True,
            "files_deleted": 0,
            "personal_paths_emitted": False,
            "secret_values_emitted": False,
        }
    )


def _copy_category(
    *,
    name: str,
    sources: Iterable[tuple[Path, Path]],
) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    for source, destination in sorted(sources, key=lambda item: item[0].as_posix()):
        digest = sha256_file(source)
        copy_verified_file(source, destination, digest)
        entries.append(
            {
                "source": _relative(source, ROOT),
                "destination": _relative(destination, DATA_ROOT),
                "bytes": source.stat().st_size,
                "sha256": digest,
                "verified": True,
            }
        )
    index = _self_hash(
        {
            "schema_version": "phase5-storage-category-1.0",
            "status": "PASS",
            "category": name,
            "file_count": len(entries),
            "bytes": sum(int(row["bytes"]) for row in entries),
            "files": entries,
            "source_preserved": True,
            "files_deleted": 0,
        }
    )
    index_path = DATA_ROOT / "manifests" / "migration" / f"{name}.json"
    freeze_json(index_path, index)
    return {
        "category": name,
        "file_count": index["file_count"],
        "bytes": index["bytes"],
        "index": _relative(index_path, DATA_ROOT),
        "index_file_sha256": sha256_file(index_path),
        "bundle_sha256": index["manifest_sha256"],
    }


def _tree_sources(source_root: Path, destination_root: Path) -> list[tuple[Path, Path]]:
    return [
        (source, destination_root / source.relative_to(source_root))
        for source in source_root.rglob("*")
        if source.is_file()
    ]


def main() -> int:
    """Prepare D:, verify 25 immutable ZIPs, and copy reusable derivatives."""
    session_manifest = json.loads(SESSION_MANIFEST.read_text(encoding="utf-8"))
    raw_records = _raw_sources()
    reused_dates = frozenset(date.fromisoformat(str(row["session_date"])) for row in raw_records)
    config = build_phase5_storage_config(
        session_manifest,
        reused_dates=reused_dates,
        data_root=DATA_ROOT,
        projected_peak_additional_bytes=PROJECTED_PENDING_PEAK_BYTES,
    )
    preflight = storage_preflight(config)
    for path in (
        config.raw_root,
        config.event_root,
        config.manifest_root,
        config.temporary_root,
        DATA_ROOT / "cache" / "massive",
        DATA_ROOT / "data" / "fmp",
        DATA_ROOT / "logs",
    ):
        path.mkdir(parents=True, exist_ok=True)

    reused_manifest = _copy_raw(raw_records)
    freeze_json(REUSED_MANIFEST, reused_manifest)
    categories = [
        _copy_category(
            name="calibration_option_events",
            sources=_tree_sources(
                ROOT / "artifacts" / "calibration_20d" / "option_events",
                config.event_root,
            ),
        ),
        _copy_category(
            name="pilot_option_events",
            sources=_tree_sources(
                ROOT / "artifacts" / "pilot" / "option_events",
                config.event_root,
            ),
        ),
        _copy_category(
            name="calibration_massive_cache",
            sources=_tree_sources(
                ROOT / "artifacts" / "calibration_20d" / "massive_b1q_cache_v2",
                DATA_ROOT / "cache" / "massive" / "calibration_20d",
            ),
        ),
        _copy_category(
            name="pilot_massive_cache",
            sources=_tree_sources(
                ROOT / "artifacts" / "b1_full_origin" / "massive_contract_day_cache",
                DATA_ROOT / "cache" / "massive" / "pilot_v2",
            ),
        ),
        _copy_category(
            name="retained_fmp",
            sources=[
                (
                    ROOT / "artifacts" / "calibration_20d" / "underlying_1min_20d.parquet",
                    DATA_ROOT / "data" / "fmp" / "underlying_1min_calibration_20d.parquet",
                ),
                (
                    ROOT / "artifacts" / "pilot" / "underlying_1min.parquet",
                    DATA_ROOT / "data" / "fmp" / "underlying_1min_pilot_5d.parquet",
                ),
            ],
        ),
    ]
    migration = _self_hash(
        {
            "schema_version": "phase5-storage-migration-1.0",
            "status": "PASS",
            "data_root": "MDS650_DATA_ROOT",
            "reused_session_count": 25,
            "pending_session_count": len(config.sessions),
            "minimum_free_bytes": config.minimum_free_bytes,
            "projected_pending_peak_bytes": config.projected_peak_additional_bytes,
            "categories": categories,
            "source_preserved": True,
            "files_deleted": 0,
            "personal_paths_emitted": False,
            "secret_values_emitted": False,
        }
    )
    freeze_json(MIGRATION_MANIFEST, migration)
    print(
        json.dumps(
            {
                "status": "PASS",
                "reused_sessions": 25,
                "pending_sessions": len(config.sessions),
                "copied_categories": len(categories),
                "projected_minimum_free_bytes": preflight["projected_minimum_free_bytes"],
                "source_files_deleted": 0,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
