"""Regression contracts for the target and PIT closure gate artifacts."""

from __future__ import annotations

import json
from pathlib import Path

import polars as pl
import pytest
from tests.evidence import require_evidence_root

pytestmark = pytest.mark.evidence

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _evidence_root() -> Path:
    """Return the mounted evidence package for the historical PIT gates."""
    return require_evidence_root(
        "artifacts/pit/fmp_bar_semantics_v3.json",
        "artifacts/pit/uw_created_at_semantics_v1.json",
        "artifacts/pit/common_history_continuity_v4.json",
        "artifacts/pit/canonical_forecast_origins.parquet",
        "artifacts/pit/pit_gate_final_report.json",
        "artifacts/api_audit/common_history_continuity_v5.json",
    )


def _pit() -> Path:
    return _evidence_root() / "artifacts" / "pit"


def _json(name: str) -> dict:
    return json.loads((_pit() / name).read_text(encoding="utf-8"))


def test_target_horizon_remains_rv30_and_rv10_is_not_introduced() -> None:
    text = (REPOSITORY_ROOT / "docs" / "target_horizon_decision.md").read_text(encoding="utf-8")
    assert "PASS_RV30_FROZEN" in text
    assert "rv10_introduced`: `false" in text
    assert "31 prices" in text and "30 one-minute log returns" in text


def test_fmp_probe_records_calendar_and_missing_minute_diagnostics() -> None:
    data = _json("fmp_bar_semantics_v3.json")
    assert data["status"] == "NO_VERIFICADO"
    assert data["bar_boundary_semantics"] == "NO VERIFICADO"
    assert len(data["records"]) == 40
    assert all(row["http_status"] == 200 for row in data["records"])
    assert all(row["observed_labels_consistent_with_start_bars"] for row in data["records"])
    assert any(row["missing_expected_start_labels"] for row in data["records"])
    assert all(row["close_label_alignment"] is False for row in data["records"])
    cross = data["cross_interval_probe"]
    assert cross["one_min_http_status"] == 200
    assert cross["five_min_http_status"] == 200
    assert cross["one_min_rows"] == 390
    assert cross["five_min_rows"] == 78
    assert cross["five_min_labels_matching_one_min_start_labels"] == 78
    assert cross["five_min_labels_matching_four_minutes_before_one_min_labels"] == 0
    assert cross["interpretation"] == "CONSISTENT_WITH_START_LABELS_NOT_CONTRACTUAL_PROOF"


def test_uw_created_at_remains_an_operational_proxy() -> None:
    data = _json("uw_created_at_semantics_v1.json")
    assert data["status"] == "NO_VERIFICADO"
    assert data["full_tape"]["publication_time_proven"] is False
    assert data["full_tape"]["operational_availability_proxy"] is True
    assert all(row["executed_at_present"] is False for row in data["records"])
    assert "trade record was created" in data["documentation"]["created_at_documented_as"]
    assert data["documentation"]["created_at_publication_semantics"] == "not defined"
    assert data["documentation"]["created_at_availability_semantics"] == "not defined"


def test_common_history_reports_observed_points_not_daily_continuity() -> None:
    data = _json("common_history_continuity_v4.json")
    assert data["status"] == "NO_VERIFICADO"
    assert data["daily_continuity_established"] is False
    assert data["expected_session_count"] > 200
    assert len(data["observed_common_dates_by_asset"]) == 8
    assert all(
        data["missing_sessions_by_asset"][asset]
        for asset in data["missing_sessions_by_asset"]
    )


def test_daily_common_history_v5_is_complete_bounded_and_sanitized() -> None:
    data = json.loads(
        (
            _evidence_root() / "artifacts" / "api_audit" / "common_history_continuity_v5.json"
        ).read_text(encoding="utf-8")
    )
    assert data["sessions_probed_count"] == 251
    assert len(data["records"]) == 251 * 8
    assert len({(row["asset"], row["date"]) for row in data["records"]}) == 251 * 8
    assert data["full_tape_downloaded"] is False
    assert data["raw_payloads_retained"] is False
    assert data["secret_values_emitted"] is False
    assert data["personal_paths_emitted"] is False
    assert data["common_dates_all_assets_count"] == 233
    massive_behavior = data["massive_expired_parameter_behavior"]
    assert massive_behavior["expired_true_requests"] == 2008
    assert massive_behavior["expired_false_fallback_requests"] == 2008
    assert massive_behavior["fallback_was_sanitized_and_recorded"] is True
    assert massive_behavior["not_silent"] is True
    assert all(row["uw_pit_claim"] is False for row in data["records"])
    assert all(
        not row["massive_quote_pass"] or row["massive_sip_le_origin"]
        for row in data["records"]
    )
    text = json.dumps(data).lower()
    assert "apikey=" not in text and "authorization: bearer" not in text
    assert "c:\\users\\" not in text


def test_canonical_forecast_origins_have_one_target_and_no_future_predictors() -> None:
    frame = pl.read_parquet(_pit() / "canonical_forecast_origins.parquet")
    assert frame.height == 2840
    assert frame["origin_id"].n_unique() == 2840
    assert frame["price_count"].unique().to_list() == [31]
    assert frame["future_close_count"].unique().to_list() == [30]
    assert frame["predictors_after_origin_count"].unique().to_list() == [0]
    assert frame["target_fields_are_not_predictors"].unique().to_list() == [True]


def test_final_gate_report_is_fail_closed_and_sanitized() -> None:
    data = _json("pit_gate_final_report.json")
    assert data["overall_status"] == "FAIL_CLOSED"
    assert data["critical_gates_all_pass"] is False
    assert data["next_action"] == "STOP_BEFORE_MODELING_BACKFILL_QLIKE"
    text = (_pit() / "pit_gate_final_report.json").read_text(encoding="utf-8").lower()
    assert "apikey=" not in text
    assert "authorization: bearer" not in text
    assert "c:\\users\\" not in text
