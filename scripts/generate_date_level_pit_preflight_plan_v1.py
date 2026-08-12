"""Generate a calendar-derived candidate plan; this does not execute a PIT preflight."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections.abc import Callable, Mapping
from datetime import datetime
from importlib import import_module
from pathlib import Path
from typing import Any, Final, Protocol, cast

ASSETS: Final[tuple[str, ...]] = ("SPY", "QQQ", "AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "META")
SENTINELS: Final[tuple[tuple[str, str], ...]] = (
    ("2025-10-20", "ANOMALY_UW"),
    ("2025-11-28", "EARLY_CLOSE"),
    ("2025-12-24", "EARLY_CLOSE"),
    ("2026-01-20", "WINTER_REGULAR"),
    ("2026-03-06", "PRE_DST"),
    ("2026-03-09", "POST_DST"),
    ("2026-07-13", "SUMMER_REGULAR"),
)
DEFAULT_OUTPUT: Final[Path] = Path("artifacts/preflight/date_level_pit_preflight_plan_v1.json")


class SessionCalendar(Protocol):
    def is_session(self, session: str) -> bool: ...

    def session_open(self, session: str) -> datetime: ...

    def session_close(self, session: str) -> datetime: ...


def canonical_json(value: Mapping[str, Any]) -> bytes:
    """Return the stable JSON representation used for semantic hashing and output."""
    serialized = json.dumps(
        value, allow_nan=False, ensure_ascii=True, separators=(",", ":"), sort_keys=True
    )
    return serialized.encode("utf-8")


def _xnys_calendar() -> SessionCalendar:
    module = import_module("exchange_calendars")
    calendar_factory_name = "get_calendar"
    get_calendar = cast(Callable[[str], SessionCalendar], getattr(module, calendar_factory_name))
    return get_calendar("XNYS")


def _calendar_metadata(calendar: SessionCalendar, session_date: str) -> dict[str, bool | int | str]:
    opened = calendar.session_open(session_date)
    closed = calendar.session_close(session_date)
    duration_minutes = int((closed - opened).total_seconds() // 60)
    return {
        "calendar": "XNYS",
        "timezone": "America/New_York",
        "is_xnys_session": bool(calendar.is_session(session_date)),
        "session_type": "EARLY_CLOSE" if duration_minutes < 390 else "REGULAR",
        "open_utc": opened.isoformat(),
        "close_utc": closed.isoformat(),
        "session_length_minutes": duration_minutes,
    }


def _semantic_self_hash(plan: Mapping[str, Any]) -> str:
    hash_payload = dict(plan)
    hash_payload.pop("semantic_self_hash", None)
    return f"sha256:{hashlib.sha256(canonical_json(hash_payload)).hexdigest()}"


def build_plan() -> dict[str, Any]:
    """Build the fixed calendar-only candidate plan from the local XNYS calendar."""
    calendar = _xnys_calendar()
    sessions = [
        {
            "date": session_date,
            "scenario": scenario,
            "calendar_metadata": _calendar_metadata(calendar, session_date),
        }
        for session_date, scenario in SENTINELS
    ]
    plan: dict[str, Any] = {
        "artifact_type": "date_level_pit_preflight_plan_v1",
        "schema_version": "1.0.0",
        "status": "CANDIDATE_APPROVAL_REQUIRED",
        "flags": {
            "NO_PROVIDER_CALLS_EXECUTED": True,
            "NOT_AUTHORIZATION_FOR_ACQUISITION": True,
        },
        "calendar": {
            "exchange": "XNYS",
            "timezone": "America/New_York",
            "source": "exchange_calendars",
        },
        "assets": list(ASSETS),
        "sentinel_sessions": sessions,
        "semantic_hash_scope": "canonical-json-excluding-semantic_self_hash",
    }
    plan["semantic_self_hash"] = _semantic_self_hash(plan)
    return plan


def render_plan(plan: Mapping[str, Any] | None = None) -> bytes:
    """Render the candidate plan as canonical UTF-8 JSON with one trailing newline."""
    return canonical_json(build_plan() if plan is None else plan) + os.linesep.encode("ascii")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    output = parser.parse_args().output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(render_plan())


if __name__ == "__main__":
    main()
