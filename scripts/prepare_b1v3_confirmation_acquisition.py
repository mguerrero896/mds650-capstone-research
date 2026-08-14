"""Prepare source-bound B1v3 storage and hardlink verified reusable evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from mds650.b1v3_confirmation import (
    canonical_sha256,
    provider_passed_sessions_from_report,
    write_json_if_identical,
)
from mds650.b1v3_confirmation_acquisition import (
    build_storage_projection,
    link_verified_file,
    reusable_records_from_manifest,
    sha256_file,
)
from mds650.b1v3_provider_preflight_v2 import validate_json_schema

GIB = 1024**3
MINIMUM_FREE_BYTES = 80 * GIB
ENGINEERING_MARGIN_BYTES = 5 * GIB
_MASSIVE_NAME_RE = re.compile(r"^[A-Z]+_(\d{4}-\d{2}-\d{2})_.*\.json$")


def _json_object(path: Path, *, code: str) -> dict[str, Any]:
    if not path.is_file():
        raise ValueError(code)
    decoded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(decoded, dict):
        raise ValueError(code)
    return decoded


def _plan_sessions(plan: Mapping[str, Any], report: Mapping[str, Any]) -> tuple[str, ...]:
    unsigned = {key: value for key, value in plan.items() if key != "plan_sha256"}
    if plan.get("plan_sha256") != canonical_sha256(unsigned):
        raise ValueError("B1V3_ACQUISITION_PLAN_HASH_INVALID")
    training = plan.get("training_sessions")
    confirmation = plan.get("confirmation_sessions")
    provider = plan.get("provider_preflight")
    if (
        plan.get("status") != "PASS_PRISTINE_60_30_FROZEN"
        or plan.get("target_blind") is not True
        or plan.get("safe_to_acquire") is not True
        or plan.get("safe_to_read_outcomes") is not False
        or plan.get("outcome_read_count") != 0
        or not isinstance(training, list)
        or not isinstance(confirmation, list)
        or len(training) != 60
        or len(confirmation) != 30
        or not isinstance(provider, Mapping)
        or provider.get("report_sha256") != report.get("report_sha256")
    ):
        raise ValueError("B1V3_ACQUISITION_PLAN_GATE_INVALID")
    values = tuple(str(value) for value in (*training, *confirmation))
    if values != provider_passed_sessions_from_report(report):
        raise ValueError("B1V3_ACQUISITION_PROVIDER_DATE_MISMATCH")
    return values


def _uw_content_lengths(report: Mapping[str, Any]) -> dict[str, int]:
    records = report.get("records")
    if not isinstance(records, Mapping):
        raise ValueError("B1V3_ACQUISITION_UW_METADATA_INVALID")
    values = records.get("unusual_whales")
    if not isinstance(values, list):
        raise ValueError("B1V3_ACQUISITION_UW_METADATA_INVALID")
    output: dict[str, int] = {}
    for row in values:
        if not isinstance(row, Mapping):
            raise ValueError("B1V3_ACQUISITION_UW_METADATA_INVALID")
        day, size = row.get("session_date"), row.get("content_length_bytes")
        if not isinstance(day, str) or not isinstance(size, int) or size <= 0 or day in output:
            raise ValueError("B1V3_ACQUISITION_UW_METADATA_INVALID")
        output[day] = size
    return output


def _massive_daily_files(
    cache_root: Path,
    reusable_sessions: Sequence[str],
) -> tuple[dict[str, list[Path]], tuple[int, ...]]:
    allowed = set(reusable_sessions)
    grouped: dict[str, list[Path]] = {day: [] for day in reusable_sessions}
    for path in cache_root.glob("*.json"):
        match = _MASSIVE_NAME_RE.fullmatch(path.name)
        if match and match.group(1) in allowed:
            grouped[match.group(1)].append(path)
    if any(not paths for paths in grouped.values()):
        raise ValueError("B1V3_ACQUISITION_MASSIVE_REUSE_DATE_MISSING")
    return grouped, tuple(
        sum(path.stat().st_size for path in grouped[day]) for day in reusable_sessions
    )


def _safe_relative_path(value: object) -> Path:
    if not isinstance(value, str):
        raise ValueError("B1V3_REUSE_PARQUET_PATH_INVALID")
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("B1V3_REUSE_PARQUET_PATH_INVALID")
    return path


def _link_full_tape_reuse(
    *,
    records: Mapping[str, Mapping[str, Any]],
    source_root: Path,
    destination_root: Path,
) -> tuple[list[dict[str, Any]], int, int]:
    summaries: list[dict[str, Any]] = []
    linked_files = 0
    logical_bytes = 0
    for day, record in records.items():
        raw_sha = str(record["raw_sha256"])
        raw_source = source_root / "raw" / "full_tape" / day / f"full_tape_{day}.zip"
        raw_destination = (
            destination_root / "raw" / "full_tape" / day / f"full_tape_{day}.zip"
        )
        link_verified_file(raw_source, raw_destination, raw_sha)
        linked_files += 1
        logical_bytes += int(record["raw_bytes"])
        parquet_files = record["parquet_files"]
        if not isinstance(parquet_files, list):
            raise ValueError("B1V3_REUSE_CHECKPOINT_INVALID")
        for item in parquet_files:
            if not isinstance(item, Mapping):
                raise ValueError("B1V3_REUSE_CHECKPOINT_INVALID")
            relative = _safe_relative_path(item.get("relative_path"))
            expected = item.get("sha256")
            size = item.get("bytes")
            if not isinstance(expected, str) or not isinstance(size, int):
                raise ValueError("B1V3_REUSE_CHECKPOINT_INVALID")
            link_verified_file(source_root / relative, destination_root / relative, expected)
            linked_files += 1
            logical_bytes += size
        summaries.append(
            {
                "session_date": day,
                "source_checkpoint_sha256": record["checkpoint_sha256"],
                "raw_sha256": raw_sha,
                "parquet_file_count": len(parquet_files),
                "logical_bytes": int(record["raw_bytes"]) + int(record["parquet_bytes"]),
                "file_identity_verified": True,
            }
        )
    return summaries, linked_files, logical_bytes


def _link_massive_reuse(
    *,
    grouped: Mapping[str, Sequence[Path]],
    source_root: Path,
    destination_root: Path,
) -> tuple[int, int, str]:
    digest = hashlib.sha256()
    file_count = 0
    logical_bytes = 0
    for day in sorted(grouped):
        for source in sorted(grouped[day], key=lambda path: path.name):
            file_hash = sha256_file(source)
            link_verified_file(source, destination_root / source.name, file_hash)
            size = source.stat().st_size
            digest.update(f"{source.name}|{size}|{file_hash}\n".encode())
            file_count += 1
            logical_bytes += size
    resolved = source_root / "resolved_contracts_phase6_strict_v3.json"
    if not resolved.is_file():
        raise ValueError("B1V3_ACQUISITION_MASSIVE_CONTRACT_CACHE_MISSING")
    resolved_hash = sha256_file(resolved)
    resolved_destination = destination_root / resolved.name
    if resolved_destination.exists():
        if sha256_file(resolved_destination) != resolved_hash:
            raise ValueError("B1V3_ACQUISITION_MASSIVE_CONTRACT_CACHE_CONFLICT")
    else:
        resolved_destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(resolved, resolved_destination)
        if sha256_file(resolved_destination) != resolved_hash:
            resolved_destination.unlink(missing_ok=True)
            raise ValueError("B1V3_ACQUISITION_MASSIVE_CONTRACT_CACHE_COPY_FAILED")
    return file_count, logical_bytes, digest.hexdigest()


def prepare_acquisition(
    *,
    confirmation_plan_path: Path,
    provider_report_path: Path,
    source_manifest_path: Path,
    source_data_root: Path,
    source_massive_cache_root: Path,
    destination_data_root: Path,
    schema_path: Path,
    output_path: Path,
    execute_links: bool,
) -> dict[str, Any]:
    """Validate capacity and optionally hardlink all reusable target-blind evidence."""
    plan = _json_object(confirmation_plan_path, code="B1V3_ACQUISITION_PLAN_INVALID")
    report = _json_object(provider_report_path, code="B1V3_ACQUISITION_REPORT_INVALID")
    source_manifest = _json_object(
        source_manifest_path,
        code="B1V3_ACQUISITION_SOURCE_MANIFEST_INVALID",
    )
    sessions = _plan_sessions(plan, report)
    reusable = reusable_records_from_manifest(source_manifest, allowed_sessions=sessions)
    grouped, massive_daily_bytes = _massive_daily_files(
        source_massive_cache_root,
        tuple(reusable),
    )
    destination_data_root.mkdir(parents=True, exist_ok=True)
    free_bytes = shutil.disk_usage(destination_data_root).free
    projection = build_storage_projection(
        all_sessions=sessions,
        reusable_records=reusable,
        uw_content_lengths=_uw_content_lengths(report),
        massive_daily_bytes=massive_daily_bytes,
        current_free_bytes=free_bytes,
        minimum_free_bytes=MINIMUM_FREE_BYTES,
        engineering_margin_bytes=ENGINEERING_MARGIN_BYTES,
    )
    reuse_summaries: list[dict[str, Any]] = []
    full_tape_file_count = 0
    full_tape_logical_bytes = 0
    massive_file_count = 0
    massive_logical_bytes = 0
    massive_inventory_sha256: str | None = None
    if execute_links:
        reuse_summaries, full_tape_file_count, full_tape_logical_bytes = (
            _link_full_tape_reuse(
                records=reusable,
                source_root=source_data_root,
                destination_root=destination_data_root,
            )
        )
        massive_file_count, massive_logical_bytes, massive_inventory_sha256 = (
            _link_massive_reuse(
                grouped=grouped,
                source_root=source_massive_cache_root,
                destination_root=destination_data_root / "cache" / "massive",
            )
        )
    document: dict[str, Any] = {
        **projection,
        "status": (
            "PASS_STORAGE_AND_REUSE_PREPARED"
            if execute_links
            else "PASS_STORAGE_PREFLIGHT_LINKS_NOT_EXECUTED"
        ),
        "source_bindings": {
            "confirmation_plan_sha256": plan["plan_sha256"],
            "provider_report_sha256": report["report_sha256"],
            "reusable_manifest_sha256": source_manifest["manifest_sha256"],
        },
        "reuse": {
            "executed": execute_links,
            "method": "NTFS_HARDLINK_SAME_VOLUME_VERIFIED_BY_SHA256",
            "full_tape_file_count": full_tape_file_count,
            "full_tape_logical_bytes": full_tape_logical_bytes,
            "massive_file_count": massive_file_count,
            "massive_logical_bytes": massive_logical_bytes,
            "massive_inventory_sha256": massive_inventory_sha256,
            "session_records": reuse_summaries,
        },
    }
    document["manifest_sha256"] = canonical_sha256(document)
    validate_json_schema(document, schema_path=schema_path, error_code="B1V3_STORAGE_REUSE")
    if execute_links:
        payload = (json.dumps(document, indent=2, sort_keys=True) + "\n").encode("utf-8")
        write_json_if_identical(output_path, payload)
    return document


def _arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check-only", action="store_true")
    mode.add_argument("--execute-links", action="store_true")
    parser.add_argument(
        "--confirmation-plan",
        type=Path,
        default=Path("artifacts/b1v3_confirmation_plan/confirmation_plan_provider_passed.json"),
    )
    parser.add_argument(
        "--provider-report",
        type=Path,
        default=Path("artifacts/b1v3_provider_preflight_v2/provider_preflight_report.json"),
    )
    parser.add_argument(
        "--source-manifest",
        type=Path,
        default=Path("artifacts/methodology/b2_confirmation_acquisition_manifest_v1.json"),
    )
    parser.add_argument("--source-data-root", type=Path, default=Path("D:/MDS650/b2_confirmation"))
    parser.add_argument(
        "--source-massive-cache-root",
        type=Path,
        default=Path("D:/MDS650/b2_confirmation/cache/massive"),
    )
    parser.add_argument(
        "--destination-data-root",
        type=Path,
        default=Path("D:/MDS650/b1v3_confirmation"),
    )
    parser.add_argument(
        "--schema",
        type=Path,
        default=Path(
            "specs/001-pit-options-rv30/contracts/"
            "b1v3-confirmation-storage-reuse-v1.schema.json"
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(
            "artifacts/b1v3_confirmation_panel/storage_and_reuse_preflight.json"
        ),
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the storage/reuse preparation without emitting personal paths."""
    args = _arguments(argv)
    result = prepare_acquisition(
        confirmation_plan_path=args.confirmation_plan,
        provider_report_path=args.provider_report,
        source_manifest_path=args.source_manifest,
        source_data_root=args.source_data_root,
        source_massive_cache_root=args.source_massive_cache_root,
        destination_data_root=args.destination_data_root,
        schema_path=args.schema,
        output_path=args.output,
        execute_links=args.execute_links,
    )
    print(
        json.dumps(
            {
                "status": result["status"],
                "reusable_session_count": result["reusable_session_count"],
                "missing_session_count": result["missing_session_count"],
                "peak_additional_bytes": result["peak_additional_bytes"],
                "projected_minimum_free_bytes": result["projected_minimum_free_bytes"],
                "safe_to_continue": result["safe_to_continue"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
