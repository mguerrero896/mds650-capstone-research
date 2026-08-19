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


def test_ewma_is_point_in_time_and_cannot_see_the_future() -> None:
    """The leak this pins: a full-sample seed makes early values depend on later returns.

    Appending observations must never change a value already emitted. With the old
    full-sample mean seed, every element moved when the series grew.
    """

    rng = np.random.default_rng(3)
    returns = rng.normal(scale=0.01, size=200)
    short = ewma_variance(returns[:120], decay=0.9, warmup=5)
    long = ewma_variance(returns, decay=0.9, warmup=5)
    assert short == pytest.approx(long[:120], nan_ok=True)


def test_ewma_expands_its_seed_then_switches_to_the_recursion() -> None:
    returns = np.array([0.1, 0.2, 0.3, 0.4], dtype=np.float64)
    values = ewma_variance(returns, decay=0.5, warmup=2)
    # Warm-up rows have too little history to state a variance.
    assert np.isnan(values[:2]).all()
    # At index 2 the state is the expanding mean of the first two squared returns.
    assert values[2] == pytest.approx((0.1**2 + 0.2**2) / 2)
    assert values[3] == pytest.approx(0.5 * values[2] + 0.5 * 0.3**2)


def test_ewma_is_computed_per_asset_so_one_name_cannot_seed_another() -> None:
    from mds650.rp2.baseline import ewma_variance_by_asset

    returns = np.array([0.5, 0.5, 0.5, 0.001, 0.001, 0.001], dtype=np.float64)
    assets = np.array(["LOUD", "LOUD", "LOUD", "QUIET", "QUIET", "QUIET"])
    pooled = ewma_variance(returns, decay=0.9, warmup=2)
    split = ewma_variance_by_asset(returns, assets, decay=0.9, warmup=2)
    # Pooling lets the loud name's state carry into the quiet one at the switch.
    assert split[5] < pooled[5]
    assert split[2] == pytest.approx(ewma_variance(returns[:3], decay=0.9, warmup=2)[2])


@pytest.mark.parametrize("decay", [0.0, 1.0, -0.5])
def test_ewma_rejects_an_invalid_decay(decay: float) -> None:
    with pytest.raises(ValueError, match="RP2_EWMA_DECAY_INVALID"):
        ewma_variance(np.array([0.1]), decay=decay)


def test_ewma_rejects_an_empty_series_or_a_bad_warmup() -> None:
    with pytest.raises(ValueError, match="RP2_EWMA_SERIES_INVALID"):
        ewma_variance(np.array([], dtype=np.float64))
    with pytest.raises(ValueError, match="RP2_EWMA_WARMUP_INVALID"):
        ewma_variance(np.array([0.1, 0.2]), warmup=0)


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
