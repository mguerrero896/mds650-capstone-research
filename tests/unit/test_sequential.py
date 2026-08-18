"""Contract tests for the sequential-multiplicity primitives (decision 64)."""

from __future__ import annotations

import math

import pytest

from mds650 import sequential


def test_alpha_spending_telescopes_to_total() -> None:
    schedule = sequential.alpha_spending_schedule(0.05, 1_000)
    assert schedule[0] == pytest.approx(0.025)  # 0.05 / (1*2)
    assert schedule[1] == pytest.approx(0.05 / 6)
    assert sum(schedule) < 0.05
    assert sum(schedule) == pytest.approx(0.05 * (1 - 1 / 1_001))
    assert all(later < earlier for earlier, later in zip(schedule, schedule[1:], strict=False))


def test_alpha_spending_rejects_invalid_inputs() -> None:
    with pytest.raises(ValueError, match="SEQUENTIAL_ALPHA_INVALID"):
        sequential.alpha_spending_schedule(0.0, 3)
    with pytest.raises(ValueError, match="SEQUENTIAL_ALPHA_INVALID"):
        sequential.alpha_spending_schedule(1.5, 3)
    with pytest.raises(ValueError, match="SEQUENTIAL_CAMPAIGNS_INVALID"):
        sequential.alpha_spending_schedule(0.05, 0)


def test_e_value_and_martingale_multiply() -> None:
    e1 = sequential.e_value_from_likelihood_ratio(-10.0, -12.0)
    e2 = sequential.e_value_from_likelihood_ratio(-8.0, -8.5)
    running = sequential.test_martingale([e1, e2])
    assert running[0] == pytest.approx(e1)
    assert running[1] == pytest.approx(e1 * e2)
    assert e1 == pytest.approx(math.exp(2.0))


def test_always_valid_p_uses_the_peak() -> None:
    # evidence rises then collapses: the peak, not the endpoint, sets the p-value
    p = sequential.always_valid_p_value([4.0, 5.0, 0.01])
    assert p == pytest.approx(1.0 / 20.0)
    assert sequential.always_valid_p_value([0.5, 0.5]) == 1.0


def test_martingale_rejects_degenerate_inputs() -> None:
    with pytest.raises(ValueError, match="SEQUENTIAL_EVALUES_EMPTY"):
        sequential.test_martingale([])
    with pytest.raises(ValueError, match="SEQUENTIAL_EVALUE_INVALID"):
        sequential.test_martingale([1.0, 0.0])
