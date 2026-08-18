"""Block 8 - the model ladder.

Level 1 (smooth / parametric), level 2 (non-linear tabular) and level 3 (hierarchical
partial pooling) are implemented here behind one interface: every model is fitted on a
boolean training mask and returns a variance forecast for **all** rows, so the caller
decides what is in and out of sample.

Level 4 (trade-sequence networks) is intentionally absent: the program gates it behind
"only after demonstrating that the tabular baseline does not capture the signal", and no
deep-learning stack is installed in this environment.  Its absence is reported, not faked.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Final

import numpy as np
import numpy.typing as npt
from sklearn.linear_model import (  # type: ignore[import-untyped]
    GammaRegressor,
    Ridge,
    TweedieRegressor,
)
from sklearn.preprocessing import SplineTransformer  # type: ignore[import-untyped]

type FloatArray = npt.NDArray[np.float64]

VARIANCE_FLOOR: Final = 1e-12
_LIGHTGBM_ROUNDS: Final = 300
_LIGHTGBM_LEAVES: Final = 31
_LIGHTGBM_LEARNING_RATE: Final = 0.05


def _log(values: FloatArray) -> FloatArray:
    return np.log(np.maximum(values, VARIANCE_FLOOR))


def _smearing(residuals: FloatArray) -> float:
    return float(np.exp(0.5 * float(np.var(residuals))))


def fit_log_ols(
    design: FloatArray, target: FloatArray, train: npt.NDArray[np.bool_]
) -> FloatArray:
    """Ordinary least squares on log variance with lognormal retransformation."""

    response = _log(target)
    coefficients, *_ = np.linalg.lstsq(design[train], response[train], rcond=None)
    fitted = design @ coefficients
    return np.asarray(np.exp(fitted) * _smearing(response[train] - fitted[train]))


def fit_ridge_log(
    design: FloatArray, target: FloatArray, train: npt.NDArray[np.bool_], *, alpha: float = 1.0
) -> FloatArray:
    """Ridge on log variance - the regularised sibling of :func:`fit_log_ols`."""

    response = _log(target)
    model = Ridge(alpha=alpha, fit_intercept=False)
    model.fit(design[train], response[train])
    fitted = np.asarray(model.predict(design), dtype=np.float64)
    return np.asarray(np.exp(fitted) * _smearing(response[train] - fitted[train]))


def fit_gamma_glm(
    design: FloatArray, target: FloatArray, train: npt.NDArray[np.bool_], *, alpha: float = 1e-4
) -> FloatArray:
    """Gamma GLM with a log link, fitted on the variance scale directly."""

    model = GammaRegressor(alpha=alpha, fit_intercept=False, max_iter=500)
    model.fit(design[train], np.maximum(target[train], VARIANCE_FLOOR))
    return np.asarray(model.predict(design), dtype=np.float64)


def fit_tweedie_glm(
    design: FloatArray, target: FloatArray, train: npt.NDArray[np.bool_], *, power: float = 1.7
) -> FloatArray:
    """Tweedie GLM, a compromise between Poisson and Gamma variance functions."""

    model = TweedieRegressor(power=power, alpha=1e-4, fit_intercept=False, max_iter=500)
    model.fit(design[train], np.maximum(target[train], VARIANCE_FLOOR))
    return np.asarray(model.predict(design), dtype=np.float64)


def fit_spline_additive(
    design: FloatArray, target: FloatArray, train: npt.NDArray[np.bool_], *, knots: int = 6
) -> FloatArray:
    """Additive spline model: a GAM in the generalised-additive sense, on log variance.

    Each column gets its own B-spline basis and the bases are summed - no interactions -
    which is what makes it a genuinely different family from a boosted tree.
    """

    response = _log(target)
    transformer = SplineTransformer(n_knots=knots, degree=3, include_bias=False)
    transformer.fit(design[train])
    basis = np.asarray(transformer.transform(design), dtype=np.float64)
    basis = np.column_stack([np.ones(basis.shape[0]), basis])
    model = Ridge(alpha=1.0, fit_intercept=False)
    model.fit(basis[train], response[train])
    fitted = np.asarray(model.predict(basis), dtype=np.float64)
    return np.asarray(np.exp(fitted) * _smearing(response[train] - fitted[train]))


def fit_lightgbm(
    design: FloatArray,
    target: FloatArray,
    train: npt.NDArray[np.bool_],
    *,
    monotone: Sequence[int] | None = None,
    seed: int = 20260818,
) -> FloatArray:
    """Gradient-boosted trees on log variance, optionally with monotone constraints."""

    import lightgbm as lgb

    response = _log(target)
    parameters: dict[str, object] = {
        "objective": "regression",
        "num_leaves": _LIGHTGBM_LEAVES,
        "learning_rate": _LIGHTGBM_LEARNING_RATE,
        "verbose": -1,
        "seed": seed,
        "deterministic": True,
        "force_row_wise": True,
    }
    if monotone is not None:
        parameters["monotone_constraints"] = list(monotone)
    dataset = lgb.Dataset(design[train], label=response[train], free_raw_data=False)
    booster = lgb.train(parameters, dataset, num_boost_round=_LIGHTGBM_ROUNDS)
    fitted = np.asarray(booster.predict(design), dtype=np.float64)
    return np.asarray(np.exp(fitted) * _smearing(response[train] - fitted[train]))


@dataclass(frozen=True, slots=True)
class PooledIntercepts:
    """Empirical-Bayes partial pooling of per-group offsets."""

    grand_mean: float
    between_variance: float
    offsets: dict[int, float]

    def apply(self, groups: npt.NDArray[np.int64]) -> FloatArray:
        return np.array([self.offsets.get(int(g), 0.0) for g in groups], dtype=np.float64)


def partial_pooling(
    residuals: FloatArray, groups: npt.NDArray[np.int64], train: npt.NDArray[np.bool_]
) -> PooledIntercepts:
    """Shrink per-group mean residuals toward zero by their own signal-to-noise ratio.

    ``theta_g ~ N(mu, tau^2)`` estimated by moments: the shrinkage weight is
    ``tau^2 / (tau^2 + sigma^2 / n_g)``, which is total pooling when groups are
    indistinguishable and no pooling when they are sharply different.  This is the
    level-3 model the program asks for, without a sampler.
    """

    if residuals.shape != groups.shape or residuals.shape != train.shape:
        raise ValueError("RP2_POOLING_SHAPE_MISMATCH")
    usable = train & np.isfinite(residuals)
    if not usable.any():
        return PooledIntercepts(grand_mean=0.0, between_variance=0.0, offsets={})
    grand = float(np.mean(residuals[usable]))
    within = float(np.var(residuals[usable]))
    means: dict[int, float] = {}
    counts: dict[int, int] = {}
    for group in np.unique(groups[usable]):
        mask = usable & (groups == group)
        means[int(group)] = float(np.mean(residuals[mask]))
        counts[int(group)] = int(mask.sum())
    spread = float(np.var(list(means.values()))) if len(means) > 1 else 0.0
    between = max(spread - within / max(np.mean(list(counts.values())), 1.0), 0.0)
    offsets: dict[int, float] = {}
    for group, mean in means.items():
        weight = between / (between + within / max(counts[group], 1)) if between > 0.0 else 0.0
        offsets[group] = weight * (mean - grand)
    return PooledIntercepts(grand_mean=grand, between_variance=between, offsets=offsets)


#: Every model the ladder runs, keyed by name.
Fitter = Callable[[FloatArray, FloatArray, npt.NDArray[np.bool_]], FloatArray]

LADDER: Final[dict[str, Fitter]] = {
    "log_ols": fit_log_ols,
    "ridge_log": fit_ridge_log,
    "gamma_glm": fit_gamma_glm,
    "tweedie_glm": fit_tweedie_glm,
    "spline_additive": fit_spline_additive,
    "lightgbm": fit_lightgbm,
}

#: Families that count as genuinely independent for the two-family requirement.
INDEPENDENT_FAMILIES: Final[dict[str, str]] = {
    "log_ols": "smooth_linear",
    "ridge_log": "smooth_linear",
    "gamma_glm": "smooth_glm",
    "tweedie_glm": "smooth_glm",
    "spline_additive": "smooth_additive",
    "lightgbm": "tree",
}
