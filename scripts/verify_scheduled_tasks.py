"""Report MDS650 scheduled tasks that are enabled but will never run again.

MDS650_UW_LatencyWatchdog sat at State=Ready with an empty NextRunTime from
2026-08-18 06:40 onward, because it had been registered from a -Once trigger
carrying a seven-hour repetition rather than a daily one. Nothing noticed, and
the collector ran unwatched through the three sessions that truncated.

An enabled task with no next run is the signal. The task is meant to run and
Windows is saying it will not, so there is nothing to interpret.

Usage:
    uv run python scripts/verify_scheduled_tasks.py
    uv run python scripts/verify_scheduled_tasks.py --from-json state.json
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path
from typing import Any

# Tasks that must exist. A deleted task reports nothing at all, so absence has
# to be checked separately from health.
EXPECTED = (
    "MDS650_UW_LatencyCollector",
    "MDS650_UW_LatencyWatchdog",
    "MDS650_UW_LatencyPostCheck",
    "MDS650_UW_LatencyReconcile",
    "MDS650_Phase8A_BlindCollector",
    "MDS650_Phase8A_CollectionWatch",
)
# A -Once trigger is not wrong by itself: MDS650_AlertForwarder uses one with a
# P3650D repetition and will not expire until 2036. What killed the UW watchdog
# was a -Once trigger whose repetition ran out the same night (PT7H) and never
# re-armed. So the rule is the duration, not the trigger class.
ONE_SHOT_TRIGGER = "MSFT_TaskTimeTrigger"
SHORT_REPETITION = re.compile(r"^PT(?:\d+H|\d+M|\d+S|\d+H\d+M)$")

POWERSHELL_QUERY = (
    "Get-ScheduledTask | Where-Object { $_.TaskName -match 'MDS650' } | ForEach-Object { "
    "$i = $_ | Get-ScheduledTaskInfo; [PSCustomObject]@{ Name=$_.TaskName; "
    "State=[string]$_.State; Next=[string]$i.NextRunTime; "
    "Trigger=[string]$_.Triggers[0].CimClass.CimClassName; "
    "RepDuration=[string]$_.Triggers[0].Repetition.Duration; "
    "LastResult=('0x{0:X8}' -f $i.LastTaskResult) } } | ConvertTo-Json -Depth 3"
)


def collect() -> list[dict[str, Any]]:
    """Read live task state via PowerShell."""
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", POWERSHELL_QUERY],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise SystemExit(f"cannot read scheduled tasks: {result.stderr.strip()[:200]}")
    parsed = json.loads(result.stdout)
    return parsed if isinstance(parsed, list) else [parsed]


def reasons(
    tasks: list[dict[str, Any]],
    expected: tuple[str, ...] | list[str] = EXPECTED,
) -> list[str]:
    """Return every reason the task fleet cannot be trusted to run."""
    found: list[str] = []
    present = {task.get("Name", "") for task in tasks}
    for name in expected:
        if name not in present:
            found.append(f"{name} does not exist; it was deleted or never registered")

    for task in tasks:
        name = task.get("Name", "<unnamed>")
        if str(task.get("State", "")).lower() == "disabled":
            continue  # an owner turned it off on purpose
        if not str(task.get("Next", "")).strip():
            found.append(
                f"{name} is enabled with no next run: its trigger has expired and it "
                "will never fire again"
            )
        duration = str(task.get("RepDuration", "")).strip()
        if task.get("Trigger") == ONE_SHOT_TRIGGER and SHORT_REPETITION.match(duration):
            found.append(
                f"{name} is a one-shot trigger whose repetition ends after {duration} and "
                "never re-arms; a nightly task needs MSFT_TaskDailyTrigger"
            )
        last = str(task.get("LastResult", "0x00000000"))
        if last not in ("0x00000000", "0x00041301", "0x00041303"):
            found.append(f"{name} last exited {last}")
    return found


def check(
    tasks: list[dict[str, Any]],
    expected: tuple[str, ...] | list[str] = EXPECTED,
) -> int:
    return 1 if reasons(tasks, expected) else 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-json", type=Path, default=None)
    arguments = parser.parse_args()
    tasks = (
        json.loads(arguments.from_json.read_text(encoding="utf-8"))
        if arguments.from_json
        else collect()
    )
    found = reasons(tasks)
    for reason in found:
        print(f"[tasks] FAIL: {reason}")
    if not found:
        print(f"[tasks] {len(tasks)} MDS650 task(s) healthy; every enabled one has a next run")
    raise SystemExit(1 if found else 0)


if __name__ == "__main__":
    main()
