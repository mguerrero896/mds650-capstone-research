"""Tests for the sign-agnostic independent-replication freeze."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import exchange_calendars as xcals
import pytest
from jsonschema import Draft202012Validator

from mds650.b1_independent_replication import (
    build_exposure_ledger,
    build_replication_preregistration,
    build_replication_provider_preflight_plan,
    collect_exposed_result_dates,
)
from mds650.b1v3_evaluation import b1v3_information_sets, b1v3_method_contract


def _sessions(start: str, end: str) -> list[str]:
    calendar = xcals.get_calendar("XNYS")
    return [str(value.date()) for value in calendar.sessions_in_range(start, end)]


TRAINING = _sessions("2024-09-16", "2024-12-09")
REPLICATION = _sessions("2024-12-10", "2025-01-24")
ROOT = Path(__file__).resolve().parents[2]


def test_exposure_ledger_freezes_exact_disjoint_xnys_sessions() -> None:
    ledger = build_exposure_ledger(
        training_sessions=TRAINING,
        replication_sessions=REPLICATION,
        exposed_result_dates=["2024-10-28", "2025-07-03"],
        prior_evidence_cutoff_session=date.fromisoformat("2024-12-09"),
        design_sha256="a" * 64,
    )
    assert ledger["status"] == "FROZEN_DATE_ONLY_ZERO_READS"
    assert len(ledger["training_sessions"]) == 60
    assert len(ledger["replication_sessions"]) == 30
    assert ledger["replication_target_reads"] == 0
    assert ledger["overlap_count"] == 0


def test_exposed_date_collection_is_allowlisted_and_conservative() -> None:
    dates = collect_exposed_result_dates(
        phase5_ledger={
            "status": "PASS_DATE_ONLY_EXPOSURE_LEDGER",
            "exposed_sessions": ["2025-07-01", "2025-07-02"],
        },
        b1v3_plan={
            "status": "PASS_PRISTINE_60_30_FROZEN",
            "training_sessions": ["2024-08-02"],
            "confirmation_sessions": ["2024-12-09"],
        },
        independent_window={
            "status": "READY_FOR_BOUNDED_BODY_ACQUISITION",
            "all_dates": ["2026-01-02"],
        },
    )
    assert dates == [
        "2024-08-02",
        "2024-12-09",
        "2025-07-01",
        "2025-07-02",
        "2026-01-02",
    ]

    with pytest.raises(ValueError, match="EXPOSURE_SOURCE_STATUS_INVALID"):
        collect_exposed_result_dates(
            phase5_ledger={"status": "FAIL", "exposed_sessions": []},
            b1v3_plan={
                "status": "PASS_PRISTINE_60_30_FROZEN",
                "training_sessions": [],
                "confirmation_sessions": [],
            },
            independent_window={
                "status": "READY_FOR_BOUNDED_BODY_ACQUISITION",
                "all_dates": [],
            },
        )


def test_exposure_ledger_fails_on_prior_exposure_or_non_session() -> None:
    with pytest.raises(ValueError, match="REPLICATION_DATE_PREVIOUSLY_EXPOSED"):
        build_exposure_ledger(
            training_sessions=TRAINING,
            replication_sessions=REPLICATION,
            exposed_result_dates=[REPLICATION[0]],
            prior_evidence_cutoff_session=date.fromisoformat("2024-12-09"),
            design_sha256="a" * 64,
        )
    invalid = [*REPLICATION[:-1], "2026-05-09"]
    with pytest.raises(ValueError, match="REPLICATION_SESSION_INVALID"):
        build_exposure_ledger(
            training_sessions=TRAINING,
            replication_sessions=invalid,
            exposed_result_dates=[],
            prior_evidence_cutoff_session=date.fromisoformat("2024-12-09"),
            design_sha256="a" * 64,
        )


def test_preregistration_freezes_existing_method_and_accepts_every_sign() -> None:
    ledger = build_exposure_ledger(
        training_sessions=TRAINING,
        replication_sessions=REPLICATION,
        exposed_result_dates=[],
        prior_evidence_cutoff_session=date.fromisoformat("2024-12-09"),
        design_sha256="a" * 64,
    )
    preregistration = build_replication_preregistration(
        exposure_ledger=ledger,
        design_sha256="a" * 64,
        code_sha256="b" * 64,
        uv_lock_sha256="c" * 64,
    )
    assert preregistration["status"] == "FROZEN_BEFORE_PROVIDER_PAYLOAD"
    assert preregistration["information_sets"] == {
        name: list(features) for name, features in b1v3_information_sets().items()
    }
    assert preregistration["method"] == b1v3_method_contract()
    assert preregistration["replication_target_reads"] == 0
    assert preregistration["permitted_terminal_states"] == [
        "REPLICATED_MODEL_INDEPENDENT",
        "REPLICATED_GAMMA_ONLY",
        "NOT_REPLICATED",
        "INVALID_REPLICATION",
    ]
    assert preregistration["result_sign_selection"] == "PROHIBITED"
    contracts = ROOT / "specs/001-pit-options-rv30/contracts"
    for name, document in (
        ("b1-independent-replication-exposure-v1.schema.json", ledger),
        ("b1-independent-replication-preregistration-v1.schema.json", preregistration),
    ):
        schema = json.loads((contracts / name).read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        assert not list(Draft202012Validator(schema).iter_errors(document))


def test_provider_preflight_plan_is_six_asset_thirty_session_target_blind() -> None:
    ledger = build_exposure_ledger(
        training_sessions=TRAINING,
        replication_sessions=REPLICATION,
        exposed_result_dates=[],
        prior_evidence_cutoff_session=date.fromisoformat("2024-12-09"),
        design_sha256="a" * 64,
    )
    preregistration = build_replication_preregistration(
        exposure_ledger=ledger,
        design_sha256="a" * 64,
        code_sha256="b" * 64,
        uv_lock_sha256="c" * 64,
    )
    plan = build_replication_provider_preflight_plan(preregistration)
    mapping = plan.to_mapping()
    assert mapping["outcome_read_count"] == 0
    assert mapping["training_session_count"] == 0
    assert mapping["confirmation_session_count"] == 30
    assert mapping["assets"] == ["AAPL", "AMZN", "META", "MSFT", "NVDA", "TSLA"]
    assert [row["date"] for row in mapping["sessions"]] == REPLICATION
    assert {row["role"] for row in mapping["sessions"]} == {"confirmation"}

    schema = json.loads(
        (
            ROOT
            / "specs/001-pit-options-rv30/contracts/"
            "b1-independent-replication-provider-plan-v1.schema.json"
        ).read_text(encoding="utf-8")
    )
    Draft202012Validator.check_schema(schema)
    assert not list(Draft202012Validator(schema).iter_errors(mapping))
