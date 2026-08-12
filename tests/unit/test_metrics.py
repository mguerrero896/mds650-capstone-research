"""Loss, paired-day bootstrap and multiplicity contracts."""

from __future__ import annotations

import numpy as np
import polars as pl
import pytest

from mds650.metrics import (
    holm_adjust,
    paired_day_bootstrap,
    qlike_losses,
    regression_metrics,
)


def test_qlike_is_zero_for_exact_positive_forecast() -> None:
    losses = qlike_losses([1.0, 2.0], [1.0, 2.0])

    assert losses.tolist() == pytest.approx([0.0, 0.0])


def test_regression_metrics_match_direct_definitions() -> None:
    actual = np.array([1.0, 2.0])
    forecast = np.array([1.5, 1.5])

    metrics = regression_metrics(actual, forecast)

    assert metrics["mae"] == pytest.approx(0.5)
    assert metrics["rmse"] == pytest.approx(0.5)
    assert metrics["qlike"] == pytest.approx(float(qlike_losses(actual, forecast).mean()))


def test_paired_day_bootstrap_is_clustered_and_deterministic() -> None:
    differences = pl.DataFrame(
        {
            "session_date": ["2026-06-01"] * 2 + ["2026-06-02"] * 2 + ["2026-06-03"] * 2,
            "loss_difference": [1.0, 1.0, 2.0, 2.0, 3.0, 3.0],
        }
    )

    first = paired_day_bootstrap(
        differences,
        repetitions=1_000,
        seed=650,
    )
    second = paired_day_bootstrap(
        differences,
        repetitions=1_000,
        seed=650,
    )
    reversed_rows = paired_day_bootstrap(
        differences.reverse(),
        repetitions=1_000,
        seed=650,
    )

    assert first == second
    assert first == reversed_rows
    assert first["estimate"] == pytest.approx(2.0)
    assert first["clusters"] == 3
    assert first["repetitions"] == 1_000
    assert first["ci_low"] <= first["estimate"] <= first["ci_high"]


def test_holm_adjustment_is_monotone_in_sorted_order() -> None:
    adjusted = holm_adjust({"delta_b1": 0.01, "delta_b2": 0.04, "robust": 0.03})

    assert adjusted == pytest.approx({"delta_b1": 0.03, "delta_b2": 0.06, "robust": 0.06})
