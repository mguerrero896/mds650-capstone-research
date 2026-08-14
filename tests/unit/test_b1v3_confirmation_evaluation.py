"""One-read scientific evaluation contracts for B1v3."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np
import polars as pl
import pytest

import mds650.b1v3_confirmation_evaluation as evaluation
from mds650.b1v3_confirmation_common import B1V3_PRIMARY_INFORMATION_SETS
from mds650.b1v3_confirmation_evaluation import (
    evaluate_b1v3_confirmation,
    forecast_b1v3_confirmation,
)
from mds650.b1v3_evaluation import build_b1v3_preregistration
from mds650.metrics import qlike_losses
from mds650.study_design import canonical_sha256

_ASSETS = ("AAPL", "AMZN", "META", "MSFT", "NVDA", "TSLA")
_ROLES = ("gamma_glm_confirmatory", "lightgbm_robustness")
_SETS = ("B0", "B1v3a", "B2")
_TIMING = (
    "FMP_DELAY_2_MINUTES",
    "MASSIVE_CUTOFF_60_SECONDS",
    "MASSIVE_CUTOFF_300_SECONDS",
    "UW_CREATED_AT_120_SECONDS",
    "UW_CREATED_AT_300_SECONDS",
)


def _dates(start: datetime, count: int) -> list[str]:
    return [(start + timedelta(days=index)).date().isoformat() for index in range(count)]


def _preregistration() -> dict[str, Any]:
    training = _dates(datetime(2024, 8, 1, tzinfo=UTC), 60)
    confirmation = _dates(datetime(2024, 11, 1, tzinfo=UTC), 30)
    plan: dict[str, Any] = {
        "status": "PASS_PRISTINE_60_30_FROZEN",
        "target_blind": True,
        "outcome_read_count": 0,
        "safe_to_read_outcomes": False,
        "training_session_count": 60,
        "confirmation_session_count": 30,
        "training_sessions": training,
        "confirmation_sessions": confirmation,
        "plan_sha256": "1" * 64,
    }
    information_sets = {
        name: {"feature_count": len(features), "features": list(features)}
        for name, features in B1V3_PRIMARY_INFORMATION_SETS.items()
    }
    common = {
        "status": "PASS_TARGET_BLIND_COMMON_PREDICTOR_PANEL",
        "target_blind": True,
        "outcome_read_count": 0,
        "safe_to_read_outcomes": False,
        "safe_to_evaluate_scientifically": False,
        "plan_sha256": "1" * 64,
        "manifest_sha256": "2" * 64,
        "scope": {
            "training_session_count": 60,
            "confirmation_session_count": 30,
            "assets": list(_ASSETS),
            "origin_identity_sha256": "3" * 64,
        },
        "information_sets": information_sets,
        "output": {"sha256": "4" * 64},
    }
    return build_b1v3_preregistration(
        plan,
        common,
        common_manifest_file_sha256="5" * 64,
        design_sha256="6" * 64,
        evaluation_code_sha256="7" * 64,
        uv_lock_sha256="8" * 64,
    )


def _selected() -> dict[str, dict[str, dict[str, float | int]]]:
    return {
        "gamma_glm_confirmatory": {
            name: {"alpha": 0.1, "max_iter": 2000, "tol": 1e-8}
            for name in _SETS
        },
        "lightgbm_robustness": {
            name: {
                "learning_rate": 0.03,
                "max_depth": 3,
                "min_child_samples": 50,
                "n_estimators": 200,
                "num_leaves": 7,
                "reg_lambda": 1.0,
            }
            for name in _SETS
        },
    }


def _method_freeze() -> dict[str, Any]:
    document: dict[str, Any] = {
        "status": "FROZEN_AFTER_TRAINING_BEFORE_CONFIRMATION",
        "safe_to_read_confirmation": False,
        "outcome_read_count": 1,
        "training_read_count": 1,
        "confirmation_read_count": 0,
        "preregistration_manifest_sha256": _preregistration()["manifest_sha256"],
        "common_panel_sha256": "4" * 64,
        "selected_parameters": _selected(),
        "training_mde": {"delta_b1v3": 1e-8, "delta_b2": 1e-8},
        "volatility_regime_cutpoints": {"lower": 0.1, "upper": 0.2},
    }
    document["manifest_sha256"] = canonical_sha256(document)
    return document


def _prediction_rows() -> pl.DataFrame:
    rows: list[dict[str, Any]] = []
    start = datetime(2024, 11, 1, 15, tzinfo=UTC)
    for day in range(30):
        session_date = (start + timedelta(days=day)).date().isoformat()
        for asset_index, asset in enumerate(_ASSETS):
            origin = start + timedelta(days=day, minutes=asset_index * 5)
            origin_id = f"{asset}:{origin.isoformat()}"
            actual = 1.0 + (day % 3) * 0.01
            for role in _ROLES:
                for information_set, forecast in (
                    ("B0", 1.30),
                    ("B1v3a", 1.15),
                    ("B2", 1.05),
                ):
                    qlike = float(qlike_losses(np.array([actual]), np.array([forecast]))[0])
                    rows.append(
                        {
                            "origin_id": origin_id,
                            "asset": asset,
                            "session_date": session_date,
                            "forecast_origin_utc": origin,
                            "session_tercile": ("first", "middle", "last")[day % 3],
                            "volatility_regime": ("low", "normal", "high")[day % 3],
                            "fold": 1000,
                            "model_role": role,
                            "information_set": information_set,
                            "rv30": actual,
                            "forecast": forecast,
                            "qlike_loss": qlike,
                            "absolute_error": abs(actual - forecast),
                            "squared_error": (actual - forecast) ** 2,
                        }
                    )
    return pl.DataFrame(rows)


def test_confirmation_forecasts_use_frozen_parameters_without_retuning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    preregistration = _preregistration()
    method_freeze = _method_freeze()
    features = B1V3_PRIMARY_INFORMATION_SETS["B2"]
    rows: list[dict[str, Any]] = []
    for role, sessions in (
        ("development", preregistration["training_sessions"]),
        ("confirmation", preregistration["confirmation_sessions"]),
    ):
        for session_date in sessions:
            origin = datetime.fromisoformat(f"{session_date}T15:00:00+00:00")
            for asset in _ASSETS:
                row: dict[str, Any] = {
                    "origin_id": f"{asset}:{origin.isoformat()}",
                    "asset": asset,
                    "session_date": session_date,
                    "forecast_origin_utc": origin,
                    "session_tercile": "middle",
                    "role": role,
                    "rv30": 1.0,
                }
                row.update(
                    {
                        feature: asset if feature == "b0v2_asset_identity" else 0.1
                        for feature in features
                    }
                )
                rows.append(row)
    panel = pl.DataFrame(rows)
    calls: list[tuple[str, str]] = []

    def fake_forecast(
        training: pl.DataFrame,
        testing: pl.DataFrame,
        *,
        fold: Any,
        information_set: str,
        features: tuple[str, ...],
        role: str,
        parameters: Any,
        preregistration: Any,
    ) -> pl.DataFrame:
        del training, fold, features, parameters, preregistration
        calls.append((role, information_set))
        return testing.select(
            "origin_id",
            "asset",
            "session_date",
            "forecast_origin_utc",
            "session_tercile",
            "volatility_regime",
            "rv30",
        ).with_columns(
            pl.lit(1000).alias("fold"),
            pl.lit(role).alias("model_role"),
            pl.lit(information_set).alias("information_set"),
            pl.lit(1.0).alias("forecast"),
            pl.lit(0.0).alias("qlike_loss"),
            pl.lit(0.0).alias("absolute_error"),
            pl.lit(0.0).alias("squared_error"),
        )

    monkeypatch.setattr(evaluation, "forecast_phase6_fold", fake_forecast)

    forecasts = forecast_b1v3_confirmation(
        panel,
        preregistration=preregistration,
        method_freeze=method_freeze,
    )

    assert forecasts.height == 30 * len(_ASSETS) * len(_ROLES) * len(_SETS)
    assert set(calls) == {(role, name) for role in _ROLES for name in _SETS}


def test_evaluation_requires_all_timing_variants_and_can_confirm_both_edges() -> None:
    primary = _prediction_rows()
    timing = pl.concat(
        [primary.with_columns(pl.lit(variant).alias("timing_variant")) for variant in _TIMING]
    )

    result = evaluate_b1v3_confirmation(
        primary,
        method_freeze=_method_freeze(),
        preregistration=_preregistration(),
        timing_predictions=timing,
    )

    assert result["claims"]["delta_b1v3"]["status"] == "GLOBAL_EDGE_CONFIRMED"
    assert result["claims"]["delta_b2"]["status"] == "GLOBAL_EDGE_CONFIRMED"
    assert result["decision"] == "GLOBAL_B1V3_AND_B2_EDGE_CONFIRMED"
    assert result["all_signs_retained"] is True
    assert set(result["global_holm"]) == {"delta_b1v3", "delta_b2"}


def test_evaluation_fails_closed_without_registered_timing_views() -> None:
    with pytest.raises(ValueError, match="B1V3_TIMING_VARIANTS_INCOMPLETE"):
        evaluate_b1v3_confirmation(
            _prediction_rows(),
            method_freeze=_method_freeze(),
            preregistration=_preregistration(),
            timing_predictions=None,
        )


def test_evaluation_preserves_positive_below_mde_and_negative_results() -> None:
    primary = _prediction_rows()
    timing = pl.concat(
        [primary.with_columns(pl.lit(variant).alias("timing_variant")) for variant in _TIMING]
    )
    high_mde = _method_freeze()
    high_mde["training_mde"] = {"delta_b1v3": 1.0, "delta_b2": 1.0}
    high_mde["manifest_sha256"] = canonical_sha256(
        {key: value for key, value in high_mde.items() if key != "manifest_sha256"}
    )

    positive = evaluate_b1v3_confirmation(
        primary,
        method_freeze=high_mde,
        preregistration=_preregistration(),
        timing_predictions=timing,
    )

    assert positive["decision"] == "POSITIVE_BUT_NOT_GLOBALLY_CONFIRMED"
    assert "effect_meets_training_mde" in positive["claims"]["delta_b1v3"][
        "failed_conditions"
    ]

    negative = (
        primary.with_columns(
            pl.when(pl.col("information_set") == "B0")
            .then(pl.lit(1.05))
            .when(pl.col("information_set") == "B1v3a")
            .then(pl.lit(1.15))
            .otherwise(pl.lit(1.30))
            .alias("forecast")
        )
        .with_columns(
            (
                pl.col("rv30") / pl.col("forecast")
                - (pl.col("rv30") / pl.col("forecast")).log()
                - 1.0
            ).alias("qlike_loss"),
            (pl.col("rv30") - pl.col("forecast")).abs().alias("absolute_error"),
            (pl.col("rv30") - pl.col("forecast")).pow(2).alias("squared_error"),
        )
    )
    negative_timing = pl.concat(
        [negative.with_columns(pl.lit(variant).alias("timing_variant")) for variant in _TIMING]
    )
    negative_result = evaluate_b1v3_confirmation(
        negative,
        method_freeze=_method_freeze(),
        preregistration=_preregistration(),
        timing_predictions=negative_timing,
    )

    assert negative_result["decision"] == "GLOBAL_EDGE_NOT_CONFIRMED"
    assert negative_result["claims"]["delta_b1v3"]["status"] == (
        "GLOBAL_EDGE_NOT_CONFIRMED"
    )
