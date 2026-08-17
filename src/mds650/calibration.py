"""Mincer-Zarnowitz calibration diagnostics and log-scale recalibration.

Gate 2 machinery: quantifies forecast calibration per model x information set
and applies a training-only (or prespecified split-sample) log-scale
recalibration so the B2 increment can be re-estimated on bias-corrected
forecasts. If the Gamma-specific B2 gain collapses once the baseline is
recalibrated, the gain was bias repair, not information (pre-stated rule).
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np
from numpy.typing import NDArray

type FloatArray = NDArray[np.float64]


def _positive_arrays(
    actual: Sequence[float] | FloatArray,
    forecast: Sequence[float] | FloatArray,
) -> tuple[FloatArray, FloatArray]:
    observed = np.asarray(actual, dtype=np.float64)
    predicted = np.asarray(forecast, dtype=np.float64)
    if observed.ndim != 1 or predicted.shape != observed.shape or observed.size < 3:
        raise ValueError("CALIBRATION_ARRAY_SHAPE_INVALID")
    if not np.isfinite(observed).all() or not np.isfinite(predicted).all():
        raise ValueError("CALIBRATION_INPUT_NONFINITE")
    if (observed <= 0).any() or (predicted <= 0).any():
        raise ValueError("CALIBRATION_REQUIRES_POSITIVE_VALUES")
    return observed, predicted


def mincer_zarnowitz(
    actual: Sequence[float] | FloatArray,
    forecast: Sequence[float] | FloatArray,
) -> dict[str, float | int]:
    """Log-scale Mincer-Zarnowitz regression ``ln(actual) = a + b ln(forecast)``.

    Parameters
    ----------
    actual, forecast:
        Strictly positive realized values and forecasts.

    Returns
    -------
    dict
        Intercept ``a``, slope ``b``, ``r_squared``, residual variance
        ``sigma2``, joint Wald statistic for ``(a, b) = (0, 1)`` and count.
        A calibrated forecast has ``a = 0`` and ``b = 1``.
    """
    observed, predicted = _positive_arrays(actual, forecast)
    y = np.log(observed)
    x = np.log(predicted)
    count = y.size
    x_centered = x - x.mean()
    denominator = float(np.dot(x_centered, x_centered))
    if denominator == 0.0:
        raise ValueError("CALIBRATION_DEGENERATE_FORECAST")
    slope = float(np.dot(x_centered, y - y.mean()) / denominator)
    intercept = float(y.mean() - slope * x.mean())
    residuals = y - intercept - slope * x
    sigma2 = float(np.dot(residuals, residuals) / (count - 2))
    total = float(np.dot(y - y.mean(), y - y.mean()))
    r_squared = 1.0 - float(np.dot(residuals, residuals)) / total if total > 0 else 0.0
    slope_variance = sigma2 / denominator
    intercept_variance = sigma2 * (1.0 / count + x.mean() ** 2 / denominator)
    covariance = -sigma2 * x.mean() / denominator
    delta = np.asarray([intercept - 0.0, slope - 1.0], dtype=np.float64)
    matrix = np.asarray(
        [[intercept_variance, covariance], [covariance, slope_variance]],
        dtype=np.float64,
    )
    try:
        wald = float(delta @ np.linalg.solve(matrix, delta))
    except np.linalg.LinAlgError as error:
        raise ValueError("CALIBRATION_WALD_SINGULAR") from error
    return {
        "intercept": intercept,
        "slope": slope,
        "r_squared": r_squared,
        "sigma2": sigma2,
        "wald_joint": wald,
        "observations": count,
    }


def recalibrate(
    forecast: Sequence[float] | FloatArray,
    *,
    intercept: float,
    slope: float,
    sigma2: float,
    smearing: bool = True,
) -> FloatArray:
    """Apply a fitted log-scale correction to forecasts.

    Parameters
    ----------
    forecast:
        Strictly positive raw forecasts.
    intercept, slope, sigma2:
        Coefficients from :func:`mincer_zarnowitz` fitted on training data only.
    smearing:
        Multiply by ``exp(sigma2 / 2)`` (lognormal retransformation) so the
        corrected forecast targets the conditional mean, which QLIKE scores.

    Returns
    -------
    numpy.ndarray
        Corrected forecasts ``exp(a + b ln f [+ sigma2 / 2])``.
    """
    predicted = np.asarray(forecast, dtype=np.float64)
    if predicted.ndim != 1 or predicted.size == 0:
        raise ValueError("CALIBRATION_ARRAY_SHAPE_INVALID")
    if not np.isfinite(predicted).all() or (predicted <= 0).any():
        raise ValueError("CALIBRATION_REQUIRES_POSITIVE_VALUES")
    if not (math.isfinite(intercept) and math.isfinite(slope) and math.isfinite(sigma2)):
        raise ValueError("CALIBRATION_COEFFICIENTS_INVALID")
    if sigma2 < 0:
        raise ValueError("CALIBRATION_COEFFICIENTS_INVALID")
    adjustment = sigma2 / 2.0 if smearing else 0.0
    return np.exp(intercept + slope * np.log(predicted) + adjustment)
