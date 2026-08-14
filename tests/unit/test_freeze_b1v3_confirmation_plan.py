from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import exchange_calendars as xcals  # type: ignore[import-untyped]
import pytest
from scripts.freeze_b1v3_confirmation_plan import freeze_confirmation_plan, main

from mds650.b1v3_confirmation import (
    B1V3_PREFLIGHT_ASSETS,
    ExposureSource,
    build_confirmation_plan,
    build_session_exposure_ledger,
    canonical_sha256,
)

ROOT = Path(__file__).parents[2]
SCHEMA = ROOT / "specs/001-pit-options-rv30/contracts/b1v3-confirmation-plan.schema.json"


def _sessions(count: int = 90) -> list[str]:
    calendar = xcals.get_calendar("XNYS")
    return [
        value.date().isoformat()
        for value in calendar.sessions_in_range("2024-08-02", "2025-02-24")[:count]
    ]


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def _provider_report(sessions: list[str]) -> dict[str, object]:
    records: dict[str, list[dict[str, object]]] = {
        "fmp": [],
        "massive": [],
        "unusual_whales": [],
    }
    for session in sessions:
        for asset in B1V3_PREFLIGHT_ASSETS:
            records["fmp"].append(
                {"provider": "fmp", "session_date": session, "asset": asset, "pass": True}
            )
            records["massive"].append(
                {
                    "provider": "massive",
                    "session_date": session,
                    "asset": asset,
                    "pass": True,
                    "primary_filter_pass": False,
                }
            )
        records["unusual_whales"].append(
            {
                "provider": "unusual_whales",
                "session_date": session,
                "asset": None,
                "pass": True,
            }
        )
    report: dict[str, object] = {
        "schema_version": "b1v3-provider-preflight-report-2.0",
        "status": "PASS_PROVIDER_PREFLIGHT_ASSUMPTION_BOUND",
        "target_blind": True,
        "safe_to_acquire_predictors": True,
        "safe_to_read_outcomes": False,
        "outcome_read_count": 0,
        "provider_counts": {
            "fmp": {"expected": len(sessions) * 8, "passed": len(sessions) * 8},
            "massive": {"expected": len(sessions) * 8, "passed": len(sessions) * 8},
            "unusual_whales": {"expected": len(sessions), "passed": len(sessions)},
        },
        "records": records,
    }
    report["report_sha256"] = canonical_sha256(report)
    return report


def _package(tmp_path: Path) -> tuple[Path, Path, Path]:
    sessions = _sessions()
    exposure_source = tmp_path / "prior_dates.json"
    _write_json(exposure_source, {"sessions": ["2025-01-02"]})
    ledger = build_session_exposure_ledger(
        (ExposureSource("prior_dates", exposure_source),)
    )
    candidates = [
        value.date().isoformat()
        for value in xcals.get_calendar("XNYS").sessions_in_range(
            date(2024, 8, 2), date(2025, 2, 24)
        )
    ]
    pending = build_confirmation_plan(
        exposure_ledger=ledger,
        candidate_sessions=candidates,
        provider_passed_sessions=None,
    )
    ledger_path = tmp_path / "ledger.json"
    pending_path = tmp_path / "pending.json"
    report_path = tmp_path / "provider.json"
    _write_json(ledger_path, ledger)
    _write_json(pending_path, pending)
    _write_json(report_path, _provider_report(sessions))
    return ledger_path, pending_path, report_path


def test_freezer_binds_report_and_preserves_outcome_gate(tmp_path: Path) -> None:
    ledger_path, pending_path, report_path = _package(tmp_path)
    output = tmp_path / "frozen.json"

    plan = freeze_confirmation_plan(
        exposure_ledger_path=ledger_path,
        pending_plan_path=pending_path,
        provider_report_path=report_path,
        schema_path=SCHEMA,
        output_path=output,
    )

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert plan["status"] == "PASS_PRISTINE_60_30_FROZEN"
    assert plan["safe_to_acquire"] is True
    assert plan["safe_to_read_outcomes"] is False
    assert plan["outcome_read_count"] == 0
    assert plan["provider_preflight"]["report_sha256"] == report["report_sha256"]
    assert len(plan["training_sessions"]) == 60
    assert len(plan["confirmation_sessions"]) == 30
    before = output.read_bytes()
    freeze_confirmation_plan(
        exposure_ledger_path=ledger_path,
        pending_plan_path=pending_path,
        provider_report_path=report_path,
        schema_path=SCHEMA,
        output_path=output,
    )
    assert output.read_bytes() == before


def test_freezer_rejects_tampered_pending_plan(tmp_path: Path) -> None:
    ledger_path, pending_path, report_path = _package(tmp_path)
    pending = json.loads(pending_path.read_text(encoding="utf-8"))
    pending["candidate_session_count"] = 1
    _write_json(pending_path, pending)

    with pytest.raises(ValueError, match="B1V3_PENDING_PLAN_HASH_INVALID"):
        freeze_confirmation_plan(
            exposure_ledger_path=ledger_path,
            pending_plan_path=pending_path,
            provider_report_path=report_path,
            schema_path=SCHEMA,
            output_path=tmp_path / "frozen.json",
        )


def test_freezer_cli_help_is_directly_executable() -> None:
    with pytest.raises(SystemExit, match="0"):
        main(["--help"])
