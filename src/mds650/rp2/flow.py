"""Block 6 - Gate 5: option-flow microstructure without premature aggregation.

The program's diagnosis is that reducing thousands of trades to a handful of five-minute
counts destroys sequence, direction, moneyness, tenor, Greeks and quote impact.  This
module supplies the primitives that keep them: Black-Scholes Greeks for exposure-weighted
flow, a Hawkes intensity for burstiness, concentration and entropy for how spread out the
activity is, and trade-to-quote impact for whether a trade actually moved the surface.

Direction is taken from the tape's own side classification (ask side = buyer initiated,
bid side = seller initiated), never inferred from price moves after the fact.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Final

import numpy as np
import numpy.typing as npt
from scipy.special import ndtr

type FloatArray = npt.NDArray[np.float64]

MIN_IV: Final = 0.01
MAX_IV: Final = 5.0
#: Only large enough to keep the square root away from zero. It used to be one day,
#: which quietly re-floored every 0DTE contract back to a full day inside the Greeks —
#: exactly the rounding the exact-clock tenor exists to remove.
MIN_TENOR_YEARS: Final = 60.0 / (365.25 * 24 * 3600)
#: Contract multiplier for US equity options.
CONTRACT_MULTIPLIER: Final = 100.0
#: Default decay constant, in seconds: clustering at the one-minute scale.
DECAY_SECONDS: Final = 60.0


@dataclass(frozen=True, slots=True)
class Greeks:
    """Per-contract Black-Scholes sensitivities at zero rates and dividends."""

    delta: FloatArray
    gamma: FloatArray
    vega: FloatArray


def _normal_pdf(values: FloatArray) -> FloatArray:
    return np.exp(-0.5 * values**2) / math.sqrt(2.0 * math.pi)


def _normal_cdf(values: FloatArray) -> FloatArray:
    # ndtr is the vectorised C implementation; a np.vectorize(math.erf) fallback costs a
    # Python call per element and is far too slow at tape scale.
    return np.asarray(ndtr(values), dtype=np.float64)


def black_scholes_greeks(
    spot: FloatArray,
    strike: FloatArray,
    tenor_years: FloatArray,
    iv: FloatArray,
    is_call: npt.NDArray[np.bool_],
) -> Greeks:
    """Delta, gamma and vega for every trade, zero rates and zero dividends.

    Vega is per one volatility point (not per 100), gamma is per unit of spot.
    """

    tenor = np.maximum(tenor_years, MIN_TENOR_YEARS)
    sigma = np.clip(iv, MIN_IV, MAX_IV)
    root = sigma * np.sqrt(tenor)
    d1 = (np.log(np.maximum(spot, 1e-9) / np.maximum(strike, 1e-9)) + 0.5 * sigma**2 * tenor) / root
    pdf = _normal_pdf(d1)
    call_delta = _normal_cdf(d1)
    return Greeks(
        delta=np.where(is_call, call_delta, call_delta - 1.0),
        gamma=pdf / (np.maximum(spot, 1e-9) * root),
        vega=np.maximum(spot, 1e-9) * pdf * np.sqrt(tenor),
    )


def signed_exposure(
    sensitivity: FloatArray, size: FloatArray, direction: FloatArray, *, scale: FloatArray | None
) -> float:
    """Sum of ``direction * sensitivity * size * multiplier`` (times an optional scale)."""

    weight = sensitivity * size * CONTRACT_MULTIPLIER
    if scale is not None:
        weight = weight * scale
    return float(np.sum(direction * weight))


def exponential_decay_intensity(
    times_seconds: FloatArray, *, baseline: float, excitation: float, decay: float = DECAY_SECONDS
) -> FloatArray:
    """Exponentially-weighted count of recent events, evaluated just before each event.

    ``x_i = mu + alpha * sum_{t_j < t_i} exp(-(t_i - t_j) / beta)`` by the standard O(n)
    recursion, so a long window costs no more than a short one.

    **This is not a Hawkes intensity.** It has the same functional form, but ``mu``,
    ``alpha`` and ``beta`` are supplied rather than estimated from the data, so it carries
    no self-excitation parameter and supports no branching-ratio or stability claim. It is
    a decay-weighted activity measure; calling it Hawkes would assert a fitted model that
    does not exist.
    """

    if decay <= 0.0:
        raise ValueError("RP2_DECAY_INVALID")
    if times_seconds.ndim != 1:
        raise ValueError("RP2_DECAY_TIMES_INVALID")
    out = np.empty(times_seconds.size, dtype=np.float64)
    state = 0.0
    previous = times_seconds[0] if times_seconds.size else 0.0
    for index, moment in enumerate(times_seconds):
        state *= math.exp(-(float(moment) - float(previous)) / decay)
        out[index] = baseline + excitation * state
        state += 1.0
        previous = moment
    return out


def burstiness(times_seconds: FloatArray) -> dict[str, float]:
    """Interarrival summary: rate, coefficient of variation and Fano-style dispersion.

    A Poisson process has coefficient of variation one; clustering pushes it above one.
    """

    if times_seconds.size < 3:
        return {
            "rate_per_second": float("nan"),
            "interarrival_cv": float("nan"),
            "interarrival_median": float("nan"),
        }
    gaps = np.diff(np.sort(times_seconds))
    mean = float(np.mean(gaps))
    span = float(times_seconds.max() - times_seconds.min())
    return {
        "rate_per_second": float(times_seconds.size / span) if span > 0.0 else float("nan"),
        "interarrival_cv": float(np.std(gaps) / mean) if mean > 0.0 else float("nan"),
        "interarrival_median": float(np.median(gaps)),
    }


def herfindahl(weights: FloatArray, *, normalised: bool = True) -> float:
    """Concentration of a non-negative weight vector.

    The raw Herfindahl index has a floor of ``1/n``, so it falls simply because more
    contracts traded - it confounds *how concentrated* the flow was with *how much* of it
    there was. The normalised form ``(H - 1/n) / (1 - 1/n)`` removes that floor and is 0
    for perfectly even flow and 1 for a single contract, whatever ``n`` is. A single
    observation has no defined concentration and returns NaN rather than 1.
    """

    positive = weights[np.isfinite(weights) & (weights > 0.0)]
    if positive.size == 0:
        return float("nan")
    share = positive / positive.sum()
    index = float(np.sum(share**2))
    if not normalised:
        return index
    count = positive.size
    if count < 2:
        return float("nan")
    floor = 1.0 / count
    return (index - floor) / (1.0 - floor)


def shannon_entropy(weights: FloatArray, *, normalised: bool = True) -> float:
    """Entropy of a non-negative weight vector.

    Raw entropy has a ceiling of ``log(n)``, so like the raw Herfindahl it grows with the
    number of contracts. The normalised form divides by that ceiling: 0 means all weight on
    one point and 1 means perfectly even, independent of ``n``.
    """

    positive = weights[np.isfinite(weights) & (weights > 0.0)]
    if positive.size == 0:
        return float("nan")
    share = positive / positive.sum()
    entropy = float(-np.sum(share * np.log(share)))
    if not normalised:
        return entropy
    if positive.size < 2:
        return float("nan")
    return entropy / math.log(positive.size)


def trade_to_quote_impact(
    contract_key: npt.NDArray[np.int64],
    iv: FloatArray,
    mid: FloatArray,
    relative_spread: FloatArray,
) -> dict[str, float]:
    """Mean change in implied volatility, mid and spread between consecutive trades.

    Trades are compared only within the same contract and in the order they arrived, so
    the statistic measures whether activity actually moved that contract's quote rather
    than cross-sectional dispersion.
    """

    if contract_key.size < 2:
        return {"d_iv": float("nan"), "d_mid_rel": float("nan"), "d_spread": float("nan")}
    order = np.lexsort((np.arange(contract_key.size), contract_key))
    keys = contract_key[order]
    same = keys[1:] == keys[:-1]
    if not same.any():
        return {"d_iv": float("nan"), "d_mid_rel": float("nan"), "d_spread": float("nan")}
    iv_sorted, mid_sorted, spread_sorted = iv[order], mid[order], relative_spread[order]
    d_iv = (iv_sorted[1:] - iv_sorted[:-1])[same]
    d_mid = ((mid_sorted[1:] - mid_sorted[:-1]) / np.maximum(mid_sorted[:-1], 1e-9))[same]
    d_spread = (spread_sorted[1:] - spread_sorted[:-1])[same]
    return {
        "d_iv": float(np.mean(d_iv)),
        "d_mid_rel": float(np.mean(d_mid)),
        "d_spread": float(np.mean(d_spread)),
    }


def residualise(values: FloatArray, design: FloatArray, train: npt.NDArray[np.bool_]) -> FloatArray:
    """Abnormal component of a flow variable: residual against a conditioning design.

    The expectation model is estimated on ``train`` rows only, which the caller sets to
    strictly earlier history, so the residual at any row never uses its own future.
    """

    if design.shape[0] != values.size or train.shape[0] != values.size:
        raise ValueError("RP2_RESIDUALISE_SHAPE_MISMATCH")
    usable = train & np.isfinite(values) & np.isfinite(design).all(axis=1)
    if usable.sum() < design.shape[1] + 1:
        return np.full(values.size, np.nan, dtype=np.float64)
    coefficients, *_ = np.linalg.lstsq(design[usable], values[usable], rcond=None)
    fitted = design @ coefficients
    return np.asarray(values - fitted, dtype=np.float64)
