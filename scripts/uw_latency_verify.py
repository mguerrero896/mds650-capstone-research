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
from typing import Any
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
# Mirrors close_ny in scripts/uw_latency_collector.py: the collector polls until
# 16:05 New York. A session that stops materially earlier did not cover its window.
CLOSE_NY = dt.time(16, 5)
# 2026-08-17 (the one session that closed properly) finished 5 minutes inside this
# budget; 2026-08-18/19/20 fell short by 110 to 332 minutes. Fifteen minutes
# separates the two populations without flagging ordinary shutdown jitter.
COMPLETION_TOLERANCE_SECONDS = 900


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


def _read_json(path: Path) -> dict[str, Any] | None:
    """Return the parsed object, or None when it is absent or unreadable.

    Unreadable is deliberately collapsed into absent: both mean the artifact
    cannot certify anything, and both must fail closed at the call site.
    """
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _stamp(payload: dict[str, Any] | None, key: str) -> dt.datetime | None:
    """Parse one ISO-8601 field into an aware UTC datetime, or None."""
    if payload is None or not isinstance(payload.get(key), str):
        return None
    try:
        parsed = dt.datetime.fromisoformat(payload[key])
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.UTC)


def _verify(session: dt.date) -> int:
    session_dir = STORE / session.isoformat()
    observations = session_dir / "observations.jsonl"
    counts = dict.fromkeys(ASSETS, 0)
    errors = 0
    last_receipt: dt.datetime | None = None
    if observations.exists():
        with observations.open(encoding="utf-8") as handle:
            for line in handle:
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    errors += 1
                    continue
                if not isinstance(row, dict):
                    # A bare scalar parses fine but has no .get; without this the
                    # verifier would die before writing capture_report.json and
                    # leave the previous day's green report in place.
                    errors += 1
                    continue
                if row.get("kind") == "observation" and row.get("asset") in counts:
                    counts[str(row["asset"])] += 1
                    stamp = _stamp(row, "receipt_utc")
                    if stamp is not None and (last_receipt is None or stamp > last_receipt):
                        last_receipt = stamp
                elif row.get("kind") == "poll_error":
                    errors += 1

    total = sum(counts.values())
    close_utc = dt.datetime.combine(session, CLOSE_NY, tzinfo=NY).astimezone(dt.UTC)
    deadline = close_utc - dt.timedelta(seconds=COMPLETION_TOLERANCE_SECONDS)
    summary = _read_json(session_dir / "collector_summary.json")
    heartbeat = _read_json(session_dir / "heartbeat.json")
    finished = _stamp(summary, "finished_utc")
    last_beat = _stamp(heartbeat, "utc")

    def _shortfall(stamp: dt.datetime | None) -> float | None:
        return None if stamp is None else (close_utc - stamp).total_seconds()

    def _short_by(stamp: dt.datetime) -> str:
        return f"{(close_utc - stamp).total_seconds() / 60:.0f} min before close"

    # Every condition below is a reason the session cannot be certified. They are
    # collected rather than short-circuited so one report explains the whole failure.
    failures: list[str] = []
    absent = sorted(asset for asset, count in counts.items() if count == 0)
    if absent:
        failures.append(f"NO capture for {','.join(absent)}")
    if summary is None:
        failures.append("collector_summary.json absent or unreadable (collector never closed)")
    elif finished is None:
        failures.append("collector_summary.json has no parseable finished_utc")
    elif finished < deadline:
        failures.append(f"collector finished {_short_by(finished)}")
    elif summary.get("termination") not in (None, "normal"):
        # The collector records how it ended; a stop that was not a clean close
        # cannot certify the session even when its finished_utc looks late enough.
        failures.append(f"collector terminated as {summary['termination']}, not a normal close")
    claimed = summary.get("observed_records") if summary is not None else None
    if isinstance(claimed, int) and claimed > total:
        # Deliberately not equality. The watchdog restarts a stalled collector
        # (uw_latency_verify._watchdog), and a restarted run re-enters main() with
        # its counters at zero while appending to the same tape, so its summary
        # legitimately describes only part of the file. Claiming MORE than the
        # tape holds is the case that cannot be legitimate.
        failures.append(f"summary claims {claimed} records, tape holds only {total}")
    if last_beat is None:
        failures.append("heartbeat.json absent or unreadable")
    elif last_beat < deadline:
        failures.append(f"final heartbeat {_short_by(last_beat)}")
    if last_receipt is None:
        failures.append("no observation carries a parseable receipt_utc")
    elif last_receipt < deadline:
        failures.append(f"coverage ends {_short_by(last_receipt)}")

    report = {
        "session": session.isoformat(),
        "verified_utc": dt.datetime.now(dt.UTC).isoformat(),
        "counts": counts,
        "poll_errors": errors,
        "total": total,
        "configured_close_utc": close_utc.isoformat(),
        "collector_summary_present": summary is not None,
        "collector_finished_utc": finished.isoformat() if finished else None,
        "final_heartbeat_utc": last_beat.isoformat() if last_beat else None,
        "last_observation_utc": last_receipt.isoformat() if last_receipt else None,
        "coverage_shortfall_seconds": _shortfall(last_receipt),
        "heartbeat_shortfall_seconds": _shortfall(last_beat),
        "complete": not failures,
        "failures": failures,
    }
    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / "capture_report.json").write_text(json.dumps(report, indent=1), encoding="utf-8")

    if failures:
        _alert(f"session {session} INCOMPLETE (total {total}): " + "; ".join(failures))
        return 1
    print(f"[uw-latency] session {session} verified: {total} records, {errors} poll errors")
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
