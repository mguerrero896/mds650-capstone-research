"""The QLIKE loss as a boosting objective, so the model optimises what decides the result.

The programme's decision criterion is QLIKE. The non-linear model optimised squared error on
the log scale and was then judged on QLIKE, which is not the same thing: log-MSE is
symmetric in log space and penalises an over-forecast and an under-forecast of the same
ratio equally, while QLIKE is asymmetric and punishes under-forecasting a variance far more.
A model tuned for one and scored on the other is being asked a question it was never told.

On the log-variance scale ``z = log sigma^2`` the loss is

    L(y, z) = y * exp(-z) + z - log y - 1

with

    g(z) = 1 - y * exp(-z)      h(z) = y * exp(-z)

``L`` is non-negative, is zero exactly at ``z = log y``, and its Hessian is strictly
positive wherever the target is, which is what a second-order booster needs.
"""

from __future__ import annotations

from typing import Final

import numpy as np
import numpy.typing as npt

from mds650.metrics import qlike_from_variance

type FloatArray = npt.NDArray[np.float64]

#: Raw predictions are clipped before exponentiating. Without it a boosting step that
#: overshoots early produces inf, the gradient becomes nan, and the run dies with no number
#: to report rather than with a bad one.
EXPONENT_CLIP: Final = 30.0
#: A non-positive target has no log. The floor is the programme's variance floor.
TARGET_FLOOR: Final = 1e-12


def qlike_loss(target: FloatArray, raw_prediction: FloatArray) -> FloatArray:
    """Per-observation QLIKE on the log-variance scale, zero at a perfect forecast."""

    safe_target = np.maximum(np.asarray(target, dtype=np.float64), TARGET_FLOOR)
    variance = np.exp(np.clip(raw_prediction, -EXPONENT_CLIP, EXPONENT_CLIP))
    return qlike_from_variance(safe_target, variance)


def qlike_gradient_hessian(
    raw_prediction: FloatArray, target: FloatArray
) -> tuple[FloatArray, FloatArray]:
    """First and second derivatives of QLIKE with respect to the raw log-variance."""

    if raw_prediction.shape != target.shape:
        raise ValueError("RP2_QLIKE_SHAPE_MISMATCH")
    variance = np.exp(np.clip(raw_prediction, -EXPONENT_CLIP, EXPONENT_CLIP))
    ratio = np.maximum(target, TARGET_FLOOR) / variance
    gradient = 1.0 - ratio
    hessian = ratio
    return np.asarray(gradient, dtype=np.float64), np.asarray(hessian, dtype=np.float64)


def lightgbm_objective(
    target: FloatArray,
) -> object:
    """A LightGBM objective callable bound to this target vector.

    LightGBM calls the objective as ``(preds, dataset)`` and expects ``(grad, hess)``. The
    target is captured rather than read from the dataset so that the same function works for
    a plain array and for a dataset built with ``free_raw_data=False``.
    """

    def objective(raw_prediction: FloatArray, _dataset: object) -> tuple[FloatArray, FloatArray]:
        return qlike_gradient_hessian(np.asarray(raw_prediction, dtype=np.float64), target)

    return objective


def lightgbm_metric(target: FloatArray) -> object:
    """A LightGBM eval function reporting mean QLIKE, so early stopping sees the criterion."""

    def metric(raw_prediction: FloatArray, _dataset: object) -> tuple[str, float, bool]:
        value = float(np.mean(qlike_loss(target, np.asarray(raw_prediction, dtype=np.float64))))
        return "qlike", value, False

    return metric
