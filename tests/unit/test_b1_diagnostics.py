"""Tests for development-only B1 diagnostic primitives."""

from __future__ import annotations

import json
import math
from pathlib import Path

import exchange_calendars as xcals
import polars as pl
import pytest
from jsonschema import Draft202012Validator

from mds650.b1_diagnostics import (
    B1_DIAGNOSTIC_FAMILIES,
    build_b1_diagnostic_document,
    build_reason_waterfall,
    chronological_b1_loss_deltas,
    collinearity_diagnostics,
    extract_gamma_coefficients,
    summarize_feature_distributions,
    summarize_iv_geometry,
    summarize_lag_availability,
    summarize_quote_quality,
)
from mds650.b1v3 import B1V3A_FEATURES
from mds650.modeling import fit_positive_model

_CALENDAR = xcals.get_calendar("XNYS")
TRAINING = tuple(
    str(value.date())
    for value in _CALENDAR.sessions_in_range("2024-09-16", "2024-12-09")
)
REPLICATION = tuple(
    str(value.date())
    for value in _CALENDAR.sessions_in_range("2024-12-10", "2025-01-24")
)
ROOT = Path(__file__).resolve().parents[2]


def _feature_rows() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "origin_id": ["a", "b", "c", "d"],
            "asset": ["AAPL", "AAPL", "MSFT", "MSFT"],
            "session_date": [TRAINING[0], TRAINING[0], TRAINING[1], TRAINING[1]],
            "session_tercile": ["first", "middle", "last", "last"],
            "b0_information_set_complete": [False, True, True, True],
            B1V3A_FEATURES[0]: [None, None, 1.0, 2.0],
            B1V3A_FEATURES[1]: [None, None, None, 0.2],
            B1V3A_FEATURES[2]: [None, None, 0.1, 0.3],
            "b1v3a_information_set_complete": [False, False, False, True],
            "b1v3_level_missing_reason": [None, "ATM_LEVEL_MISSING", None, None],
            "b1v3_missing_reason": ["B0_INCOMPLETE", "ATM_LEVEL_MISSING", "LAG_5M", None],
            "b0v2_underlying_rv_30m": [0.1, 0.2, 0.3, 0.4],
            "b0v2_underlying_rv_5m": [0.01, 0.02, 0.03, 0.04],
        }
    )


def _attempt_rows() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "origin_id": ["b", "b", "c", "d"],
            "asset": ["AAPL", "AAPL", "MSFT", "MSFT"],
            "session_date": [TRAINING[0], TRAINING[0], TRAINING[1], TRAINING[1]],
            "sip_timestamp": [1, None, 2, 3],
            "iv_success": [True, False, False, True],
            "failure_reason": [None, "NO_QUOTE", "IV_NO_CONVERGENCE", None],
            "quote_age_seconds": [2.0, None, 8.0, 4.0],
            "relative_spread": [0.1, None, 0.2, 0.15],
            "iv": [0.2, None, None, 0.3],
            "bucket": ["medium", "medium", "short", "medium"],
            "option_type": ["call", "put", "put", "call"],
            "target_moneyness": [1.0, 1.0, 0.975, 1.025],
            "dte": [45.0, 45.0, 15.0, 40.0],
        }
    )


def test_reason_waterfall_is_exhaustive_and_mutually_exclusive() -> None:
    waterfall = build_reason_waterfall(_feature_rows())
    global_rows = waterfall.filter(
        (pl.col("asset") == "ALL") & (pl.col("session_tercile") == "ALL")
    )
    assert global_rows["terminal_count"].sum() == 4
    assert set(global_rows["terminal_reason_code"]) == {
        "B0_INCOMPLETE",
        "B1_LEVEL_GEOMETRY_MISSING",
        "B1_EXACT_5M_LAG_MISSING",
        "B1V3A_COMPLETE",
    }


def test_quote_and_feature_summaries_are_finite_and_complete() -> None:
    quote = summarize_quote_quality(
        _attempt_rows(),
        _feature_rows().select("origin_id", "session_tercile"),
    )
    global_quote = quote.filter(
        (pl.col("asset") == "ALL") & (pl.col("session_tercile") == "ALL")
    ).row(0, named=True)
    assert global_quote["attempt_count"] == 4
    assert global_quote["quote_returned_count"] == 3
    assert global_quote["iv_success_count"] == 2

    distributions = summarize_feature_distributions(
        _feature_rows(),
        (*B1V3A_FEATURES, "b0v2_underlying_rv_30m"),
    )
    assert set(distributions["feature"]) == {
        *B1V3A_FEATURES,
        "b0v2_underlying_rv_30m",
    }
    for row in distributions.iter_rows(named=True):
        for key in ("mean", "standard_deviation", "p05", "median", "p95"):
            assert row[key] is None or math.isfinite(float(row[key]))


def test_iv_geometry_and_lag_availability_are_separate_diagnostics() -> None:
    attempts = _attempt_rows()
    geometry = summarize_iv_geometry(attempts)
    assert geometry["attempt_count"].sum() == attempts.height
    assert geometry["iv_success_count"].sum() == 2
    assert geometry["iv_success_rate"].is_finite().all()

    lags = summarize_lag_availability(_feature_rows())
    global_lags = lags.filter(
        (pl.col("asset") == "ALL") & (pl.col("session_tercile") == "ALL")
    ).row(0, named=True)
    assert global_lags["origin_count"] == 4
    assert global_lags["level_available_count"] == 2
    assert global_lags["lag_5m_available_count"] == 1
    assert global_lags["lag_30m_available_count"] == 2


def test_collinearity_reports_rank_and_condition_without_target() -> None:
    frame = pl.DataFrame(
        {
            "x": [1.0, 2.0, 3.0, 4.0],
            "twice_x": [2.0, 4.0, 6.0, 8.0],
            "independent": [0.0, 1.0, 0.0, 1.0],
        }
    )
    result = collinearity_diagnostics(frame, ("x", "twice_x", "independent"))
    assert result["matrix_rank"] < result["feature_count"]
    assert result["rank_deficient"] is True
    assert result["condition_number"] is None or result["condition_number"] > 1.0


def test_chronological_loss_delta_is_paired_and_gamma_coefficients_are_named() -> None:
    forecasts = pl.DataFrame(
        {
            "origin_id": ["a", "b", "a", "b"],
            "asset": ["AAPL", "MSFT", "AAPL", "MSFT"],
            "session_date": [TRAINING[30], TRAINING[31], TRAINING[30], TRAINING[31]],
            "session_tercile": ["first", "last", "first", "last"],
            "fold": [101, 101, 101, 101],
            "information_set": ["B0", "B0", "B1v3a", "B1v3a"],
            "model_role": ["gamma_glm_confirmatory"] * 4,
            "qlike_loss": [1.0, 2.0, 0.8, 2.2],
        }
    )
    deltas = chronological_b1_loss_deltas(forecasts)
    global_delta = next(
        row
        for row in deltas
        if row["scope"] == "GLOBAL" and row["fold"] == 101
    )
    assert global_delta["observation_count"] == 2
    assert global_delta["delta_b1v3"] == pytest.approx(0.0)

    fit_frame = pl.DataFrame(
        {
            "b0v2_asset_identity": ["AAPL", "AAPL", "MSFT", "MSFT"],
            "x": [1.0, 2.0, 3.0, 4.0],
            "rv30": [0.1, 0.2, 0.3, 0.4],
        }
    )
    fitted = fit_positive_model(
        fit_frame,
        feature_columns=("b0v2_asset_identity", "x"),
        categorical_columns=("b0v2_asset_identity",),
        target_column="rv30",
        role="gamma_glm_confirmatory",
        parameters={"alpha": 0.1, "max_iter": 2000, "tol": 1e-8},
        seed=650,
    )
    coefficients = extract_gamma_coefficients(
        fitted,
        information_set="B1v3a",
        selected_parameters={"alpha": 0.1, "max_iter": 2000, "tol": 1e-8},
    )
    assert any(record["feature"] == "numeric__x" for record in coefficients)
    assert any(record["feature"] == "__INTERCEPT__" for record in coefficients)
    assert all(math.isfinite(float(record["coefficient"])) for record in coefficients)


def test_diagnostic_document_is_deterministic_target_scoped_and_self_hashed() -> None:
    inputs = {
        "features": "a" * 64,
        "attempts": "b" * 64,
        "training_targets": "c" * 64,
    }
    kwargs = {
        "feature_frame": _feature_rows(),
        "attempt_frame": _attempt_rows(),
        "training_sessions": TRAINING,
        "replication_sessions": REPLICATION,
        "source_hashes": inputs,
        "chronological_loss_deltas": [
            {"fold": 1, "delta_b1v3": -0.01, "observations": 2}
        ],
        "gamma_coefficients": [
            {"information_set": "B1v3a", "feature": B1V3A_FEATURES[0], "coefficient": 0.2}
        ],
    }
    first = build_b1_diagnostic_document(**kwargs)
    second = build_b1_diagnostic_document(**kwargs)
    assert first == second
    assert first["manifest_sha256"] == second["manifest_sha256"]
    assert first["replication_target_reads"] == 0
    assert first["diagnostic_families"] == list(B1_DIAGNOSTIC_FAMILIES)

    contaminated = _feature_rows().with_columns(
        pl.when(pl.col("origin_id") == "a")
        .then(pl.lit(REPLICATION[0]))
        .otherwise(pl.col("session_date"))
        .alias("session_date")
    )
    with pytest.raises(ValueError, match="B1_DIAGNOSTIC_REPLICATION_DATE_READ"):
        build_b1_diagnostic_document(**{**kwargs, "feature_frame": contaminated})

    schema = json.loads(
        (
            ROOT
            / "specs/001-pit-options-rv30/contracts/b1-diagnostic-v1.schema.json"
        ).read_text(encoding="utf-8")
    )
    Draft202012Validator.check_schema(schema)
    assert not list(Draft202012Validator(schema).iter_errors(first))
