"""Block 3 - realized measures must match their brute-force definitions."""

from __future__ import annotations

import math

import numpy as np
import pytest

from mds650.rp2.realized import (
    BIPOWER_SCALE,
    backward_rv,
    forward_measures,
    log_returns,
    relative_measurement_noise,
)


def _returns(size: int = 400, seed: int = 3) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.normal(scale=0.0008, size=size)


def test_log_returns_matches_the_definition() -> None:
    closes = np.array([100.0, 101.0, 99.5], dtype=np.float64)
    expected = np.array([math.log(101.0 / 100.0), math.log(99.5 / 101.0)])
    assert log_returns(closes) == pytest.approx(expected)


@pytest.mark.parametrize("bad", [np.array([100.0]), np.array([100.0, 0.0])])
def test_log_returns_rejects_degenerate_series(bad: np.ndarray) -> None:
    with pytest.raises(ValueError, match="RP2_RETURNS_"):
        log_returns(bad)


def test_forward_measures_match_a_brute_force_reference() -> None:
    returns = _returns()
    origins = np.array([0, 37, 150, 279], dtype=np.int64)
    horizon = 30
    measures = forward_measures(returns, origins, horizon)
    for position, start in enumerate(origins):
        window = returns[start : start + horizon]
        assert measures.rv[position] == pytest.approx(float(np.sum(window**2)))
        expected_bv = BIPOWER_SCALE * float(
            np.sum(np.abs(window[1:]) * np.abs(window[:-1]))
        )
        assert measures.bipower[position] == pytest.approx(expected_bv)
        assert measures.quarticity[position] == pytest.approx(
            horizon / 3.0 * float(np.sum(window**4))
        )
        assert measures.semivariance_up[position] == pytest.approx(
            float(np.sum(window[window > 0] ** 2))
        )
        assert measures.semivariance_down[position] == pytest.approx(
            float(np.sum(window[window < 0] ** 2))
        )


def test_jump_and_continuous_decompose_realized_variance() -> None:
    measures = forward_measures(_returns(), np.array([0, 100], dtype=np.int64), 60)
    assert np.all(measures.jump >= 0.0)
    assert measures.continuous + measures.jump == pytest.approx(measures.rv)


def test_semivariances_decompose_realized_variance() -> None:
    measures = forward_measures(_returns(), np.array([5, 90], dtype=np.int64), 45)
    total = measures.semivariance_up + measures.semivariance_down
    assert total == pytest.approx(measures.rv)


def test_a_single_large_return_shows_up_as_a_jump() -> None:
    returns = np.full(60, 1e-5, dtype=np.float64)
    returns[30] = 0.05
    measures = forward_measures(returns, np.array([0], dtype=np.int64), 60)
    assert measures.jump[0] > 0.9 * measures.rv[0]

    smooth = forward_measures(np.full(60, 1e-4), np.array([0], dtype=np.int64), 60)
    # Constant returns: bipower exceeds RV by pi/2, so the jump part is exactly zero.
    assert smooth.jump[0] == 0.0


def test_backward_rv_uses_the_window_ending_at_the_origin() -> None:
    returns = _returns()
    origins = np.array([60, 200], dtype=np.int64)
    values = backward_rv(returns, origins, 30)
    for position, origin in enumerate(origins):
        assert values[position] == pytest.approx(float(np.sum(returns[origin - 30 : origin] ** 2)))


def test_window_bounds_are_enforced() -> None:
    returns = _returns(size=50)
    with pytest.raises(ValueError, match="RP2_WINDOW_EXCEEDS_SERIES"):
        forward_measures(returns, np.array([40], dtype=np.int64), 30)
    with pytest.raises(ValueError, match="RP2_WINDOW_NEGATIVE_INDEX"):
        forward_measures(returns, np.array([-1], dtype=np.int64), 5)
    with pytest.raises(ValueError, match="RP2_WINDOW_NEGATIVE_INDEX"):
        backward_rv(returns, np.array([5], dtype=np.int64), 30)
    with pytest.raises(ValueError, match="RP2_HORIZON_TOO_SHORT"):
        forward_measures(returns, np.array([0], dtype=np.int64), 1)


def test_relative_noise_falls_as_the_horizon_grows() -> None:
    returns = _returns(size=600)
    noises: list[float] = []
    for horizon in (15, 30, 60, 120):
        measures = forward_measures(returns, np.array([0], dtype=np.int64), horizon)
        noises.append(
            float(relative_measurement_noise(measures.rv, measures.quarticity, horizon)[0])
        )
    assert noises == sorted(noises, reverse=True)
    with pytest.raises(ValueError, match="RP2_HORIZON_TOO_SHORT"):
        relative_measurement_noise(np.array([1.0]), np.array([1.0]), 0)
