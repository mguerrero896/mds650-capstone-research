"""Gate 5.3(d): same-day verification of the UW latency collector.

Checks that the just-closed session captured observations for every asset,
writes a per-session capture report, and raises a loud alert (alert file +
Windows popup when available) on any shortfall. Also serves as the watchdog
check: ``--watchdog`` verifies the heartbeat is fresh and restarts the
collector via Scheduled Task if it stalled mid-session.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import json
import os
import subprocess
from pathlib import Path
from zoneinfo import ZoneInfo

import exchange_calendars  # type: ignore[import-untyped]

DATA_ROOT = Path(os.environ.get("MDS650_EXTERNAL_ROOT", "D:/MDS650"))
STORE = DATA_ROOT / "uw_latency" / "sessions"
LOGS = DATA_ROOT / "logs"
ALERT = LOGS / "UW_LATENCY_ALERT.txt"
ASSETS = ("AAPL", "AMZN", "META", "MSFT", "NVDA", "TSLA")
NY = ZoneInfo("America/New_York")
HEARTBEAT_STALE_SECONDS = 300
COLLECTOR_TASK = "MDS650_UW_LatencyCollector"


def _alert(message: str) -> None:
    LOGS.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now(dt.UTC).isoformat()
    with ALERT.open("a", encoding="utf-8") as handle:
        handle.write(f"{stamp} {message}\n")
    with contextlib.suppress(OSError):
        subprocess.run(
            ["msg", "*", f"MDS650 UW latency: {message}"],
            check=False,
            capture_output=True,
            timeout=10,
        )
    print(f"[uw-latency] ALERT: {message}")


def _latest_session() -> dt.date | None:
    calendar = exchange_calendars.get_calendar("XNYS")
    probe = dt.datetime.now(NY).date()
    for _ in range(7):
        if calendar.is_session(probe.isoformat()):
            return probe
        probe -= dt.timedelta(days=1)
    return None


def _watchdog() -> None:
    now_ny = dt.datetime.now(NY)
    session = now_ny.date()
    calendar = exchange_calendars.get_calendar("XNYS")
    if not calendar.is_session(session.isoformat()):
        return
    open_ny = dt.datetime.combine(session, dt.time(9, 30), tzinfo=NY)
    close_ny = dt.datetime.combine(session, dt.time(16, 0), tzinfo=NY)
    if not open_ny <= now_ny <= close_ny:
        return
    heartbeat_path = STORE / session.isoformat() / "heartbeat.json"
    stale = True
    if heartbeat_path.exists():
        payload = json.loads(heartbeat_path.read_text(encoding="utf-8"))
        beat = dt.datetime.fromisoformat(payload["utc"])
        stale = (dt.datetime.now(dt.UTC) - beat).total_seconds() > HEARTBEAT_STALE_SECONDS
    if stale:
        _alert(f"heartbeat stale for {session}; restarting collector task")
        subprocess.run(
            ["schtasks", "/Run", "/TN", COLLECTOR_TASK],
            check=False,
            capture_output=True,
            timeout=30,
        )


def _verify(session: dt.date) -> int:
    session_dir = STORE / session.isoformat()
    observations = session_dir / "observations.jsonl"
    counts = dict.fromkeys(ASSETS, 0)
    errors = 0
    if observations.exists():
        with observations.open(encoding="utf-8") as handle:
            for line in handle:
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    errors += 1
                    continue
                if row.get("kind") == "observation" and row.get("asset") in counts:
                    counts[str(row["asset"])] += 1
                elif row.get("kind") == "poll_error":
                    errors += 1
    report = {
        "session": session.isoformat(),
        "verified_utc": dt.datetime.now(dt.UTC).isoformat(),
        "counts": counts,
        "poll_errors": errors,
        "total": sum(counts.values()),
    }
    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / "capture_report.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    missing = sorted(asset for asset, count in counts.items() if count == 0)
    if missing:
        _alert(f"session {session}: NO capture for {','.join(missing)} (total {report['total']})")
        return 1
    print(
        f"[uw-latency] session {session} verified: {report['total']} records, "
        f"{errors} poll errors"
    )
    return 0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--watchdog", action="store_true")
    parser.add_argument("--session", default=None)
    arguments = parser.parse_args()
    if arguments.watchdog:
        _watchdog()
        return
    session = (
        dt.date.fromisoformat(arguments.session) if arguments.session else _latest_session()
    )
    if session is None:
        _alert("no recent XNYS session found for verification")
        raise SystemExit(1)
    raise SystemExit(_verify(session))


if __name__ == "__main__":
    main()
