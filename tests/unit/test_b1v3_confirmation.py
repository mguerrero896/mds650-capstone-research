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
    B1V3_PREFLIGHT_ASSETS,
    ExposureSource,
    build_confirmation_plan,
    build_session_exposure_ledger,
    canonical_sha256,
    enumerate_xnys_sessions,
    provider_passed_sessions_from_report,
    select_pristine_split,
    sha256_file,
    validate_confirmation_plan_schema,
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


def _provider_report(sessions: list[str]) -> dict[str, object]:
    records: dict[str, list[dict[str, object]]] = {
        "fmp": [],
        "massive": [],
        "unusual_whales": [],
    }
    for session in sessions:
        for asset in B1V3_PREFLIGHT_ASSETS:
            records["fmp"].append(
                {
                    "provider": "fmp",
                    "session_date": session,
                    "asset": asset,
                    "pass": True,
                }
            )
            records["massive"].append(
                {
                    "provider": "massive",
                    "session_date": session,
                    "asset": asset,
                    "pass": True,
                    "primary_filter_pass": asset != "AAPL",
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
    document: dict[str, object] = {
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
    document["report_sha256"] = canonical_sha256(document)
    return document


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


def test_empty_exposure_ledger_and_invalid_hash_chunk_fail_closed(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="B1V3_EXPOSURE_SOURCES_EMPTY"):
        build_session_exposure_ledger(())
    source = tmp_path / "source.json"
    source.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="B1V3_CONFIRMATION_HASH_CHUNK_INVALID"):
        sha256_file(source, chunk_size=0)


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
        provider_report_sha256="a" * 64,
    )

    assert plan["status"] == "PASS_PRISTINE_60_30_FROZEN"
    assert plan["safe_to_acquire"] is True
    assert plan["safe_to_read_outcomes"] is False
    assert len(plan["training_sessions"]) == 60
    assert len(plan["confirmation_sessions"]) == 30
    assert plan["exposed_overlap"] == []
    assert plan["provider_preflight"]["report_sha256"] == "a" * 64
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.validate(plan, schema)


def test_provider_report_derives_common_dates_from_technical_pass_not_freshness() -> None:
    sessions = _sessions("2024-08-01", 90)
    report = _provider_report(sessions)

    passed = provider_passed_sessions_from_report(report)

    assert list(passed) == sessions


def test_provider_report_fails_closed_on_hash_duplicate_or_incomplete_asset() -> None:
    sessions = _sessions("2024-08-01", 90)

    bad_hash = _provider_report(sessions)
    bad_hash["report_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="B1V3_PROVIDER_PREFLIGHT_HASH_INVALID"):
        provider_passed_sessions_from_report(bad_hash)

    duplicate = _provider_report(sessions)
    duplicate_records = duplicate["records"]
    assert isinstance(duplicate_records, dict)
    fmp_records = duplicate_records["fmp"]
    assert isinstance(fmp_records, list)
    fmp_records.append(dict(fmp_records[0]))
    duplicate["report_sha256"] = canonical_sha256(
        {key: value for key, value in duplicate.items() if key != "report_sha256"}
    )
    with pytest.raises(ValueError, match="B1V3_PROVIDER_PREFLIGHT_DUPLICATE_RECORD"):
        provider_passed_sessions_from_report(duplicate)

    incomplete = _provider_report(sessions)
    incomplete_records = incomplete["records"]
    assert isinstance(incomplete_records, dict)
    incomplete_fmp = incomplete_records["fmp"]
    assert isinstance(incomplete_fmp, list)
    incomplete_fmp.pop()
    incomplete["report_sha256"] = canonical_sha256(
        {key: value for key, value in incomplete.items() if key != "report_sha256"}
    )
    with pytest.raises(ValueError, match="B1V3_PROVIDER_PREFLIGHT_COUNT_INVALID"):
        provider_passed_sessions_from_report(incomplete)


def test_provider_report_rejects_gate_schema_and_record_drift() -> None:
    sessions = _sessions("2024-08-01", 90)

    bad_gate = _provider_report(sessions)
    bad_gate["safe_to_read_outcomes"] = True
    bad_gate["report_sha256"] = canonical_sha256(
        {key: value for key, value in bad_gate.items() if key != "report_sha256"}
    )
    with pytest.raises(ValueError, match="B1V3_PROVIDER_PREFLIGHT_GATE_INVALID"):
        provider_passed_sessions_from_report(bad_gate)

    bad_schema = _provider_report(sessions)
    bad_schema["records"] = []
    bad_schema["report_sha256"] = canonical_sha256(
        {key: value for key, value in bad_schema.items() if key != "report_sha256"}
    )
    with pytest.raises(ValueError, match="B1V3_PROVIDER_PREFLIGHT_SCHEMA_INVALID"):
        provider_passed_sessions_from_report(bad_schema)

    bad_record = _provider_report(sessions)
    records = bad_record["records"]
    assert isinstance(records, dict)
    uw_records = records["unusual_whales"]
    assert isinstance(uw_records, list)
    uw_records[0]["asset"] = "AAPL"
    bad_record["report_sha256"] = canonical_sha256(
        {key: value for key, value in bad_record.items() if key != "report_sha256"}
    )
    with pytest.raises(ValueError, match="B1V3_PROVIDER_PREFLIGHT_RECORD_INVALID"):
        provider_passed_sessions_from_report(bad_record)


def test_confirmation_schema_validator_rejects_missing_and_invalid_documents(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="B1V3_CONFIRMATION_SCHEMA_MISSING"):
        validate_confirmation_plan_schema({}, tmp_path / "missing.json")
    invalid_schema = tmp_path / "invalid-schema.json"
    invalid_schema.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="B1V3_CONFIRMATION_SCHEMA_INVALID"):
        validate_confirmation_plan_schema({}, invalid_schema)
    with pytest.raises(ValueError, match="B1V3_CONFIRMATION_SCHEMA_VALIDATION_FAILED"):
        validate_confirmation_plan_schema({}, SCHEMA_PATH)


def test_confirmation_plan_rejects_unexpected_or_invalid_provider_hash(tmp_path: Path) -> None:
    eligible = _sessions("2024-08-01", 95)
    ledger = build_session_exposure_ledger(
        (_source(tmp_path, "previous_study", [eligible[94]]),)
    )
    with pytest.raises(ValueError, match="B1V3_PROVIDER_REPORT_HASH_UNEXPECTED"):
        build_confirmation_plan(
            exposure_ledger=ledger,
            candidate_sessions=eligible,
            provider_passed_sessions=None,
            provider_report_sha256="a" * 64,
        )
    with pytest.raises(ValueError, match="B1V3_PROVIDER_REPORT_HASH_INVALID"):
        build_confirmation_plan(
            exposure_ledger=ledger,
            candidate_sessions=eligible,
            provider_passed_sessions=eligible[:90],
            provider_report_sha256="not-a-hash",
        )


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


def test_planner_freezes_from_self_hashed_v2_provider_report(tmp_path: Path) -> None:
    sessions = _sessions("2024-08-01", 90)
    source = _source(tmp_path, "previous_study", ["2025-01-02"])
    report_path = tmp_path / "provider_preflight.json"
    report_path.write_text(json.dumps(_provider_report(sessions)), encoding="utf-8")

    _ledger, plan = plan_confirmation(
        exposure_sources=[source],
        candidate_start=date.fromisoformat(sessions[0]),
        candidate_end=date.fromisoformat(sessions[-1]),
        provider_preflight_path=report_path,
        ledger_path=tmp_path / "ledger.json",
        plan_path=tmp_path / "plan.json",
        schema_path=SCHEMA_PATH,
    )

    assert plan["status"] == "PASS_PRISTINE_60_30_FROZEN"
    assert plan["training_sessions"] == sessions[:60]
    assert plan["confirmation_sessions"] == sessions[60:]
    assert plan["provider_preflight"]["passed_session_count"] == 90


def test_cli_help_is_directly_executable() -> None:
    with pytest.raises(SystemExit, match="0"):
        main(["--help"])
