"""Block 11 - a QLIKE improvement is not yet economic alpha.

Turns a variance forecast into the three economic bridges the program names: a variance-risk
strategy (bridge B), a risk-management utility comparison (bridge C), and the performance
statistics that decide whether either is worth anything after costs - including the deflated
Sharpe ratio, which is what stops a best-of-many-configurations Sharpe from being read as
real.

Bridge A (delta-hedged options) needs a per-contract execution simulator with the full
quote book through the holding period; the local tape carries NBBO only at trade instants,
so it is not implemented here rather than being approximated into a number that would look
like a P&L.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Final

import numpy as np
import numpy.typing as npt
from scipy import stats

type FloatArray = npt.NDArray[np.float64]

#: Thirteen non-overlapping 30-minute windows per session, 252 sessions per year.
PERIODS_PER_YEAR: Final = 252.0 * 13.0


@dataclass(frozen=True, slots=True)
class StrategyRun:
    """One variance-risk strategy path."""

    position: FloatArray
    gross_pnl: FloatArray
    net_pnl: FloatArray
    turnover: float
    traded_share: float


def variance_risk_strategy(
    implied_variance: FloatArray,
    forecast_variance: FloatArray,
    realized_variance: FloatArray,
    *,
    cost_per_unit: FloatArray,
    buffer: float,
) -> StrategyRun:
    """Trade the gap between implied and forecast variance, only when it clears costs.

    The signal is ``VRP_hat = IV^2 - E[RV]``.  Short variance when the premium is large
    enough to pay for the round trip plus a buffer, long variance when it is negative
    enough, flat otherwise.  Payoff of a unit short-variance position is
    ``IV^2 - RV_realized``.
    """

    if not (
        implied_variance.shape == forecast_variance.shape == realized_variance.shape
    ):
        raise ValueError("RP2_ECON_SHAPE_MISMATCH")
    if buffer < 0.0:
        raise ValueError("RP2_ECON_BUFFER_INVALID")
    edge = implied_variance - forecast_variance
    threshold = cost_per_unit + buffer
    position = np.where(edge > threshold, -1.0, np.where(edge < -threshold, 1.0, 0.0))
    gross = position * (realized_variance - implied_variance)
    traded = np.abs(position)
    net = gross - traded * cost_per_unit
    return StrategyRun(
        position=position,
        gross_pnl=gross,
        net_pnl=net,
        turnover=float(np.sum(traded)),
        traded_share=float(np.mean(traded)),
    )


@dataclass(frozen=True, slots=True)
class Performance:
    """Standard performance statistics of a per-period P&L series."""

    periods: int
    mean: float
    volatility: float
    sharpe_annual: float
    sortino_annual: float
    hit_rate: float
    max_drawdown: float
    expected_shortfall_5pct: float
    skewness: float
    kurtosis: float


def performance_metrics(pnl: FloatArray, *, periods_per_year: float = PERIODS_PER_YEAR
                        ) -> Performance:
    """Summarise a P&L series; annualisation uses the caller's period count."""

    finite = pnl[np.isfinite(pnl)]
    if finite.size < 2:
        raise ValueError("RP2_ECON_SERIES_TOO_SHORT")
    mean = float(np.mean(finite))
    volatility = float(np.std(finite, ddof=1))
    downside = finite[finite < 0.0]
    downside_volatility = float(np.std(downside, ddof=1)) if downside.size > 1 else float("nan")
    equity = np.cumsum(finite)
    drawdown = equity - np.maximum.accumulate(equity)
    tail = np.quantile(finite, 0.05)
    scale = math.sqrt(periods_per_year)
    return Performance(
        periods=int(finite.size),
        mean=mean,
        volatility=volatility,
        sharpe_annual=scale * mean / volatility if volatility > 0.0 else float("nan"),
        sortino_annual=(
            scale * mean / downside_volatility if downside_volatility > 0.0 else float("nan")
        ),
        hit_rate=float(np.mean(finite > 0.0)),
        max_drawdown=float(np.min(drawdown)),
        expected_shortfall_5pct=float(np.mean(finite[finite <= tail])),
        skewness=float(stats.skew(finite)),
        kurtosis=float(stats.kurtosis(finite, fisher=False)),
    )


def deflated_sharpe_ratio(
    observed_sharpe: float, *, trials: int, observations: int, skewness: float, kurtosis: float
) -> float:
    """Bailey-Lopez de Prado deflated Sharpe: probability the Sharpe is not luck.

    ``observed_sharpe`` and the returned threshold are per-period, not annualised.  With
    many trials the expected maximum Sharpe under the null rises, and a raw Sharpe that
    clears zero can still fail this.
    """

    if trials < 1 or observations < 4:
        raise ValueError("RP2_ECON_DSR_PARAMS_INVALID")
    euler = 0.5772156649015329
    expected_max = (1.0 - euler) * stats.norm.ppf(1.0 - 1.0 / trials) + euler * stats.norm.ppf(
        1.0 - 1.0 / (trials * math.e)
    )
    numerator = (observed_sharpe - expected_max) * math.sqrt(observations - 1.0)
    denominator = math.sqrt(
        max(
            1.0
            - skewness * observed_sharpe
            + (kurtosis - 1.0) / 4.0 * observed_sharpe**2,
            1e-12,
        )
    )
    return float(stats.norm.cdf(numerator / denominator))


def break_even_cost(gross_pnl: FloatArray, turnover: float) -> float:
    """Per-unit cost at which the gross P&L is exactly consumed."""

    if turnover <= 0.0:
        return float("nan")
    return float(np.sum(gross_pnl) / turnover)


@dataclass(frozen=True, slots=True)
class RiskUtility:
    """Bridge C: does the forecast make risk management measurably better?"""

    target_volatility_tracking_error: float
    var_breach_rate: float
    var_breach_target: float
    expected_shortfall_error: float
    certainty_equivalent: float


def risk_management_utility(
    forecast_variance: FloatArray,
    realized_variance: FloatArray,
    realized_return: FloatArray,
    *,
    target_variance: float,
    var_level: float = 0.05,
    risk_aversion: float = 2.0,
) -> RiskUtility:
    """Volatility targeting, VaR breaches and certainty equivalent under one forecast.

    A better variance forecast should size positions so that realised variance sits closer
    to target, produce a breach rate closer to its nominal level, and raise the
    mean-variance certainty equivalent - all of which are economic value that never shows
    up as a trading P&L.
    """

    if not (
        forecast_variance.shape == realized_variance.shape == realized_return.shape
    ):
        raise ValueError("RP2_ECON_SHAPE_MISMATCH")
    if target_variance <= 0.0:
        raise ValueError("RP2_ECON_TARGET_INVALID")
    weight = np.sqrt(target_variance / np.maximum(forecast_variance, 1e-16))
    achieved = weight**2 * realized_variance
    tracking = float(np.sqrt(np.mean((achieved / target_variance - 1.0) ** 2)))
    quantile = stats.norm.ppf(var_level)
    threshold = quantile * np.sqrt(np.maximum(forecast_variance, 1e-16))
    breaches = realized_return < threshold
    breach_rate = float(np.mean(breaches))
    shortfall_model = -np.sqrt(np.maximum(forecast_variance, 1e-16)) * stats.norm.pdf(
        quantile
    ) / var_level
    realised_shortfall = (
        float(np.mean(realized_return[breaches])) if breaches.any() else float("nan")
    )
    shortfall_error = (
        abs(realised_shortfall - float(np.mean(shortfall_model[breaches])))
        if breaches.any()
        else float("nan")
    )
    portfolio_return = weight * realized_return
    certainty = float(
        np.mean(portfolio_return) - 0.5 * risk_aversion * float(np.var(portfolio_return))
    )
    return RiskUtility(
        target_volatility_tracking_error=tracking,
        var_breach_rate=breach_rate,
        var_breach_target=var_level,
        expected_shortfall_error=shortfall_error,
        certainty_equivalent=certainty,
    )
