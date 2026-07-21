"""TDD tests for deterministic 30-minute realized variance."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from mds650.targets import compute_realized_variance

FIXTURE = Path(__file__).parents[1] / "fixtures" / "rv30_prices.json"


def test_rv30_uses_anchor_and_exactly_thirty_future_closes() -> None:
    """RV30 is the non-annualized sum of squared one-minute log returns."""
    anchor = 100.0
    future = [100.0 * (1.001**i) for i in range(1, 31)]

    expected = 30 * math.log(1.001) ** 2

    assert compute_realized_variance(anchor, future) == pytest.approx(expected)


def test_rv30_rejects_missing_or_nonpositive_prices() -> None:
    """Missing and nonpositive prices fail rather than being imputed."""
    with pytest.raises(ValueError, match="RV30_REQUIRES_EXACTLY_30_FUTURE_CLOSES"):
        compute_realized_variance(100.0, [101.0])
    with pytest.raises(ValueError, match="RV30_PRICE_MUST_BE_POSITIVE"):
        compute_realized_variance(0.0, [101.0] * 30)


def test_rv30_fixture_contains_thirty_one_prices_and_thirty_returns() -> None:
    """The contract fixture makes the 31-price requirement auditable."""
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert fixture["price_count"] == 31
    assert fixture["return_count"] == 30
    assert len([fixture["anchor_close"], *fixture["future_closes"]]) == 31
    assert compute_realized_variance(fixture["anchor_close"], fixture["future_closes"]) > 0
