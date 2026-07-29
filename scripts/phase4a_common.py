"""Small deterministic helpers shared by the Phase 4A evidence builder."""

# ruff: noqa: E501

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from typing import Any


def availability_is_valid(
    raw_timestamp: datetime,
    forecast_origin: datetime,
    *,
    delay_minutes: int,
) -> bool:
    """Return whether a raw bar is available at a forecast origin.

    Parameters
    ----------
    raw_timestamp, forecast_origin:
        Timezone-aware timestamps in the same instant basis.
    delay_minutes:
        Conservative research delay applied to the raw provider label.

    Returns
    -------
    bool
        ``True`` only when ``raw_timestamp + delay <= forecast_origin``.

    Raises
    ------
    ValueError
        If either timestamp is naive or the delay is negative.
    """
    if raw_timestamp.tzinfo is None or forecast_origin.tzinfo is None:
        raise ValueError("NAIVE_TIMESTAMP")
    if delay_minutes < 0:
        raise ValueError("NEGATIVE_AVAILABILITY_DELAY")
    return raw_timestamp + timedelta(minutes=delay_minutes) <= forecast_origin


def build_origin_id(asset: str, session_date: str, forecast_origin: datetime) -> str:
    """Build the canonical ``asset|date|origin`` primary key."""
    if not asset or not session_date or forecast_origin.tzinfo is None:
        raise ValueError("INVALID_ORIGIN_KEY")
    return f"{asset}|{session_date}|{forecast_origin.isoformat()}"


def nested_benchmark_flags(*, atm: bool, skew: bool, term: bool) -> dict[str, bool]:
    """Return component flags and monotone B1a/B1b/B1c benchmark flags."""
    return {
        "atm_iv_available": bool(atm),
        "skew_available": bool(skew),
        "term_structure_available": bool(term),
        "b1a_complete": bool(atm),
        "b1b_complete": bool(atm and skew),
        "b1c_complete": bool(atm and skew and term),
    }


def checkpoint_payload(session: str, row_ids: list[str], source_hash: str) -> dict[str, Any]:
    """Create a content-addressed checkpoint manifest for restart tests."""
    unique_ids = sorted(set(row_ids))
    payload: dict[str, Any] = {
        "schema_version": "phase4a-checkpoint-v1",
        "session": session,
        "row_ids": unique_ids,
        "rows": len(unique_ids),
        "source_hash": source_hash,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    payload["payload_sha256"] = hashlib.sha256(canonical).hexdigest()
    return payload


def validate_checkpoint(payload: dict[str, Any]) -> bool:
    """Validate checkpoint integrity and fail closed on corruption."""
    required = {"schema_version", "session", "row_ids", "rows", "source_hash", "payload_sha256"}
    if not required <= payload.keys() or payload.get("schema_version") != "phase4a-checkpoint-v1":
        raise ValueError("CHECKPOINT_CORRUPTED")
    row_ids = payload.get("row_ids")
    if (
        not isinstance(row_ids, list)
        or row_ids != sorted(set(row_ids))
        or payload.get("rows") != len(row_ids)
    ):
        raise ValueError("CHECKPOINT_CORRUPTED")
    unsigned = {key: value for key, value in payload.items() if key != "payload_sha256"}
    canonical = json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode()
    if hashlib.sha256(canonical).hexdigest() != payload.get("payload_sha256"):
        raise ValueError("CHECKPOINT_CORRUPTED")
    return True
