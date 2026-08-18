"""Block 10 - Clark-West, Giacomini-White, clustered means and SPA."""

from __future__ import annotations

import numpy as np
import pytest

from mds650.rp2.inference import (
    clark_west_terms,
    clustered_mean_test,
    giacomini_white,
    hansen_spa,
    newey_west_variance,
    stationary_bootstrap_indices,
)


def test_clark_west_matches_its_definition() -> None:
    actual = np.array([1.0, 2.0, 3.0])
    restricted = np.array([1.5, 1.5, 2.5])
    unrestricted = np.array([1.2, 2.2, 2.9])
    expected = (actual - restricted) ** 2 - (
        (actual - unrestricted) ** 2 - (restricted - unrestricted) ** 2
    )
    assert clark_west_terms(actual, restricted, unrestricted) == pytest.approx(expected)


def test_clark_west_is_positive_when_the_extra_terms_are_pure_noise() -> None:
    rng = np.random.default_rng(4)
    actual = rng.normal(size=5000)
    restricted = np.zeros_like(actual)
    # Unrestricted model adds estimation noise only: no true signal.
    unrestricted = rng.normal(scale=0.1, size=5000)
    plain = (actual - restricted) ** 2 - (actual - unrestricted) ** 2
    adjusted = clark_west_terms(actual, restricted, unrestricted)
    assert float(np.mean(plain)) < float(np.mean(adjusted))


def test_clark_west_rejects_mismatched_shapes() -> None:
    with pytest.raises(ValueError, match="RP2_CW_SHAPE_MISMATCH"):
        clark_west_terms(np.ones(3), np.ones(2), np.ones(3))


def test_clustered_mean_test_separates_signal_from_noise() -> None:
    rng = np.random.default_rng(5)
    clusters = np.repeat(np.arange(60, dtype=np.int64), 20)
    positive = clustered_mean_test(
        0.3 + rng.normal(scale=0.5, size=clusters.size), clusters
    )
    assert positive.mean == pytest.approx(0.3, abs=0.1)
    assert positive.p_value_one_sided < 0.01
    assert positive.clusters == 60

    null = clustered_mean_test(rng.normal(scale=0.5, size=clusters.size), clusters)
    assert null.p_value_two_sided > 0.05


def test_clustered_mean_test_needs_enough_clusters() -> None:
    with pytest.raises(ValueError, match="RP2_INFERENCE_TOO_FEW_CLUSTERS"):
        clustered_mean_test(np.ones(4), np.array([0, 0, 1, 1], dtype=np.int64))


def test_newey_west_variance_grows_with_positive_autocorrelation() -> None:
    rng = np.random.default_rng(6)
    white = rng.normal(size=4000)
    correlated = np.copy(white)
    for index in range(1, correlated.size):
        correlated[index] += 0.8 * correlated[index - 1]
    assert newey_west_variance(correlated, lags=10) > newey_west_variance(white, lags=10)
    assert newey_west_variance(white, lags=0) == pytest.approx(float(np.var(white)), rel=0.01)
    with pytest.raises(ValueError, match="RP2_INFERENCE_LAGS_INVALID"):
        newey_west_variance(white, lags=-1)


def test_giacomini_white_detects_state_dependence() -> None:
    rng = np.random.default_rng(8)
    clusters = np.repeat(np.arange(90, dtype=np.int64), 15)
    state = rng.normal(size=clusters.size)
    conditional = giacomini_white(
        0.5 * state + rng.normal(scale=0.3, size=clusters.size), state[:, None], clusters
    )
    assert conditional.p_value < 0.01

    unconditional = giacomini_white(
        rng.normal(scale=0.3, size=clusters.size), state[:, None], clusters
    )
    assert unconditional.p_value > 0.01


def test_stationary_bootstrap_draws_valid_contiguous_blocks() -> None:
    generator = np.random.default_rng(2)
    indices = stationary_bootstrap_indices(500, block_mean=5.0, generator=generator)
    assert indices.size == 500
    assert indices.min() >= 0 and indices.max() < 500
    # Most consecutive draws continue the previous block.
    continued = np.mean(np.diff(indices) == 1)
    assert continued > 0.5
    with pytest.raises(ValueError, match="RP2_INFERENCE_BOOTSTRAP_PARAMS_INVALID"):
        stationary_bootstrap_indices(10, block_mean=1.0, generator=generator)


def test_spa_rejects_when_one_candidate_is_genuinely_better() -> None:
    rng = np.random.default_rng(12)
    size = 800
    benchmark = rng.normal(loc=1.0, scale=0.2, size=size)
    candidates = {
        "good": benchmark - 0.2 + rng.normal(scale=0.05, size=size),
        "bad": benchmark + 0.5 + rng.normal(scale=0.05, size=size),
    }
    result = hansen_spa(benchmark, candidates, repetitions=400, seed=3)
    assert result.best_model == "good"
    assert result.spa_p_value < 0.05
    assert result.candidates == 2


def test_spa_does_not_reject_on_a_family_of_useless_candidates() -> None:
    rng = np.random.default_rng(13)
    size = 800
    benchmark = rng.normal(loc=1.0, scale=0.2, size=size)
    candidates = {
        f"noise_{index}": benchmark + rng.normal(scale=0.05, size=size) for index in range(6)
    }
    result = hansen_spa(benchmark, candidates, repetitions=400, seed=4)
    assert result.spa_p_value > 0.05


def test_spa_validates_its_inputs() -> None:
    with pytest.raises(ValueError, match="RP2_INFERENCE_NO_CANDIDATES"):
        hansen_spa(np.ones(50), {})
    with pytest.raises(ValueError, match="RP2_INFERENCE_TOO_FEW_OBSERVATIONS"):
        hansen_spa(np.ones(5), {"a": np.zeros(5)})
