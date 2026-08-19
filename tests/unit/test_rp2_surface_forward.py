"""Block 5 - the forward, the exact tenor, and the diagnostics that bound them.

Every test here fails against the previous behaviour. The previous behaviour was not
obviously broken: it produced finite, plausible numbers. That is precisely why these are
worth pinning.
"""

from __future__ import annotations

import math
from datetime import UTC, date, datetime

import numpy as np
import pytest

from mds650.rp2.surface import (
    black_scholes_delta,
    butterfly_arbitrage_violations,
    implied_forward,
    put_call_parity_residual,
    surface_coverage,
    tenor_years_to_expiry,
)


def test_a_contract_expiring_this_afternoon_is_not_a_one_day_option() -> None:
    """The leak this pins: a whole-day tenor floor mis-prices the whole front of the surface.

    At 12:00 ET on expiry day the contract has four hours left. Flooring the tenor at one
    calendar day claims six times that much variance, exactly where option activity is
    heaviest.
    """

    origin = datetime(2025, 6, 20, 16, 0, tzinfo=UTC)  # 12:00 America/New_York
    tenor = tenor_years_to_expiry(origin, date(2025, 6, 20))
    assert tenor == pytest.approx(4.0 / 24.0 / 365.0, rel=1e-6)
    assert tenor < 1.0 / 365.0


def test_an_expired_contract_can_never_be_priced() -> None:
    after_close = datetime(2025, 6, 20, 21, 30, tzinfo=UTC)  # 17:30 ET, past the close
    assert tenor_years_to_expiry(after_close, date(2025, 6, 20)) == 0.0


def test_an_early_origin_sees_more_than_a_whole_day_to_a_next_day_expiry() -> None:
    origin = datetime(2025, 6, 19, 14, 0, tzinfo=UTC)  # 10:00 ET
    tenor = tenor_years_to_expiry(origin, date(2025, 6, 20))
    assert tenor == pytest.approx(30.0 / 24.0 / 365.0, rel=1e-6)


def _parity_quotes(
    strikes: np.ndarray, *, forward: float, discount: float
) -> tuple[np.ndarray, np.ndarray]:
    """Call and put mids that satisfy ``C - P = D (F - K)`` exactly."""

    spread = discount * (forward - strikes)
    put = np.full_like(strikes, 5.0)
    return put + spread, put


def test_the_forward_is_measured_from_the_quotes_not_assumed_to_be_the_spot() -> None:
    strikes = np.array([90.0, 95.0, 100.0, 105.0, 110.0])
    rate, tenor = 0.05, 0.25
    discount = math.exp(-rate * tenor)
    forward = 101.5
    call, put = _parity_quotes(strikes, forward=forward, discount=discount)
    fit = implied_forward(strikes, call, put, tenor_years=tenor, spot=100.0)
    assert fit.forward == pytest.approx(forward, rel=1e-9)
    assert fit.discount_factor == pytest.approx(discount, rel=1e-9)
    assert fit.rate == pytest.approx(rate, rel=1e-6)
    # F = S exp((r - q) T): a forward above the spot at a 5% rate implies a small yield.
    assert fit.dividend_yield == pytest.approx(rate - math.log(forward / 100.0) / tenor, rel=1e-6)
    assert fit.plausible and fit.pairs == 5


def test_the_forward_fails_closed_rather_than_falling_back_to_zero_rates() -> None:
    strikes = np.array([100.0, 105.0])
    call, put = _parity_quotes(strikes, forward=101.0, discount=0.99)
    fit = implied_forward(strikes, call, put, tenor_years=0.25, spot=100.0)
    assert math.isnan(fit.forward) and not fit.plausible and fit.pairs == 2


def test_a_spread_that_rises_with_the_strike_is_refused_as_a_parity_line() -> None:
    strikes = np.array([90.0, 100.0, 110.0])
    # C - P increasing in K is arbitrage-inconsistent: it cannot be a discount factor.
    fit = implied_forward(
        strikes,
        np.array([1.0, 3.0, 6.0]),
        np.array([1.0, 1.0, 1.0]),
        tenor_years=0.25,
        spot=100.0,
    )
    assert math.isnan(fit.discount_factor) and not fit.plausible


def test_an_implausible_implied_rate_is_flagged_rather_than_used() -> None:
    strikes = np.array([90.0, 100.0, 110.0])
    call, put = _parity_quotes(strikes, forward=100.0, discount=0.5)  # r about 277%
    fit = implied_forward(strikes, call, put, tenor_years=0.25, spot=100.0)
    assert math.isfinite(fit.forward) and not fit.plausible


def test_delta_is_measured_against_the_forward_so_the_wings_move_with_financing() -> None:
    """The defect this pins: at zero rates the wrong strike is called at-the-money.

    With a 4% rate over 90 days the forward sits about 1% above the spot. Under the old
    spot convention the 100 strike scored a 0.5 delta; against the forward it does not, and
    a 25-delta wing read off the spot convention is not the 25-delta wing.
    """

    strike = np.array([100.0])
    tenor = np.array([0.25])
    iv = np.array([0.30])
    is_call = np.array([True])
    at_spot = black_scholes_delta(np.array([100.0]), strike, tenor, iv, is_call)[0]
    at_forward = black_scholes_delta(np.array([101.0]), strike, tenor, iv, is_call)[0]
    assert at_forward > at_spot
    assert at_forward - at_spot > 0.02


def test_the_parity_residual_no_longer_reports_financing_as_a_quote_defect() -> None:
    """Against ``S - K`` a perfectly consistent surface looks broken at long tenors."""

    strikes = np.array([90.0, 100.0, 110.0])
    tenor, rate, spot = 0.25, 0.05, 100.0
    discount = math.exp(-rate * tenor)
    forward = spot / discount  # no dividend: F = S e^{rT}
    call, put = _parity_quotes(strikes, forward=forward, discount=discount)
    measured = put_call_parity_residual(
        call, put, strikes, forward=forward, discount_factor=discount, scale=spot
    )
    assert measured == pytest.approx(0.0, abs=1e-9)
    # The zero-rate form: C - P - (S - K), evaluated on the same arbitrage-free quotes.
    naive = float(np.median(np.abs(call - put - (spot - strikes))) / spot)
    assert naive > 1e-3


def test_a_concave_call_curve_is_counted_as_a_butterfly_violation() -> None:
    strikes = np.array([90.0, 100.0, 110.0])
    convex = np.array([12.0, 5.0, 1.5])
    assert butterfly_arbitrage_violations(strikes, convex) == 0
    concave = np.array([12.0, 8.0, 1.5])  # middle above the chord: negative butterfly cost
    assert butterfly_arbitrage_violations(strikes, concave) == 1


def test_butterfly_check_handles_unequal_strike_spacing() -> None:
    strikes = np.array([90.0, 92.0, 110.0])
    # Linear in K is the boundary case and must not be counted as a violation.
    linear = np.array([12.0, 11.0, 2.0])
    assert butterfly_arbitrage_violations(strikes, linear) == 0


def test_coverage_reports_a_truncated_grid_rather_than_letting_it_pass() -> None:
    log_moneyness = np.array([-0.01, 0.0, 0.01])
    tenor = np.array([0.02, 0.02, 0.02])
    strikes = np.array([99.0, 100.0, 101.0])
    delta = np.array([0.52, 0.50, 0.48])  # never reaches either wing
    coverage = surface_coverage(log_moneyness, tenor, strikes, delta)
    assert coverage.contracts == 3 and coverage.strikes == 3
    assert not coverage.spans_call_wing and not coverage.spans_put_wing
    assert coverage.max_log_moneyness == pytest.approx(0.01)


def test_coverage_counts_zero_dte_contracts_separately() -> None:
    tenor = np.array([0.5 / 365.0, 30.0 / 365.0])
    coverage = surface_coverage(
        np.array([0.0, 0.0]), tenor, np.array([100.0, 100.0]), np.array([0.5, 0.5])
    )
    assert coverage.zero_dte_contracts == 1
