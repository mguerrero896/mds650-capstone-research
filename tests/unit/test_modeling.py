"""Positive-forecast and fixed-role contracts for Phase 5 models."""

from __future__ import annotations

import numpy as np
import polars as pl
import pytest

from mds650.modeling import fit_positive_model


def _training_frame() -> pl.DataFrame:
    x = np.arange(1.0, 41.0)
    return pl.DataFrame(
        {
            "asset": ["AAPL", "MSFT"] * 20,
            "x1": x,
            "x2": np.log1p(x),
            "rv30": 0.001 + 0.00001 * x,
        }
    )


@pytest.mark.parametrize(
    ("role", "parameters"),
    [
        (
            "gamma_glm_confirmatory",
            {"alpha": 0.01, "max_iter": 2_000, "tol": 1e-8},
        ),
        (
            "lightgbm_robustness",
            {
                "learning_rate": 0.05,
                "max_depth": 3,
                "min_child_samples": 2,
                "n_estimators": 20,
                "num_leaves": 7,
                "reg_lambda": 1.0,
            },
        ),
    ],
)
def test_registered_models_emit_finite_positive_predictions(
    role: str,
    parameters: dict[str, float | int],
) -> None:
    frame = _training_frame()

    fitted = fit_positive_model(
        frame,
        feature_columns=("asset", "x1", "x2"),
        categorical_columns=("asset",),
        target_column="rv30",
        role=role,
        parameters=parameters,
        seed=650,
    )
    predictions = fitted.predict(frame)

    assert fitted.role == role
    assert predictions.shape == (frame.height,)
    assert np.isfinite(predictions).all()
    assert (predictions > 0).all()


def test_preprocessor_is_fit_on_training_rows_only() -> None:
    training = _training_frame()
    fitted = fit_positive_model(
        training,
        feature_columns=("asset", "x1", "x2"),
        categorical_columns=("asset",),
        target_column="rv30",
        role="gamma_glm_confirmatory",
        parameters={"alpha": 0.01, "max_iter": 2_000, "tol": 1e-8},
        seed=650,
    )
    scaler = fitted.estimator.named_steps["preprocess"].named_transformers_[
        "numeric"
    ]

    assert scaler.mean_[0] == pytest.approx(training["x1"].mean())
    assert scaler.mean_[0] != pytest.approx(10_000.0)


def test_unknown_model_role_fails_closed() -> None:
    with pytest.raises(ValueError, match="UNKNOWN_MODEL_ROLE"):
        fit_positive_model(
            _training_frame(),
            feature_columns=("asset", "x1", "x2"),
            categorical_columns=("asset",),
            target_column="rv30",
            role="select_best_result",
            parameters={},
            seed=650,
        )
