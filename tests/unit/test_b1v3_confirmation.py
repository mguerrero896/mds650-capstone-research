from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path

import exchange_calendars as xcals  # type: ignore[import-untyped]
import jsonschema
import pytest
from scripts.plan_b1v3_confirmation import main, plan_confirmation

from mds650.b1v3_confirmation import (
    ExposureSource,
    build_confirmation_plan,
    build_session_exposure_ledger,
    canonical_sha256,
    enumerate_xnys_sessions,
    select_pristine_split,
    write_json_if_identical,
)

ROOT = Path(__file__).parents[2]
SCHEMA_PATH = (
    ROOT / "specs" / "001-pit-options-rv30" / "contracts" / "b1v3-confirmation-plan.schema.json"
)


def _source(tmp_path: Path, name: str, dates: list[str]) -> ExposureSource:
    path = tmp_path / f"{name}.json"
    path.write_text(json.dumps({"sessions": dates}), encoding="utf-8")
    return ExposureSource(logical_name=name, path=path)


def _sessions(start: str, count: int) -> list[str]:
    calendar = xcals.get_calendar("XNYS")
    values = calendar.sessions_in_range(start, "2026-12-31")[:count]
    return [value.date().isoformat() for value in values]


def test_exposure_ledger_binds_sources_and_deduplicates_overlaps(tmp_path: Path) -> None:
    first = _source(tmp_path, "first", ["2025-01-02", "2025-01-03"])
    second = _source(tmp_path, "second", ["2025-01-03", "2025-01-06"])

    ledger = build_session_exposure_ledger((first, second))

    assert ledger["exposed_session_count"] == 3
    assert ledger["exposed_sessions"] == ["2025-01-02", "2025-01-03", "2025-01-06"]
    assert ledger["sessions"][1] == {
        "date": "2025-01-03",
        "source_logical_names": ["first", "second"],
    }
    assert ledger["ledger_sha256"] == canonical_sha256(
        {key: value for key, value in ledger.items() if key != "ledger_sha256"}
    )
    assert ledger["sources"][0]["sha256"] == hashlib.sha256(first.path.read_bytes()).hexdigest()
    assert str(tmp_path) not in json.dumps(ledger)


@pytest.mark.parametrize(
    ("logical_name", "dates", "error"),
    [
        ("", ["2025-01-02"], "B1V3_EXPOSURE_SOURCE_NAME_INVALID"),
        ("bad", ["not-a-date"], "B1V3_EXPOSURE_SOURCE_NO_DATES"),
        ("bad", ["2025-01-04"], "B1V3_EXPOSURE_NOT_XNYS_SESSION"),
    ],
)
def test_exposure_ledger_rejects_invalid_sources(
    tmp_path: Path,
    logical_name: str,
    dates: list[str],
    error: str,
) -> None:
    source = _source(tmp_path, logical_name or "physical", dates)
    source = ExposureSource(logical_name=logical_name, path=source.path)
    with pytest.raises(ValueError, match=error):
        build_session_exposure_ledger((source,))


def test_exposure_ledger_rejects_outcome_like_source_filename(tmp_path: Path) -> None:
    source = _source(tmp_path, "safe_name", ["2025-01-02"])
    forbidden = tmp_path / "qlike_results.json"
    forbidden.write_bytes(source.path.read_bytes())
    with pytest.raises(ValueError, match="B1V3_EXPOSURE_SOURCE_FORBIDDEN"):
        build_session_exposure_ledger((ExposureSource(logical_name="forbidden", path=forbidden),))


def test_pristine_selector_chooses_earliest_contiguous_60_30_block() -> None:
    eligible = _sessions("2024-08-01", 100)
    exposed = {eligible[0], eligible[1]}

    split = select_pristine_split(
        eligible_sessions=eligible,
        exposed_sessions=exposed,
        training_count=60,
        confirmation_count=30,
    )

    assert list(split.training_sessions) == eligible[2:62]
    assert list(split.confirmation_sessions) == eligible[62:92]
    assert not set(split.training_sessions) & set(split.confirmation_sessions)
    assert not set(split.all_sessions) & exposed


def test_pristine_selector_fails_on_gap_or_insufficient_sessions() -> None:
    eligible = _sessions("2024-08-01", 90)
    del eligible[45]

    with pytest.raises(ValueError, match="NO_PRISTINE_30_SESSION_BLOCK"):
        select_pristine_split(
            eligible_sessions=eligible,
            exposed_sessions=(),
            training_count=60,
            confirmation_count=30,
        )


def test_confirmation_plan_stays_pending_without_provider_passes(tmp_path: Path) -> None:
    eligible = _sessions("2024-08-01", 95)
    source = _source(tmp_path, "previous_study", ["2025-01-02"])
    ledger = build_session_exposure_ledger((source,))

    plan = build_confirmation_plan(
        exposure_ledger=ledger,
        candidate_sessions=eligible,
        provider_passed_sessions=None,
    )

    assert plan["status"] == "PENDING_DATE_LEVEL_PROVIDER_PREFLIGHT"
    assert plan["safe_to_acquire"] is False
    assert plan["safe_to_read_outcomes"] is False
    assert plan["training_sessions"] == eligible[:60]
    assert plan["confirmation_sessions"] == eligible[60:90]
    assert plan["provider_preflight"]["passed_session_count"] == 0
    assert plan["plan_sha256"] == canonical_sha256(
        {key: value for key, value in plan.items() if key != "plan_sha256"}
    )


def test_confirmation_plan_freezes_only_when_all_90_sessions_pass(tmp_path: Path) -> None:
    eligible = _sessions("2024-08-01", 95)
    source = _source(tmp_path, "previous_study", [eligible[94]])
    ledger = build_session_exposure_ledger((source,))

    plan = build_confirmation_plan(
        exposure_ledger=ledger,
        candidate_sessions=eligible,
        provider_passed_sessions=eligible[:90],
    )

    assert plan["status"] == "PASS_PRISTINE_60_30_FROZEN"
    assert plan["safe_to_acquire"] is True
    assert plan["safe_to_read_outcomes"] is False
    assert len(plan["training_sessions"]) == 60
    assert len(plan["confirmation_sessions"]) == 30
    assert plan["exposed_overlap"] == []
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.validate(plan, schema)


def test_confirmation_plan_fails_closed_on_partial_provider_passes(tmp_path: Path) -> None:
    eligible = _sessions("2024-08-01", 95)
    source = _source(tmp_path, "previous_study", [eligible[94]])
    ledger = build_session_exposure_ledger((source,))

    plan = build_confirmation_plan(
        exposure_ledger=ledger,
        candidate_sessions=eligible,
        provider_passed_sessions=eligible[:89],
    )

    assert plan["status"] == "NO_PRISTINE_30_SESSION_BLOCK"
    assert plan["training_sessions"] == []
    assert plan["confirmation_sessions"] == []
    assert plan["safe_to_acquire"] is False


def test_confirmation_plan_rejects_provider_dates_outside_candidates(tmp_path: Path) -> None:
    eligible = _sessions("2024-08-01", 95)
    source = _source(tmp_path, "previous_study", [eligible[94]])
    ledger = build_session_exposure_ledger((source,))
    outside = _sessions("2024-01-02", 90)

    with pytest.raises(ValueError, match="B1V3_PROVIDER_SESSIONS_OUTSIDE_CANDIDATES"):
        build_confirmation_plan(
            exposure_ledger=ledger,
            candidate_sessions=eligible,
            provider_passed_sessions=outside,
        )


def test_xnys_enumerator_observes_weekends_and_holidays() -> None:
    sessions = enumerate_xnys_sessions(date(2025, 7, 3), date(2025, 7, 7))
    assert sessions == ("2025-07-03", "2025-07-07")


def test_writer_is_idempotent_and_conflict_safe(tmp_path: Path) -> None:
    output = tmp_path / "manifest.json"
    payload = b'{"stable":true}\n'
    assert write_json_if_identical(output, payload) == "CREATED"
    assert write_json_if_identical(output, payload) == "IDENTICAL"
    with pytest.raises(ValueError, match="B1V3_CONFIRMATION_OUTPUT_CONFLICT"):
        write_json_if_identical(output, b'{"stable":false}\n')


def test_planner_writes_schema_valid_pending_outputs(tmp_path: Path) -> None:
    source = _source(tmp_path, "previous_study", ["2025-01-02"])
    ledger_path = tmp_path / "ledger.json"
    plan_path = tmp_path / "plan.json"

    ledger, plan = plan_confirmation(
        exposure_sources=[source],
        candidate_start=date(2024, 8, 1),
        candidate_end=date(2025, 1, 31),
        provider_preflight_path=None,
        ledger_path=ledger_path,
        plan_path=plan_path,
        schema_path=SCHEMA_PATH,
    )

    assert ledger_path.is_file()
    assert plan_path.is_file()
    assert ledger["target_blind"] is True
    assert plan["status"] == "PENDING_DATE_LEVEL_PROVIDER_PREFLIGHT"


def test_cli_help_is_directly_executable() -> None:
    with pytest.raises(SystemExit, match="0"):
        main(["--help"])
