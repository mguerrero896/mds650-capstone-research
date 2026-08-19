"""Power by simulation: selection shrinkage, correct size, and no formula extrapolation."""

from __future__ import annotations

import math

import numpy as np
import pytest

from mds650.rp2.power import (
    FrozenDesign,
    sessions_for_power,
    shrink_selected_effect,
    simulate_power,
)


def _design(effect: float, candidates: int = 1) -> FrozenDesign:
    return FrozenDesign(
        target="signed_return_120",
        score="dml_t",
        sign=1,
        effect=effect,
        alpha_one_sided=0.0025,
        selection_candidates=candidates,
    )


def test_a_frozen_design_refuses_incoherent_settings() -> None:
    with pytest.raises(ValueError, match="RP2_POWER_SIGN_INVALID"):
        FrozenDesign("t", "s", 0, 0.1, 0.0025, 1)
    with pytest.raises(ValueError, match="RP2_POWER_ALPHA_INVALID"):
        FrozenDesign("t", "s", 1, 0.1, 0.9, 1)
    with pytest.raises(ValueError, match="RP2_POWER_CANDIDATES_INVALID"):
        FrozenDesign("t", "s", 1, 0.1, 0.0025, 0)


def test_selection_shrinkage_grows_with_the_number_of_candidates() -> None:
    """The winner's curse this corrects: the best of k noisy effects is biased upward."""

    effect, error = 1.0, 0.2
    one = shrink_selected_effect(effect, candidates=1, standard_error=error)
    few = shrink_selected_effect(effect, candidates=10, standard_error=error)
    many = shrink_selected_effect(effect, candidates=36, standard_error=error)
    assert one == pytest.approx(effect)
    assert effect > few > many >= 0.0
    # The correction is sqrt(2 ln k) standard errors.
    assert few == pytest.approx(effect - math.sqrt(2 * math.log(10)) * error)


def test_shrinkage_never_flips_the_sign() -> None:
    assert shrink_selected_effect(0.1, candidates=1000, standard_error=1.0) == 0.0
    assert shrink_selected_effect(-0.1, candidates=1000, standard_error=1.0) == 0.0
    negative = shrink_selected_effect(-5.0, candidates=10, standard_error=0.2)
    assert negative < 0.0


def test_shrinkage_validates_its_inputs() -> None:
    with pytest.raises(ValueError, match="RP2_POWER_SHRINK_PARAMS_INVALID"):
        shrink_selected_effect(1.0, candidates=0, standard_error=1.0)


def test_the_null_rejection_rate_matches_alpha() -> None:
    """A power number is meaningless if the test is mis-sized, so size is reported too."""

    rng = np.random.default_rng(5)
    scores = rng.normal(scale=0.02, size=200)
    result = simulate_power(scores, _design(0.0), sessions=120, repetitions=4000, seed=11)
    assert result.rejection_rate_under_null < 0.02
    # With a zero effect, power collapses onto the size.
    assert result.power == pytest.approx(result.rejection_rate_under_null, abs=0.01)


def test_power_rises_with_sample_size_and_with_effect() -> None:
    rng = np.random.default_rng(7)
    scores = rng.normal(scale=0.02, size=200)
    small = simulate_power(scores, _design(0.005), sessions=30, repetitions=1500, seed=2)
    large = simulate_power(scores, _design(0.005), sessions=240, repetitions=1500, seed=2)
    bigger = simulate_power(scores, _design(0.02), sessions=30, repetitions=1500, seed=2)
    assert large.power > small.power
    assert bigger.power > small.power


def test_a_fat_tailed_series_needs_more_sessions_than_a_thin_one() -> None:
    """Blocked resampling keeps the observed dispersion instead of assuming normality."""

    rng = np.random.default_rng(9)
    thin = rng.normal(scale=0.02, size=300)
    fat = rng.standard_t(df=3, size=300) * 0.02
    design = _design(0.006)
    thin_power = simulate_power(thin, design, sessions=120, repetitions=1500, seed=4).power
    fat_power = simulate_power(fat, design, sessions=120, repetitions=1500, seed=4).power
    assert thin_power > fat_power


def test_an_unreachable_target_returns_none_rather_than_an_extrapolation() -> None:
    rng = np.random.default_rng(13)
    scores = rng.normal(scale=0.5, size=200)
    needed, curve = sessions_for_power(
        scores, _design(1e-5), candidates=(30, 60), repetitions=400, seed=6
    )
    assert needed is None
    assert len(curve) == 2


def test_a_reachable_target_returns_the_smallest_sufficient_size() -> None:
    rng = np.random.default_rng(15)
    scores = rng.normal(scale=0.01, size=300)
    needed, curve = sessions_for_power(
        scores, _design(0.01), candidates=(30, 60, 120), repetitions=800, seed=8
    )
    assert needed == 30
    assert curve[0].power >= 0.80


def test_simulation_refuses_a_series_too_short_to_resample() -> None:
    with pytest.raises(ValueError, match="RP2_POWER_TOO_FEW_SESSIONS"):
        simulate_power(np.ones(5), _design(0.1), sessions=30)
    with pytest.raises(ValueError, match="RP2_POWER_PARAMS_INVALID"):
        simulate_power(np.ones(50), _design(0.1), sessions=1)
