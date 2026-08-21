"""The 95th percentile of a sum is not the sum of the 95th percentiles.

`scripts/rp2_block2_pit_ledger.py` published `end_to_end_p95_seconds` as
`provider_p95 + local_p95`, and that number feeds `recommended_cutoff_seconds`, so it sets
a design parameter. Adding two quantiles gives the value the sum would have if the two
delays were perfectly rank-correlated — every slow provider record also arriving slowly
locally. Under any weaker dependence the real tail is different, and quantiles are not even
subadditive, so the sum is not a bound in either direction: it is one specific dependence
assumption, stated by arithmetic rather than in words.

Both stages already keep a histogram, so the independent case is computable rather than
assumed. These tests pin the two quantities against cases whose answers are known without
the estimator.
"""

from __future__ import annotations

import numpy as np
import pytest

from mds650.rp2.pit_ledger import (
    comonotonic_sum_quantile,
    independent_sum_quantile,
    latency_bin_edges,
    pooled_quantile,
)


def _point_mass(seconds: float, count: int = 10_000) -> np.ndarray:
    """A histogram whose whole mass sits in the bin containing ``seconds``."""
    edges = latency_bin_edges()
    histogram = np.zeros(len(edges) - 1, dtype=np.int64)
    histogram[int(np.searchsorted(edges, seconds, side="right")) - 1] = count
    return histogram


def test_two_point_masses_sum_to_their_sum() -> None:
    """With all mass at one value each, dependence cannot matter: X+Y is a constant."""
    first, second = _point_mass(2.0), _point_mass(8.0)

    independent = independent_sum_quantile(first, second, 0.95)
    comonotonic = comonotonic_sum_quantile(first, second, 0.95)

    # The bins are log-spaced at 200 per decade, so a value is located to about 1.2 %.
    assert independent == pytest.approx(10.0, rel=0.03)
    assert comonotonic == pytest.approx(10.0, rel=0.03)


def test_independence_and_comonotonicity_disagree_on_a_spread_distribution() -> None:
    """The distinction the published field erased, on a case where it is visible."""
    edges = latency_bin_edges()
    # Ninety per cent fast, ten per cent slow, in both stages.
    first = np.zeros(len(edges) - 1, dtype=np.int64)
    first[int(np.searchsorted(edges, 0.1, side="right")) - 1] = 9_000
    first[int(np.searchsorted(edges, 100.0, side="right")) - 1] = 1_000
    second = first.copy()

    independent = independent_sum_quantile(first, second, 0.95)
    comonotonic = comonotonic_sum_quantile(first, second, 0.95)

    # Comonotonic: the slow tenth of one stage is exactly the slow tenth of the other, so
    # the 95th percentile is 100 + 100. Independent: the chance both are slow at once is
    # one per cent, so the 95th percentile is one slow stage and one fast one.
    assert comonotonic == pytest.approx(200.0, rel=0.03)
    assert independent == pytest.approx(100.1, rel=0.03)
    assert independent < comonotonic


def test_the_estimate_is_deterministic() -> None:
    """A design parameter may not move between two runs of the same code."""
    first, second = _point_mass(1.0, 5_000), _point_mass(3.0, 5_000)
    assert independent_sum_quantile(first, second, 0.95) == independent_sum_quantile(
        first, second, 0.95
    )


def test_an_empty_stage_leaves_the_other_untouched() -> None:
    """No local measurement means the end-to-end tail is the provider's own."""
    provider = _point_mass(4.0)
    empty = np.zeros(len(latency_bin_edges()) - 1, dtype=np.int64)

    assert independent_sum_quantile(provider, empty, 0.95) == pytest.approx(
        pooled_quantile(provider, 0.95), rel=0.03
    )
    assert comonotonic_sum_quantile(provider, empty, 0.95) == pytest.approx(
        pooled_quantile(provider, 0.95), rel=1e-9
    )


def test_both_stages_empty_is_unmeasured_rather_than_zero() -> None:
    empty = np.zeros(len(latency_bin_edges()) - 1, dtype=np.int64)
    assert np.isnan(independent_sum_quantile(empty, empty, 0.95))
    assert np.isnan(comonotonic_sum_quantile(empty, empty, 0.95))
