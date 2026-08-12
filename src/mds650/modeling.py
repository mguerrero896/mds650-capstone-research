"""Fixed positive-mean model roles for Phase 5."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
import polars as pl
from lightgbm import LGBMRegressor
from sklearn.compose import ColumnTransformer  # type: ignore[import-untyped]
from sklearn.linear_model import GammaRegressor  # type: ignore[import-untyped]
from sklearn.pipeline import Pipeline  # type: ignore[import-untyped]
from sklearn.preprocessing import (  # type: ignore[import-untyped]
    OneHotEncoder,
    StandardScaler,
)

MODEL_ROLES = frozenset({"gamma_glm_confirmatory", "lightgbm_robustness"})


@dataclass(frozen=True)
class FittedPositiveModel:
    """A fitted preregistered model with its immutable feature contract."""

    role: str
    feature_columns: tuple[str, ...]
    estimator: Pipeline
    forecast_floor: float

    def predict(self, frame: pl.DataFrame) -> np.ndarray:
        """Predict finite positive RV30 values.

        Parameters
        ----------
        frame:
            Rows containing the frozen feature columns.

        Returns
        -------
        numpy.ndarray
            One strictly positive prediction per row.

        Raises
        ------
        ValueError
            If a feature is missing or a prediction is non-finite.
        """
        missing = set(self.feature_columns) - set(frame.columns)
        if missing:
            raise ValueError(f"MODEL_FEATURES_MISSING:{','.join(sorted(missing))}")
        predictors = frame.select(self.feature_columns).to_pandas()
        predictions = np.asarray(
            self.estimator.predict(predictors),
            dtype=np.float64,
        )
        if predictions.shape != (frame.height,) or not np.isfinite(predictions).all():
            raise ValueError("NONFINITE_MODEL_PREDICTION")
        return np.maximum(predictions, self.forecast_floor)


def _model_for_role(
    role: str,
    parameters: Mapping[str, float | int],
    seed: int,
) -> object:
    if role == "gamma_glm_confirmatory":
        allowed = {"alpha", "max_iter", "tol"}
        if unexpected := set(parameters) - allowed:
            raise ValueError(f"UNKNOWN_GAMMA_PARAMETERS:{','.join(sorted(unexpected))}")
        return GammaRegressor(**dict(parameters))
    if role == "lightgbm_robustness":
        allowed = {
            "learning_rate",
            "max_depth",
            "min_child_samples",
            "n_estimators",
            "num_leaves",
            "reg_lambda",
        }
        if unexpected := set(parameters) - allowed:
            raise ValueError(f"UNKNOWN_LIGHTGBM_PARAMETERS:{','.join(sorted(unexpected))}")
        model_parameters: dict[str, Any] = dict(parameters)
        return LGBMRegressor(
            objective="gamma",
            random_state=seed,
            deterministic=True,
            force_col_wise=True,
            n_jobs=1,
            verbosity=-1,
            **model_parameters,
        )
    raise ValueError(f"UNKNOWN_MODEL_ROLE:{role}")


def fit_positive_model(
    frame: pl.DataFrame,
    *,
    feature_columns: Sequence[str],
    categorical_columns: Sequence[str],
    target_column: str,
    role: str,
    parameters: Mapping[str, float | int],
    seed: int,
    forecast_floor: float = 1e-12,
) -> FittedPositiveModel:
    """Fit one fixed-role positive RV30 model on training rows only.

    Parameters
    ----------
    frame:
        Training history only.
    feature_columns:
        Frozen predictor names for one information set.
    categorical_columns:
        Predictor names encoded as categories.
    target_column:
        Strictly positive RV30 target.
    role:
        ``gamma_glm_confirmatory`` or ``lightgbm_robustness``.
    parameters:
        Parameters from the preregistered role-specific grid.
    seed:
        Frozen random seed.
    forecast_floor:
        Strictly positive lower prediction bound.

    Returns
    -------
    FittedPositiveModel
        Fitted pipeline and immutable feature contract.

    Raises
    ------
    ValueError
        If columns, target values, roles or parameters violate the contract.
    """
    features = tuple(feature_columns)
    categorical = tuple(categorical_columns)
    required = {*features, target_column}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"MODEL_COLUMNS_MISSING:{','.join(sorted(missing))}")
    if target_column in features or not features:
        raise ValueError("TARGET_IN_FEATURES_OR_EMPTY_FEATURE_SET")
    if not set(categorical) <= set(features):
        raise ValueError("CATEGORICAL_FEATURE_NOT_REGISTERED")
    if forecast_floor <= 0:
        raise ValueError("NONPOSITIVE_FORECAST_FLOOR")
    target = np.asarray(frame[target_column].to_numpy(), dtype=np.float64)
    if target.shape != (frame.height,) or not np.isfinite(target).all():
        raise ValueError("NONFINITE_MODEL_TARGET")
    if (target <= 0).any():
        raise ValueError("NONPOSITIVE_GAMMA_TARGET")

    numeric = tuple(column for column in features if column not in categorical)
    if not numeric:
        raise ValueError("MODEL_NUMERIC_FEATURES_REQUIRED")
    numeric_values = frame.select(numeric).to_numpy()
    if not np.isfinite(numeric_values).all():
        raise ValueError("NONFINITE_MODEL_FEATURE")
    if any(frame[column].null_count() for column in categorical):
        raise ValueError("NULL_CATEGORICAL_FEATURE")

    transformers: list[tuple[str, object, list[str]]] = [
        (
            "numeric",
            StandardScaler(),
            list(numeric),
        )
    ]
    if categorical:
        transformers.append(
            (
                "categorical",
                OneHotEncoder(handle_unknown="ignore"),
                list(categorical),
            )
        )
    preprocess = ColumnTransformer(transformers, remainder="drop")
    estimator = Pipeline(
        [
            ("preprocess", preprocess),
            ("model", _model_for_role(role, parameters, seed)),
        ]
    )
    predictors = frame.select(features).to_pandas()
    estimator.fit(predictors, target)
    return FittedPositiveModel(
        role=role,
        feature_columns=features,
        estimator=estimator,
        forecast_floor=forecast_floor,
    )
