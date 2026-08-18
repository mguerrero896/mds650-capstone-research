"""Phase 9 same-day capture verification (decision 59).

Checks that the just-closed session's manifest exists and is complete (bars for
all six assets, tape archive present, quote sweep with OK rows), alerts loudly
on any shortfall, and reports campaign progress toward 60 sessions.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import json
import os
import subprocess
from pathlib import Path
from zoneinfo import ZoneInfo

import exchange_calendars  # type: ignore[import-untyped]

DATA_ROOT = Path(os.environ.get("MDS650_EXTERNAL_ROOT", "D:/MDS650"))
STORE = DATA_ROOT / "phase9"
ALERT = DATA_ROOT / "logs" / "PHASE9_ALERT.txt"
NY = ZoneInfo("America/New_York")
WINDOW_START = dt.date(2026, 8, 19)


def _alert(message: str) -> None:
    ALERT.parent.mkdir(parents=True, exist_ok=True)
    with ALERT.open("a", encoding="utf-8") as handle:
        handle.write(f"{dt.datetime.now(dt.UTC).isoformat()} {message}\n")
    with contextlib.suppress(OSError):
        subprocess.run(
            ["msg", "*", f"MDS650 Phase 9: {message}"],
            check=False,
            capture_output=True,
            timeout=10,
        )
    print(f"[phase9-verify] ALERT: {message}")


def main() -> None:
    calendar = exchange_calendars.get_calendar("XNYS")
    probe = dt.datetime.now(NY)
    session: dt.date | None = None
    for _ in range(7):
        day = probe.date()
        if calendar.is_session(day.isoformat()):
            close_ny = dt.datetime.combine(day, dt.time(16, 0), tzinfo=NY)
            if probe > close_ny + dt.timedelta(minutes=30):
                session = day
                break
        probe -= dt.timedelta(days=1)
    if session is None:
        return
    if session < WINDOW_START:
        print(f"[phase9-verify] session {session} predates the window start; nothing to verify")
        return
    manifest_path = STORE / "raw" / session.isoformat() / "session_manifest.json"
    if not manifest_path.exists():
        _alert(f"session {session}: NO manifest (collector missed or still running)")
        raise SystemExit(1)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    problems = []
    if manifest.get("bars_rows", 0) < 6 * 380:
        problems.append(f"bars_rows={manifest.get('bars_rows')}")
    if manifest.get("tape_bytes", 0) < 1_000_000:
        problems.append(f"tape_bytes={manifest.get('tape_bytes')}")
    if manifest.get("quote_ok", 0) == 0:
        problems.append("quote_ok=0")
    counter_path = STORE / "counter.json"
    captured = 0
    if counter_path.exists():
        captured = len(json.loads(counter_path.read_text(encoding="utf-8"))["sessions"])
    if problems:
        _alert(f"session {session}: capture shortfall ({', '.join(problems)})")
        raise SystemExit(1)
    print(f"[phase9-verify] session {session} complete; campaign {captured}/60")


if __name__ == "__main__":
    main()
