"""Out-of-band healthcheck for the Phase 8 collection watchdog.

The watchdog (``phase8_watch.ps1``, scheduled task ``MDS650_Phase8A_CollectionWatch``)
cannot report its own startup failure. On 2026-08-20 20:00:02 it exited
0xE0434352: the .NET Runtime 1026 event traces the unhandled exception to
``Microsoft.PowerShell.ManagedPSEntry.Main``, i.e. pwsh failed to bind
``System.Management.Automation 7.6.0.500`` and terminated before the script's
first statement. No log line, no alert, no seal check.

That is invisible from inside the watchdog because its healthy path deletes the
alert file: a run that died at host startup and a run that found everything in
order both leave no alert behind. This check inverts the default — a run that
left no record is a failure, not a silence.

It reads the watchdog's own text log and nothing else: no evaluator, no holdout
store, no target or feature access.

Usage:
    uv run python scripts/phase8_watchdog_health.py                  # yesterday's run
    uv run python scripts/phase8_watchdog_health.py --date 2026-08-20
    uv run python scripts/phase8_watchdog_health.py --log path/to/phase8_watch.log
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import re
from pathlib import Path

DATA_ROOT = Path(os.environ.get("MDS650_EXTERNAL_ROOT", "D:/MDS650"))
DEFAULT_LOG = DATA_ROOT / "logs" / "phase8_watch.log"
# 2026-08-19T20:00:03 completed=22/30 expected>=21 reads=0
LINE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\S+\s+completed=\d+/\d+\s+expected>=\d+\s+reads=(?P<reads>\d+)\s*$"
)


def reasons(log: Path, expected_date: dt.date) -> list[str]:
    """Return every reason the watchdog run for `expected_date` is not trustworthy."""
    stamp = expected_date.isoformat()
    try:
        content = log.read_text(encoding="utf-8")
    except OSError as error:
        return [f"watchdog log unreadable at {log}: {error.__class__.__name__}"]

    same_day = [line for line in content.splitlines() if line.startswith(f"{stamp}T")]
    if not same_day:
        return [
            f"no watchdog run recorded for {stamp}: the task produced no log line, "
            "so its body never executed (a host-level startup failure looks exactly "
            "like this)"
        ]

    found: list[str] = []
    parsed = [match for match in (LINE.match(line) for line in same_day) if match]
    if not parsed:
        found.append(f"watchdog line for {stamp} does not match the expected format")
        return found

    latest = parsed[-1]
    if int(latest["reads"]) != 0:
        found.append(f"PHASE8 SEAL BROKEN: holdout_reads={latest['reads']} on {stamp}")
    return found


def check(log: Path, expected_date: dt.date) -> int:
    """Exit-code form of :func:`reasons` — 0 only when nothing is wrong."""
    return 1 if reasons(log, expected_date) else 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log", type=Path, default=DEFAULT_LOG)
    parser.add_argument(
        "--date",
        default=None,
        help="session date to audit (default: yesterday, the last run that must have finished)",
    )
    arguments = parser.parse_args()
    expected = (
        dt.date.fromisoformat(arguments.date)
        if arguments.date
        else dt.date.today() - dt.timedelta(days=1)
    )
    found = reasons(arguments.log, expected)
    for reason in found:
        print(f"[phase8-watchdog] FAIL: {reason}")
    if not found:
        print(f"[phase8-watchdog] {expected.isoformat()}: watchdog ran, seal intact")
    raise SystemExit(1 if found else 0)


if __name__ == "__main__":
    main()
