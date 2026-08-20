"""Block 10 - Clark-West, Giacomini-White, clustered means and SPA."""

from __future__ import annotations

import numpy as np
import pytest

from mds650.rp2.inference import (
    SESSION_BLOCK_LENGTH,
    aggregate_by_session,
    clark_west_terms,
    clustered_mean_test,
    giacomini_white,
    hansen_spa,
    minimum_detectable_effect,
    newey_west_variance,
    session_block_bootstrap,
    session_block_draws,
    session_giacomini_white,
    stationary_bootstrap_indices,
    wild_cluster_bootstrap,
)


def test_clark_west_matches_its_definition() -> None:
    actual = np.array([1.0, 2.0, 3.0])
    restricted = np.array([1.5, 1.5, 2.5])
    unrestricted = np.array([1.2, 2.2, 2.9])
    expected = (actual - restricted) ** 2 - (
        (actual - unrestricted) ** 2 - (restricted - unrestricted) ** 2
    )
    terms = clark_west_terms(actual, restricted, unrestricted, nested_linear=True)
    assert terms == pytest.approx(expected)


def test_clark_west_is_positive_when_the_extra_terms_are_pure_noise() -> None:
    rng = np.random.default_rng(4)
    actual = rng.normal(size=5000)
    restricted = np.zeros_like(actual)
    # Unrestricted model adds estimation noise only: no true signal.
    unrestricted = rng.normal(scale=0.1, size=5000)
    plain = (actual - restricted) ** 2 - (actual - unrestricted) ** 2
    adjusted = clark_west_terms(actual, restricted, unrestricted, nested_linear=True)
    assert float(np.mean(plain)) < float(np.mean(adjusted))


def test_clark_west_rejects_mismatched_shapes() -> None:
    with pytest.raises(ValueError, match="RP2_CW_SHAPE_MISMATCH"):
        clark_west_terms(np.ones(3), np.ones(2), np.ones(3), nested_linear=True)


def test_clustered_mean_test_separates_signal_from_noise() -> None:
    rng = np.random.default_rng(5)
    clusters = np.repeat(np.arange(60, dtype=np.int64), 20)
    positive = clustered_mean_test(0.3 + rng.normal(scale=0.5, size=clusters.size), clusters)
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
        "gamma_glm|good": benchmark - 0.2 + rng.normal(scale=0.05, size=size),
        "gamma_glm|bad": benchmark + 0.5 + rng.normal(scale=0.05, size=size),
    }
    sessions = np.repeat(np.arange(size // 4, dtype=np.int64), 4)
    result = hansen_spa(benchmark, candidates, sessions=sessions, repetitions=400, seed=3)
    assert result.best_model == "gamma_glm|good"
    assert result.spa_p_value < 0.05
    assert result.candidates == 2


def test_spa_does_not_reject_on_a_family_of_useless_candidates() -> None:
    rng = np.random.default_rng(13)
    size = 800
    benchmark = rng.normal(loc=1.0, scale=0.2, size=size)
    candidates = {
        f"ridge_log|noise_{index}": benchmark + rng.normal(scale=0.05, size=size)
        for index in range(6)
    }
    sessions = np.repeat(np.arange(size // 4, dtype=np.int64), 4)
    result = hansen_spa(benchmark, candidates, sessions=sessions, repetitions=400, seed=4)
    assert result.spa_p_value > 0.05


def test_spa_validates_its_inputs() -> None:
    with pytest.raises(ValueError, match="RP2_INFERENCE_NO_CANDIDATES"):
        hansen_spa(np.ones(50), {}, sessions=np.arange(50, dtype=np.int64))
    with pytest.raises(ValueError, match="RP2_INFERENCE_TOO_FEW_OBSERVATIONS"):
        hansen_spa(np.ones(5), {"a": np.zeros(5)}, sessions=np.arange(5, dtype=np.int64))


def test_clark_west_refuses_a_non_nested_pair() -> None:
    """The misuse this pins: applying the nested adjustment to two boosted trees.

    A tree on a larger feature set is a different function class, not a parameter
    restriction of the smaller one, so the adjustment has no derivation there and inflates
    the statistic toward significance.
    """

    with pytest.raises(ValueError, match="RP2_CW_REQUIRES_NESTED_LINEAR"):
        clark_west_terms(np.ones(5), np.ones(5), np.ones(5), nested_linear=False)


def test_session_aggregation_collapses_overlapping_origins() -> None:
    values = np.array([1.0, 3.0, 10.0, 20.0, 30.0], dtype=np.float64)
    sessions = np.array([0, 0, 1, 1, 1], dtype=np.int64)
    means, labels = aggregate_by_session(values, sessions)
    assert means.tolist() == [2.0, 20.0]
    assert labels.tolist() == [0, 1]


def test_session_aggregation_widens_the_interval_versus_treating_origins_as_independent() -> None:
    """Sixty-six origins a day are not sixty-six independent draws.

    Testing them as if they were shrinks the standard error by roughly sqrt(66); the
    session-blocked interval on the aggregated series must be materially wider.
    """

    rng = np.random.default_rng(17)
    per_session = rng.normal(loc=0.02, scale=0.5, size=80)
    origins = np.repeat(per_session, 66) + rng.normal(scale=1e-6, size=80 * 66)
    sessions = np.repeat(np.arange(80, dtype=np.int64), 66)

    naive_se = float(np.std(origins, ddof=1) / np.sqrt(origins.size))
    means, _ = aggregate_by_session(origins, sessions)
    blocked = session_block_bootstrap(means, block_length=5, repetitions=400, seed=3)
    blocked_half_width = (blocked["ci_high"] - blocked["ci_low"]) / 2.0
    assert blocked_half_width > 4.0 * naive_se
    assert blocked["sessions"] == 80.0


def test_session_block_bootstrap_rejects_degenerate_input() -> None:
    with pytest.raises(ValueError, match="RP2_INFERENCE_BOOTSTRAP_PARAMS_INVALID"):
        session_block_bootstrap(np.ones(2))


def test_a_clustered_mean_weights_every_session_alike() -> None:
    """The estimate is the mean of the session means, not of the origins.

    Weighting by the number of origins in a day makes a busy session count for more than
    a quiet one, and an early close count for less than a full day. The contract fixes the
    session as the unit of observation; the weights have to say the same thing.
    """

    values = np.concatenate([np.full(90, 1.0), np.full(10, 0.0), np.full(10, 0.0)])
    clusters = np.concatenate(
        [np.zeros(90, dtype=np.int64), np.ones(10, dtype=np.int64), np.full(10, 2, dtype=np.int64)]
    )
    assert clustered_mean_test(values, clusters).mean == pytest.approx(1.0 / 3.0)


def test_the_spa_test_is_given_one_observation_per_session() -> None:
    rng = np.random.default_rng(4)
    sessions = np.repeat(np.arange(60, dtype=np.int64), 5)
    benchmark = rng.lognormal(-1.0, 0.4, sessions.size)
    candidates = {
        "gamma_glm|B0+B1": benchmark - 0.01,
        "gamma_glm|B0+B1+B2": benchmark - 0.02,
    }
    spa = hansen_spa(benchmark, candidates, sessions=sessions, repetitions=200, seed=1)
    assert spa.observations == 60, "the SPA sample size is sessions, not origins"

    # Splitting each session into two identical half-sessions must not double the sample.
    doubled = np.repeat(sessions, 2)
    spa_doubled = hansen_spa(
        np.repeat(benchmark, 2),
        {name: np.repeat(values, 2) for name, values in candidates.items()},
        sessions=doubled,
        repetitions=200,
        seed=1,
    )
    assert spa_doubled.observations == 60
    assert spa_doubled.spa_p_value == pytest.approx(spa.spa_p_value)


def test_the_spa_test_refuses_a_cross_family_comparison() -> None:
    """`log-OLS B0 vs LightGBM B0+B1+B2` is not a contrast; it is a horse race.

    A family compared against itself across information sets isolates the information. A
    family compared against a different family across information sets confounds the two.
    """

    rng = np.random.default_rng(6)
    sessions = np.repeat(np.arange(40, dtype=np.int64), 4)
    benchmark = rng.lognormal(-1.0, 0.4, sessions.size)
    with pytest.raises(ValueError, match="RP2_INFERENCE_FAMILY_MISMATCH"):
        hansen_spa(
            benchmark,
            {"lightgbm_qlike|B0+B1": benchmark - 0.01},
            sessions=sessions,
            benchmark_name="ridge_log|B0",
            repetitions=50,
        )


def test_the_block_bootstrap_resamples_whole_sessions_in_blocks() -> None:
    """Every resampled value is one of the observed session means, never a blend of two."""

    observed = np.arange(1.0, 21.0)
    drawn = session_block_draws(observed, block_length=SESSION_BLOCK_LENGTH, repetitions=50, seed=2)
    assert drawn.shape == (50, observed.size)
    assert np.isin(drawn, observed).all(), "a resample invented a value no session produced"
    # Consecutive sessions travel together: inside a block the index advances by one.
    positions = np.searchsorted(observed, drawn)
    steps = np.diff(positions.reshape(50, -1), axis=1) % observed.size
    assert float(np.mean(steps == 1)) > 0.7, "blocks of five must preserve local order"


def test_the_wild_cluster_bootstrap_rejects_a_real_effect_and_spares_a_null() -> None:
    rng = np.random.default_rng(9)
    null = rng.normal(0.0, 1.0, 120)
    assert wild_cluster_bootstrap(null, repetitions=999, seed=3) > 0.05
    assert wild_cluster_bootstrap(null + 1.0, repetitions=999, seed=3) < 0.05


def test_the_minimum_detectable_effect_shrinks_with_sessions_and_grows_with_noise() -> None:
    """A null is only informative next to the smallest effect the design could have seen."""

    quiet = np.full(100, 0.0) + np.random.default_rng(12).normal(0.0, 0.1, 100)
    loud = np.random.default_rng(12).normal(0.0, 1.0, 100)
    assert minimum_detectable_effect(quiet) < minimum_detectable_effect(loud)
    assert minimum_detectable_effect(loud[:50]) > minimum_detectable_effect(loud)
    assert minimum_detectable_effect(loud) > 0.0


def test_the_conditional_test_is_run_on_one_row_per_session() -> None:
    """Cluster-robust errors fix the uncertainty, not the weighting.

    Giacomini-White regresses the loss difference on ex-ante state. Fitted on per-origin
    rows, a session with more origins contributes more to the coefficients and so to the
    Wald statistic, whatever the covariance does afterwards. Splitting a session in two
    must not change the answer.
    """

    rng = np.random.default_rng(19)
    sessions = np.repeat(np.arange(60, dtype=np.int64), 6)
    state = rng.normal(size=(sessions.size, 2))
    difference = 0.3 * state[:, 0] + rng.normal(scale=0.2, size=sessions.size)

    plain = session_giacomini_white(difference, state, sessions)
    busy = sessions == 0
    doubled = session_giacomini_white(
        np.concatenate([difference, difference[busy]]),
        np.vstack([state, state[busy]]),
        np.concatenate([sessions, sessions[busy]]),
    )
    assert doubled.wald == pytest.approx(plain.wald, rel=1e-12)
    assert doubled.clusters == plain.clusters == 60


def test_the_minimum_detectable_effect_widens_under_serial_dependence() -> None:
    """The power calculation must use the same variance the interval does.

    An IID standard error on a series that the block bootstrap treats as dependent makes
    a null look more informative than the sample supports.
    """

    rng = np.random.default_rng(23)
    innovations = rng.normal(size=400)
    dependent = np.empty(400)
    dependent[0] = innovations[0]
    for index in range(1, 400):
        dependent[index] = 0.6 * dependent[index - 1] + innovations[index]
    independent = rng.permutation(dependent)  # identical values, dependence destroyed

    assert minimum_detectable_effect(dependent) > 1.2 * minimum_detectable_effect(independent)
