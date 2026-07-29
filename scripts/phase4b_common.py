"""Small, deterministic Phase 4B contracts shared by local builders."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from typing import Any

import polars as pl

WINDOW_SPECS: dict[str, int] = {
    "primary_60s": 60,
    "sensitivity_120s": 120,
    "sensitivity_300s": 300,
}

B2_ALIASES: dict[str, str] = {
    "median_implied_volatility": "implied_volatility_median",
    "implied_volatility_change_within_bin": "within_bin_iv_change",
}


def window_bounds(origin: datetime, delay_seconds: int) -> tuple[datetime, datetime]:
    """Return the fixed five-minute event window ending before ``origin``.

    Parameters
    ----------
    origin:
        Timezone-aware forecast origin.
    delay_seconds:
        Operational cutoff in seconds.

    Returns
    -------
    tuple[datetime, datetime]
        Half-open ``[start, end)`` bounds in the same timezone as ``origin``.

    Raises
    ------
    ValueError
        If the origin is naive or the delay is negative.
    """
    if origin.tzinfo is None or delay_seconds < 0:
        raise ValueError("INVALID_WINDOW_ARGUMENT")
    end = origin - timedelta(seconds=delay_seconds)
    return end - timedelta(minutes=5), end


def event_is_eligible(
    executed_at: datetime,
    created_at: datetime,
    origin: datetime,
    delay_seconds: int,
) -> bool:
    """Apply the event-time and operational-availability predicates."""
    if any(value.tzinfo is None for value in (executed_at, created_at, origin)):
        raise ValueError("NAIVE_EVENT_TIMESTAMP")
    start, end = window_bounds(origin, delay_seconds)
    return start <= executed_at < end and max(executed_at, created_at) <= end


def strict_window_origin(executed_at: datetime, delay_seconds: int) -> datetime:
    """Map an event to the unique five-minute origin for a shifted window.

    The strict ceiling assigns events exactly on a boundary to the next window,
    which implements ``[window_start, window_end)`` without duplicate assignment.
    """
    if executed_at.tzinfo is None or delay_seconds < 0:
        raise ValueError("INVALID_WINDOW_ARGUMENT")
    shifted = executed_at + timedelta(seconds=delay_seconds)
    floor_minute = (shifted.minute // 5) * 5
    floor = shifted.replace(minute=floor_minute, second=0, microsecond=0)
    return floor + timedelta(minutes=5)


def canonicalize_b2_frame(frame: pl.DataFrame) -> pl.DataFrame:
    """Map known B2 aliases and reject conflicting canonical values."""
    result = frame
    for alias, canonical in B2_ALIASES.items():
        if alias not in result.columns:
            continue
        if canonical in result.columns:
            left = result.get_column(alias)
            right = result.get_column(canonical)
            if not left.equals(right):
                raise ValueError("B2_ALIAS_CONFLICT")
            result = result.drop(alias)
        else:
            result = result.rename({alias: canonical})
    return result


def _sha256_payload(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(canonical).hexdigest()


def build_checkpoint(
    *,
    session: str,
    session_list: list[str],
    config: dict[str, Any],
    input_hashes: dict[str, str],
    schema_hash: str,
    request_hashes: list[str],
    output_hash: str,
    origin_ids: list[str],
) -> dict[str, Any]:
    """Create a content-addressed Phase 4B session checkpoint."""
    hashes = list(input_hashes.values()) + [schema_hash, output_hash, *request_hashes]
    if any(len(value) != 64 for value in hashes):
        raise ValueError("INVALID_CHECKPOINT_HASH")
    ids = sorted(set(origin_ids))
    payload: dict[str, Any] = {
        "schema_version": "phase4b-checkpoint-v1",
        "status": "PASS",
        "session": session,
        "session_list": sorted(session_list),
        "session_list_sha256": _sha256_payload({"sessions": sorted(session_list)}),
        "config": config,
        "config_sha256": _sha256_payload(config),
        "input_sha256": dict(sorted(input_hashes.items())),
        "schema_sha256": schema_hash,
        "request_sha256": sorted(request_hashes),
        "output_sha256": output_hash,
        "origin_id_count": len(ids),
        "origin_id_sha256": _sha256_payload({"origin_ids": ids}),
        "origin_ids": ids,
    }
    payload["payload_sha256"] = _sha256_payload(payload)
    return payload


def validate_checkpoint(payload: dict[str, Any]) -> bool:
    """Validate hashes, sorted IDs and the signed checkpoint payload."""
    required = {
        "schema_version",
        "status",
        "session",
        "session_list",
        "session_list_sha256",
        "config",
        "config_sha256",
        "input_sha256",
        "schema_sha256",
        "request_sha256",
        "output_sha256",
        "origin_id_count",
        "origin_id_sha256",
        "origin_ids",
        "payload_sha256",
    }
    if not required <= payload.keys() or payload.get("schema_version") != "phase4b-checkpoint-v1":
        raise ValueError("CHECKPOINT_CORRUPTED")
    if payload.get("status") != "PASS":
        raise ValueError("CHECKPOINT_NOT_PASS")
    origin_ids = payload.get("origin_ids")
    if not isinstance(origin_ids, list) or origin_ids != sorted(set(origin_ids)):
        raise ValueError("CHECKPOINT_CORRUPTED")
    if payload.get("origin_id_count") != len(origin_ids):
        raise ValueError("CHECKPOINT_CORRUPTED")
    all_hashes = list(payload.get("input_sha256", {}).values()) + [
        payload.get("schema_sha256"),
        payload.get("output_sha256"),
        *payload.get("request_sha256", []),
    ]
    if any(not isinstance(value, str) or len(value) != 64 for value in all_hashes):
        raise ValueError("CHECKPOINT_CORRUPTED")
    unsigned = {key: value for key, value in payload.items() if key != "payload_sha256"}
    if _sha256_payload(unsigned) != payload.get("payload_sha256"):
        raise ValueError("CHECKPOINT_CORRUPTED")
    if _sha256_payload({"origin_ids": origin_ids}) != payload.get("origin_id_sha256"):
        raise ValueError("CHECKPOINT_CORRUPTED")
    return True


def holdout_read_guard(manifest: dict[str, Any], requested_dates: list[str]) -> bool:
    """Deny any attempt to read a sealed-but-unacquired holdout date."""
    if manifest.get("status") != "SEALED_NOT_ACQUIRED":
        raise PermissionError("PROSPECTIVE_HOLDOUT_STATE_INVALID")
    blocked = set(manifest.get("session_dates", [])) & set(requested_dates)
    if blocked:
        raise PermissionError("PROSPECTIVE_HOLDOUT_READ_BLOCKED")
    return True
