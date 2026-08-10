"""Development-only candidate models for the RV30 edge audit."""

from __future__ import annotations

import itertools
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np
import polars as pl
from sklearn.compose import ColumnTransformer  # type: ignore[import-untyped]
from sklearn.linear_model import ElasticNet, LinearRegression, Ridge  # type: ignore[import-untyped]
from sklearn.pipeline import Pipeline  # type: ignore[import-untyped]
from sklearn.preprocessing import OneHotEncoder, StandardScaler  # type: ignore[import-untyped]

from mds650.modeling import FittedPositiveModel, fit_positive_model

FORECAST_FLOOR = 1e-12
SEED = 650

B0_FEATURES = (
    "asset",
    "b0_spot",
    "b0_rv_5m_lag",
    "b0_rv_30m_lag",
    "b0_return_5m_lag",
    "b0_volume_5m_lag",
    "b0_session_minute",
)
B1_FEATURES = (*B0_FEATURES, "b1q_atm_iv")
B2_FEATURES = (
    *B1_FEATURES,
    "b2_log_trade_count",
    "b2_unique_contract_share",
    "b2_log_mean_trade_premium",
    "b2_log_max_trade_premium",
    "b2_call_put_premium_imbalance_scaled",
    "b2_execution_side_premium_imbalance",
    "b2_repeated_contract_premium_share",
    "b2_strike_concentration",
    "b2_expiry_concentration",
)
INFORMATION_SETS: dict[str, tuple[str, ...]] = {
    "B0": B0_FEATURES,
    "B1a": B1_FEATURES,
    "B2": B2_FEATURES,
}


@dataclass(frozen=True)
class FittedDevelopmentCandidate:
    """Immutable predictor wrapper for one development candidate."""

    model_name: str
    feature_columns: tuple[str, ...]
    estimator: Pipeline | FittedPositiveModel | None
    log_target: bool
    forecast_floor: float = FORECAST_FLOOR

    def predict(self, frame: pl.DataFrame) -> np.ndarray:
        """Predict finite positive RV30 values for new rows.

        Parameters
        ----------
        frame:
            Rows containing the candidate's frozen features.

        Returns
        -------
        numpy.ndarray
            One positive forecast per row.

        Raises
        ------
        ValueError
            If a feature is missing or the prediction is non-finite.
        """
        missing = set(self.feature_columns) - set(frame.columns)
        if missing:
            raise ValueError(f"DEVELOPMENT_MODEL_FEATURES_MISSING:{','.join(sorted(missing))}")
        if self.model_name == "persistence":
            predictions = persistence_forecast(frame)
        elif isinstance(self.estimator, FittedPositiveModel):
            predictions = self.estimator.predict(frame)
        elif isinstance(self.estimator, Pipeline):
            predictors = frame.select(self.feature_columns).to_pandas()
            raw = np.asarray(self.estimator.predict(predictors), dtype=np.float64)
            predictions = np.exp(np.clip(raw, -40.0, 5.0)) if self.log_target else raw
        else:
            raise ValueError("DEVELOPMENT_MODEL_NOT_FITTED")
        if predictions.shape != (frame.height,) or not np.isfinite(predictions).all():
            raise ValueError("DEVELOPMENT_MODEL_NONFINITE_PREDICTION")
        return np.maximum(np.asarray(predictions, dtype=np.float64), self.forecast_floor)


def persistence_forecast(frame: pl.DataFrame) -> np.ndarray:
    """Use the last observed 30-minute realised variance as a naive forecast."""
    if "b0_rv_30m_lag" not in frame.columns:
        raise ValueError("PERSISTENCE_LAG_MISSING")
    values = np.asarray(frame["b0_rv_30m_lag"].to_numpy(), dtype=np.float64)
    if values.ndim != 1 or not np.isfinite(values).all() or (values <= 0).any():
        raise ValueError("PERSISTENCE_LAG_INVALID")
    return np.maximum(values, FORECAST_FLOOR)


def candidate_parameter_grid(model_name: str) -> list[dict[str, float | int]]:
    """Return the frozen development candidate grid.

    Parameters
    ----------
    model_name:
        One of ``persistence``, ``har_rv``, ``ridge``, ``elastic_net``,
        ``gamma_glm`` or ``lightgbm``.

    Returns
    -------
    list[dict[str, float | int]]
        Deterministically ordered parameter variants.
    """
    if model_name in {"persistence", "har_rv"}:
        return [{}]
    if model_name == "ridge":
        return [{"alpha": 1.0}]
    if model_name == "elastic_net":
        return [{"alpha": 0.01, "l1_ratio": 0.5}]
    if model_name == "gamma_glm":
        return [{"alpha": alpha, "max_iter": 2_000, "tol": 1e-8} for alpha in (0.0, 0.01, 0.1, 1.0)]
    if model_name == "lightgbm":
        grid = {
            "learning_rate": (0.03, 0.05),
            "max_depth": (3, 5),
            "min_child_samples": (50,),
            "n_estimators": (200, 500),
            "num_leaves": (7, 15),
            "reg_lambda": (1.0,),
        }
        names = tuple(sorted(grid))
        return [
            dict(zip(names, values, strict=True))
            for values in itertools.product(*(grid[name] for name in names))
        ]
    raise ValueError(f"UNKNOWN_DEVELOPMENT_MODEL:{model_name}")


def _log_linear_pipeline(
    feature_columns: Sequence[str],
    model_name: str,
    parameters: Mapping[str, float | int],
    seed: int,
) -> Pipeline:
    features = tuple(feature_columns)
    categorical = [name for name in features if name == "asset"]
    numeric = [name for name in features if name not in categorical]
    if not numeric:
        raise ValueError("DEVELOPMENT_NUMERIC_FEATURES_REQUIRED")
    transformers: list[tuple[str, object, list[str]]] = [
        ("numeric", StandardScaler(), numeric),
    ]
    if categorical:
        transformers.append(("categorical", OneHotEncoder(handle_unknown="ignore"), categorical))
    preprocess = ColumnTransformer(transformers, remainder="drop")
    if model_name == "har_rv":
        model: object = LinearRegression()
    elif model_name == "ridge":
        model = Ridge(alpha=float(parameters["alpha"]))
    elif model_name == "elastic_net":
        model = ElasticNet(
            alpha=float(parameters["alpha"]),
            l1_ratio=float(parameters["l1_ratio"]),
            max_iter=2_000,
            tol=1e-5,
            random_state=seed,
        )
    else:
        raise ValueError(f"UNKNOWN_LOG_LINEAR_MODEL:{model_name}")
    return Pipeline([("preprocess", preprocess), ("model", model)])


def fit_development_candidate(
    frame: pl.DataFrame,
    *,
    feature_columns: Sequence[str],
    model_name: str,
    parameters: Mapping[str, float | int],
    seed: int = SEED,
    forecast_floor: float = FORECAST_FLOOR,
) -> FittedDevelopmentCandidate:
    """Fit one candidate using training rows only.

    ``har_rv`` is a log-linear HAR-RV benchmark with the registered B0/B1/B2
    additions supplied as exogenous controls; it never sees the target column
    as a predictor. Ridge and Elastic Net use the same information-set columns.
    """
    features = tuple(feature_columns)
    allowed_models = {"persistence", "har_rv", "ridge", "elastic_net", "gamma_glm", "lightgbm"}
    if model_name not in allowed_models:
        raise ValueError(f"UNKNOWN_DEVELOPMENT_MODEL:{model_name}")
    missing = (set(features) | {"rv30"}) - set(frame.columns)
    if missing:
        raise ValueError(f"DEVELOPMENT_MODEL_COLUMNS_MISSING:{','.join(sorted(missing))}")
    if "rv30" in features or not features:
        raise ValueError("DEVELOPMENT_TARGET_IN_FEATURES_OR_EMPTY")
    target = np.asarray(frame["rv30"].to_numpy(), dtype=np.float64)
    if not np.isfinite(target).all() or (target <= 0).any():
        raise ValueError("DEVELOPMENT_TARGET_INVALID")
    if forecast_floor <= 0:
        raise ValueError("DEVELOPMENT_FORECAST_FLOOR_INVALID")
    if model_name == "persistence":
        if parameters:
            raise ValueError("PERSISTENCE_PARAMETERS_NOT_ALLOWED")
        return FittedDevelopmentCandidate(model_name, features, None, False, forecast_floor)
    if model_name in {"gamma_glm", "lightgbm"}:
        role = "gamma_glm_confirmatory" if model_name == "gamma_glm" else "lightgbm_robustness"
        fitted = fit_positive_model(
            frame,
            feature_columns=features,
            categorical_columns=("asset",) if "asset" in features else (),
            target_column="rv30",
            role=role,
            parameters=parameters,
            seed=seed,
            forecast_floor=forecast_floor,
        )
        return FittedDevelopmentCandidate(model_name, features, fitted, False, forecast_floor)
    if model_name not in {"har_rv", "ridge", "elastic_net"}:
        raise ValueError(f"UNKNOWN_DEVELOPMENT_MODEL:{model_name}")
    numeric = frame.select([name for name in features if name != "asset"]).to_numpy()
    if not np.isfinite(numeric).all():
        raise ValueError("DEVELOPMENT_FEATURE_INVALID")
    estimator = _log_linear_pipeline(features, model_name, parameters, seed)
    estimator.fit(frame.select(features).to_pandas(), np.log(np.maximum(target, forecast_floor)))
    return FittedDevelopmentCandidate(model_name, features, estimator, True, forecast_floor)
