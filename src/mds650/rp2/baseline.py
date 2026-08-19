"""Block 4 - Gate 3: baseline machinery for a B0 that is hard to beat.

Holds the challenger models the program requires B0 to beat (persistence, intraday mean,
EWMA, simple HAR, intraday GARCH) plus the calibration diagnostic that decides whether any
B1/B2 advantage on top of it is interpretable at all.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Final

import numpy as np
import numpy.typing as npt
from scipy.optimize import minimize

type FloatArray = npt.NDArray[np.float64]
type IntArray = npt.NDArray[np.int64]

VARIANCE_FLOOR: Final = 1e-12
#: RiskMetrics-style default for the one-minute EWMA recursion.
EWMA_LAMBDA: Final = 0.97
#: Observations required before a cold-started recursion reports a level at all.
EWMA_WARMUP: Final = 20


def causal_ewma_horizon_variance(
    returns: FloatArray,
    origins: IntArray,
    *,
    decay: float = EWMA_LAMBDA,
    horizon: int,
    initial_state: float | None,
    warmup: int = EWMA_WARMUP,
) -> tuple[FloatArray, float]:
    """Forecast the variance of the next ``horizon`` minutes from observed returns alone.

    The recursion is the RiskMetrics one, ``h_t = lam h_{t-1} + (1 - lam) r_{t-1}^2``, run
    over one-minute returns, and the forecast at an origin is ``horizon * h_t``. It is
    causal by construction: ``h`` at an origin has absorbed the returns strictly before it
    and nothing else, so perturbing the tape after the origin cannot move the number.

    ``initial_state`` carries the recursion across a session break. Passing ``None`` starts
    cold, seeding from the expanding mean of squared returns until ``warmup`` observations
    exist; earlier origins return NaN rather than a confident level built from two points.
    The final state is returned so the next session continues from it, which is what makes
    the series one recursion per asset rather than one per session.

    Nothing here reads the target. The producer previously fed the EWMA the square root of
    RV30 itself, which made the benchmark a smoothed copy of the answer.
    """

    if not 0.0 < decay < 1.0:
        raise ValueError("RP2_EWMA_DECAY_INVALID")
    if returns.ndim != 1:
        raise ValueError("RP2_EWMA_SERIES_INVALID")
    if horizon < 1:
        raise ValueError("RP2_EWMA_HORIZON_INVALID")
    if warmup < 1:
        raise ValueError("RP2_EWMA_WARMUP_INVALID")
    if origins.size and (int(origins.min()) < 0 or int(origins.max()) > returns.size):
        raise ValueError("RP2_EWMA_ORIGIN_OUT_OF_RANGE")

    squared = returns**2
    #: ``states[k]`` is the variance state after absorbing ``returns[:k]``.
    states = np.full(returns.size + 1, np.nan, dtype=np.float64)
    state = initial_state
    running_sum = 0.0
    for index in range(returns.size + 1):
        if state is not None and (initial_state is not None or index >= warmup):
            states[index] = state
        if index == returns.size:
            break
        if initial_state is None and index < warmup:
            running_sum += float(squared[index])
            state = running_sum / (index + 1)
        else:
            assert state is not None
            state = decay * state + (1.0 - decay) * float(squared[index])
    carried = state if state is not None else float("nan")
    return horizon * states[origins], float(carried)


@dataclass(frozen=True, slots=True)
class Garch11:
    """Fitted zero-mean GARCH(1,1) parameters."""

    omega: float
    alpha: float
    beta: float

    @property
    def persistence(self) -> float:
        return self.alpha + self.beta

    def filter(self, returns: FloatArray) -> FloatArray:
        """Conditional variances, ``out[i]`` conditioned on ``returns[:i]``."""

        out = np.empty(returns.size, dtype=np.float64)
        unconditional = self.omega / max(1.0 - self.persistence, 1e-6)
        state = unconditional
        for index in range(returns.size):
            out[index] = state
            state = self.omega + self.alpha * float(returns[index] ** 2) + self.beta * state
        return out


def fit_garch11(returns: FloatArray, *, scale: float = 1e4) -> Garch11:
    """Quasi-maximum-likelihood GARCH(1,1) on zero-mean returns.

    Returns are rescaled before optimisation because one-minute variances are ~1e-8 and
    unscaled optimisation is numerically hopeless; the parameters are scaled back.
    """

    if returns.ndim != 1 or returns.size < 100:
        raise ValueError("RP2_GARCH_SERIES_TOO_SHORT")
    scaled = returns * scale
    variance = float(np.var(scaled))

    def negative_log_likelihood(theta: FloatArray) -> float:
        omega, alpha, beta = np.exp(theta[0]), _logistic(theta[1]), _logistic(theta[2])
        if alpha + beta >= 0.999:
            return 1e12
        model = Garch11(omega=float(omega), alpha=float(alpha), beta=float(beta))
        sigma2 = np.maximum(model.filter(scaled), 1e-10)
        return float(0.5 * np.sum(np.log(sigma2) + scaled**2 / sigma2))

    start = np.array([math.log(max(variance, 1e-8) * 0.05), _logit(0.08), _logit(0.90)])
    result = minimize(
        negative_log_likelihood,
        start,
        method="Nelder-Mead",
        options={"maxiter": 2000, "fatol": 1e-6, "xatol": 1e-6},
    )
    omega, alpha, beta = (
        float(np.exp(result.x[0])),
        float(_logistic(result.x[1])),
        float(_logistic(result.x[2])),
    )
    return Garch11(omega=omega / scale**2, alpha=alpha, beta=beta)


def _logistic(value: float) -> float:
    return 1.0 / (1.0 + math.exp(-value))


def _logit(value: float) -> float:
    return math.log(value / (1.0 - value))


def seasonality_index(
    minute_bucket: npt.NDArray[np.int64],
    log_variance: FloatArray,
    train: npt.NDArray[np.bool_],
    *,
    buckets: int,
) -> FloatArray:
    """Mean training log-variance per intraday bucket, centred on the global mean.

    Buckets never observed in training fall back to the global mean, so the index is
    defined everywhere without leaking test-period information.
    """

    if minute_bucket.shape != log_variance.shape or minute_bucket.shape != train.shape:
        raise ValueError("RP2_SEASONALITY_SHAPE_MISMATCH")
    global_mean = float(np.mean(log_variance[train])) if train.any() else 0.0
    totals = np.zeros(buckets, dtype=np.float64)
    counts = np.zeros(buckets, dtype=np.int64)
    np.add.at(totals, minute_bucket[train], log_variance[train])
    np.add.at(counts, minute_bucket[train], 1)
    means = np.where(counts > 0, totals / np.maximum(counts, 1), global_mean)
    return (means - global_mean)[minute_bucket]


@dataclass(frozen=True, slots=True)
class Calibration:
    """Mincer-Zarnowitz calibration of a variance forecast on the log scale."""

    intercept: float
    slope: float
    r_squared: float
    residual_std: float

    @property
    def well_calibrated(self) -> bool:
        """Slope within 0.15 of one and intercept small relative to residual spread.

        The intercept tolerance carries an absolute floor so that a (degenerate) perfect
        forecast, whose residual spread is zero, is not failed by floating-point dust.
        """

        tolerance = max(0.5 * self.residual_std, 0.05)
        return abs(self.slope - 1.0) <= 0.15 and abs(self.intercept) <= tolerance


def mincer_zarnowitz(actual: FloatArray, forecast: FloatArray) -> Calibration:
    """Regress ``log actual`` on ``log forecast``; a perfect forecast gives (0, 1)."""

    if actual.shape != forecast.shape or actual.size < 3:
        raise ValueError("RP2_CALIBRATION_SHAPE_INVALID")
    response = np.log(np.maximum(actual, VARIANCE_FLOOR))
    regressor = np.log(np.maximum(forecast, VARIANCE_FLOOR))
    design = np.column_stack([np.ones(regressor.size), regressor])
    coefficients, *_ = np.linalg.lstsq(design, response, rcond=None)
    fitted = design @ coefficients
    residual = response - fitted
    centred = response - response.mean()
    denominator = float(centred @ centred)
    r_squared = 1.0 - float(residual @ residual) / denominator if denominator > 0 else float("nan")
    return Calibration(
        intercept=float(coefficients[0]),
        slope=float(coefficients[1]),
        r_squared=r_squared,
        residual_std=float(np.std(residual)),
    )


def smearing_factor(log_residuals: FloatArray) -> float:
    """Lognormal retransformation factor ``exp(0.5 * Var(residual))``."""

    if log_residuals.size == 0:
        raise ValueError("RP2_SMEARING_EMPTY")
    return float(np.exp(0.5 * float(np.var(log_residuals))))
