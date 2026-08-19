"""Block 5 - surface reconstruction primitives."""

from __future__ import annotations

import math

import numpy as np
import pytest

from mds650.rp2.surface import (
    annualise_intraday_variance,
    black_scholes_delta,
    calendar_arbitrage_violations,
    fit_smile,
    implied_minus_trailing_variance,
    interpolate_total_variance,
    model_free_variance,
    put_call_parity_residual,
    total_variance,
    wing_quotes,
)


def test_at_the_money_delta_is_about_a_half() -> None:
    delta = black_scholes_delta(
        100.0,
        np.array([100.0]),
        np.array([30.0 / 365.0]),
        np.array([0.25]),
        np.array([True]),
    )
    assert delta[0] == pytest.approx(0.51, abs=0.02)


def test_call_and_put_delta_satisfy_parity() -> None:
    strike = np.array([90.0, 100.0, 110.0])
    tenor = np.full(3, 30.0 / 365.0)
    iv = np.full(3, 0.3)
    call = black_scholes_delta(100.0, strike, tenor, iv, np.array([True, True, True]))
    put = black_scholes_delta(100.0, strike, tenor, iv, np.array([False, False, False]))
    assert call - put == pytest.approx(np.ones(3))


def test_total_variance_scales_with_tenor() -> None:
    values = total_variance(np.array([0.2, 0.2]), np.array([0.25, 0.5]))
    assert values[1] == pytest.approx(2.0 * values[0])


def test_total_variance_interpolates_and_extrapolates_flat() -> None:
    tenors = np.array([0.25, 0.5])
    variances = np.array([0.01, 0.03])
    out = interpolate_total_variance(tenors, variances, np.array([0.1, 0.375, 0.9]))
    assert out[0] == pytest.approx(0.01)
    assert out[1] == pytest.approx(0.02)
    assert out[2] == pytest.approx(0.03)
    empty = interpolate_total_variance(np.array([]), np.array([]), np.array([0.5]))
    assert math.isnan(empty[0])


def test_smile_fit_recovers_a_known_quadratic() -> None:
    k = np.linspace(-0.3, 0.3, 25)
    iv = 0.25 - 0.4 * k + 1.5 * k**2
    fit = fit_smile(k, iv)
    assert fit.level == pytest.approx(0.25)
    assert fit.slope == pytest.approx(-0.4)
    assert fit.curvature == pytest.approx(1.5)
    assert fit.residual_std == pytest.approx(0.0, abs=1e-12)
    assert fit.points == 25


def test_smile_fit_degrades_gracefully_on_too_few_points() -> None:
    fit = fit_smile(np.array([0.0, 0.0]), np.array([0.2, 0.3]))
    assert fit.level == pytest.approx(0.25)
    assert math.isnan(fit.slope)
    assert fit.points == 2


def test_wing_quotes_interpolate_both_sides() -> None:
    delta = np.array([0.1, 0.3, -0.1, -0.3])
    iv = np.array([0.30, 0.22, 0.40, 0.28])
    call_iv, put_iv = wing_quotes(delta, iv)
    assert call_iv == pytest.approx(0.24)
    assert put_iv == pytest.approx(0.31)


def test_wing_quotes_return_nan_when_a_wing_is_not_spanned() -> None:
    call_iv, put_iv = wing_quotes(np.array([0.4, 0.45]), np.array([0.2, 0.21]))
    assert math.isnan(call_iv)
    assert math.isnan(put_iv)


def test_model_free_variance_is_positive_and_grows_with_option_prices() -> None:
    strikes = np.linspace(80.0, 120.0, 17)
    cheap = np.full(strikes.size, 0.5)
    rich = np.full(strikes.size, 1.5)
    low = model_free_variance(strikes, cheap, 100.0, 30.0 / 365.0)
    high = model_free_variance(strikes, rich, 100.0, 30.0 / 365.0)
    assert 0.0 < low < high
    assert math.isnan(model_free_variance(np.array([100.0]), np.array([1.0]), 100.0, 0.1))


def test_calendar_violations_count_decreasing_total_variance() -> None:
    tenors = np.array([0.1, 0.2, 0.3, 0.4])
    assert calendar_arbitrage_violations(tenors, np.array([0.01, 0.02, 0.03, 0.04])) == 0
    assert calendar_arbitrage_violations(tenors, np.array([0.01, 0.005, 0.03, 0.02])) == 2
    assert calendar_arbitrage_violations(np.array([0.1]), np.array([0.01])) == 0


def test_put_call_parity_residual_is_zero_for_consistent_quotes() -> None:
    """Zero rates are now a special case (F = S, D = 1), not the built-in assumption."""

    strike = np.array([95.0, 100.0, 105.0])
    spot = 100.0
    call = np.array([6.0, 3.0, 1.5])
    put = call - (spot - strike)
    measured = put_call_parity_residual(
        call, put, strike, forward=spot, discount_factor=1.0, scale=spot
    )
    assert measured == pytest.approx(0.0)
    assert math.isnan(
        put_call_parity_residual(call, put, strike, forward=spot, discount_factor=1.0, scale=0.0)
    )
    assert math.isnan(
        put_call_parity_residual(
            call, put, strike, forward=float("nan"), discount_factor=1.0, scale=spot
        )
    )


def test_implied_minus_trailing_variance_and_annualisation() -> None:
    assert implied_minus_trailing_variance(0.06, 0.04) == pytest.approx(0.02)
    assert math.isnan(implied_minus_trailing_variance(float("nan"), 0.04))
    annual = annualise_intraday_variance(1e-5)
    assert annual == pytest.approx(1e-5 * 252.0 * 13.0)
    assert math.isnan(annualise_intraday_variance(-1.0))
