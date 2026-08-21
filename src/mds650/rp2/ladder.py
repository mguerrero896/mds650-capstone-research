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

from mds650.rp2.qlike_objective import EXPONENT_CLIP, lightgbm_objective

type FloatArray = npt.NDArray[np.float64]

VARIANCE_FLOOR: Final = 1e-12
_LIGHTGBM_ROUNDS: Final = 300
_LIGHTGBM_LEAVES: Final = 31
_LIGHTGBM_LEARNING_RATE: Final = 0.05


def _log(values: FloatArray) -> FloatArray:
    return np.log(np.maximum(values, VARIANCE_FLOOR))


def _smearing(residuals: FloatArray) -> float:
    return float(np.exp(0.5 * float(np.var(residuals))))


def fit_log_ols(design: FloatArray, target: FloatArray, train: npt.NDArray[np.bool_]) -> FloatArray:
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


def fit_lightgbm_qlike(
    design: FloatArray,
    target: FloatArray,
    train: npt.NDArray[np.bool_],
    *,
    monotone: Sequence[int] | None = None,
    seed: int = 20260818,
) -> FloatArray:
    """Gradient-boosted trees that descend QLIKE itself.

    The decision criterion of this programme is QLIKE, and the log-MSE variant is judged on
    it after being trained on something else. Log-MSE is symmetric in log space: it charges
    the same for over-forecasting a variance by a factor of two as for under-forecasting it
    by a factor of two. QLIKE does not, and QLIKE is what decides the result.

    No smearing correction is applied and none is needed. The minimiser of
    ``E[y e^{-z} + z]`` is ``e^z = E[y | x]``, so the raw score already targets the
    conditional mean of the variance rather than of its logarithm — the retransformation
    bias the log-MSE fit has to correct for never arises.
    """

    import lightgbm as lgb

    parameters: dict[str, object] = {
        "objective": lightgbm_objective(target[train]),
        "num_leaves": _LIGHTGBM_LEAVES,
        "learning_rate": _LIGHTGBM_LEARNING_RATE,
        "verbose": -1,
        "seed": seed,
        "deterministic": True,
        "force_row_wise": True,
    }
    if monotone is not None:
        parameters["monotone_constraints"] = list(monotone)
    # The booster starts from the training mean log variance rather than from zero: a first
    # step of exp(0) = 1 against a target near 1e-8 is a gradient of -1e8.
    start = float(np.mean(_log(target[train])))
    dataset = lgb.Dataset(
        design[train],
        label=_log(target[train]),
        init_score=np.full(int(train.sum()), start),
        free_raw_data=False,
    )
    booster = lgb.train(parameters, dataset, num_boost_round=_LIGHTGBM_ROUNDS)
    raw = start + np.asarray(booster.predict(design), dtype=np.float64)
    return np.asarray(np.exp(np.clip(raw, -EXPONENT_CLIP, EXPONENT_CLIP)), dtype=np.float64)


@dataclass(frozen=True, slots=True)
class PooledIntercepts:
    """Empirical-Bayes partial pooling of per-group offsets."""

    grand_mean: float
    between_variance: float
    offsets: dict[int, float]
    #: The sampling variance of each group's mean, with the SESSION as the unit. Published
    #: so a reader can see the term tau^2 is measured against rather than infer it.
    sampling_variance: dict[int, float]

    def apply(self, groups: npt.NDArray[np.int64]) -> FloatArray:
        return np.array([self.offsets.get(int(g), 0.0) for g in groups], dtype=np.float64)


def session_weighted_level(losses: FloatArray, sessions: npt.NDArray[np.int64]) -> float:
    """Mean loss with the session as the unit, matching the contrasts beside it.

    The contrasts aggregate to the session first, because origins five minutes apart share
    overlapping thirty-minute targets: a busy session would otherwise outweigh a quiet one
    and an early close would count for less than a full day. The published LEVELS averaged
    every evaluated row instead, so `level(base) - level(expanded)` did not reproduce the
    published delta - by 2.2 % for gamma_glm and 2.0 % for ridge_log on the RP2-v3
    development panel. Two numbers in one record that do not describe the same quantity are
    worse than either alone.
    """

    if losses.shape != sessions.shape:
        raise ValueError("RP2_LADDER_LEVEL_SHAPE_MISMATCH")
    finite = np.isfinite(losses)
    if not finite.any():
        return float("nan")
    values, labels = losses[finite], sessions[finite]
    means = np.array([values[labels == label].mean() for label in np.unique(labels)])
    return float(means.mean())


def partial_pooling(
    residuals: FloatArray,
    groups: npt.NDArray[np.int64],
    train: npt.NDArray[np.bool_],
    *,
    sessions: npt.NDArray[np.int64],
) -> PooledIntercepts:
    """Shrink per-group mean residuals toward zero by their own signal-to-noise ratio.

    ``theta_g ~ N(mu, tau^2)`` estimated by moments: the shrinkage weight is
    ``tau^2 / (tau^2 + v_g)``, where ``v_g`` is the sampling variance of group g's mean.
    Total pooling when groups are indistinguishable, none when they are sharply different.
    This is the level-3 model the program asks for, without a sampler.

    ``v_g`` is measured with the SESSION as the unit. It was ``sigma^2 / n_g`` with ``n_g``
    the number of ORIGINS in the group - 15,270 per asset in the published fit - which is
    the sampling variance only if residuals inside a group are independent. They are not:
    origins are five minutes apart and share overlapping thirty-minute targets, which is
    why `aggregate_by_session`, `_contrast` and `session_weighted_level` all refuse to
    treat them as the unit. On the published development fit the origin-based term was
    1.4473e-5 against a session-clustered 8.5937e-5, 5.9 times smaller, so tau^2 came out
    inflated and the intercepts were shrunk too little: weight 0.969 against 0.817.
    """

    if residuals.shape != groups.shape or residuals.shape != train.shape:
        raise ValueError("RP2_POOLING_SHAPE_MISMATCH")
    if sessions.shape != residuals.shape:
        raise ValueError("RP2_POOLING_SESSION_SHAPE_MISMATCH")
    usable = train & np.isfinite(residuals)
    if not usable.any():
        return PooledIntercepts(
            grand_mean=0.0, between_variance=0.0, offsets={}, sampling_variance={}
        )
    grand = float(np.mean(residuals[usable]))
    means: dict[int, float] = {}
    sampling: dict[int, float] = {}
    for group in np.unique(groups[usable]):
        mask = usable & (groups == group)
        block = residuals[mask]
        means[int(group)] = float(np.mean(block))
        # One value per session, then the variance of those over their own count. A group
        # observed on many origins of few sessions has the precision of the few sessions.
        labels = sessions[mask]
        per_session = np.array(
            [block[labels == label].mean() for label in np.unique(labels)], dtype=np.float64
        )
        sampling[int(group)] = (
            float(np.var(per_session, ddof=1)) / per_session.size if per_session.size > 1 else 0.0
        )
    # The sample variance of G group means, not the population variance of them. With the
    # six assets this programme runs, `np.var`'s default divisor of G understates the
    # spread by a sixth, and tau^2 is the numerator of the shrinkage weight: a smaller tau
    # pulls every per-asset intercept harder toward the grand mean than the data supports.
    # The subtraction below floors at zero, so an understated spread can collapse the term
    # entirely and turn partial pooling into total pooling without saying so.
    spread = float(np.var(list(means.values()), ddof=1)) if len(means) > 1 else 0.0
    # E[Var(m_g | theta_g)] over the groups, each measured on its own sessions.
    between = max(spread - float(np.mean(list(sampling.values()))), 0.0) if sampling else 0.0
    offsets: dict[int, float] = {}
    for group, mean in means.items():
        weight = between / (between + sampling[group]) if between > 0.0 else 0.0
        offsets[group] = weight * (mean - grand)
    return PooledIntercepts(
        grand_mean=grand,
        between_variance=between,
        offsets=offsets,
        sampling_variance=sampling,
    )


#: Every model the ladder runs, keyed by name.
Fitter = Callable[[FloatArray, FloatArray, npt.NDArray[np.bool_]], FloatArray]

#: The three primary families of the frozen research contract. No fourth family is added
#: until these are closed; a family introduced after the numbers arrive is a search over
#: model space wearing the costume of a robustness check.
PRIMARY_MODELS: Final[tuple[str, ...]] = ("gamma_glm", "ridge_log", "lightgbm_qlike")

LADDER: Final[dict[str, Fitter]] = {
    "log_ols": fit_log_ols,
    "ridge_log": fit_ridge_log,
    "gamma_glm": fit_gamma_glm,
    "tweedie_glm": fit_tweedie_glm,
    "spline_additive": fit_spline_additive,
    "lightgbm": fit_lightgbm,
    "lightgbm_qlike": fit_lightgbm_qlike,
}

#: Families that count as genuinely independent for the two-family requirement.
def assert_primary_models(models: Sequence[str]) -> None:
    """Refuse a run that would report results without one of the deciding families.

    The contract freezes three families and the programme's conclusions are read off them.
    A run that quietly dropped one would still produce an artifact, and the artifact would
    look complete.
    """

    fitted = set(models)
    for name in PRIMARY_MODELS:
        if name not in fitted:
            raise ValueError(f"RP2_PRIMARY_MODEL_MISSING:{name}")


INDEPENDENT_FAMILIES: Final[dict[str, str]] = {
    "log_ols": "smooth_linear",
    "ridge_log": "smooth_linear",
    "gamma_glm": "smooth_glm",
    "tweedie_glm": "smooth_glm",
    "spline_additive": "smooth_additive",
    "lightgbm": "tree",
    "lightgbm_qlike": "tree",
}
