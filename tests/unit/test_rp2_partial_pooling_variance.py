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
    """Residuals with an exact per-group mean and no within-group variation."""
    residuals = np.repeat(np.asarray(offsets, dtype=np.float64), per_group)
    groups = np.repeat(np.arange(len(offsets), dtype=np.int64), per_group)
    train = np.ones(residuals.size, dtype=bool)
    return residuals, groups, train


def test_the_spread_between_groups_uses_the_unbiased_divisor() -> None:
    """With no within-group noise, tau^2 is exactly the sample variance of the means."""
    offsets = [-0.30, -0.18, -0.05, 0.07, 0.19, 0.27]
    assert len(offsets) == GROUPS
    residuals, groups, train = _clean_groups(offsets, per_group=500)

    pooled = partial_pooling(residuals, groups, train)

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
    residuals, groups, train = _clean_groups(offsets, per_group=500)

    pooled = partial_pooling(residuals, groups, train)

    # No within-group noise means no reason to shrink at all: every offset survives whole.
    grand = float(np.mean(offsets))
    for index, offset in enumerate(offsets):
        assert pooled.offsets[index] == pytest.approx(offset - grand, abs=1e-12)


def test_a_single_group_still_reports_no_spread() -> None:
    """One group has no between-group variance to estimate, and ddof=1 would divide by 0."""
    residuals, groups, train = _clean_groups([0.4], per_group=100)

    pooled = partial_pooling(residuals, groups, train)

    assert pooled.between_variance == 0.0
    assert pooled.offsets == {0: 0.0}


def test_within_group_noise_still_pulls_the_offsets_in() -> None:
    """The correction must not turn partial pooling into no pooling."""
    generator = np.random.default_rng(650)
    offsets = [-0.02, -0.01, 0.0, 0.01, 0.015, 0.02]
    residuals = np.repeat(np.asarray(offsets), 200) + generator.normal(0.0, 1.0, 1_200)
    groups = np.repeat(np.arange(len(offsets), dtype=np.int64), 200)
    train = np.ones(residuals.size, dtype=bool)

    pooled = partial_pooling(residuals, groups, train)

    grand = float(np.mean(residuals))
    for group in range(len(offsets)):
        raw = float(np.mean(residuals[groups == group])) - grand
        assert abs(pooled.offsets[group]) <= abs(raw) + 1e-12, "an offset grew rather than shrank"
