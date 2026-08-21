"""An MDS650 scheduled task that will never run again must not look healthy.

MDS650_UW_LatencyWatchdog was registered from a -Once trigger decorated with a
seven-hour repetition. It fired every 30 minutes from 2026-08-17 23:40 until
2026-08-18 06:40 and then went dead. Windows reported it State=Ready with an
empty NextRunTime, which is indistinguishable from healthy at a glance — and
the three sessions that truncated on 08-18, 08-19 and 08-20 all ran unwatched.

An empty NextRunTime on an enabled task is the whole signal. It needs no
heuristics: the task is enabled, so it is meant to run, and Windows is saying it
never will again.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "verify_scheduled_tasks.py"


def _load() -> Any:
    spec = importlib.util.spec_from_file_location("verify_scheduled_tasks", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["verify_scheduled_tasks"] = module
    spec.loader.exec_module(module)
    return module


def _task(name: str, **overrides: Any) -> dict[str, Any]:
    task = {
        "Name": name,
        "State": "Ready",
        "Next": "22/08/2026 6:20:00 AM",
        "Trigger": "MSFT_TaskDailyTrigger",
        "LastResult": "0x00000000",
        "RepDuration": "",
    }
    task.update(overrides)
    return task


HEALTHY = [
    _task("MDS650_UW_LatencyCollector"),
    _task("MDS650_UW_LatencyWatchdog"),
    _task("MDS650_UW_LatencyPostCheck"),
]


def test_healthy_fleet_passes() -> None:
    assert _load().reasons(HEALTHY, expected=[]) == []


def test_expired_trigger_is_reported() -> None:
    """The exact 2026-08-18 shape: enabled, Ready, and never running again."""
    module = _load()
    fleet = [*HEALTHY[:2], _task("MDS650_UW_LatencyWatchdog", Next="")]
    found = module.reasons(fleet, expected=[])
    assert found
    assert any("MDS650_UW_LatencyWatchdog" in reason for reason in found)


def test_short_repetition_one_shot_is_reported() -> None:
    """PT7H is what killed the UW watchdog: one window, then silence."""
    module = _load()
    fleet = [
        _task("MDS650_UW_LatencyWatchdog", Trigger="MSFT_TaskTimeTrigger", RepDuration="PT7H")
    ]
    assert module.reasons(fleet, expected=[])


def test_long_repetition_one_shot_is_not_reported() -> None:
    """MDS650_AlertForwarder uses P3650D and does not expire until 2036."""
    module = _load()
    fleet = [
        _task("MDS650_AlertForwarder", Trigger="MSFT_TaskTimeTrigger", RepDuration="P3650D")
    ]
    assert module.reasons(fleet, expected=[]) == []


def test_disabled_task_is_not_reported() -> None:
    """A task the owner turned off is a decision, not a failure."""
    module = _load()
    fleet = [_task("MDS650_Knowledge_AutoSync", State="Disabled", Next="")]
    assert module.reasons(fleet, expected=[]) == []


def test_failing_last_result_is_reported() -> None:
    """0xE0434352 is what the Phase 8 watchdog returned when pwsh died."""
    module = _load()
    fleet = [_task("MDS650_Phase8A_CollectionWatch", LastResult="0xE0434352")]
    assert module.reasons(fleet, expected=[])


def test_missing_expected_task_is_reported() -> None:
    """A task that was deleted cannot be observed as unhealthy; it must be named."""
    module = _load()
    found = module.reasons([_task("MDS650_UW_LatencyCollector")], expected=["MDS650_Absent_Task"])
    assert any("MDS650_Absent_Task" in reason for reason in found)


def test_check_returns_exit_code() -> None:
    module = _load()
    assert module.check(HEALTHY, expected=[]) == 0
    assert module.check([_task("MDS650_UW_LatencyWatchdog", Next="")], expected=[]) == 1
