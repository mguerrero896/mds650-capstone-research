"""Block 2 - pooled latency binning, cutoff derivation and stability verdict."""

from __future__ import annotations

import math

import numpy as np
import pytest

from mds650.rp2.pit_ledger import (
    CUTOFF_FLOOR_SECONDS,
    LATENCY_BIN_COUNT,
    empty_sample,
    latency_bin_edges,
    pooled_quantile,
    recommended_cutoff_seconds,
    stability_verdict,
    summarise_latencies,
)


def test_bin_edges_span_the_declared_decades() -> None:
    edges = latency_bin_edges()
    assert edges.size == LATENCY_BIN_COUNT + 1
    assert edges[0] == pytest.approx(1e-4)
    assert edges[-1] == pytest.approx(1e7)


def test_pooled_quantiles_track_the_empirical_ones() -> None:
    rng = np.random.default_rng(11)
    values = np.exp(rng.normal(loc=-2.0, scale=1.5, size=200_000))
    sample = summarise_latencies(values)
    for quantile in (0.5, 0.9, 0.95, 0.99):
        pooled = pooled_quantile(sample.histogram, quantile)
        empirical = float(np.quantile(values, quantile))
        assert pooled == pytest.approx(empirical, rel=0.02)


def test_summary_counts_edges_and_backfill() -> None:
    values = np.array([-1.0, 0.0, 0.5, 90.0, 3600.0], dtype=np.float64)
    sample = summarise_latencies(values, duplicate_id_rows=2, cross_session_rows=1)
    assert sample.rows == 5
    assert sample.non_positive == 2
    assert sample.over_backfill_threshold == 2
    assert sample.duplicate_id_rows == 2
    assert sample.cross_session_rows == 1
    assert sample.maximum_seconds == pytest.approx(3600.0)


def test_merging_is_additive_and_starts_from_a_neutral_element() -> None:
    left = summarise_latencies(np.array([0.5, 2.0]))
    right = summarise_latencies(np.array([4.0]))
    merged = empty_sample().merged_with(left).merged_with(right)
    assert merged.rows == 3
    assert merged.histogram.sum() == 3
    assert merged.maximum_seconds == pytest.approx(4.0)
    assert merged.total_seconds == pytest.approx(6.5)


def test_pooled_quantile_rejects_degenerate_inputs() -> None:
    with pytest.raises(ValueError, match="RP2_PIT_QUANTILE_OUT_OF_RANGE"):
        pooled_quantile(empty_sample().histogram, 1.0)
    assert math.isnan(pooled_quantile(empty_sample().histogram, 0.5))


def test_cutoff_never_falls_below_the_floor_and_scales_with_p95() -> None:
    assert recommended_cutoff_seconds(0.2) == CUTOFF_FLOOR_SECONDS
    assert recommended_cutoff_seconds(83.0) == 166.0
    with pytest.raises(ValueError, match="RP2_PIT_P95_INVALID"):
        recommended_cutoff_seconds(float("nan"))


def test_stability_verdict_flags_an_outlying_session() -> None:
    assert stability_verdict([0.2, 0.21, 0.19, 0.25])
    assert not stability_verdict([0.2, 0.21, 0.19, 12.0])
    assert not stability_verdict([])


def _stats(p95: float, backfill: float) -> dict[str, object]:
    return {"quantiles_seconds": {"p95": p95}, "backfill_share": backfill}


def test_session_admissibility_flags_both_failure_modes() -> None:
    from mds650.rp2.pit_ledger import session_admissibility

    verdicts = session_admissibility(
        {
            "2025-01-02": _stats(0.3, 0.0001),
            "2025-01-03": _stats(500.0, 0.0001),
            "2025-01-06": _stats(0.3, 0.05),
            "2025-01-07": _stats(500.0, 0.05),
        },
        cutoff_seconds=120.0,
    )
    by_session = {item.session: item for item in verdicts}
    assert by_session["2025-01-02"].admissible
    assert by_session["2025-01-03"].reason == "P95_ABOVE_CUTOFF"
    assert by_session["2025-01-06"].reason == "BACKFILL_SHARE_ABOVE_CEILING"
    assert by_session["2025-01-07"].reason == "P95_ABOVE_CUTOFF+BACKFILL_SHARE_ABOVE_CEILING"
    assert sum(1 for item in verdicts if item.admissible) == 1


def test_session_admissibility_rejects_malformed_stats() -> None:
    from mds650.rp2.pit_ledger import session_admissibility

    with pytest.raises(ValueError, match="RP2_PIT_SESSION_STATS_MALFORMED"):
        session_admissibility({"x": {"quantiles_seconds": 1.0}}, cutoff_seconds=1.0)
