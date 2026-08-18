"""Block 5 - Gate 4: an arbitrage-aware option-implied volatility surface.

The local tape stores, for every option trade, the prevailing NBBO and the provider's
implied volatility for that contract.  Each trade is therefore a quote observation at a
point in time, and the union of the most recent observation per contract at a cutoff is a
(sparse) snapshot of the surface.  This module turns such a snapshot into the surface
features the program asks for: constant-maturity total variance, smile shape, risk
reversal and butterfly, term structure, quote quality and no-arbitrage diagnostics.

Interpolation is always on **total variance** ``w(T) = sigma^2(T) * T``, never on implied
volatility directly.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Final

import numpy as np
import numpy.typing as npt

type FloatArray = npt.NDArray[np.float64]

#: Constant maturities, in calendar days, at which the surface is sampled.
CONSTANT_MATURITY_DAYS: Final[tuple[int, ...]] = (7, 14, 30, 60, 90)
TRADING_DAYS_PER_YEAR: Final = 252.0
CALENDAR_DAYS_PER_YEAR: Final = 365.0
#: Deltas at which the risk reversal and butterfly are read.
WING_DELTA: Final = 0.25
MIN_IV: Final = 0.01
MAX_IV: Final = 5.0


def _normal_cdf(values: FloatArray) -> FloatArray:
    erf = np.vectorize(math.erf, otypes=[np.float64])
    return np.asarray(0.5 * (1.0 + erf(values / math.sqrt(2.0))), dtype=np.float64)


def black_scholes_delta(
    spot: float, strike: FloatArray, tenor_years: FloatArray, iv: FloatArray, is_call: FloatArray
) -> FloatArray:
    """Black-Scholes delta at zero rates and zero dividends.

    Zero rates are a deliberate simplification: the tape carries no discount curve, and at
    the tenors used here (7-90 days) the rate term shifts delta by well under the width of
    a delta bucket.  Recorded rather than hidden.
    """

    safe_tenor = np.maximum(tenor_years, 1.0 / CALENDAR_DAYS_PER_YEAR)
    safe_iv = np.clip(iv, MIN_IV, MAX_IV)
    denominator = safe_iv * np.sqrt(safe_tenor)
    d1 = (np.log(spot / np.maximum(strike, 1e-9)) + 0.5 * safe_iv**2 * safe_tenor) / denominator
    call_delta = _normal_cdf(d1)
    return np.where(is_call, call_delta, call_delta - 1.0)


def total_variance(iv: FloatArray, tenor_years: FloatArray) -> FloatArray:
    """``w(T) = sigma^2(T) * T`` - the quantity that is safe to interpolate."""

    return np.clip(iv, MIN_IV, MAX_IV) ** 2 * np.maximum(tenor_years, 0.0)


def interpolate_total_variance(
    tenors: FloatArray, variances: FloatArray, targets: FloatArray
) -> FloatArray:
    """Linear interpolation of total variance in tenor, flat outside the observed range.

    Flat extrapolation in ``w`` (not in ``sigma``) keeps implied volatility finite and
    monotone-consistent beyond the observed expiries.
    """

    if tenors.size == 0:
        return np.full(targets.shape, np.nan, dtype=np.float64)
    order = np.argsort(tenors)
    sorted_tenors, sorted_variances = tenors[order], variances[order]
    return np.interp(targets, sorted_tenors, sorted_variances)


@dataclass(frozen=True, slots=True)
class SmileFit:
    """Quadratic fit of implied volatility against log-moneyness."""

    level: float
    slope: float
    curvature: float
    residual_std: float
    points: int


def fit_smile(log_moneyness: FloatArray, iv: FloatArray, *, weights: FloatArray | None = None
              ) -> SmileFit:
    """Weighted quadratic fit ``iv = a + b*k + c*k^2``; ``a`` is the at-the-money level."""

    finite = np.isfinite(log_moneyness) & np.isfinite(iv)
    k, y = log_moneyness[finite], iv[finite]
    if k.size < 3 or np.ptp(k) <= 0.0:
        return SmileFit(
            level=float(np.mean(y)) if y.size else float("nan"),
            slope=float("nan"),
            curvature=float("nan"),
            residual_std=float("nan"),
            points=int(k.size),
        )
    weight = np.ones_like(k) if weights is None else np.sqrt(np.maximum(weights[finite], 0.0))
    design = np.column_stack([np.ones_like(k), k, k**2]) * weight[:, None]
    coefficients, *_ = np.linalg.lstsq(design, y * weight, rcond=None)
    fitted = np.column_stack([np.ones_like(k), k, k**2]) @ coefficients
    return SmileFit(
        level=float(coefficients[0]),
        slope=float(coefficients[1]),
        curvature=float(coefficients[2]),
        residual_std=float(np.std(y - fitted)),
        points=int(k.size),
    )


def wing_quotes(delta: FloatArray, iv: FloatArray, *, wing: float = WING_DELTA
                ) -> tuple[float, float]:
    """Implied volatility at the ``wing``-delta call and put, by interpolation in delta.

    Returns ``(call_iv, put_iv)``; either is NaN when that wing is not spanned.
    """

    finite = np.isfinite(delta) & np.isfinite(iv)
    delta, iv = delta[finite], iv[finite]
    calls = delta > 0.0
    call_iv = _interp_at(delta[calls], iv[calls], wing)
    puts = delta < 0.0
    put_iv = _interp_at(-delta[puts], iv[puts], wing)
    return call_iv, put_iv


def _interp_at(x: FloatArray, y: FloatArray, target: float) -> float:
    if x.size < 2:
        return float("nan")
    order = np.argsort(x)
    xs, ys = x[order], y[order]
    if target < xs[0] or target > xs[-1]:
        return float("nan")
    return float(np.interp(target, xs, ys))


def model_free_variance(
    strikes: FloatArray, mids: FloatArray, forward: float, tenor_years: float
) -> float:
    """VIX-style model-free implied variance over the observed strike grid.

    ``(2/T) * sum(dK_i / K_i^2 * Q(K_i)) - (1/T) * (F/K_0 - 1)^2`` with zero rates.  The
    grid is whatever strikes actually traded, so the caller must report coverage: a sparse
    grid biases this estimator downward.
    """

    finite = np.isfinite(strikes) & np.isfinite(mids) & (strikes > 0.0) & (mids > 0.0)
    strikes, mids = strikes[finite], mids[finite]
    if strikes.size < 3 or tenor_years <= 0.0:
        return float("nan")
    order = np.argsort(strikes)
    strikes, mids = strikes[order], mids[order]
    widths = np.empty_like(strikes)
    widths[1:-1] = (strikes[2:] - strikes[:-2]) / 2.0
    widths[0] = strikes[1] - strikes[0]
    widths[-1] = strikes[-1] - strikes[-2]
    below = strikes[strikes <= forward]
    k0 = float(below[-1]) if below.size else float(strikes[0])
    integral = float(np.sum(widths / strikes**2 * mids))
    return 2.0 / tenor_years * integral - (forward / k0 - 1.0) ** 2 / tenor_years


def calendar_arbitrage_violations(tenors: FloatArray, variances: FloatArray) -> int:
    """Count tenor pairs where total variance decreases - a calendar-spread arbitrage."""

    finite = np.isfinite(tenors) & np.isfinite(variances)
    tenors, variances = tenors[finite], variances[finite]
    if tenors.size < 2:
        return 0
    order = np.argsort(tenors)
    return int(np.count_nonzero(np.diff(variances[order]) < 0.0))


def put_call_parity_residual(
    call_mid: FloatArray, put_mid: FloatArray, strike: FloatArray, spot: float
) -> float:
    """Median absolute ``C - P - (S - K)`` relative to spot, over matched strikes."""

    finite = np.isfinite(call_mid) & np.isfinite(put_mid) & np.isfinite(strike)
    if not finite.any() or spot <= 0.0:
        return float("nan")
    residual = call_mid[finite] - put_mid[finite] - (spot - strike[finite])
    return float(np.median(np.abs(residual)) / spot)


def variance_risk_premium(implied_variance_annual: float, expected_rv_annual: float) -> float:
    """``VRP = IV^2 - E[RV]`` with both terms on the same annualised variance scale."""

    if not math.isfinite(implied_variance_annual) or not math.isfinite(expected_rv_annual):
        return float("nan")
    return implied_variance_annual - expected_rv_annual


def annualise_intraday_variance(variance_30m: float, *, minutes: float = 30.0) -> float:
    """Scale a 30-minute realized variance to an annual variance (390-minute sessions)."""

    if not math.isfinite(variance_30m) or variance_30m < 0.0:
        return float("nan")
    periods_per_year = TRADING_DAYS_PER_YEAR * (390.0 / minutes)
    return variance_30m * periods_per_year
