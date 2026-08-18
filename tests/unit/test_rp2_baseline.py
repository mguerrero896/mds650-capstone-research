"""Block 4 - challenger models and the calibration diagnostic."""

from __future__ import annotations

import numpy as np
import pytest

from mds650.rp2.baseline import (
    Garch11,
    ewma_variance,
    fit_garch11,
    mincer_zarnowitz,
    seasonality_index,
    smearing_factor,
)


def test_ewma_uses_only_the_past() -> None:
    returns = np.array([0.1, 0.2, 0.3], dtype=np.float64)
    values = ewma_variance(returns, decay=0.5)
    seed = float(np.mean(returns**2))
    assert values[0] == pytest.approx(seed)
    assert values[1] == pytest.approx(0.5 * seed + 0.5 * 0.1**2)
    assert values[2] == pytest.approx(0.5 * values[1] + 0.5 * 0.2**2)


@pytest.mark.parametrize("decay", [0.0, 1.0, -0.5])
def test_ewma_rejects_an_invalid_decay(decay: float) -> None:
    with pytest.raises(ValueError, match="RP2_EWMA_DECAY_INVALID"):
        ewma_variance(np.array([0.1]), decay=decay)


def test_ewma_rejects_an_empty_series() -> None:
    with pytest.raises(ValueError, match="RP2_EWMA_SERIES_INVALID"):
        ewma_variance(np.array([], dtype=np.float64))


def test_garch_filter_follows_the_recursion() -> None:
    model = Garch11(omega=1e-6, alpha=0.1, beta=0.85)
    returns = np.array([0.01, -0.02, 0.005], dtype=np.float64)
    filtered = model.filter(returns)
    unconditional = model.omega / (1.0 - model.persistence)
    assert filtered[0] == pytest.approx(unconditional)
    assert filtered[1] == pytest.approx(1e-6 + 0.1 * 0.01**2 + 0.85 * unconditional)
    assert model.persistence == pytest.approx(0.95)


def test_garch_recovers_a_persistent_process() -> None:
    rng = np.random.default_rng(5)
    omega, alpha, beta = 1.0e-8, 0.08, 0.90
    size = 4000
    returns = np.zeros(size, dtype=np.float64)
    state = omega / (1.0 - alpha - beta)
    for index in range(size):
        returns[index] = float(rng.normal(scale=np.sqrt(state)))
        state = omega + alpha * returns[index] ** 2 + beta * state
    fitted = fit_garch11(returns)
    assert 0.7 < fitted.persistence < 1.0
    assert fitted.omega > 0.0


def test_garch_rejects_a_short_series() -> None:
    with pytest.raises(ValueError, match="RP2_GARCH_SERIES_TOO_SHORT"):
        fit_garch11(np.zeros(10))


def test_seasonality_index_is_centred_and_ignores_the_test_period() -> None:
    buckets = np.array([0, 0, 1, 1, 2], dtype=np.int64)
    values = np.array([1.0, 1.0, 3.0, 3.0, 99.0], dtype=np.float64)
    train = np.array([True, True, True, True, False])
    index = seasonality_index(buckets, values, train, buckets=3)
    assert index[0] == pytest.approx(-1.0)
    assert index[2] == pytest.approx(1.0)
    # Bucket 2 is unseen in training, so it falls back to the global mean (offset zero).
    assert index[4] == pytest.approx(0.0)


def test_seasonality_index_rejects_mismatched_shapes() -> None:
    with pytest.raises(ValueError, match="RP2_SEASONALITY_SHAPE_MISMATCH"):
        seasonality_index(
            np.array([0], dtype=np.int64),
            np.array([1.0, 2.0]),
            np.array([True]),
            buckets=1,
        )


def test_perfect_forecast_calibrates_to_zero_and_one() -> None:
    rng = np.random.default_rng(2)
    actual = np.exp(rng.normal(size=500))
    calibration = mincer_zarnowitz(actual, actual)
    assert calibration.intercept == pytest.approx(0.0, abs=1e-9)
    assert calibration.slope == pytest.approx(1.0, abs=1e-9)
    assert calibration.well_calibrated


def test_a_biased_forecast_is_flagged() -> None:
    rng = np.random.default_rng(4)
    actual = np.exp(rng.normal(size=800))
    calibration = mincer_zarnowitz(actual, actual * 0.2)
    assert calibration.intercept > 1.0
    assert not calibration.well_calibrated


def test_calibration_rejects_bad_shapes() -> None:
    with pytest.raises(ValueError, match="RP2_CALIBRATION_SHAPE_INVALID"):
        mincer_zarnowitz(np.array([1.0, 2.0]), np.array([1.0]))


def test_smearing_factor_is_one_for_a_perfect_fit() -> None:
    assert smearing_factor(np.zeros(10)) == pytest.approx(1.0)
    assert smearing_factor(np.array([-1.0, 1.0])) == pytest.approx(np.exp(0.5))
    with pytest.raises(ValueError, match="RP2_SMEARING_EMPTY"):
        smearing_factor(np.array([], dtype=np.float64))
