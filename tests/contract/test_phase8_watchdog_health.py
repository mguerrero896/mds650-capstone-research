"""A Phase 8 watchdog that never started must not look like a healthy one.

On 2026-08-20 20:00:02 the watchdog task exited 0xE0434352. The .NET Runtime
1026 event puts the failure at ``Microsoft.PowerShell.ManagedPSEntry.Main`` —
pwsh could not bind ``System.Management.Automation 7.6.0.500`` and died before
the first line of ``phase8_watch.ps1`` ran. ``phase8_watch.log`` therefore has
lines for 08-17, 08-18 and 08-19 and none for 08-20.

That silence is unobservable from inside the watchdog, because its healthy path
deletes ``PHASE8_ALERT.txt``: a dead run and a clean run leave the same empty
state. This healthcheck runs out of band and fails closed on the absence.

It reads only the watchdog's own text log. It never opens the evaluator, the
holdout store, or the canonical repository root.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "phase8_watchdog_health.py"

# Verbatim shape of the real log, including the three healthy runs.
HEALTHY_LINES = [
    "2026-08-17T20:00:01 completed=20/30 expected>=20 reads=0",
    "2026-08-18T20:00:03 completed=21/30 expected>=20 reads=0",
    "2026-08-19T20:00:03 completed=22/30 expected>=21 reads=0",
]


def _load() -> Any:
    spec = importlib.util.spec_from_file_location("phase8_watchdog_health", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["phase8_watchdog_health"] = module
    spec.loader.exec_module(module)
    return module


def _log(tmp_path: Path, lines: list[str]) -> Path:
    path = tmp_path / "phase8_watch.log"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_run_recorded_for_expected_date_passes(tmp_path: Path) -> None:
    module = _load()
    log = _log(tmp_path, HEALTHY_LINES)
    assert module.check(log, dt.date(2026, 8, 19)) == 0


def test_missing_run_for_expected_date_fails(tmp_path: Path) -> None:
    """The real 2026-08-20 incident: three lines present, the fourth absent."""
    module = _load()
    log = _log(tmp_path, HEALTHY_LINES)
    assert module.check(log, dt.date(2026, 8, 20)) != 0


def test_absent_log_fails(tmp_path: Path) -> None:
    module = _load()
    assert module.check(tmp_path / "phase8_watch.log", dt.date(2026, 8, 19)) != 0


def test_empty_log_fails(tmp_path: Path) -> None:
    module = _load()
    log = _log(tmp_path, [])
    assert module.check(log, dt.date(2026, 8, 19)) != 0


def test_unparseable_line_for_expected_date_fails(tmp_path: Path) -> None:
    module = _load()
    log = _log(tmp_path, [*HEALTHY_LINES, "2026-08-20T20:00:03 garbage"])
    assert module.check(log, dt.date(2026, 8, 20)) != 0


def test_broken_seal_fails(tmp_path: Path) -> None:
    """A run that recorded a holdout read is a failure even though it ran."""
    module = _load()
    log = _log(
        tmp_path,
        [*HEALTHY_LINES, "2026-08-20T20:00:03 completed=23/30 expected>=22 reads=1"],
    )
    assert module.check(log, dt.date(2026, 8, 20)) != 0


def test_reasons_name_the_failure(tmp_path: Path) -> None:
    """The exit code alone is not evidence; the reason must be printable."""
    module = _load()
    log = _log(tmp_path, HEALTHY_LINES)
    reasons = module.reasons(log, dt.date(2026, 8, 20))
    assert reasons, "a failing check must explain itself"
    assert any("2026-08-20" in reason for reason in reasons)
