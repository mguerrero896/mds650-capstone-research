"""Fail-closed contracts for the single Phase 5 holdout read."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import polars as pl
import pytest
from jsonschema import Draft202012Validator

from mds650.holdout import EXPECTED_HOLDOUT_SESSIONS, authorize_holdout_read
from mds650.stability import b2_sensitivity_column
from mds650.study_design import B2_FEATURE_NAMES, canonical_sha256

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import run_phase5_holdout as holdout_runner  # noqa: E402

AFTER_HOLDOUT = datetime(2026, 7, 31, 20, 1, tzinfo=UTC)
STABILITY_SCHEMA = (
    ROOT / "specs" / "001-pit-options-rv30" / "contracts" / "phase5-stability-results.schema.json"
)


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
        "b0_plus2_spot": [190.0 + index for index in range(rows)],
        "b0_plus2_rv_5m_lag": [0.0001 + index * 1e-7 for index in range(rows)],
        "b0_plus2_rv_30m_lag": [0.0006 + index * 1e-7 for index in range(rows)],
        "b0_plus2_return_5m_lag": [(-1) ** index * 0.0001 for index in range(rows)],
        "b0_plus2_volume_5m_lag": [1_000_000.0 + index for index in range(rows)],
        "b0_plus2_available_at_utc": origins,
        "b0_plus2_availability_valid": [True] * rows,
    }
    data.update(
        {
            feature: [0.01 * (position + 1) + index * 1e-5 for index in range(rows)]
            for position, feature in enumerate(B2_FEATURE_NAMES)
        }
    )
    return pl.DataFrame(data)


def _stability_sidecar(panel: pl.DataFrame) -> pl.DataFrame:
    columns: list[pl.Expr] = []
    for delay in (120, 300):
        columns.extend(
            [
                (pl.col("forecast_origin_utc") - pl.duration(seconds=delay + 300)).alias(
                    f"b2_window_start__{delay}s"
                ),
                (pl.col("forecast_origin_utc") - pl.duration(seconds=delay)).alias(
                    f"b2_window_end__{delay}s"
                ),
                (pl.col("forecast_origin_utc") - pl.duration(seconds=delay)).alias(
                    f"b2_max_operational_time__{delay}s"
                ),
                pl.lit(True).alias(f"b2_option_activity_present__{delay}s"),
                *[
                    pl.col(feature).alias(b2_sensitivity_column(feature, delay))
                    for feature in B2_FEATURE_NAMES
                ],
            ]
        )
    return (
        panel.select("origin_id", "forecast_origin_utc", *B2_FEATURE_NAMES)
        .with_columns(columns)
        .drop("forecast_origin_utc", *B2_FEATURE_NAMES)
    )


def test_holdout_runner_executes_once_end_to_end(tmp_path: Path) -> None:
    development_dates = [f"2026-06-{day:02d}" for day in range(1, 21)]
    development_path = tmp_path / "development.parquet"
    development_stability_path = tmp_path / "development_stability.parquet"
    holdout_path = tmp_path / "holdout.parquet"
    holdout_stability_path = tmp_path / "holdout_stability.parquet"
    ledger_path = tmp_path / "ledger.json"
    freeze_path = tmp_path / "method_freeze.json"
    forecasts_path = tmp_path / "forecasts.parquet"
    results_path = tmp_path / "results.json"
    stability_results_path = tmp_path / "stability_results.json"
    development_panel = _panel(development_dates)
    holdout_panel = _panel(list(EXPECTED_HOLDOUT_SESSIONS))
    development_panel.write_parquet(development_path)
    _stability_sidecar(development_panel).write_parquet(development_stability_path)
    holdout_panel.write_parquet(holdout_path)
    _stability_sidecar(holdout_panel).write_parquet(holdout_stability_path)

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
            "stability_definition": {
                "session_tercile_upper_bounds": [130.0, 260.0],
                "volatility_regime": {
                    "source": "b0_rv_30m_lag",
                    "quantiles": [1 / 3, 2 / 3],
                    "interpolation": "linear",
                    "lower_cutpoint": 0.0006006333333333333,
                    "upper_cutpoint": 0.0006012666666666666,
                    "fit_scope": "SELECTED_ASSET_DEVELOPMENT_PANEL_ONLY",
                },
                "fmp_delay_minutes": [1, 2],
                "b2_delay_seconds": [60, 120, 300],
                "sensitivity_hyperparameters": "FROZEN_PRIMARY_WITHOUT_RETUNING",
                "confirmatory_role": "gamma_glm_confirmatory",
                "confirmatory_family_expanded": False,
                "operationalization_timing": "AFTER_DEVELOPMENT_BEFORE_HOLDOUT",
                "preregistration_scope": (
                    "STABILITY_DIMENSIONS_PREDECLARED;"
                    "MATERIAL_REVERSAL_THRESHOLD_PRE_HOLDOUT_CLARIFICATION"
                ),
                "systematic_reversal_rule": {
                    "minimum_sessions_per_stratum": 2,
                    "material_negative_definition": "BOOTSTRAP_CI_HIGH_STRICTLY_BELOW_ZERO",
                    "minimum_material_negative_strata": 2,
                    "minimum_negative_origin_share": 0.5,
                    "timing_variant_rule": (
                        "ANY_NONPRIMARY_VARIANT_WITH_CI_HIGH_STRICTLY_BELOW_ZERO"
                    ),
                },
            },
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
            "contract_hashes": {
                relative_path: holdout_runner._sha256_file(ROOT / relative_path)
                for relative_path in holdout_runner.REQUIRED_CONTRACT_PATHS
            },
            "input_hashes": {
                "common_development_80d.parquet": holdout_runner._sha256_file(development_path),
                "development_stability_inputs_80d.parquet": holdout_runner._sha256_file(
                    development_stability_path
                ),
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
            "stability_panel_sha256": holdout_runner._sha256_file(holdout_stability_path),
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
        development_stability_path=development_stability_path,
        holdout_panel_path=holdout_path,
        holdout_stability_path=holdout_stability_path,
        forecasts_path=forecasts_path,
        results_path=results_path,
        stability_results_path=stability_results_path,
        now_utc=AFTER_HOLDOUT,
    )

    forecasts = pl.read_parquet(forecasts_path)
    stability = json.loads(stability_results_path.read_text(encoding="utf-8"))
    stability_schema = json.loads(STABILITY_SCHEMA.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(stability_schema)
    Draft202012Validator(stability_schema).validate(stability)
    assert result["status"] == "PASS_HOLDOUT_READ_ONCE"
    assert result["holdout_reads"] == 1
    assert forecasts.height == len(EXPECTED_HOLDOUT_SESSIONS) * 6
    assert forecasts["fold"].unique().to_list() == [5]
    assert stability["status"] == "PASS_SINGLE_HOLDOUT_READ_STABILITY"
    assert {row["variant_id"] for row in stability["timing_sensitivity"]} == {
        "FMP_DELAY_1_MINUTE",
        "FMP_DELAY_2_MINUTES",
        "B2_DELAY_60_SECONDS",
        "B2_DELAY_120_SECONDS",
        "B2_DELAY_300_SECONDS",
    }
    assert {row["dimension"] for row in stability["primary_strata"]} == {
        "asset",
        "session_tercile",
        "volatility_regime",
    }
    assert json.loads(ledger_path.read_text(encoding="utf-8"))["holdout_reads"] == 1
    with pytest.raises(PermissionError, match="HOLDOUT_ALREADY_READ"):
        holdout_runner.execute_holdout(
            ledger_path=ledger_path,
            method_freeze_path=freeze_path,
            development_panel_path=development_path,
            development_stability_path=development_stability_path,
            holdout_panel_path=holdout_path,
            holdout_stability_path=holdout_stability_path,
            forecasts_path=forecasts_path,
            results_path=results_path,
            stability_results_path=stability_results_path,
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


def test_holdout_runner_rejects_frozen_contract_drift() -> None:
    contract_hashes = {
        relative_path: holdout_runner._sha256_file(ROOT / relative_path)
        for relative_path in holdout_runner.REQUIRED_CONTRACT_PATHS
    }
    contract_hashes[next(iter(contract_hashes))] = "0" * 64

    with pytest.raises(
        PermissionError,
        match="METHOD_FREEZE_CONTRACT_HASH_MISMATCH",
    ):
        holdout_runner._validate_contract_hashes({"contract_hashes": contract_hashes})


def test_stability_sidecar_rejects_future_operational_timestamp() -> None:
    panel = _panel(list(EXPECTED_HOLDOUT_SESSIONS))
    sidecar = _stability_sidecar(panel).with_columns(
        pl.lit(datetime(2030, 1, 1, tzinfo=UTC)).alias("b2_max_operational_time__120s")
    )

    with pytest.raises(ValueError, match="HOLDOUT_STABILITY_PANEL_CONTRACT_INVALID"):
        holdout_runner._validate_stability_sidecar(
            sidecar,
            primary=panel,
            delays_seconds=(120, 300),
        )


def test_material_reversal_rule_is_frozen_and_sign_symmetric() -> None:
    primary = [
        {
            "model_role": "gamma_glm_confirmatory",
            "contrast": "delta_b2",
            "dimension": "asset",
            "level": "AAPL",
            "session_count": 10,
            "origin_count": 60,
            "ci_high": -0.01,
        },
        {
            "model_role": "gamma_glm_confirmatory",
            "contrast": "delta_b2",
            "dimension": "asset",
            "level": "MSFT",
            "session_count": 10,
            "origin_count": 60,
            "ci_high": -0.02,
        },
        {
            "model_role": "gamma_glm_confirmatory",
            "contrast": "delta_b2",
            "dimension": "asset",
            "level": "NVDA",
            "session_count": 10,
            "origin_count": 80,
            "ci_high": 0.03,
        },
    ]
    timing = [
        {
            "model_role": "gamma_glm_confirmatory",
            "contrast": "delta_b2",
            "variant_id": "B2_DELAY_120_SECONDS",
            "ci_high": -0.001,
        }
    ]

    result = holdout_runner._assess_reversals(primary, timing)

    assert result["delta_b2"]["pass"] is False
    assert result["delta_b2"]["systematic_stratum_reversals"][0]["dimension"] == "asset"
    assert result["delta_b2"]["material_timing_reversals"] == ["B2_DELAY_120_SECONDS"]
    assert result["delta_b1"]["pass"] is True
