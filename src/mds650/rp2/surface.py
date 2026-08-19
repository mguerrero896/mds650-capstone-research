"""Block 5 - Gate 4: an arbitrage-aware option-implied volatility surface.

The local tape stores, for every option trade, the prevailing NBBO and the provider's
implied volatility for that contract.  Each trade is therefore a quote observation at a
point in time, and the union of the most recent observation per contract at a cutoff is a
(sparse) snapshot of the surface.  This module turns such a snapshot into the surface
features the program asks for: constant-maturity total variance, smile shape, risk
reversal and butterfly, term structure, quote quality and no-arbitrage diagnostics.

Interpolation is always on **total variance** ``w(T) = sigma^2(T) * T``, never on implied
volatility directly.

Moneyness and delta are measured against the **forward**, not the spot.  The forward is not
assumed and no external rate or dividend series is plugged in: it is read out of the option
quotes themselves by put-call parity, ``C - P = D * (F - K)``, fitted across co-strike pairs.
That yields the discount factor, the implied financing rate and the implied dividend yield as
*measurements* with a residual, rather than as inputs that could silently be wrong or
stale.  A snapshot with too few co-strike pairs to fit gets NaN and a coverage flag, never a
zero-rate fallback.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Final
from zoneinfo import ZoneInfo

import numpy as np
import numpy.typing as npt

type FloatArray = npt.NDArray[np.float64]
type BoolArray = npt.NDArray[np.bool_]

#: Constant maturities, in calendar days, at which the surface is sampled.
CONSTANT_MATURITY_DAYS: Final[tuple[int, ...]] = (7, 14, 30, 60, 90)
TRADING_DAYS_PER_YEAR: Final = 252.0
CALENDAR_DAYS_PER_YEAR: Final = 365.0
#: Deltas at which the risk reversal and butterfly are read.
WING_DELTA: Final = 0.25
MIN_IV: Final = 0.01
MAX_IV: Final = 5.0
#: Exchange time zone and the hour at which US equity options expire (16:00 ET).
MARKET_TIME_ZONE: Final = "America/New_York"
EXPIRY_CLOSE: Final = time(16, 0)
SECONDS_PER_YEAR: Final = CALENDAR_DAYS_PER_YEAR * 86400.0
#: Implied financing rates outside this band mean the parity fit is reading noise, not a
#: curve.  Wide on purpose: it rejects nonsense, it does not impose a view.
PLAUSIBLE_RATE_BAND: Final[tuple[float, float]] = (-0.05, 0.25)


def tenor_years_to_expiry(
    origin: datetime, expiry: date, *, time_zone: str = MARKET_TIME_ZONE
) -> float:
    """Exact time to expiry in years, measured to the 16:00 ET close on the expiry date.

    Rounding a tenor to whole calendar days destroys the front of the surface: a contract
    expiring this afternoon is not a one-day option and is not a zero-day option either -
    with four hours left it carries roughly ``4/24`` of a day of variance.  Counting whole
    days assigns it either 0 (dividing by zero, or being dropped) or 1 (overstating its
    variance by a factor of six).  Both are wrong in a way that matters most exactly where
    option activity concentrates.

    Returns ``0.0`` once the close has passed, so an expired contract can never be priced.
    """

    zone = ZoneInfo(time_zone)
    close = datetime.combine(expiry, EXPIRY_CLOSE, tzinfo=zone)
    seconds = (close - origin).total_seconds()
    return max(seconds, 0.0) / SECONDS_PER_YEAR


@dataclass(frozen=True, slots=True)
class ImpliedForward:
    """The forward, discount factor and implied carry read out of co-strike quotes."""

    forward: float
    discount_factor: float
    rate: float
    dividend_yield: float
    pairs: int
    residual_std: float
    plausible: bool


def implied_forward(
    strikes: FloatArray,
    call_mid: FloatArray,
    put_mid: FloatArray,
    *,
    tenor_years: float,
    spot: float,
) -> ImpliedForward:
    """Fit ``C - P = D * (F - K)`` across co-strike pairs; report F, D, r and q.

    Put-call parity is an arbitrage identity, not a model: at a single expiry the call-put
    spread is exactly linear in the strike, with slope ``-D`` and zero at the forward.  A
    least-squares line through the observed pairs therefore *measures* the discount factor
    and the forward the market is actually quoting, including whatever borrow, dividend and
    financing it embeds - none of which an external Treasury series would capture.

    Fails closed: fewer than three distinct co-strike pairs, a non-positive tenor or a
    degenerate slope all return NaN with ``pairs`` recorded, never a zero-rate fallback.
    """

    finite = np.isfinite(strikes) & np.isfinite(call_mid) & np.isfinite(put_mid)
    k, spread = strikes[finite], call_mid[finite] - put_mid[finite]
    distinct = np.unique(k)
    if distinct.size < 3 or tenor_years <= 0.0 or spot <= 0.0:
        return ImpliedForward(
            forward=float("nan"),
            discount_factor=float("nan"),
            rate=float("nan"),
            dividend_yield=float("nan"),
            pairs=int(distinct.size),
            residual_std=float("nan"),
            plausible=False,
        )
    design = np.column_stack([np.ones_like(k), k])
    coefficients, *_ = np.linalg.lstsq(design, spread, rcond=None)
    intercept, slope = float(coefficients[0]), float(coefficients[1])
    residual_std = float(np.std(spread - design @ coefficients))
    if slope >= 0.0:
        # The spread must fall with the strike; a flat or rising fit is not a parity line.
        return ImpliedForward(
            forward=float("nan"),
            discount_factor=float("nan"),
            rate=float("nan"),
            dividend_yield=float("nan"),
            pairs=int(distinct.size),
            residual_std=residual_std,
            plausible=False,
        )
    discount = -slope
    forward = intercept / discount
    rate = -math.log(discount) / tenor_years if discount > 0.0 else float("nan")
    carry = math.log(forward / spot) / tenor_years if forward > 0.0 else float("nan")
    dividend_yield = rate - carry
    low, high = PLAUSIBLE_RATE_BAND
    plausible = bool(forward > 0.0 and math.isfinite(rate) and low <= rate <= high)
    return ImpliedForward(
        forward=forward,
        discount_factor=discount,
        rate=rate,
        dividend_yield=dividend_yield,
        pairs=int(distinct.size),
        residual_std=residual_std,
        plausible=plausible,
    )


def _normal_cdf(values: FloatArray) -> FloatArray:
    erf = np.vectorize(math.erf, otypes=[np.float64])
    return np.asarray(0.5 * (1.0 + erf(values / math.sqrt(2.0))), dtype=np.float64)


def black_scholes_delta(
    forward: FloatArray,
    strike: FloatArray,
    tenor_years: FloatArray,
    iv: FloatArray,
    is_call: BoolArray,
) -> FloatArray:
    """Black-76 delta with respect to the forward.

    The forward is passed in rather than approximated by the spot.  Under the previous
    zero-rate convention the strike that priced as at-the-money was ``K = S``; with a 4-5%
    financing rate and a 90-day tenor the true at-the-money strike is about 1% higher, which
    moves a 25-delta wing by several delta points and mislabels which quotes are wings at
    all.  ``forward`` broadcasts against ``strike``, so a per-expiry forward can be supplied.
    """

    safe_tenor = np.maximum(tenor_years, 1.0 / (CALENDAR_DAYS_PER_YEAR * 24.0))
    safe_iv = np.clip(iv, MIN_IV, MAX_IV)
    denominator = safe_iv * np.sqrt(safe_tenor)
    log_moneyness = np.log(np.maximum(forward, 1e-9) / np.maximum(strike, 1e-9))
    d1 = (log_moneyness + 0.5 * safe_iv**2 * safe_tenor) / denominator
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


def fit_smile(
    log_moneyness: FloatArray, iv: FloatArray, *, weights: FloatArray | None = None
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


def wing_quotes(
    delta: FloatArray, iv: FloatArray, *, wing: float = WING_DELTA
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
    call_mid: FloatArray,
    put_mid: FloatArray,
    strike: FloatArray,
    *,
    forward: float,
    discount_factor: float,
    scale: float,
) -> float:
    """Median absolute ``C - P - D * (F - K)`` relative to ``scale``.

    Measured against the *fitted* forward and discount factor.  The earlier form compared
    against ``S - K``, which silently assumes zero rates and zero dividends: on a 90-day
    tenor at a 5% rate that assumption alone injects a residual of roughly 1% of spot, so
    the diagnostic reported financing as if it were a quote-quality defect.
    """

    finite = np.isfinite(call_mid) & np.isfinite(put_mid) & np.isfinite(strike)
    if not finite.any() or scale <= 0.0:
        return float("nan")
    if not (math.isfinite(forward) and math.isfinite(discount_factor)):
        return float("nan")
    residual = call_mid[finite] - put_mid[finite] - discount_factor * (forward - strike[finite])
    return float(np.median(np.abs(residual)) / scale)


def butterfly_arbitrage_violations(strikes: FloatArray, mids: FloatArray) -> int:
    """Count strike triples where the call price is concave - a butterfly arbitrage.

    A call price must be convex in the strike: ``C(K-) - 2 C(K) + C(K+) >= 0``.  Where it is
    not, a long butterfly costs a negative amount, and any variance read off that region of
    the smile is reading a quote error rather than a price.  Calendar monotonicity is
    already checked across tenors; this is the within-tenor complement, and without it a
    surface can pass every diagnostic while being locally unpriceable.
    """

    finite = np.isfinite(strikes) & np.isfinite(mids)
    strikes, mids = strikes[finite], mids[finite]
    if strikes.size < 3:
        return 0
    order = np.argsort(strikes)
    strikes, mids = strikes[order], mids[order]
    unique, index = np.unique(strikes, return_index=True)
    if unique.size < 3:
        return 0
    prices = mids[index]
    left, right = unique[:-2], unique[2:]
    middle = unique[1:-1]
    # Convexity with unequal spacing: compare the middle price to the chord.
    weight = (right - middle) / (right - left)
    chord = weight * prices[:-2] + (1.0 - weight) * prices[2:]
    return int(np.count_nonzero(prices[1:-1] > chord + 1e-9))


@dataclass(frozen=True, slots=True)
class SurfaceCoverage:
    """What the snapshot actually spans - reported so a thin surface cannot pass as a full one."""

    contracts: int
    expiries: int
    strikes: int
    min_log_moneyness: float
    max_log_moneyness: float
    spans_call_wing: bool
    spans_put_wing: bool
    zero_dte_contracts: int


def surface_coverage(
    log_moneyness: FloatArray,
    tenor_years: FloatArray,
    strikes: FloatArray,
    delta: FloatArray,
    *,
    wing: float = WING_DELTA,
) -> SurfaceCoverage:
    """Describe the span of an observed snapshot.

    Every surface statistic downstream - the model-free variance most of all - is biased by
    a narrow strike grid, and the bias has a sign: a grid that stops before the wings omits
    the tails and understates variance.  Reporting the span is what lets a reader tell an
    estimate from a truncation.
    """

    finite = np.isfinite(log_moneyness)
    spanned = log_moneyness[finite]
    finite_delta = delta[np.isfinite(delta)]
    positive_tenor = tenor_years[np.isfinite(tenor_years)]
    return SurfaceCoverage(
        contracts=int(finite.sum()),
        expiries=int(np.unique(np.round(positive_tenor, 8)).size),
        strikes=int(np.unique(strikes[np.isfinite(strikes)]).size),
        min_log_moneyness=float(spanned.min()) if spanned.size else float("nan"),
        max_log_moneyness=float(spanned.max()) if spanned.size else float("nan"),
        spans_call_wing=bool(np.any(finite_delta <= wing) and np.any(finite_delta >= 0.5)),
        spans_put_wing=bool(np.any(finite_delta >= -wing) and np.any(finite_delta <= -0.5)),
        zero_dte_contracts=int(np.count_nonzero(positive_tenor < 1.0 / CALENDAR_DAYS_PER_YEAR)),
    )


def implied_minus_trailing_variance(
    implied_variance_annual: float, trailing_rv_annual: float
) -> float:
    """``IV^2 - trailing RV``, both on the same annualised variance scale.

    **This is not a variance risk premium.** A VRP is the gap between the risk-neutral
    expectation and the *physical expectation of future* variance. Substituting the
    trailing realisation makes the quantity a backward-looking spread: it is mechanically
    large whenever variance has just fallen and small whenever it has just risen, which is
    a property of the recent past rather than of any premium. Naming it VRP would assert an
    expectation model that was never estimated.
    """

    if not math.isfinite(implied_variance_annual) or not math.isfinite(trailing_rv_annual):
        return float("nan")
    return float(implied_variance_annual - trailing_rv_annual)


def annualise_intraday_variance(variance_30m: float, *, minutes: float = 30.0) -> float:
    """Scale a 30-minute realized variance to an annual variance (390-minute sessions)."""

    if not math.isfinite(variance_30m) or variance_30m < 0.0:
        return float("nan")
    periods_per_year = TRADING_DAYS_PER_YEAR * (390.0 / minutes)
    return variance_30m * periods_per_year
