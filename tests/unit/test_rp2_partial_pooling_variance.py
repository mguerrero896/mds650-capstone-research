"""The between-group variance is estimated from six groups, so the divisor matters.

`partial_pooling` estimates ``tau^2`` by moments: the variance of the per-group mean
residuals, less the sampling variance those means carry. It took the variance of the
group means with `np.var`, which divides by G rather than by G - 1. With the six assets
this programme runs, that is a systematic 1/6 understatement of the spread between groups.

`tau^2` is the numerator of the shrinkage weight ``tau^2 / (tau^2 + sigma^2 / n_g)``, so
understating it shrinks every per-asset intercept harder toward the grand mean than the
data supports — and it does so silently, because a smaller tau still produces a plausible
model. The subtraction of ``sigma^2 / n`` makes it worse: the estimate is floored at zero,
so an understated spread can collapse the whole term and turn partial pooling into total
pooling.
"""

from __future__ import annotations

import numpy as np
import pytest

from mds650.rp2.ladder import partial_pooling

#: The programme's six development assets.
GROUPS = 6


def _clean_groups(offsets: list[float], per_group: int) -> tuple:
    """Residuals with an exact per-group mean and no within-group variation.

    One session per row, so the session-clustered sampling variance is the plain one and
    these cases stay about the divisor rather than about clustering.
    """
    residuals = np.repeat(np.asarray(offsets, dtype=np.float64), per_group)
    groups = np.repeat(np.arange(len(offsets), dtype=np.int64), per_group)
    train = np.ones(residuals.size, dtype=bool)
    sessions = np.arange(residuals.size, dtype=np.int64)
    return residuals, groups, train, sessions


def test_the_spread_between_groups_uses_the_unbiased_divisor() -> None:
    """With no within-group noise, tau^2 is exactly the sample variance of the means."""
    offsets = [-0.30, -0.18, -0.05, 0.07, 0.19, 0.27]
    assert len(offsets) == GROUPS
    residuals, groups, train, sessions = _clean_groups(offsets, per_group=500)

    pooled = partial_pooling(residuals, groups, train, sessions=sessions)

    unbiased = float(np.var(offsets, ddof=1))
    biased = float(np.var(offsets))
    assert unbiased > biased  # the two differ by exactly G / (G - 1)
    assert unbiased / biased == np.float64(GROUPS) / (GROUPS - 1)
    # With no within-group variation sigma^2 is zero, so the moment estimator returns the
    # sample variance of the means unchanged. Exact equality would test float arithmetic.
    assert pooled.between_variance == pytest.approx(unbiased, rel=1e-12), (
        f"tau^2 came back as {pooled.between_variance}, which is the population variance "
        f"{biased} rather than the sample variance {unbiased} of six group means"
    )


def test_understating_the_spread_would_over_shrink_the_offsets() -> None:
    """The consequence the divisor has, stated as the number a reader would see."""
    offsets = [-0.30, -0.18, -0.05, 0.07, 0.19, 0.27]
    residuals, groups, train, sessions = _clean_groups(offsets, per_group=500)

    pooled = partial_pooling(residuals, groups, train, sessions=sessions)

    # No within-group noise means no reason to shrink at all: every offset survives whole.
    grand = float(np.mean(offsets))
    for index, offset in enumerate(offsets):
        assert pooled.offsets[index] == pytest.approx(offset - grand, abs=1e-12)


def test_a_single_group_still_reports_no_spread() -> None:
    """One group has no between-group variance to estimate, and ddof=1 would divide by 0."""
    residuals, groups, train, sessions = _clean_groups([0.4], per_group=100)

    pooled = partial_pooling(residuals, groups, train, sessions=sessions)

    assert pooled.between_variance == 0.0
    assert pooled.offsets == {0: 0.0}


def test_within_group_noise_still_pulls_the_offsets_in() -> None:
    """The correction must not turn partial pooling into no pooling."""
    generator = np.random.default_rng(650)
    offsets = [-0.02, -0.01, 0.0, 0.01, 0.015, 0.02]
    residuals = np.repeat(np.asarray(offsets), 200) + generator.normal(0.0, 1.0, 1_200)
    groups = np.repeat(np.arange(len(offsets), dtype=np.int64), 200)
    train = np.ones(residuals.size, dtype=bool)
    sessions = np.arange(residuals.size, dtype=np.int64)

    pooled = partial_pooling(residuals, groups, train, sessions=sessions)

    grand = float(np.mean(residuals))
    for group in range(len(offsets)):
        raw = float(np.mean(residuals[groups == group])) - grand
        assert abs(pooled.offsets[group]) <= abs(raw) + 1e-12, "an offset grew rather than shrank"


def test_the_sampling_variance_uses_the_session_not_the_origin() -> None:
    """Origins inside a session are not independent draws, and this term assumed they were.

    `tau^2 = Var(m_g) - E[Var(m_g | theta_g)]` needs the sampling variance of each group
    mean. It was estimated as `within / n_g` with `n_g` the count of ORIGINS - 15,270 per
    asset in the published fit. Origins are five minutes apart and share overlapping
    thirty-minute targets, which is exactly why `aggregate_by_session`, `_contrast` and
    `session_weighted_level` all refuse to treat them as the unit. Reproducing the
    published development fit, the origin-based term is 1.4473e-5 where the
    session-clustered one is 8.5937e-5, 5.9 times larger, so tau^2 was inflated and the
    intercepts shrunk too little: weight 0.969 against 0.817.

    Here each session's origins are identical, so an origin carries no information a
    session did not already carry, and the two estimators must differ by exactly the
    number of origins per session.
    """
    per_session, origins_each, groups_count = 40, 10, 4
    generator = np.random.default_rng(650)
    residuals, groups, sessions = [], [], []
    for group in range(groups_count):
        offset = 0.05 * group
        for session in range(per_session):
            value = offset + generator.normal(0.0, 1.0)
            residuals.extend([value] * origins_each)
            groups.extend([group] * origins_each)
            sessions.extend([group * per_session + session] * origins_each)
    residuals = np.asarray(residuals, dtype=np.float64)
    groups = np.asarray(groups, dtype=np.int64)
    sessions = np.asarray(sessions, dtype=np.int64)
    train = np.ones(residuals.size, dtype=bool)

    pooled = partial_pooling(residuals, groups, train, sessions=sessions)

    # Every origin repeats its session, so the honest sampling variance of a group mean is
    # the variance of its 40 session values over 40 - not over 400 origins.
    for group in range(groups_count):
        mask = groups == group
        session_values = np.array(
            [residuals[mask & (sessions == s)][0] for s in np.unique(sessions[mask])]
        )
        honest = float(np.var(session_values, ddof=1)) / session_values.size
        assert pooled.sampling_variance[group] == pytest.approx(honest, rel=1e-9), (
            f"group {group} reports sampling variance {pooled.sampling_variance[group]}, "
            f"which is not the {honest} the session as the unit gives"
        )
