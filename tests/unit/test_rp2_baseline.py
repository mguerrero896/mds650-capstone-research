"""Block 4 - challenger models and the calibration diagnostic."""

from __future__ import annotations

import numpy as np
import pytest

from mds650.rp2.baseline import (
    Garch11,
    fit_garch11,
    mincer_zarnowitz,
    seasonality_index,
    smearing_factor,
)


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


def test_ewma_forecast_at_t_is_invariant_to_returns_after_t() -> None:
    """A forecast that moves when the future changes is not a forecast."""

    from mds650.rp2.baseline import causal_ewma_horizon_variance

    rng = np.random.default_rng(11)
    returns = rng.normal(0.0, 1e-3, 400)
    origins = np.array([60, 120, 200], dtype=np.int64)

    before, _ = causal_ewma_horizon_variance(
        returns, origins, decay=0.97, horizon=30, initial_state=None
    )
    violent = returns.copy()
    violent[201:] = rng.normal(0.0, 5e-1, violent.size - 201)
    after, _ = causal_ewma_horizon_variance(
        violent, origins, decay=0.97, horizon=30, initial_state=None
    )
    assert np.array_equal(before, after, equal_nan=True)


def test_ewma_state_is_separate_for_each_asset() -> None:
    """Two names share a recursion only if one is allowed to seed the other."""

    from mds650.rp2.baseline import causal_ewma_horizon_variance

    quiet = np.full(300, 1e-4)
    loud = np.full(300, 1e-1)
    origins = np.array([100, 200], dtype=np.int64)

    alone, alone_state = causal_ewma_horizon_variance(
        quiet, origins, decay=0.97, horizon=30, initial_state=None
    )
    # Pooling would have the loud series set the state the quiet one starts from.
    pooled, _ = causal_ewma_horizon_variance(
        np.concatenate([loud, quiet]),
        origins + loud.size,
        decay=0.97,
        horizon=30,
        initial_state=None,
    )
    assert not np.allclose(alone, pooled)
    assert np.isfinite(alone_state)


def test_ewma_30m_forecast_uses_only_observed_one_minute_returns() -> None:
    """The recursion is h_t = lam h_{t-1} + (1-lam) r_{t-1}^2 and RV30_hat = 30 h_t."""

    from mds650.rp2.baseline import causal_ewma_horizon_variance

    rng = np.random.default_rng(3)
    returns = rng.normal(0.0, 2e-3, 120)
    origins = np.array([100], dtype=np.int64)
    decay, horizon, warmup = 0.94, 30, 20

    state = float(np.mean(returns[:warmup] ** 2))
    for index in range(warmup, 100):
        state = decay * state + (1.0 - decay) * float(returns[index] ** 2)
    expected = horizon * state

    forecast, carried = causal_ewma_horizon_variance(
        returns, origins, decay=decay, horizon=horizon, initial_state=None
    )
    assert forecast[0] == pytest.approx(expected)
    assert carried == pytest.approx(
        state * decay ** 20 + sum(
            (1 - decay) * decay ** (19 - k) * float(returns[100 + k] ** 2) for k in range(20)
        )
    )


def test_a_carried_state_continues_the_recursion_across_a_break() -> None:
    """The state is transportable: two sessions must equal one uninterrupted series."""

    from mds650.rp2.baseline import causal_ewma_horizon_variance

    rng = np.random.default_rng(5)
    returns = rng.normal(0.0, 1e-3, 200)
    origins = np.array([150], dtype=np.int64)

    whole, _ = causal_ewma_horizon_variance(
        returns, origins, decay=0.97, horizon=30, initial_state=None
    )
    _, carried = causal_ewma_horizon_variance(
        returns[:100], np.array([], dtype=np.int64), decay=0.97, horizon=30, initial_state=None
    )
    split, _ = causal_ewma_horizon_variance(
        returns[100:], origins - 100, decay=0.97, horizon=30, initial_state=carried
    )
    assert split[0] == pytest.approx(whole[0])
