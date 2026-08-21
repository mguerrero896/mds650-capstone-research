"""Gate 5.2: live Unusual Whales latency collector.

Polls the bounded flow-alerts endpoint for the six outcome assets during one
XNYS session, recording every observed record verbatim together with the local
receipt timestamp. Observations are appended crash-safely (one JSON line per
record, flushed per batch); a heartbeat file is refreshed every cycle so the
watchdog can restart a stalled collector. Zero model reads; zero sealed data.

Usage:
    uv run python scripts/uw_latency_collector.py            # today's session
    uv run python scripts/uw_latency_collector.py --dry-run  # 3-cycle exercise
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import json
import os
import signal
import time
from pathlib import Path
from types import FrameType
from zoneinfo import ZoneInfo

import exchange_calendars  # type: ignore[import-untyped]

from mds650.providers.unusual_whales import UnusualWhalesProvider

DATA_ROOT = Path(os.environ.get("MDS650_EXTERNAL_ROOT", "D:/MDS650"))
STORE = DATA_ROOT / "uw_latency" / "sessions"
LOGS = DATA_ROOT / "logs"
ASSETS = ("AAPL", "AMZN", "META", "MSFT", "NVDA", "TSLA")
NY = ZoneInfo("America/New_York")
POLL_SECONDS = 60
PAGE_LIMIT = 200


def _api_key() -> str:
    key = os.environ.get("UNUSUAL_WHALES_API_KEY") or os.environ.get("UNUSUALWHALES_API_KEY")
    if not key:
        LOGS.mkdir(parents=True, exist_ok=True)
        (LOGS / "UW_LATENCY_ALERT.txt").write_text(
            f"{dt.datetime.now(dt.UTC).isoformat()} COLLECTOR_CREDENTIALS_MISSING\n",
            encoding="utf-8",
        )
        raise SystemExit("UW_LATENCY_CREDENTIALS_MISSING")
    return key


def _session_today() -> dt.date | None:
    calendar = exchange_calendars.get_calendar("XNYS")
    now_ny = dt.datetime.now(NY)
    session = now_ny.date()
    return session if calendar.is_session(session.isoformat()) else None


def _heartbeat(session_dir: Path, cycle: int, observed: int) -> None:
    payload = {
        "utc": dt.datetime.now(dt.UTC).isoformat(),
        "cycle": cycle,
        "observed_records": observed,
        "pid": os.getpid(),
    }
    tmp = session_dir / "heartbeat.json.tmp"
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    tmp.replace(session_dir / "heartbeat.json")


def _poll_cycle(
    provider: UnusualWhalesProvider,
    session_dir: Path,
    cursors: dict[str, str],
    seen: dict[str, set[str]],
) -> int:
    observed = 0
    receipt = dt.datetime.now(dt.UTC).isoformat()
    lines: list[str] = []
    for asset in ASSETS:
        try:
            response = provider.flow_alerts(
                ticker_symbol=asset,
                newer_than=cursors[asset],
                older_than=dt.datetime.now(dt.UTC).isoformat(),
                limit=PAGE_LIMIT,
            )
        except Exception as error:  # noqa: BLE001 - a failed poll must not kill the session
            failure = {
                "kind": "poll_error",
                "asset": asset,
                "receipt_utc": receipt,
                "error": repr(error),
            }
            lines.append(json.dumps(failure))
            continue
        payload = response.payload if isinstance(response.payload, dict) else {}
        raw_records = payload.get("data")
        records = raw_records if isinstance(raw_records, list) else []
        newest = cursors[asset]
        for record in records:
            if not isinstance(record, dict):
                continue
            fallback_id = json.dumps(record, sort_keys=True, default=str)[:64]
            record_id = str(record.get("id") or record.get("tape_time") or fallback_id)
            if record_id in seen[asset]:
                continue
            seen[asset].add(record_id)
            observed += 1
            lines.append(
                json.dumps(
                    {
                        "kind": "observation",
                        "asset": asset,
                        "receipt_utc": receipt,
                        "record_id": record_id,
                        "record": record,
                    },
                    default=str,
                )
            )
            created = record.get("created_at") or record.get("start_time")
            if created is not None:
                newest = max(newest, str(created)) if isinstance(created, str) else newest
        if isinstance(newest, str) and newest > cursors[asset]:
            cursors[asset] = newest
    if lines:
        with (session_dir / "observations.jsonl").open("a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
    return observed


def _install_cancellation() -> None:
    """Route cooperative stop signals through KeyboardInterrupt.

    Without this, a SIGTERM (or a console CTRL_BREAK, which is what Windows
    records as 0xC000013A) terminates the interpreter without unwinding, so the
    try/finally in main() never writes collector_summary.json. Converting the
    signal into an exception lets the terminal summary reach disk on every path
    the OS still lets Python run code on.
    """

    def _raise(signum: int, _frame: FrameType | None) -> None:
        raise KeyboardInterrupt(f"signal {signum}")

    for name in ("SIGINT", "SIGTERM", "SIGBREAK"):
        received = getattr(signal, name, None)
        if received is None:
            continue
        # Not every signal is settable on every platform or from every thread.
        with contextlib.suppress(OSError, ValueError):
            signal.signal(received, _raise)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--session", default=None)
    arguments = parser.parse_args()
    key = _api_key()
    if arguments.session:
        session: dt.date | None = dt.date.fromisoformat(arguments.session)
    else:
        session = _session_today()
    if session is None:
        print("[uw-latency] no XNYS session today; exiting")
        return
    session_dir = STORE / session.isoformat()
    session_dir.mkdir(parents=True, exist_ok=True)
    open_ny = dt.datetime.combine(session, dt.time(9, 30), tzinfo=NY)
    close_ny = dt.datetime.combine(session, dt.time(16, 5), tzinfo=NY)
    provider = UnusualWhalesProvider(key)
    cursors = {asset: open_ny.astimezone(dt.UTC).isoformat() for asset in ASSETS}
    seen: dict[str, set[str]] = {asset: set() for asset in ASSETS}
    total = 0
    cycle = 0
    _install_cancellation()
    termination = "killed"
    try:
        if arguments.dry_run:
            for cycle in range(1, 4):
                total += _poll_cycle(provider, session_dir, cursors, seen)
                _heartbeat(session_dir, cycle, total)
                time.sleep(2)
            print(f"[uw-latency] dry run complete: {total} records in {session_dir}")
            termination = "normal"
            return
        while dt.datetime.now(NY) < open_ny:
            _heartbeat(session_dir, cycle, total)
            time.sleep(30)
        while dt.datetime.now(NY) < close_ny:
            cycle += 1
            total += _poll_cycle(provider, session_dir, cursors, seen)
            _heartbeat(session_dir, cycle, total)
            time.sleep(POLL_SECONDS)
        termination = "normal"
    except KeyboardInterrupt:
        # SIGINT/SIGTERM/SIGBREAK arrive here via _install_cancellation, so a
        # cooperative stop still records a terminal summary. A hard
        # TerminateProcess cannot: it never unwinds this frame, the summary stays
        # absent, and uw_latency_verify._verify treats that absence as a failure.
        termination = "cancelled"
        raise
    finally:
        provider.close()
        summary = {
            "session": session.isoformat(),
            "cycles": cycle,
            "observed_records": total,
            "finished_utc": dt.datetime.now(dt.UTC).isoformat(),
            "dry_run": bool(arguments.dry_run),
            "termination": termination,
            "configured_close_utc": close_ny.astimezone(dt.UTC).isoformat(),
        }
        (session_dir / "collector_summary.json").write_text(
            json.dumps(summary, indent=1), encoding="utf-8"
        )
    print(f"[uw-latency] session {session}: {total} records over {cycle} cycles")


if __name__ == "__main__":
    main()
