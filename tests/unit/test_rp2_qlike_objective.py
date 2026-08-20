"""The QLIKE objective: its derivatives, its curvature, and that it survives small variances."""

from __future__ import annotations

import numpy as np
import pytest

from mds650.rp2.qlike_objective import (
    EXPONENT_CLIP,
    lightgbm_metric,
    lightgbm_objective,
    qlike_gradient_hessian,
    qlike_loss,
)


def test_qlike_gradient_matches_finite_difference() -> None:
    """The analytic gradient is what the booster steps along, so it is checked numerically."""

    rng = np.random.default_rng(650)
    target = rng.lognormal(-10.0, 1.5, 200)
    raw = np.log(target) + rng.normal(0.0, 0.8, 200)

    gradient, _ = qlike_gradient_hessian(raw, target)
    step = 1e-6
    numeric = (qlike_loss(target, raw + step) - qlike_loss(target, raw - step)) / (2 * step)
    assert np.allclose(gradient, numeric, rtol=1e-5, atol=1e-9)


def test_qlike_hessian_matches_finite_difference_and_is_positive() -> None:
    rng = np.random.default_rng(7)
    target = rng.lognormal(-10.0, 1.5, 200)
    raw = np.log(target) + rng.normal(0.0, 0.8, 200)

    _, hessian = qlike_gradient_hessian(raw, target)
    step = 1e-4
    up = qlike_loss(target, raw + step)
    here = qlike_loss(target, raw)
    down = qlike_loss(target, raw - step)
    numeric = (up - 2 * here + down) / step**2
    assert np.allclose(hessian, numeric, rtol=1e-3, atol=1e-6)
    assert (hessian > 0.0).all(), "a second-order booster needs strict positive curvature"


def test_the_loss_is_zero_exactly_at_a_perfect_forecast() -> None:
    target = np.array([1e-6, 1e-4, 1e-2, 1.0])
    perfect = qlike_loss(target, np.log(target))
    assert np.allclose(perfect, 0.0, atol=1e-12)
    assert (qlike_loss(target, np.log(target) + 0.5) > 0.0).all()
    assert (qlike_loss(target, np.log(target) - 0.5) > 0.0).all()

    gradient, _ = qlike_gradient_hessian(np.log(target), target)
    assert np.allclose(gradient, 0.0, atol=1e-12)


def test_qlike_punishes_under_forecasting_more_than_over_forecasting() -> None:
    """The asymmetry is the reason this objective exists.

    Log-MSE penalises a factor-of-two over-forecast and a factor-of-two under-forecast
    identically. QLIKE does not, and QLIKE is what decides the result.
    """

    target = np.array([1e-4])
    under = qlike_loss(target, np.log(target) - np.log(2.0))
    over = qlike_loss(target, np.log(target) + np.log(2.0))
    assert under > over
    # A symmetric log-scale loss would have called these equal.
    assert np.log(2.0) ** 2 == pytest.approx(np.log(2.0) ** 2)


def test_qlike_objective_is_finite_for_small_variances() -> None:
    """One overshooting boosting step must not end the run with a NaN instead of a number."""

    target = np.array([1e-12, 1e-9, 1e-6])
    for raw in (-500.0, -100.0, 0.0, 100.0, 500.0):
        gradient, hessian = qlike_gradient_hessian(np.full(3, raw), target)
        assert np.isfinite(gradient).all(), raw
        assert np.isfinite(hessian).all(), raw
        assert np.isfinite(qlike_loss(target, np.full(3, raw))).all(), raw
    assert EXPONENT_CLIP == 30.0


def test_a_non_positive_target_is_floored_rather_than_producing_a_nan() -> None:
    target = np.array([0.0, -1.0, 1e-8])
    gradient, hessian = qlike_gradient_hessian(np.zeros(3), target)
    assert np.isfinite(gradient).all()
    assert np.isfinite(hessian).all()
    assert np.isfinite(qlike_loss(target, np.zeros(3))).all()


def test_the_objective_refuses_mismatched_shapes() -> None:
    with pytest.raises(ValueError, match="RP2_QLIKE_SHAPE_MISMATCH"):
        qlike_gradient_hessian(np.zeros(3), np.ones(2))


def test_the_lightgbm_hooks_return_what_lightgbm_expects() -> None:
    target = np.array([1e-4, 4e-4, 9e-4])
    raw = np.log(target)

    objective = lightgbm_objective(target)
    gradient, hessian = objective(raw, None)  # type: ignore[operator]
    assert gradient.shape == hessian.shape == target.shape
    assert np.allclose(gradient, 0.0, atol=1e-12)

    metric = lightgbm_metric(target)
    name, value, higher_is_better = metric(raw, None)  # type: ignore[operator]
    assert name == "qlike"
    assert value == pytest.approx(0.0, abs=1e-12)
    assert higher_is_better is False


def test_the_objective_agrees_with_the_reported_metric() -> None:
    """The loss the booster descends and the loss the programme reports are one function."""

    from mds650.metrics import qlike_losses

    rng = np.random.default_rng(11)
    target = rng.lognormal(-10.0, 1.0, 500)
    forecast = target * rng.lognormal(0.0, 0.4, 500)
    assert np.allclose(qlike_loss(target, np.log(forecast)), qlike_losses(target, forecast))
