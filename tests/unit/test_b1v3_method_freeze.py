"""Training-only method-freeze contracts for the approved B1v3 study."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import polars as pl
import pytest

import mds650.b1v3_method_freeze as method_freeze
from mds650.b1v3_confirmation_common import B1V3_PRIMARY_INFORMATION_SETS
from mds650.b1v3_evaluation import build_b1v3_preregistration
from mds650.b1v3_method_freeze import (
    b1v3_training_folds,
    bind_b1v3_training_targets,
    build_b1v3_method_freeze,
    select_b1v3_final_parameters,
    training_mde_from_b1v3_forecasts,
    training_only_b1v3_oof_forecasts,
    training_volatility_regime_cutpoints,
)
from mds650.study_design import canonical_sha256

_ASSETS = ("AAPL", "AMZN", "META", "MSFT", "NVDA", "TSLA")
_SHA = "a" * 64


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
    common: dict[str, Any] = {
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


def _panels() -> tuple[pl.DataFrame, pl.DataFrame]:
    preregistration = _preregistration()
    rows: list[dict[str, Any]] = []
    targets: list[dict[str, Any]] = []
    features = B1V3_PRIMARY_INFORMATION_SETS["B2"]
    for day_index, session_date in enumerate(preregistration["training_sessions"]):
        for asset_index, asset in enumerate(_ASSETS):
            origin = datetime.fromisoformat(f"{session_date}T15:00:00+00:00")
            origin_id = f"{asset}:{origin.isoformat()}"
            feature_values = {
                feature: (
                    asset
                    if feature == "b0v2_asset_identity"
                    else 0.01 * (1 + day_index + asset_index)
                )
                for feature in features
            }
            rows.append(
                {
                    "origin_id": origin_id,
                    "asset": asset,
                    "session_date": session_date,
                    "forecast_origin_utc": origin,
                    "role": "development",
                    "session_tercile": "middle",
                    "b0_information_set_complete": True,
                    "b1v3a_information_set_complete": True,
                    "b2_information_set_complete": True,
                    **feature_values,
                }
            )
            targets.append(
                {
                    "origin_id": origin_id,
                    "asset": asset,
                    "session_date": session_date,
                    "forecast_origin_utc": origin,
                    "role": "development",
                    "session_tercile": "middle",
                    "target_price_count": 31,
                    "target_return_count": 30,
                    "rv30": 0.0001 * (1 + day_index + asset_index),
                    "drop_reason": None,
                    "max_predictor_available_at_utc": origin,
                    **feature_values,
                }
            )
    return pl.DataFrame(rows), pl.DataFrame(targets)


def test_training_folds_are_three_chronological_ten_session_blocks() -> None:
    preregistration = _preregistration()

    folds = b1v3_training_folds(preregistration)

    assert [fold.fold for fold in folds] == [101, 102, 103]
    assert folds[0].train_end.isoformat() == preregistration["training_sessions"][29]
    assert folds[0].test_start.isoformat() == preregistration["training_sessions"][30]
    assert folds[0].test_end.isoformat() == preregistration["training_sessions"][39]
    assert folds[-1].train_end.isoformat() == preregistration["training_sessions"][49]
    assert folds[-1].test_end.isoformat() == preregistration["training_sessions"][59]


def test_training_target_binding_preserves_exact_sample_and_rv30_contract() -> None:
    common, targets = _panels()

    bound = bind_b1v3_training_targets(
        common,
        targets,
        preregistration=_preregistration(),
    )

    assert bound.height == 60 * len(_ASSETS)
    assert set(bound["role"].unique()) == {"development"}
    assert set(bound["target_price_count"].unique()) == {31}
    assert set(bound["target_return_count"].unique()) == {30}
    assert bound.filter(pl.col("rv30") <= 0).is_empty()


@pytest.mark.parametrize(
    ("mutation", "error"),
    [
        (
            lambda targets: targets.with_columns(
                pl.when(pl.int_range(pl.len()) == 0)
                .then(pl.lit(30))
                .otherwise(pl.col("target_price_count"))
                .alias("target_price_count")
            ),
            "B1V3_RV30_CONTRACT_INVALID",
        ),
        (
            lambda targets: targets.with_columns(
                pl.when(pl.int_range(pl.len()) == 0)
                .then(pl.col("b0v2_log_spot") + 1.0)
                .otherwise(pl.col("b0v2_log_spot"))
                .alias("b0v2_log_spot")
            ),
            "B1V3_TRAINING_B0_DRIFT",
        ),
        (
            lambda targets: targets.with_columns(
                (pl.col("forecast_origin_utc") + pl.duration(minutes=1)).alias(
                    "max_predictor_available_at_utc"
                )
            ),
            "B1V3_TRAINING_PREDICTOR_FUTURE",
        ),
    ],
)
def test_training_target_binding_fails_closed(
    mutation: Any,
    error: str,
) -> None:
    common, targets = _panels()

    with pytest.raises(ValueError, match=error):
        bind_b1v3_training_targets(
            common,
            mutation(targets),
            preregistration=_preregistration(),
        )


def test_training_mde_uses_paired_daily_forecasts_only() -> None:
    rows: list[dict[str, Any]] = []
    for index in range(30):
        session_date = f"2024-09-{index + 1:02d}"
        for information_set, loss in (
            ("B0", 1.0 + index / 100),
            ("B1v3a", 0.95 + (index % 3) / 100),
            ("B2", 0.90 + (index % 5) / 100),
        ):
            rows.append(
                {
                    "origin_id": f"AAPL:{session_date}",
                    "session_date": session_date,
                    "fold": 101 + index // 10,
                    "information_set": information_set,
                    "qlike_loss": loss,
                }
            )

    mde = training_mde_from_b1v3_forecasts(
        pl.DataFrame(rows),
        draws=1_000,
        seed=650,
    )

    assert set(mde) == {"delta_b1v3", "delta_b2"}
    assert all(value > 0 for value in mde.values())


def test_training_oof_and_final_selection_reuse_registered_primitives(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    common, targets = _panels()
    panel = bind_b1v3_training_targets(
        common,
        targets,
        preregistration=_preregistration(),
    )
    selection_calls: list[tuple[int, str, str]] = []

    def fake_select(
        training: pl.DataFrame,
        *,
        fold: Any,
        information_set: str,
        features: tuple[str, ...],
        role: str,
        preregistration: Any,
    ) -> tuple[dict[str, float | int], list[dict[str, Any]]]:
        assert training.height > 0
        assert features == B1V3_PRIMARY_INFORMATION_SETS[information_set]
        assert preregistration["forecast_floor"] == 1e-12
        selection_calls.append((fold.fold, information_set, role))
        parameters: dict[str, float | int] = (
            {"alpha": 0.1, "max_iter": 2000, "tol": 1e-8}
            if role == "gamma_glm_confirmatory"
            else {
                "learning_rate": 0.03,
                "max_depth": 3,
                "min_child_samples": 50,
                "n_estimators": 200,
                "num_leaves": 7,
                "reg_lambda": 1.0,
            }
        )
        return parameters, [{"fold": fold.fold, "selected": True}]

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
        del training, features, parameters, preregistration
        return testing.select(
            "origin_id",
            "asset",
            "session_date",
            "forecast_origin_utc",
            "session_tercile",
            "volatility_regime",
            "rv30",
        ).with_columns(
            pl.lit(fold.fold).alias("fold"),
            pl.lit(role).alias("model_role"),
            pl.lit(information_set).alias("information_set"),
            pl.lit(1.0).alias("qlike_loss"),
        )

    monkeypatch.setattr(method_freeze, "select_phase6_parameters", fake_select)
    monkeypatch.setattr(method_freeze, "forecast_phase6_fold", fake_forecast)

    forecasts, oof_ledger = training_only_b1v3_oof_forecasts(
        panel,
        _preregistration(),
    )
    selected, final_ledger = select_b1v3_final_parameters(
        panel,
        _preregistration(),
    )
    cutpoints = training_volatility_regime_cutpoints(panel)

    assert forecasts.height == 30 * len(_ASSETS) * 3
    assert len(oof_ledger) == 9
    assert len(final_ledger) == 6
    assert set(selected) == {"gamma_glm_confirmatory", "lightgbm_robustness"}
    assert set(selected["gamma_glm_confirmatory"]) == {"B0", "B1v3a", "B2"}
    assert cutpoints["lower"] < cutpoints["upper"]
    assert len(selection_calls) == 15


def test_method_freeze_binds_training_only_outputs_and_self_hash() -> None:
    preregistration = _preregistration()
    selected = {
        role: {
            information_set: {"alpha": 0.1}
            for information_set in ("B0", "B1v3a", "B2")
        }
        for role in ("gamma_glm_confirmatory", "lightgbm_robustness")
    }

    document = build_b1v3_method_freeze(
        preregistration,
        common_panel_sha256="4" * 64,
        training_panel_sha256=_SHA,
        training_target_source_sha256="b" * 64,
        oof_forecasts_sha256="c" * 64,
        tuning_ledger_sha256="d" * 64,
        selected_parameters=selected,
        training_mde={"delta_b1v3": 0.01, "delta_b2": 0.02},
        volatility_regime_cutpoints={"lower": 0.1, "upper": 0.2},
        row_count=360,
    )
    unsigned = {key: value for key, value in document.items() if key != "manifest_sha256"}

    assert document["status"] == "FROZEN_AFTER_TRAINING_BEFORE_CONFIRMATION"
    assert document["training_read_count"] == 1
    assert document["confirmation_read_count"] == 0
    assert document["safe_to_read_confirmation"] is False
    assert document["manifest_sha256"] == canonical_sha256(unsigned)


@pytest.mark.parametrize(
    ("mutation", "error"),
    [
        (lambda values: values.update(row_count=0), "B1V3_METHOD_FREEZE_SOURCE_INVALID"),
        (
            lambda values: values["selected_parameters"].pop("lightgbm_robustness"),
            "B1V3_METHOD_FREEZE_PARAMETERS_INVALID",
        ),
        (
            lambda values: values["selected_parameters"]["gamma_glm_confirmatory"].update(
                B0={}
            ),
            "B1V3_METHOD_FREEZE_PARAMETERS_INVALID",
        ),
        (
            lambda values: values.update(
                training_mde={"delta_b1v3": 0.0, "delta_b2": 0.02}
            ),
            "B1V3_METHOD_FREEZE_MDE_INVALID",
        ),
        (
            lambda values: values.update(volatility_regime_cutpoints={"lower": 0.1}),
            "B1V3_METHOD_FREEZE_REGIME_INVALID",
        ),
        (
            lambda values: values.update(
                volatility_regime_cutpoints={"lower": 0.2, "upper": 0.1}
            ),
            "B1V3_METHOD_FREEZE_REGIME_INVALID",
        ),
    ],
)
def test_method_freeze_fails_closed_on_drift(mutation: Any, error: str) -> None:
    selected = {
        role: {
            information_set: {"alpha": 0.1}
            for information_set in ("B0", "B1v3a", "B2")
        }
        for role in ("gamma_glm_confirmatory", "lightgbm_robustness")
    }
    arguments: dict[str, Any] = {
        "common_panel_sha256": "4" * 64,
        "training_panel_sha256": _SHA,
        "training_target_source_sha256": "b" * 64,
        "oof_forecasts_sha256": "c" * 64,
        "tuning_ledger_sha256": "d" * 64,
        "selected_parameters": selected,
        "training_mde": {"delta_b1v3": 0.01, "delta_b2": 0.02},
        "volatility_regime_cutpoints": {"lower": 0.1, "upper": 0.2},
        "row_count": 360,
    }
    mutation(arguments)

    with pytest.raises(ValueError, match=error):
        build_b1v3_method_freeze(_preregistration(), **arguments)
