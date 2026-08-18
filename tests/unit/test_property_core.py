"""Property-based tests (hypothesis) for the core loss, adjustment and
inference primitives. Hermetic: synthetic data only."""

from __future__ import annotations

import numpy as np
import polars as pl
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from mds650 import inference
from mds650.calibration import mincer_zarnowitz
from mds650.metrics import holm_adjust, qlike_losses

_positive = st.floats(min_value=1e-6, max_value=1e6, allow_nan=False, allow_infinity=False)


@settings(max_examples=200, deadline=None)
@given(st.lists(_positive, min_size=1, max_size=50), st.lists(_positive, min_size=1, max_size=50))
def test_qlike_nonnegative_everywhere(actual: list[float], forecast: list[float]) -> None:
    size = min(len(actual), len(forecast))
    losses = qlike_losses(actual[:size], forecast[:size])
    assert np.all(losses >= 0.0)
    assert np.all(np.isfinite(losses))


@settings(max_examples=100, deadline=None)
@given(st.lists(_positive, min_size=1, max_size=50))
def test_qlike_zero_iff_perfect(values: list[float]) -> None:
    losses = qlike_losses(values, values)
    assert np.allclose(losses, 0.0, atol=1e-9)


@settings(max_examples=100, deadline=None)
@given(
    st.dictionaries(
        st.text(min_size=1, max_size=8),
        st.floats(min_value=1e-12, max_value=1.0, allow_nan=False),
        min_size=1,
        max_size=12,
    )
)
def test_holm_dominates_raw_and_is_bounded(p_values: dict[str, float]) -> None:
    adjusted = holm_adjust(p_values)
    assert set(adjusted) == set(p_values)
    for name, raw in p_values.items():
        assert adjusted[name] >= raw - 1e-15
        assert adjusted[name] <= 1.0
    ordered = sorted(p_values, key=p_values.__getitem__)
    for earlier, later in zip(ordered, ordered[1:], strict=False):
        assert adjusted[earlier] <= adjusted[later] + 1e-15


@settings(max_examples=50, deadline=None)
@given(st.lists(_positive, min_size=8, max_size=60), st.integers(min_value=0, max_value=2**31))
def test_mincer_zarnowitz_recovers_calibrated_forecast(values: list[float], seed: int) -> None:
    series = np.asarray(values, dtype=float)
    if np.ptp(np.log(series)) < 0.1:  # degenerate: no variation to regress on
        return
    noise = np.random.default_rng(seed).normal(0.0, 1e-6, size=series.size)
    fit = mincer_zarnowitz(series, series * np.exp(noise))
    assert abs(float(fit["intercept"])) < 1e-3
    assert abs(float(fit["slope"]) - 1.0) < 1e-3


@settings(max_examples=25, deadline=None)
@given(
    st.integers(min_value=4, max_value=20),
    st.integers(min_value=2, max_value=10),
    st.floats(min_value=-0.05, max_value=0.05, allow_nan=False),
)
def test_paired_differences_recover_constant_effect(
    days: int, origins: int, effect: float
) -> None:
    rows = []
    for day in range(days):
        date = f"2026-02-{day + 1:02d}"
        for origin in range(origins):
            base = 1.0 + 0.01 * origin
            rows.append((f"o{origin}", "AAA", date, "m", "B1", base))
            rows.append((f"o{origin}", "AAA", date, "m", "B2", base - effect))
    frame = pl.DataFrame(
        rows,
        schema=[
            "origin_id",
            "asset",
            "session_date",
            "model_role",
            "information_set",
            "qlike_loss",
        ],
        orient="row",
    )
    daily = inference.paired_daily_differences(
        frame, base_set="B1", expanded_set="B2", model="m"
    )
    assert daily.height == days
    assert daily["mean_difference"].to_numpy() == pytest.approx(
        np.full(days, effect), abs=1e-9
    )


@settings(max_examples=25, deadline=None)
@given(st.integers(min_value=1, max_value=15))
def test_moving_block_bootstrap_ci_is_ordered(block_length: int) -> None:
    rng = np.random.default_rng(650)
    series = rng.normal(0.02, 0.01, size=45)
    result = inference.moving_block_bootstrap(
        series, repetitions=199, block_length=block_length
    )
    assert float(result["ci_low"]) <= float(result["estimate"]) <= float(result["ci_high"])
