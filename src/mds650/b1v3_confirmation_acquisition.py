"""Target-blind storage and evidence-reuse controls for B1v3 confirmation."""

from __future__ import annotations

import hashlib
import math
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from mds650.b1v3_confirmation import canonical_sha256


def sha256_file(path: Path, *, chunk_size: int = 8 * 1024 * 1024) -> str:
    """Return a streaming SHA-256 digest for one immutable source file."""
    if chunk_size <= 0:
        raise ValueError("B1V3_REUSE_HASH_CHUNK_INVALID")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def reusable_records_from_manifest(
    manifest: Mapping[str, Any],
    *,
    allowed_sessions: Sequence[str],
) -> dict[str, Mapping[str, Any]]:
    """Select self-hashed target-blind acquisition checkpoints by date.

    Parameters
    ----------
    manifest:
        Prior sanitized Full Tape acquisition manifest.
    allowed_sessions:
        Frozen B1v3 training and confirmation dates.

    Returns
    -------
    dict[str, Mapping[str, Any]]
        Ordered reusable checkpoint records inside the frozen allowlist.

    Raises
    ------
    ValueError
        If manifest/checkpoint hashes, gates, identities or counts drift.
    """
    unsigned = {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    if manifest.get("manifest_sha256") != canonical_sha256(unsigned):
        raise ValueError("B1V3_REUSE_MANIFEST_HASH_INVALID")
    records_value = manifest.get("records")
    if (
        manifest.get("status") != "PASS"
        or manifest.get("target_outcome_read") is not False
        or manifest.get("oos_read_count") != 0
        or manifest.get("secret_values_emitted") is not False
        or manifest.get("personal_paths_emitted") is not False
        or not isinstance(records_value, list)
        or manifest.get("completed_count") != len(records_value)
    ):
        raise ValueError("B1V3_REUSE_MANIFEST_GATE_INVALID")
    allowed = set(allowed_sessions)
    selected: dict[str, Mapping[str, Any]] = {}
    seen: set[str] = set()
    for raw_record in records_value:
        if not isinstance(raw_record, Mapping):
            raise ValueError("B1V3_REUSE_CHECKPOINT_INVALID")
        day = raw_record.get("session_date")
        if not isinstance(day, str) or day in seen:
            raise ValueError("B1V3_REUSE_CHECKPOINT_DUPLICATE")
        seen.add(day)
        checkpoint_unsigned = {
            key: value for key, value in raw_record.items() if key != "checkpoint_sha256"
        }
        if raw_record.get("checkpoint_sha256") != canonical_sha256(checkpoint_unsigned):
            raise ValueError("B1V3_REUSE_CHECKPOINT_HASH_INVALID")
        parquet_files = raw_record.get("parquet_files")
        if (
            raw_record.get("status") != "PASS"
            or raw_record.get("duplicate_event_ids") != 0
            or raw_record.get("secret_values_emitted") is not False
            or raw_record.get("personal_paths_emitted") is not False
            or not isinstance(raw_record.get("raw_bytes"), int)
            or not isinstance(raw_record.get("raw_sha256"), str)
            or not isinstance(raw_record.get("parquet_bytes"), int)
            or not isinstance(parquet_files, list)
            or not parquet_files
        ):
            raise ValueError("B1V3_REUSE_CHECKPOINT_INVALID")
        if day in allowed:
            selected[day] = raw_record
    return dict(sorted(selected.items()))


def build_storage_projection(
    *,
    all_sessions: Sequence[str],
    reusable_records: Mapping[str, Mapping[str, Any]],
    uw_content_lengths: Mapping[str, int],
    massive_daily_bytes: Sequence[int],
    current_free_bytes: int,
    minimum_free_bytes: int,
    engineering_margin_bytes: int,
) -> dict[str, Any]:
    """Calculate a conservative storage peak before any missing-date download."""
    sessions = tuple(all_sessions)
    if not sessions or list(sessions) != sorted(set(sessions)):
        raise ValueError("B1V3_STORAGE_SESSION_ALLOWLIST_INVALID")
    if not set(reusable_records).issubset(sessions):
        raise ValueError("B1V3_STORAGE_REUSE_OUTSIDE_ALLOWLIST")
    missing = tuple(day for day in sessions if day not in reusable_records)
    if set(uw_content_lengths) != set(sessions) or any(
        not isinstance(value, int) or value <= 0 for value in uw_content_lengths.values()
    ):
        raise ValueError("B1V3_STORAGE_UW_CONTENT_LENGTH_INVALID")
    if not massive_daily_bytes or any(value <= 0 for value in massive_daily_bytes):
        raise ValueError("B1V3_STORAGE_MASSIVE_SAMPLE_INVALID")
    if min(current_free_bytes, minimum_free_bytes, engineering_margin_bytes) < 0:
        raise ValueError("B1V3_STORAGE_BYTES_INVALID")

    reusable_raw = sum(int(record["raw_bytes"]) for record in reusable_records.values())
    reusable_parquet = sum(
        int(record["parquet_bytes"]) for record in reusable_records.values()
    )
    parquet_ratio = reusable_parquet / reusable_raw if reusable_raw else 0.20
    uw_missing_raw = sum(uw_content_lengths[day] for day in missing)
    uw_filtered_projected = math.ceil(uw_missing_raw * parquet_ratio)
    ordered_massive = sorted(int(value) for value in massive_daily_bytes)
    p95_index = math.ceil(0.95 * len(ordered_massive)) - 1
    massive_p95 = ordered_massive[p95_index]
    massive_mean = sum(ordered_massive) / len(ordered_massive)
    massive_missing_p95 = massive_p95 * len(missing)
    massive_missing_mean = math.ceil(massive_mean * len(missing))
    maximum_missing_uw = max((uw_content_lengths[day] for day in missing), default=0)
    temporary_peak = max(maximum_missing_uw, massive_p95)
    final_resident = uw_missing_raw + uw_filtered_projected + massive_missing_p95
    peak_additional = final_resident + temporary_peak + engineering_margin_bytes
    projected_minimum = current_free_bytes - peak_additional
    if projected_minimum < minimum_free_bytes:
        raise ValueError("B1V3_PROJECTED_MINIMUM_FREE_SPACE_BELOW_FLOOR")
    return {
        "schema_version": "b1v3-confirmation-storage-1.0",
        "status": "PASS_STORAGE_AND_REUSE_PREFLIGHT",
        "target_blind": True,
        "safe_to_continue": True,
        "minimum_free_bytes": minimum_free_bytes,
        "current_free_bytes": current_free_bytes,
        "projected_minimum_free_bytes": projected_minimum,
        "session_count": len(sessions),
        "reusable_session_count": len(reusable_records),
        "missing_session_count": len(missing),
        "missing_sessions": list(missing),
        "uw_missing_raw_bytes": uw_missing_raw,
        "uw_filtered_projection_ratio": parquet_ratio,
        "uw_filtered_projected_bytes": uw_filtered_projected,
        "massive_daily_sample_count": len(ordered_massive),
        "massive_daily_mean_bytes": massive_mean,
        "massive_daily_p95_bytes": massive_p95,
        "massive_missing_mean_bytes": massive_missing_mean,
        "massive_missing_p95_bytes": massive_missing_p95,
        "temporary_peak_bytes": temporary_peak,
        "engineering_margin_bytes": engineering_margin_bytes,
        "final_resident_additional_bytes": final_resident,
        "peak_additional_bytes": peak_additional,
        "outcome_read_count": 0,
        "secret_values_emitted": False,
        "personal_paths_emitted": False,
    }


def link_verified_file(source: Path, destination: Path, expected_sha256: str) -> str:
    """Hardlink one verified immutable file without duplicating physical storage."""
    if not source.is_file() or sha256_file(source) != expected_sha256:
        raise ValueError("B1V3_REUSE_SOURCE_HASH_MISMATCH")
    if destination.exists():
        if (
            not destination.is_file()
            or sha256_file(destination) != expected_sha256
            or not os.path.samefile(source, destination)
        ):
            raise ValueError("B1V3_REUSE_DESTINATION_HASH_MISMATCH")
        return "REUSED_VERIFIED"
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(source, destination)
    except FileExistsError:
        if (
            not destination.is_file()
            or sha256_file(destination) != expected_sha256
            or not os.path.samefile(source, destination)
        ):
            raise ValueError("B1V3_REUSE_DESTINATION_HASH_MISMATCH") from None
        return "REUSED_VERIFIED"
    except OSError as exc:
        raise ValueError("B1V3_REUSE_HARDLINK_FAILED") from exc
    if (
        not os.path.samefile(source, destination)
        or sha256_file(destination) != expected_sha256
    ):
        destination.unlink(missing_ok=True)
        raise ValueError("B1V3_REUSE_DESTINATION_HASH_MISMATCH")
    return "LINKED_VERIFIED"
