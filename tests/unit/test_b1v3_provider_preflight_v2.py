"""Target-blind tests for the B1v3 date-level provider preflight."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from mds650.b1v3_provider_preflight_v2 import (
    B1V3PreflightError,
    build_candidate_preflight_plan,
    build_request_budget,
    derive_xnys_calendar_sessions,
    validate_fmp_session,
    validate_json_schema,
    validate_massive_quote,
    validate_storage_gate,
    validate_uw_zip_headers,
)


def _confirmation_plan() -> dict[str, object]:
    training = [f"2024-08-{day:02d}" for day in range(1, 31)] + [
        f"2024-09-{day:02d}" for day in range(1, 31)
    ]
    confirmation = [f"2024-10-{day:02d}" for day in range(1, 31)]
    plan: dict[str, object] = {
        "status": "PENDING_DATE_LEVEL_PROVIDER_PREFLIGHT",
        "target_blind": True,
        "outcome_read_count": 0,
        "training_session_count": 60,
        "confirmation_session_count": 30,
        "training_sessions": training,
        "confirmation_sessions": confirmation,
    }
    plan["plan_sha256"] = hashlib.sha256(
        json.dumps(
            plan,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    return plan


def test_candidate_plan_binds_exact_60_30_without_outcome_fields() -> None:
    all_dates = (
        *_confirmation_plan()["training_sessions"],
        *_confirmation_plan()["confirmation_sessions"],
    )
    sessions = tuple(
        {
            "date": day,
            "open_utc": f"{day}T14:30:00+00:00",
            "close_utc": f"{day}T21:00:00+00:00",
            "forecast_origin_utc": f"{day}T17:45:00+00:00",
            "forecast_origin_ns": int(
                datetime.fromisoformat(f"{day}T17:45:00+00:00").timestamp() * 1_000_000_000
            ),
            "expected_regular_minutes": 390,
        }
        for day in all_dates
    )

    plan = build_candidate_preflight_plan(
        _confirmation_plan(),
        assets=("SPY", "QQQ", "AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "META"),
        calendar_sessions=sessions,
    )

    assert len(plan.sessions) == 90
    assert plan.training_session_count == 60
    assert plan.confirmation_session_count == 30
    assert plan.outcome_read_count == 0
    assert plan.target_blind is True
    assert len(plan.plan_sha256) == 64
    assert not any(
        token in plan.to_canonical_json().decode("utf-8").lower()
        for token in ("rv30", "qlike", "prediction", "loss")
    )


def test_candidate_budget_is_exact_and_attempt_capped() -> None:
    budget = build_request_budget(asset_count=8, session_count=90)

    assert budget.fmp_requests == 720
    assert budget.uw_requests == 90
    assert budget.massive_initial_search_requests == 720
    assert budget.massive_search_request_cap == 2160
    assert budget.massive_reference_requests == 720
    assert budget.massive_quote_requests == 720
    assert budget.http_attempt_cap == 4410


def test_xnys_calendar_derivation_handles_early_close() -> None:
    (session,) = derive_xnys_calendar_sessions(("2024-11-29",))

    assert session["expected_regular_minutes"] == 210
    assert session["open_utc"] == "2024-11-29T14:30:00+00:00"
    assert session["close_utc"] == "2024-11-29T18:00:00+00:00"
    assert int(session["forecast_origin_ns"]) % (5 * 60 * 1_000_000_000) == 0


def test_storage_gate_requires_eighty_gib() -> None:
    validate_storage_gate(free_bytes=80 * 1024**3)
    with pytest.raises(B1V3PreflightError, match="B1V3_PREFLIGHT_STORAGE_GATE_FAILED"):
        validate_storage_gate(free_bytes=80 * 1024**3 - 1)


def test_json_schema_boundary_passes_and_fails_closed(tmp_path: Path) -> None:
    schema = tmp_path / "schema.json"
    schema.write_text(
        '{"$schema":"https://json-schema.org/draft/2020-12/schema",'
        '"type":"object","required":["status"],'
        '"properties":{"status":{"const":"PASS"}}}',
        encoding="utf-8",
    )

    validate_json_schema({"status": "PASS"}, schema_path=schema, error_code="TEST")
    with pytest.raises(B1V3PreflightError, match="TEST_SCHEMA_VALIDATION_FAILED"):
        validate_json_schema({"status": "FAIL"}, schema_path=schema, error_code="TEST")
    with pytest.raises(B1V3PreflightError, match="TEST_SCHEMA_UNAVAILABLE"):
        validate_json_schema(
            {"status": "PASS"},
            schema_path=tmp_path / "missing.json",
            error_code="TEST",
        )


def test_fmp_exact_session_filters_provider_over_return() -> None:
    rows = [
        {"date": "2024-08-01 09:30:00", "open": 1, "high": 2, "low": 1, "close": 2},
        {"date": "2024-08-02 09:30:00", "open": 2, "high": 3, "low": 2, "close": 3},
        {"date": "2024-08-02 09:31:00", "open": 3, "high": 4, "low": 3, "close": 4},
    ]

    evidence = validate_fmp_session(
        rows,
        session_date="2024-08-02",
        expected_minutes=2,
        forecast_origin_utc=datetime(2024, 8, 2, 13, 35, tzinfo=UTC),
    )

    assert evidence.status == "PASS_EXACT_SESSION_AVAILABILITY"
    assert evidence.returned_row_count == 3
    assert evidence.exact_session_row_count == 2
    assert evidence.provider_over_return_count == 1
    assert evidence.spot == 4.0


def test_uw_zip_contract_uses_documented_get_without_range() -> None:
    evidence = validate_uw_zip_headers(
        status_code=200,
        headers={
            "content-type": "application/zip",
            "content-length": "1136248530",
            "x-request-id": "req-123",
        },
        method="GET",
        request_headers={"Accept": "application/json"},
    )

    assert evidence.status == "PASS_TRANSPORT_METADATA_ONLY"
    assert evidence.content_length_bytes == 1_136_248_530
    assert evidence.pit_claim is False
    assert evidence.full_tape_downloaded is False

    with pytest.raises(B1V3PreflightError, match="B1V3_PREFLIGHT_UW_UNDOCUMENTED_RANGE"):
        validate_uw_zip_headers(
            status_code=206,
            headers={"content-type": "application/zip", "content-length": "1"},
            method="GET",
            request_headers={"Range": "bytes=0-0"},
        )


def test_massive_quote_must_be_last_nonfuture_valid_nbbo() -> None:
    origin_ns = 1_722_603_300_000_000_000
    evidence = validate_massive_quote(
        {
            "results": [
                {
                    "sip_timestamp": origin_ns - 10_000_000_000,
                    "bid_price": 4.0,
                    "ask_price": 4.4,
                    "sequence_number": 7,
                }
            ]
        },
        forecast_origin_ns=origin_ns,
        contract_id="O:AAPL240920C00200000",
    )

    assert evidence.status == "PASS_QUOTE_ASOF_SOURCE_TIME"
    assert evidence.quote_age_seconds == 10.0
    assert evidence.relative_spread == pytest.approx(0.0952380952)
    assert evidence.pit_receipt_claim is False
    assert evidence.primary_filter_pass is True
    assert evidence.sensitivity_filter_pass is True

    with pytest.raises(B1V3PreflightError, match="B1V3_PREFLIGHT_MASSIVE_FUTURE_QUOTE"):
        validate_massive_quote(
            {
                "results": [
                    {
                        "sip_timestamp": origin_ns + 1,
                        "bid_price": 4.0,
                        "ask_price": 4.4,
                    }
                ]
            },
            forecast_origin_ns=origin_ns,
            contract_id="O:AAPL240920C00200000",
        )


def test_stale_massive_quote_is_available_but_fails_primary_filter() -> None:
    origin_ns = 1_722_603_300_000_000_000

    evidence = validate_massive_quote(
        {
            "results": [
                {
                    "sip_timestamp": origin_ns - 120_000_000_000,
                    "bid_price": 4.0,
                    "ask_price": 4.4,
                }
            ]
        },
        forecast_origin_ns=origin_ns,
        contract_id="O:AAPL240920C00200000",
    )

    assert evidence.status == "PASS_QUOTE_ASOF_SOURCE_TIME"
    assert evidence.quote_age_seconds == 120.0
    assert evidence.primary_filter_pass is False
    assert evidence.sensitivity_filter_pass is True


def test_candidate_plan_rejects_result_like_payload_key(tmp_path: Path) -> None:
    plan = _confirmation_plan()
    plan["qlike"] = 0.1
    with pytest.raises(B1V3PreflightError, match="B1V3_PREFLIGHT_FORBIDDEN_FIELD"):
        build_candidate_preflight_plan(
            plan,
            assets=("SPY", "QQQ", "AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "META"),
            calendar_sessions=(),
        )


def test_candidate_plan_rejects_tampered_confirmation_plan_hash() -> None:
    plan = _confirmation_plan()
    plan["training_session_count"] = 61

    with pytest.raises(B1V3PreflightError, match="B1V3_PREFLIGHT_CONFIRMATION_PLAN_HASH_INVALID"):
        build_candidate_preflight_plan(
            plan,
            assets=("SPY", "QQQ", "AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "META"),
            calendar_sessions=(),
        )
