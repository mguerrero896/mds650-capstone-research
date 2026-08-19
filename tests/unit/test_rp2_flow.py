"""Block 6 - flow microstructure primitives."""

from __future__ import annotations

import math

import numpy as np
import pytest

from mds650.rp2.flow import (
    CONTRACT_MULTIPLIER,
    black_scholes_greeks,
    burstiness,
    exponential_decay_intensity,
    herfindahl,
    residualise,
    shannon_entropy,
    signed_exposure,
    trade_to_quote_impact,
)


def test_greeks_have_the_expected_signs_and_symmetry() -> None:
    spot = np.full(3, 100.0)
    strike = np.array([90.0, 100.0, 110.0])
    tenor = np.full(3, 30.0 / 365.0)
    iv = np.full(3, 0.3)
    call = black_scholes_greeks(spot, strike, tenor, iv, np.array([True, True, True]))
    put = black_scholes_greeks(spot, strike, tenor, iv, np.array([False, False, False]))
    assert np.all(call.delta > 0.0) and np.all(put.delta < 0.0)
    # Gamma and vega do not depend on option type.
    assert call.gamma == pytest.approx(put.gamma)
    assert call.vega == pytest.approx(put.vega)
    # Gamma peaks near the money.
    assert call.gamma[1] > call.gamma[0] and call.gamma[1] > call.gamma[2]


def test_signed_exposure_applies_direction_size_and_multiplier() -> None:
    exposure = signed_exposure(
        np.array([0.5, 0.5]), np.array([2.0, 3.0]), np.array([1.0, -1.0]), scale=None
    )
    assert exposure == pytest.approx((2.0 - 3.0) * 0.5 * CONTRACT_MULTIPLIER)
    scaled = signed_exposure(
        np.array([1.0]), np.array([1.0]), np.array([1.0]), scale=np.array([2.0])
    )
    assert scaled == pytest.approx(2.0 * CONTRACT_MULTIPLIER)


def test_decay_intensity_matches_the_direct_sum() -> None:
    times = np.array([0.0, 10.0, 15.0, 100.0], dtype=np.float64)
    baseline, excitation, decay = 0.1, 0.5, 60.0
    values = exponential_decay_intensity(
        times, baseline=baseline, excitation=excitation, decay=decay
    )
    for index, moment in enumerate(times):
        direct = baseline + excitation * sum(
            math.exp(-(moment - earlier) / decay) for earlier in times[:index]
        )
        assert values[index] == pytest.approx(direct)


def test_decay_intensity_rejects_a_non_positive_decay() -> None:
    with pytest.raises(ValueError, match="RP2_DECAY_INVALID"):
        exponential_decay_intensity(np.array([0.0]), baseline=1.0, excitation=1.0, decay=0.0)


def test_burstiness_separates_regular_from_clustered_arrivals() -> None:
    regular = burstiness(np.arange(0.0, 100.0, 1.0))
    clustered = burstiness(np.concatenate([np.arange(0.0, 5.0, 0.1), np.array([500.0, 900.0])]))
    assert regular["interarrival_cv"] == pytest.approx(0.0, abs=1e-9)
    assert clustered["interarrival_cv"] > 1.0
    assert math.isnan(burstiness(np.array([1.0]))["interarrival_cv"])


def test_concentration_measures_agree_at_the_extremes() -> None:
    single = np.array([5.0, 0.0, 0.0])
    uniform = np.full(4, 2.0)
    # Raw indices carry an n-dependent floor and ceiling.
    assert herfindahl(single, normalised=False) == pytest.approx(1.0)
    assert shannon_entropy(single, normalised=False) == pytest.approx(0.0)
    assert herfindahl(uniform, normalised=False) == pytest.approx(0.25)
    assert shannon_entropy(uniform, normalised=False) == pytest.approx(math.log(4.0))
    assert math.isnan(herfindahl(np.array([0.0])))


def test_normalised_concentration_does_not_move_with_the_contract_count() -> None:
    """The defect this pins: raw HHI falls simply because more contracts traded.

    Perfectly even flow over 4 contracts and over 40 have identical concentration and
    must score identically; the raw index reports 0.25 against 0.025.
    """

    for size in (4, 40, 400):
        even = np.full(size, 1.0)
        assert herfindahl(even) == pytest.approx(0.0, abs=1e-12)
        assert shannon_entropy(even) == pytest.approx(1.0)
    # One dominant contract among many scores near 1 whatever the count.
    for size in (4, 40):
        dominant = np.full(size, 1e-9)
        dominant[0] = 1.0
        assert herfindahl(dominant) == pytest.approx(1.0, abs=1e-6)
        assert shannon_entropy(dominant) == pytest.approx(0.0, abs=1e-6)
    # A vector with a single positive weight has no defined concentration: there is
    # nothing for it to be concentrated relative to.
    assert math.isnan(herfindahl(np.array([5.0, 0.0, 0.0])))
    assert math.isnan(shannon_entropy(np.array([3.0])))


def test_trade_to_quote_impact_only_compares_within_a_contract() -> None:
    keys = np.array([1, 1, 2, 2], dtype=np.int64)
    iv = np.array([0.20, 0.22, 0.50, 0.49])
    mid = np.array([1.0, 1.1, 4.0, 4.0])
    spread = np.array([0.05, 0.06, 0.10, 0.08])
    impact = trade_to_quote_impact(keys, iv, mid, spread)
    assert impact["d_iv"] == pytest.approx((0.02 + -0.01) / 2.0)
    assert impact["d_mid_rel"] == pytest.approx((0.1 / 1.0 + 0.0) / 2.0)
    assert impact["d_spread"] == pytest.approx((0.01 + -0.02) / 2.0)


def test_trade_to_quote_impact_is_nan_without_repeats() -> None:
    impact = trade_to_quote_impact(
        np.array([1, 2], dtype=np.int64),
        np.array([0.2, 0.3]),
        np.array([1.0, 2.0]),
        np.array([0.1, 0.1]),
    )
    assert math.isnan(impact["d_iv"])


def test_residualise_removes_the_conditioning_structure() -> None:
    rng = np.random.default_rng(9)
    driver = rng.normal(size=400)
    values = 3.0 + 2.0 * driver + rng.normal(scale=0.01, size=400)
    design = np.column_stack([np.ones(400), driver])
    train = np.arange(400) < 300
    residual = residualise(values, design, train)
    assert float(np.std(residual)) < 0.05
    assert float(np.mean(np.abs(residual))) < 0.05


def test_residualise_returns_nan_without_enough_training_rows() -> None:
    values = np.arange(5.0)
    design = np.column_stack([np.ones(5), np.arange(5.0)])
    out = residualise(values, design, np.array([True, False, False, False, False]))
    assert np.isnan(out).all()
    with pytest.raises(ValueError, match="RP2_RESIDUALISE_SHAPE_MISMATCH"):
        residualise(values, design[:3], np.ones(5, dtype=bool))
