"""The UW latency verifier must fail closed on incomplete sessions.

Three unattended sessions (2026-08-18/19/20) terminated before the configured
close and never wrote ``collector_summary.json``. Every one of them still
produced a green ``capture_report.json`` because the only gate was a per-asset
``count == 0`` check. The fixtures below reproduce each real failure mode with
the measured numbers from those sessions:

===========  =======  ======  ===========================  =================
session      summary  cycles  last observation vs close    heartbeat staleness
===========  =======  ======  ===========================  =================
2026-08-17   present  384     +11s (past close)            fresh
2026-08-18   ABSENT   58      -332 min                     351 min
2026-08-19   ABSENT   273     -110 min                     130 min
2026-08-20   ABSENT   273     -110 min                     129 min
===========  =======  ======  ===========================  =================

Fixtures are synthetic and live under ``tmp_path``; ``MDS650_EXTERNAL_ROOT``
redirects the verifier away from the real ``D:/MDS650`` store.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "uw_latency_verify.py"

SESSION = dt.date(2026, 8, 20)
# The collector polls until 16:05 America/New_York (close_ny in
# scripts/uw_latency_collector.py), i.e. 20:05Z for this session.
CLOSE = dt.datetime(2026, 8, 20, 20, 5, tzinfo=dt.UTC)
ASSETS = ("AAPL", "AMZN", "META", "MSFT", "NVDA", "TSLA")


def _load_verifier(external_root: Path) -> Any:
    """Import uw_latency_verify with DATA_ROOT bound to a throwaway store.

    The module resolves DATA_ROOT from the environment at import time, so the
    variable must be set before the spec is executed and the module must be
    re-imported for every fixture.
    """
    import os

    os.environ["MDS650_EXTERNAL_ROOT"] = str(external_root)
    sys.modules.pop("uw_latency_verify", None)
    spec = importlib.util.spec_from_file_location("uw_latency_verify", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["uw_latency_verify"] = module
    spec.loader.exec_module(module)
    return module


def _write_session(
    root: Path,
    *,
    records_per_asset: int,
    last_observation: dt.datetime,
    heartbeat: dt.datetime | None,
    summary_finished: dt.datetime | None,
    cycles: int,
) -> Path:
    """Materialise one synthetic session directory."""
    session_dir = root / "uw_latency" / "sessions" / SESSION.isoformat()
    session_dir.mkdir(parents=True, exist_ok=True)

    total = records_per_asset * len(ASSETS)
    lines = []
    for index in range(total):
        asset = ASSETS[index % len(ASSETS)]
        # Spread receipts backwards from the last observation, one minute apart,
        # so the newest line carries `last_observation` exactly.
        stamp = last_observation - dt.timedelta(minutes=(total - 1 - index))
        lines.append(
            json.dumps(
                {
                    "kind": "observation",
                    "asset": asset,
                    "receipt_utc": stamp.isoformat(),
                    "record_id": f"synthetic-{index}",
                    "record": {"synthetic": True},
                }
            )
        )
    (session_dir / "observations.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")

    if heartbeat is not None:
        (session_dir / "heartbeat.json").write_text(
            json.dumps(
                {
                    "utc": heartbeat.isoformat(),
                    "cycle": cycles,
                    "observed_records": total,
                    "pid": 4242,
                }
            ),
            encoding="utf-8",
        )
    if summary_finished is not None:
        (session_dir / "collector_summary.json").write_text(
            json.dumps(
                {
                    "session": SESSION.isoformat(),
                    "cycles": cycles,
                    "observed_records": total,
                    "finished_utc": summary_finished.isoformat(),
                    "dry_run": False,
                },
                indent=1,
            ),
            encoding="utf-8",
        )
    return session_dir


def _complete_session(root: Path) -> Path:
    """A session that closed properly — the 2026-08-17 shape."""
    return _write_session(
        root,
        records_per_asset=40,
        last_observation=CLOSE + dt.timedelta(seconds=11),
        heartbeat=CLOSE + dt.timedelta(minutes=4),
        summary_finished=CLOSE + dt.timedelta(minutes=5),
        cycles=384,
    )


def test_complete_session_passes(tmp_path: Path) -> None:
    """The one session that really closed must stay green."""
    _complete_session(tmp_path)
    verifier = _load_verifier(tmp_path)
    assert verifier._verify(SESSION) == 0


def test_missing_collector_summary_fails(tmp_path: Path) -> None:
    """No summary means the collector never reached its finally block."""
    _write_session(
        tmp_path,
        records_per_asset=40,
        last_observation=CLOSE + dt.timedelta(seconds=11),
        heartbeat=CLOSE + dt.timedelta(minutes=4),
        summary_finished=None,
        cycles=384,
    )
    verifier = _load_verifier(tmp_path)
    assert verifier._verify(SESSION) != 0


def test_early_termination_fails(tmp_path: Path) -> None:
    """2026-08-19/20 stopped 110 minutes before the configured close."""
    stopped = CLOSE - dt.timedelta(minutes=110)
    _write_session(
        tmp_path,
        records_per_asset=40,
        last_observation=stopped,
        heartbeat=stopped,
        summary_finished=stopped,
        cycles=273,
    )
    verifier = _load_verifier(tmp_path)
    assert verifier._verify(SESSION) != 0


def test_stale_final_heartbeat_fails(tmp_path: Path) -> None:
    """A heartbeat 129 minutes older than the close cannot certify the session."""
    _write_session(
        tmp_path,
        records_per_asset=40,
        last_observation=CLOSE + dt.timedelta(seconds=11),
        heartbeat=CLOSE - dt.timedelta(minutes=129),
        summary_finished=CLOSE + dt.timedelta(minutes=5),
        cycles=273,
    )
    verifier = _load_verifier(tmp_path)
    assert verifier._verify(SESSION) != 0


def test_short_temporal_coverage_fails(tmp_path: Path) -> None:
    """2026-08-18 ran 58 of ~384 cycles and stopped 332 minutes early."""
    stopped = CLOSE - dt.timedelta(minutes=332)
    _write_session(
        tmp_path,
        records_per_asset=40,
        last_observation=stopped,
        heartbeat=stopped,
        summary_finished=stopped,
        cycles=58,
    )
    verifier = _load_verifier(tmp_path)
    assert verifier._verify(SESSION) != 0


def test_summary_inconsistent_with_observations_fails(tmp_path: Path) -> None:
    """A summary that disagrees with the tape it claims to describe is not evidence."""
    session_dir = _complete_session(tmp_path)
    summary_path = session_dir / "collector_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["observed_records"] = summary["observed_records"] + 500
    summary_path.write_text(json.dumps(summary, indent=1), encoding="utf-8")
    verifier = _load_verifier(tmp_path)
    assert verifier._verify(SESSION) != 0


@pytest.mark.parametrize("missing_asset", ["AAPL", "TSLA"])
def test_absent_asset_still_fails(tmp_path: Path, missing_asset: str) -> None:
    """The pre-existing per-asset gate must survive the hardening."""
    session_dir = _complete_session(tmp_path)
    observations = session_dir / "observations.jsonl"
    kept = [
        line
        for line in observations.read_text(encoding="utf-8").splitlines()
        if json.loads(line)["asset"] != missing_asset
    ]
    observations.write_text("\n".join(kept) + "\n", encoding="utf-8")
    verifier = _load_verifier(tmp_path)
    assert verifier._verify(SESSION) != 0


REGISTER_SCRIPT = ROOT / "scripts" / "register_uw_latency_tasks.ps1"
COLLECTOR = ROOT / "scripts" / "uw_latency_collector.py"


def test_watchdog_trigger_is_daily_not_once() -> None:
    """A -Once trigger dies after its RepetitionDuration.

    That is why MDS650_UW_LatencyWatchdog stopped after 2026-08-18 06:40 with an
    empty NextRunTime and left three truncated sessions unwatched.
    """
    source = REGISTER_SCRIPT.read_text(encoding="utf-8")
    assert "$trigger = New-ScheduledTaskTrigger -Daily -At $Time" in source
    # The repetition is copied onto the daily trigger, never used as the trigger.
    assert "$trigger.Repetition = $pattern.Repetition" in source
    assert "$trigger = New-ScheduledTaskTrigger -Once" not in source


def test_cooperative_cancellation_raises_keyboard_interrupt() -> None:
    """Signals must unwind through Python so the terminal summary reaches disk."""
    import signal as signal_module

    spec = importlib.util.spec_from_file_location("uw_latency_collector_probe", COLLECTOR)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["uw_latency_collector_probe"] = module
    spec.loader.exec_module(module)

    previous = {
        name: signal_module.getsignal(getattr(signal_module, name))
        for name in ("SIGINT", "SIGTERM", "SIGBREAK")
        if hasattr(signal_module, name)
    }
    try:
        module._install_cancellation()
        for name in previous:
            handler = signal_module.getsignal(getattr(signal_module, name))
            assert callable(handler), f"{name} handler was not installed"
            with pytest.raises(KeyboardInterrupt):
                handler(getattr(signal_module, name), None)
    finally:
        for name, handler in previous.items():
            signal_module.signal(getattr(signal_module, name), handler)


def test_collector_records_termination_mode() -> None:
    """The summary must say how the session ended, not merely that it ended."""
    source = COLLECTOR.read_text(encoding="utf-8")
    assert '"termination": termination' in source
    assert 'termination = "cancelled"' in source
    assert 'termination = "normal"' in source
    # The default must be the pessimistic one: anything that skips both
    # assignments was killed, and must not be recorded as a clean close.
    assert 'termination = "killed"' in source


def test_watchdog_recovered_session_is_not_a_false_failure(tmp_path: Path) -> None:
    """A restarted collector's summary describes only its own run.

    _watchdog restarts a stalled collector via schtasks; the new process re-enters
    main() with its counters at zero and appends to the same observations.jsonl.
    Requiring summary.observed_records to equal the whole tape would turn every
    successful recovery into a red session — and the -Daily trigger fix in this
    same change is what makes recoveries happen again.
    """
    session_dir = _complete_session(tmp_path)
    summary_path = session_dir / "collector_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["observed_records"] = 90  # second run only; the tape holds 240
    summary["cycles"] = 140
    summary_path.write_text(json.dumps(summary, indent=1), encoding="utf-8")
    verifier = _load_verifier(tmp_path)
    assert verifier._verify(SESSION) == 0


def test_non_normal_termination_fails(tmp_path: Path) -> None:
    """A summary that says it was killed cannot certify the session."""
    session_dir = _complete_session(tmp_path)
    summary_path = session_dir / "collector_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["termination"] = "killed"
    summary_path.write_text(json.dumps(summary, indent=1), encoding="utf-8")
    verifier = _load_verifier(tmp_path)
    assert verifier._verify(SESSION) != 0
