"""Deterministic realized-variance target construction."""

from __future__ import annotations

import math
from collections.abc import Sequence


def compute_realized_variance(
    anchor_close: float,
    future_closes: Sequence[float],
    *,
    horizon_minutes: int = 30,
) -> float:
    """Compute non-annualized RV from one anchor and future one-minute closes.

    Parameters
    ----------
    anchor_close:
        Last close available at the forecast-origin boundary.
    future_closes:
        Exactly ``horizon_minutes`` strictly future one-minute closes.
    horizon_minutes:
        Fixed target horizon; the research default is 30.

    Returns
    -------
    float
        Sum of squared log returns from the anchor through the final future
        close. This is the sole primary target for the project.

    Raises
    ------
    ValueError
        If the horizon length is wrong or any price is non-finite/non-positive.
    """
    if horizon_minutes <= 0 or len(future_closes) != horizon_minutes:
        raise ValueError(f"RV{horizon_minutes}_REQUIRES_EXACTLY_{horizon_minutes}_FUTURE_CLOSES")
    prices = [anchor_close, *future_closes]
    if any(not math.isfinite(price) or price <= 0 for price in prices):
        raise ValueError("RV30_PRICE_MUST_BE_POSITIVE")
    return sum(
        math.log(current / previous) ** 2
        for previous, current in zip(prices, prices[1:], strict=False)
    )
