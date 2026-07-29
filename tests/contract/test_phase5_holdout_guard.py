"""Fail-closed contracts for the single Phase 5 holdout read."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from mds650.holdout import EXPECTED_HOLDOUT_SESSIONS, authorize_holdout_read
from mds650.study_design import B2_FEATURE_NAMES, canonical_sha256

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import run_phase5_holdout as holdout_runner  # noqa: E402

AFTER_HOLDOUT = datetime(2026, 7, 31, 20, 1, tzinfo=UTC)


def _self_hash(payload: dict[str, Any]) -> dict[str, Any]:
    result = {key: value for key, value in payload.items() if key != "manifest_sha256"}
    result["manifest_sha256"] = canonical_sha256(result)
    return result


def _freeze() -> dict[str, Any]:
    return _self_hash(
        {
            "schema_version": "phase5-method-freeze-1.0",
            "status": "FROZEN_AFTER_DEVELOPMENT_BEFORE_HOLDOUT",
            "holdout_reads": 0,
            "input_hashes": {"preregistration.json": "1" * 64},
            "holdout_hyperparameters": [{"model_role": "gamma_glm_confirmatory"}],
        }
    )


def _holdout(freeze: dict[str, Any]) -> dict[str, Any]:
    return _self_hash(
        {
            "schema_version": "phase5-holdout-access-1.0",
            "status": "ACQUIRED_NOT_READ",
            "holdout_sessions": list(EXPECTED_HOLDOUT_SESSIONS),
            "session_statuses": [
                {"session_date": day, "status": "PASS"} for day in EXPECTED_HOLDOUT_SESSIONS
            ],
            "last_session_complete": True,
            "method_freeze_sha256": freeze["manifest_sha256"],
            "preregistration_sha256": "1" * 64,
            "panel_sha256": "2" * 64,
            "release_gates": {
                "provider_source_hashes_valid": True,
                "common_panel_valid": True,
                "leakage_tests_passed": True,
                "full_test_suite_green": True,
            },
            "holdout_reads": 0,
            "authorized_at_utc": None,
        }
    )


def test_holdout_denied_before_last_session_completion() -> None:
    freeze = _freeze()

    with pytest.raises(PermissionError, match="HOLDOUT_PERIOD_INCOMPLETE"):
        authorize_holdout_read(
            _holdout(freeze),
            freeze,
            datetime(2026, 7, 29, tzinfo=UTC),
        )


def test_holdout_denied_without_matching_method_freeze() -> None:
    freeze = _freeze()
    corrupted = _self_hash({**freeze, "seed": 651})

    with pytest.raises(PermissionError, match="METHOD_FREEZE_HASH_MISMATCH"):
        authorize_holdout_read(
            _holdout(freeze),
            corrupted,
            AFTER_HOLDOUT,
        )


def test_holdout_denied_when_any_release_gate_fails() -> None:
    freeze = _freeze()
    holdout = _holdout(freeze)
    holdout["release_gates"]["leakage_tests_passed"] = False
    holdout["manifest_sha256"] = canonical_sha256(
        {key: value for key, value in holdout.items() if key != "manifest_sha256"}
    )

    with pytest.raises(PermissionError, match="HOLDOUT_RELEASE_GATES_FAILED"):
        authorize_holdout_read(holdout, freeze, AFTER_HOLDOUT)


def test_single_holdout_read_transitions_zero_to_one() -> None:
    freeze = _freeze()
    authorized = authorize_holdout_read(
        _holdout(freeze),
        freeze,
        AFTER_HOLDOUT,
    )

    assert authorized["status"] == "READ_ONCE"
    assert authorized["holdout_reads"] == 1
    assert authorized["authorized_at_utc"] == "2026-07-31T20:01:00Z"
    assert authorized["manifest_sha256"] == canonical_sha256(
        {key: value for key, value in authorized.items() if key != "manifest_sha256"}
    )

    with pytest.raises(PermissionError, match="HOLDOUT_ALREADY_READ"):
        authorize_holdout_read(authorized, freeze, AFTER_HOLDOUT)


def _panel(session_dates: list[str]) -> pl.DataFrame:
    origins = [datetime.fromisoformat(f"{day}T16:00:00+00:00") for day in session_dates]
    rows = len(origins)
    data: dict[str, Any] = {
        "origin_id": [f"AAPL|{day}|12:00" for day in session_dates],
        "asset": ["AAPL"] * rows,
        "session_date": session_dates,
        "forecast_origin_utc": origins,
        "rv30": [0.001 + index * 0.00001 for index in range(rows)],
        "target_price_count": [31] * rows,
        "target_future_close_count": [30] * rows,
        "target_validity": ["valid"] * rows,
        "common_complete": [True] * rows,
        "b0_available_at_utc": origins,
        "b1q_max_sip_timestamp_ns": [int(origin.timestamp() * 1_000_000_000) for origin in origins],
        "b2_window_end": [origin - timedelta(seconds=60) for origin in origins],
        "b2_max_operational_time": [origin - timedelta(seconds=60) for origin in origins],
        "b0_spot": [190.0 + index for index in range(rows)],
        "b0_rv_5m_lag": [0.0001 + index * 1e-7 for index in range(rows)],
        "b0_rv_30m_lag": [0.0006 + index * 1e-7 for index in range(rows)],
        "b0_return_5m_lag": [(-1) ** index * 0.0001 for index in range(rows)],
        "b0_volume_5m_lag": [1_000_000.0 + index for index in range(rows)],
        "b0_session_minute": [150.0] * rows,
        "b1q_atm_iv": [0.2 + index * 0.0001 for index in range(rows)],
    }
    data.update(
        {
            feature: [0.01 * (position + 1) + index * 1e-5 for index in range(rows)]
            for position, feature in enumerate(B2_FEATURE_NAMES)
        }
    )
    return pl.DataFrame(data)


def test_holdout_runner_executes_once_end_to_end(tmp_path: Path) -> None:
    development_dates = [f"2026-06-{day:02d}" for day in range(1, 21)]
    development_path = tmp_path / "development.parquet"
    holdout_path = tmp_path / "holdout.parquet"
    ledger_path = tmp_path / "ledger.json"
    freeze_path = tmp_path / "method_freeze.json"
    forecasts_path = tmp_path / "forecasts.parquet"
    results_path = tmp_path / "results.json"
    _panel(development_dates).write_parquet(development_path)
    _panel(list(EXPECTED_HOLDOUT_SESSIONS)).write_parquet(holdout_path)

    parameters = {
        "gamma_glm_confirmatory": {
            "alpha": 0.1,
            "max_iter": 100,
            "tol": 1e-8,
        },
        "lightgbm_robustness": {
            "learning_rate": 0.05,
            "max_depth": 3,
            "min_child_samples": 2,
            "n_estimators": 5,
            "num_leaves": 7,
            "reg_lambda": 1.0,
        },
    }
    method_freeze = _self_hash(
        {
            "schema_version": "phase5-method-freeze-1.0",
            "status": "FROZEN_AFTER_DEVELOPMENT_BEFORE_HOLDOUT",
            "holdout_reads": 0,
            "selected_assets": ["AAPL"],
            "information_sets": {
                name: list(features)
                for name, features in holdout_runner.development.INFORMATION_SETS.items()
            },
            "holdout_hyperparameters": [
                {
                    "information_set": information_set,
                    "model_role": role,
                    "parameters": parameters[role],
                }
                for information_set in holdout_runner.development.INFORMATION_SETS
                for role in holdout_runner.development.MODEL_ROLES
            ],
            "seed": 650,
            "forecast_floor": 1e-12,
            "timing": {"b2_primary_delay_seconds": 60},
            "inference": {
                "bootstrap_repetitions": 25,
                "cluster_unit": "XNYS_SESSION_DATE_WITH_ALL_ASSETS",
                "confirmatory_family": ["delta_b1", "delta_b2"],
                "multiplicity": "Holm",
            },
            "outcome_reporting": "RETAIN_ALL_POSITIVE_NEGATIVE_AND_NULL_RESULTS",
            "source_code_hashes": {
                relative_path: holdout_runner.source_sha256(ROOT / relative_path)
                for relative_path in holdout_runner.REQUIRED_SOURCE_PATHS
            },
            "input_hashes": {
                "common_development_80d.parquet": holdout_runner._sha256_file(development_path),
                "preregistration.json": "1" * 64,
            },
        }
    )
    ledger = _self_hash(
        {
            "schema_version": "phase5-holdout-access-1.0",
            "status": "ACQUIRED_NOT_READ",
            "holdout_sessions": list(EXPECTED_HOLDOUT_SESSIONS),
            "session_statuses": [
                {"session_date": day, "status": "PASS"} for day in EXPECTED_HOLDOUT_SESSIONS
            ],
            "last_session_complete": True,
            "method_freeze_sha256": method_freeze["manifest_sha256"],
            "preregistration_sha256": "1" * 64,
            "panel_sha256": holdout_runner._sha256_file(holdout_path),
            "release_gates": {
                "provider_source_hashes_valid": True,
                "common_panel_valid": True,
                "leakage_tests_passed": True,
                "full_test_suite_green": True,
            },
            "holdout_reads": 0,
            "authorized_at_utc": None,
        }
    )
    freeze_path.write_text(json.dumps(method_freeze), encoding="utf-8")
    ledger_path.write_text(json.dumps(ledger), encoding="utf-8")

    result = holdout_runner.execute_holdout(
        ledger_path=ledger_path,
        method_freeze_path=freeze_path,
        development_panel_path=development_path,
        holdout_panel_path=holdout_path,
        forecasts_path=forecasts_path,
        results_path=results_path,
        now_utc=AFTER_HOLDOUT,
    )

    forecasts = pl.read_parquet(forecasts_path)
    assert result["status"] == "PASS_HOLDOUT_READ_ONCE"
    assert result["holdout_reads"] == 1
    assert forecasts.height == len(EXPECTED_HOLDOUT_SESSIONS) * 6
    assert forecasts["fold"].unique().to_list() == [5]
    assert json.loads(ledger_path.read_text(encoding="utf-8"))["holdout_reads"] == 1
    with pytest.raises(PermissionError, match="HOLDOUT_ALREADY_READ"):
        holdout_runner.execute_holdout(
            ledger_path=ledger_path,
            method_freeze_path=freeze_path,
            development_panel_path=development_path,
            holdout_panel_path=holdout_path,
            forecasts_path=forecasts_path,
            results_path=results_path,
            now_utc=AFTER_HOLDOUT,
        )


def test_holdout_panel_rejects_b2_inside_frozen_delay() -> None:
    panel = _panel(list(EXPECTED_HOLDOUT_SESSIONS)).with_columns(
        pl.col("forecast_origin_utc").alias("b2_window_end")
    )

    with pytest.raises(ValueError, match="HOLDOUT_PANEL_CONTRACT_INVALID"):
        holdout_runner._validate_panel(
            panel,
            selected_assets=["AAPL"],
            b2_delay_seconds=60,
        )


def test_holdout_runner_rejects_frozen_source_code_drift() -> None:
    source_hashes = {
        relative_path: holdout_runner.source_sha256(ROOT / relative_path)
        for relative_path in holdout_runner.REQUIRED_SOURCE_PATHS
    }
    source_hashes["scripts/run_phase5_holdout.py"] = "0" * 64

    with pytest.raises(
        PermissionError,
        match="METHOD_FREEZE_SOURCE_HASH_MISMATCH",
    ):
        holdout_runner._validate_source_code_hashes({"source_code_hashes": source_hashes})
