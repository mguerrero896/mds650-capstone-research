from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

import exchange_calendars as xcals
from jsonschema import Draft202012Validator, FormatChecker
from scripts.generate_date_level_pit_preflight_plan_v1 import (
    build_plan,
    canonical_json,
    render_plan,
)

ROOT = Path(__file__).resolve().parents[2]
ARTIFACT_PATH = ROOT / "artifacts/preflight/date_level_pit_preflight_plan_v1.json"
SCHEMA_PATH = (
    ROOT / "specs/001-pit-options-rv30/contracts/date-level-pit-preflight-plan-v1.schema.json"
)
MATERIAL_PATHS = (
    ROOT / "scripts/generate_date_level_pit_preflight_plan_v1.py",
    SCHEMA_PATH,
    ROOT / "docs/date_level_pit_preflight_plan_v1.md",
    ARTIFACT_PATH,
)
EXPECTED_ASSETS = ("SPY", "QQQ", "AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "META")
EXPECTED_SCENARIOS = {
    "2025-10-20": "ANOMALY_UW",
    "2025-11-28": "EARLY_CLOSE",
    "2025-12-24": "EARLY_CLOSE",
    "2026-01-20": "WINTER_REGULAR",
    "2026-03-06": "PRE_DST",
    "2026-03-09": "POST_DST",
    "2026-07-13": "SUMMER_REGULAR",
}


def test_build_plan_uses_exact_assets_and_sentinel_dates() -> None:
    plan = build_plan()

    assert tuple(plan["assets"]) == EXPECTED_ASSETS
    assert tuple(session["date"] for session in plan["sentinel_sessions"]) == tuple(
        EXPECTED_SCENARIOS
    )


def test_build_plan_covers_required_scenarios_once() -> None:
    plan = build_plan()

    assert {session["date"]: session["scenario"] for session in plan["sentinel_sessions"]} == (
        EXPECTED_SCENARIOS
    )


def test_build_plan_marks_valid_xnys_sessions_with_calendar_metadata() -> None:
    calendar = xcals.get_calendar("XNYS")
    plan = build_plan()

    for session in plan["sentinel_sessions"]:
        metadata = session["calendar_metadata"]
        assert calendar.is_session(session["date"])
        assert metadata["calendar"] == "XNYS"
        assert metadata["timezone"] == "America/New_York"
        assert metadata["is_xnys_session"] is True
        assert metadata["session_type"] in {"REGULAR", "EARLY_CLOSE"}
        assert metadata["open_utc"].endswith("+00:00")
        assert metadata["close_utc"].endswith("+00:00")

    sessions = {session["date"]: session for session in plan["sentinel_sessions"]}
    assert sessions["2025-11-28"]["calendar_metadata"]["session_type"] == "EARLY_CLOSE"
    assert sessions["2025-12-24"]["calendar_metadata"]["session_type"] == "EARLY_CLOSE"
    assert sessions["2026-03-06"]["calendar_metadata"]["open_utc"] == "2026-03-06T14:30:00+00:00"
    assert sessions["2026-03-09"]["calendar_metadata"]["open_utc"] == "2026-03-09T13:30:00+00:00"


def test_build_plan_conforms_to_contract_schema() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = list(validator.iter_errors(build_plan()))

    assert errors == []


def test_build_plan_uses_a_semantic_self_hash() -> None:
    plan = build_plan()
    payload = dict(plan)
    actual_hash = payload.pop("semantic_self_hash")
    expected_hash = f"sha256:{hashlib.sha256(canonical_json(payload)).hexdigest()}"

    assert actual_hash == expected_hash


def test_render_plan_is_byte_deterministic() -> None:
    assert render_plan() == render_plan()
    assert render_plan().endswith(os.linesep.encode("ascii"))


def test_committed_plan_matches_generator_output() -> None:
    assert ARTIFACT_PATH.read_bytes() == render_plan()


def test_plan_materials_contain_no_personal_paths_or_credentials() -> None:
    personal_path = re.compile(r"(?:[A-Za-z]:\\Users\\|/Users/)")
    credential_assignment = re.compile(
        r"(?:api[_-]?key|token|password|secret)\s*(?:=|:)\s*['\"]?[A-Za-z0-9_-]{8,}",
        re.IGNORECASE,
    )

    for path in MATERIAL_PATHS:
        content = path.read_text(encoding="utf-8")
        assert personal_path.search(content) is None, path
        assert credential_assignment.search(content) is None, path
