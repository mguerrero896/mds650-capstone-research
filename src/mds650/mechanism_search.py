"""Outcome-blind, residual-learning primitives for the B2 mechanism audit.

The module deliberately keeps the mechanism search small.  A B1 forecast is
fit first; B2 is then allowed to predict only the signed residual of that
forecast.  The conditional variants add predeclared interactions with asset,
session-tercile (hour segment) or training-defined volatility regime.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import polars as pl
from sklearn.linear_model import ElasticNet, Ridge  # type: ignore[import-untyped]
from sklearn.pipeline import Pipeline  # type: ignore[import-untyped]
from sklearn.preprocessing import StandardScaler  # type: ignore[import-untyped]

from mds650.development_models import (
    B1_FEATURES as REGISTERED_B1_FEATURES,
)
from mds650.development_models import (
    B2_FEATURES as REGISTERED_B2_FEATURES,
)

FORECAST_FLOOR = 1e-12
SEED = 650
B2_FEATURES = tuple(name for name in REGISTERED_B2_FEATURES if name not in REGISTERED_B1_FEATURES)
MECHANISM_VARIANTS = (
    "global_ridge",
    "asset_ridge",
    "hour_ridge",
    "regime_ridge",
    "global_elastic_net",
)
_CONDITIONAL_GROUPS = {
    "asset_ridge": "asset",
    "hour_ridge": "session_tercile",
    "regime_ridge": "volatility_regime",
}


def add_predeclared_strata(
    frame: pl.DataFrame,
    *,
    volatility_cutpoints: tuple[float, float] | None = None,
) -> pl.DataFrame:
    """Add deterministic hour and volatility strata without using the target.

    Parameters
    ----------
    frame:
        Rows containing ``b0_session_minute`` and ``b0_rv_30m_lag``.
    volatility_cutpoints:
        Optional ``(lower, upper)`` cutpoints learned from training rows only.
        If omitted, quantiles are computed from ``frame`` for fixture use; the
        production runner always supplies training-derived cutpoints.

    Returns
    -------
    polars.DataFrame
        Input rows plus ``session_tercile`` and ``volatility_regime``.

    Raises
    ------
    ValueError
        If required columns or finite cutpoints are absent.
    """
    required = {"b0_session_minute", "b0_rv_30m_lag"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"MECHANISM_STRATA_COLUMNS_MISSING:{','.join(sorted(missing))}")
    if volatility_cutpoints is None:
        quantiles = frame.select(
            pl.col("b0_rv_30m_lag").quantile(1 / 3).alias("lower"),
            pl.col("b0_rv_30m_lag").quantile(2 / 3).alias("upper"),
        ).row(0)
        lower, upper = float(quantiles[0]), float(quantiles[1])
    else:
        lower, upper = map(float, volatility_cutpoints)
    if not np.isfinite([lower, upper]).all() or lower >= upper:
        raise ValueError("MECHANISM_STRATA_CUTPOINTS_INVALID")
    minute = pl.col("b0_session_minute")
    return frame.with_columns(
        pl.when(minute <= 130)
        .then(pl.lit("first"))
        .when(minute <= 260)
        .then(pl.lit("middle"))
        .otherwise(pl.lit("last"))
        .alias("session_tercile"),
        pl.when(pl.col("b0_rv_30m_lag") <= lower)
        .then(pl.lit("low"))
        .when(pl.col("b0_rv_30m_lag") <= upper)
        .then(pl.lit("normal"))
        .otherwise(pl.lit("high"))
        .alias("volatility_regime"),
    )


def _validate_b2_frame(frame: pl.DataFrame, mechanism_id: str) -> None:
    """Validate a target-blind design frame before conversion to NumPy."""
    if mechanism_id not in MECHANISM_VARIANTS:
        raise ValueError(f"UNKNOWN_MECHANISM_VARIANT:{mechanism_id}")
    forbidden_names = {
        "rv30",
        "qlike",
        "qlike_loss",
        "target",
        "forecast",
        "prediction",
        "b1_prediction",
        "residual_target",
    }
    forbidden = {name for name in frame.columns if name.lower() in forbidden_names}
    if forbidden:
        raise ValueError(f"MECHANISM_TARGET_COLUMN_FORBIDDEN:{','.join(sorted(forbidden))}")
    missing = set(B2_FEATURES) - set(frame.columns)
    group = _CONDITIONAL_GROUPS.get(mechanism_id)
    if group is not None:
        missing.add(group) if group not in frame.columns else None
    if missing:
        raise ValueError(f"MECHANISM_FEATURES_MISSING:{','.join(sorted(missing))}")
    values = frame.select(B2_FEATURES).to_numpy()
    if values.ndim != 2 or not np.isfinite(values).all():
        raise ValueError("MECHANISM_FEATURES_NONFINITE")


def build_mechanism_matrix(
    frame: pl.DataFrame,
    mechanism_id: str,
    *,
    levels: Sequence[str] | None = None,
) -> tuple[np.ndarray, tuple[str, ...]]:
    """Build a deterministic B2-only matrix for one registered mechanism.

    Parameters
    ----------
    frame:
        B2 columns and, for conditional variants, the grouping column.
    mechanism_id:
        One of :data:`MECHANISM_VARIANTS`.
    levels:
        Optional training-derived group levels.  Test rows must reuse the same
        levels so no category is chosen from outcome performance.

    Returns
    -------
    tuple[numpy.ndarray, tuple[str, ...]]
        Numeric matrix and its deterministic column names.

    Raises
    ------
    ValueError
        If the frame violates the target-blind contract.
    """
    _validate_b2_frame(frame, mechanism_id)
    base = frame.select(B2_FEATURES).to_numpy().astype(np.float64, copy=False)
    names = list(B2_FEATURES)
    group = _CONDITIONAL_GROUPS.get(mechanism_id)
    if group is None:
        return base, tuple(names)
    values = [str(value) for value in frame[group].to_list()]
    chosen = tuple(levels) if levels is not None else tuple(sorted(set(values)))
    if not chosen:
        raise ValueError("MECHANISM_GROUP_LEVELS_EMPTY")
    blocks = [base]
    for level in chosen:
        mask = np.asarray([value == level for value in values], dtype=np.float64)[:, None]
        blocks.append(base * mask)
        names.extend(f"{feature}__{group}__{level}" for feature in B2_FEATURES)
    return np.column_stack(blocks), tuple(names)


@dataclass(frozen=True)
class FittedResidualLearner:
    """Fitted B2 correction model with a frozen target-blind feature contract."""

    mechanism_id: str
    feature_names: tuple[str, ...]
    group_levels: tuple[str, ...]
    estimator: Pipeline
    forecast_floor: float = FORECAST_FLOOR

    def predict_correction(self, frame: pl.DataFrame) -> np.ndarray:
        """Predict the signed B2 correction for rows at or before their origin."""
        matrix, names = build_mechanism_matrix(
            frame,
            self.mechanism_id,
            levels=self.group_levels or None,
        )
        if names != self.feature_names:
            raise ValueError("MECHANISM_FEATURE_SCHEMA_DRIFT")
        correction = np.asarray(self.estimator.predict(matrix), dtype=np.float64)
        if correction.shape != (frame.height,) or not np.isfinite(correction).all():
            raise ValueError("MECHANISM_CORRECTION_NONFINITE")
        return correction


def fit_residual_learner(
    frame: pl.DataFrame,
    residual_target: Sequence[float],
    *,
    mechanism_id: str,
    seed: int = SEED,
) -> FittedResidualLearner:
    """Fit B2 only on a cross-fitted B1 residual target.

    ``residual_target`` must be generated from predictions that were produced
    without fitting the B1 model on the same row.  The function intentionally
    accepts the residual separately from ``frame`` so RV30 cannot accidentally
    become a predictor.

    Parameters
    ----------
    frame:
        Target-blind B2 columns plus optional conditional grouping columns.
    residual_target:
        Signed ``RV30 - B1_prediction`` values from training rows only.
    mechanism_id:
        Registered global or conditional mechanism.
    seed:
        Deterministic Elastic Net seed.

    Returns
    -------
    FittedResidualLearner
        Model that predicts only the B2 residual correction.

    Raises
    ------
    ValueError
        If dimensions, target values or the mechanism contract are invalid.
    """
    matrix, names = build_mechanism_matrix(frame, mechanism_id)
    residual = np.asarray(residual_target, dtype=np.float64)
    if residual.shape != (frame.height,) or not np.isfinite(residual).all():
        raise ValueError("MECHANISM_RESIDUAL_TARGET_INVALID")
    if mechanism_id == "global_elastic_net":
        estimator = ElasticNet(
            alpha=0.01,
            l1_ratio=0.5,
            max_iter=5_000,
            tol=1e-5,
            random_state=seed,
        )
    else:
        estimator = Ridge(alpha=1.0)
    pipeline = Pipeline([("scale", StandardScaler()), ("model", estimator)])
    pipeline.fit(matrix, residual)
    group = _CONDITIONAL_GROUPS.get(mechanism_id)
    levels = tuple(sorted(str(value) for value in frame[group].unique().to_list())) if group else ()
    return FittedResidualLearner(mechanism_id, names, levels, pipeline)


def combine_base_and_residual(
    base_forecast: Sequence[float] | np.ndarray,
    correction: Sequence[float] | np.ndarray,
    *,
    forecast_floor: float = FORECAST_FLOOR,
) -> np.ndarray:
    """Add a signed residual correction and enforce a positive RV30 floor."""
    base = np.asarray(base_forecast, dtype=np.float64)
    delta = np.asarray(correction, dtype=np.float64)
    if (
        base.ndim != 1
        or delta.shape != base.shape
        or not np.isfinite(base).all()
        or not np.isfinite(delta).all()
    ):
        raise ValueError("MECHANISM_FORECAST_SHAPE_OR_FINITE_INVALID")
    if forecast_floor <= 0:
        raise ValueError("MECHANISM_FORECAST_FLOOR_INVALID")
    return np.maximum(base + delta, forecast_floor)


def permute_residual_target(residual_target: Sequence[float], *, seed: int = SEED) -> np.ndarray:
    """Return a deterministic target-permutation placebo for the residual fit."""
    values = np.asarray(residual_target, dtype=np.float64)
    if values.ndim != 1 or not np.isfinite(values).all() or values.size < 2:
        raise ValueError("MECHANISM_PLACEBO_TARGET_INVALID")
    generator = np.random.default_rng(seed)
    return generator.permutation(values)


def lag_b2_one_session(frame: pl.DataFrame) -> pl.DataFrame:
    """Create a one-session-lagged B2 sensitivity by asset and origin minute."""
    required = {"asset", "session_date", "b0_session_minute", "forecast_origin_utc", *B2_FEATURES}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"MECHANISM_LAG_COLUMNS_MISSING:{','.join(sorted(missing))}")
    return (
        frame.sort(["asset", "b0_session_minute", "session_date", "forecast_origin_utc"])
        .with_columns(
            pl.col(feature).shift(1).over(["asset", "b0_session_minute"]).alias(feature)
            for feature in B2_FEATURES
        )
        .drop_nulls(B2_FEATURES)
    )
