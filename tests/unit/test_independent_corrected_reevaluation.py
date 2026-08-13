"""Contracts for the corrected independent B1 freeze and one reevaluation."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import polars as pl
import pytest
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import run_corrected_independent_replication as runner  # noqa: E402

from mds650.independent_corrected_reevaluation_v1 import (  # noqa: E402
    audit_corrected_b1,
    build_preregistration,
)


def _frames() -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    origins = pl.DataFrame(
        {
            "origin_id": ["AAPL:1", "AAPL:2"],
            "asset": ["AAPL", "AAPL"],
            "session_date": ["2025-01-02", "2025-01-02"],
            "forecast_origin_utc": [
                datetime(2025, 1, 2, 15, 0, tzinfo=UTC),
                datetime(2025, 1, 2, 15, 5, tzinfo=UTC),
            ],
            "session_tercile": ["first", "first"],
        },
        schema_overrides={"forecast_origin_utc": pl.Datetime("us", "UTC")},
    ).with_columns(pl.col("forecast_origin_utc").dt.epoch("ns").alias("forecast_origin_ns"))
    features = origins.with_columns(
        pl.col("forecast_origin_ns").alias("max_sip_timestamp_ns"),
        pl.Series("b1v2a_complete", [True, True]),
        pl.Series("b1v2b_complete", [True, False]),
        pl.Series("b1v2c_complete", [False, False]),
        pl.Series("b1v2_atm_iv_30_60_dte", [0.2, 0.21]),
    )
    attempts = pl.DataFrame(
        {
            "origin_id": ["AAPL:1", "AAPL:2"],
            "asset": ["AAPL", "AAPL"],
            "session_date": ["2025-01-02", "2025-01-02"],
            "forecast_origin_utc": origins["forecast_origin_utc"],
            "contract": ["O:AAPL1", "O:AAPL2"],
            "sip_timestamp_ns": origins["forecast_origin_ns"],
            "quote_age_seconds": [0.0, 0.0],
            "implied_volatility": [0.2, 0.21],
            "rate_source_date": ["2025-01-01", "2025-01-01"],
            "exogenous_pit_verified": [True, True],
        }
    )
    return origins, features, attempts


def test_corrected_b1_audit_proves_causal_nested_origin_alignment() -> None:
    origins, features, attempts = _frames()

    audit = audit_corrected_b1(origins=origins, features=features, attempts=attempts)

    assert audit["status"] == "PASS_TARGET_BLIND_CORRECTED_B1"
    assert audit["origin_count"] == 2
    assert audit["quote_after_origin_count"] == 0
    assert audit["rate_not_strictly_prior_count"] == 0
    assert audit["nested_coverage_monotonic"] is True
    assert audit["outcome_columns_present"] == []


def test_corrected_b1_audit_fails_on_future_quote_and_non_nested_flags() -> None:
    origins, features, attempts = _frames()
    features = features.with_columns(
        pl.Series("b1v2a_complete", [False, True]),
        pl.Series("b1v2b_complete", [True, False]),
    )
    attempts = attempts.with_columns((pl.col("sip_timestamp_ns") + 1).alias("sip_timestamp_ns"))

    with pytest.raises(ValueError, match="CORRECTED_B1_FUTURE_QUOTE"):
        audit_corrected_b1(origins=origins, features=features, attempts=attempts)


def test_preregistration_binds_corrected_inputs_and_forbids_sign_selection() -> None:
    audit = {
        "status": "PASS_TARGET_BLIND_CORRECTED_B1",
        "origin_count": 2,
        "attempt_count": 2,
        "b1a_coverage": 1.0,
        "b1b_coverage": 0.5,
        "b1c_coverage": 0.0,
        "nested_coverage_monotonic": True,
        "quote_after_origin_count": 0,
        "rate_not_strictly_prior_count": 0,
        "outcome_columns_present": [],
    }
    result = build_preregistration(
        b1_audit=audit,
        input_hashes={"corrected_b1_features": "a" * 64, "target_b0": "b" * 64},
        source_hashes={"evaluation_runner": "c" * 64, "uv_lock": "d" * 64},
        source_commit="e" * 40,
    )

    assert result["status"] == "FROZEN_AUTHORIZED_BEFORE_CORRECTED_REEVALUATION"
    assert result["scientific_role"] == "CORRECTED_FORENSIC_REEVALUATION"
    assert result["sample_independent_from_phase6"] is True
    assert result["pristine_first_read"] is False
    assert result["authorized_evaluation_count"] == 1
    assert result["selection_by_sign"] == "PROHIBITED"
    assert result["corrected_evaluation_performed"] is False


def test_preregistration_conforms_to_schema() -> None:
    schema = json.loads(
        (
            ROOT
            / "specs/001-pit-options-rv30/contracts"
            / "independent-corrected-reevaluation-v1.schema.json"
        ).read_text(encoding="utf-8")
    )
    audit = {
        "status": "PASS_TARGET_BLIND_CORRECTED_B1",
        "origin_count": 2,
        "attempt_count": 2,
        "b1a_coverage": 1.0,
        "b1b_coverage": 0.5,
        "b1c_coverage": 0.0,
        "nested_coverage_monotonic": True,
        "quote_after_origin_count": 0,
        "rate_not_strictly_prior_count": 0,
        "outcome_columns_present": [],
    }
    result = build_preregistration(
        b1_audit=audit,
        input_hashes={"corrected_b1_features": "a" * 64, "target_b0": "b" * 64},
        source_hashes={"evaluation_runner": "c" * 64, "uv_lock": "d" * 64},
        source_commit="e" * 40,
    )

    assert list(Draft202012Validator(schema).iter_errors(result)) == []


def test_corrected_runner_uses_new_paths_and_rejects_hash_drift(tmp_path: Path) -> None:
    assert runner.CORRECTED_B1 != runner.legacy.B1
    assert runner.RESULTS != runner.legacy.RESULTS
    assert runner.PREDICTIONS != runner.legacy.PREDICTIONS

    prereg = {
        "schema_version": "independent-corrected-reevaluation-v1.0",
        "status": "FROZEN_AUTHORIZED_BEFORE_CORRECTED_REEVALUATION",
        "authorized_evaluation_count": 1,
        "corrected_evaluation_performed": False,
        "selection_by_sign": "PROHIBITED",
        "pristine_first_read": False,
        "input_hashes": {"corrected_b1_features": "0" * 64},
    }
    from mds650.study_design import canonical_sha256

    prereg["preregistration_sha256"] = canonical_sha256(prereg)
    path = tmp_path / "prereg.json"
    path.write_text(json.dumps(prereg), encoding="utf-8")

    with pytest.raises(RuntimeError, match="CORRECTED_PREREG_INPUT_HASH_DRIFT"):
        runner._validate_preregistration(path, {"corrected_b1_features": "1" * 64})


def test_evaluation_run_lock_is_exclusive_and_preserves_first_claim(tmp_path: Path) -> None:
    lock = tmp_path / "evaluation_run.lock"

    runner._claim_evaluation_run(lock, "first-preregistration")

    with pytest.raises(RuntimeError, match="CORRECTED_EVALUATION_ALREADY_ATTEMPTED"):
        runner._claim_evaluation_run(lock, "second-preregistration")
    assert lock.read_text(encoding="ascii") == "first-preregistration"
