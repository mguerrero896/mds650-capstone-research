"""Target-blind contracts for the preregistered Phase 5 stability analysis."""

from __future__ import annotations

import polars as pl
import pytest

from mds650.stability import (
    add_stability_strata,
    apply_b2_delay,
    apply_fmp_delay,
    b2_sensitivity_column,
    development_volatility_cutpoints,
)
from mds650.study_design import B2_FEATURE_NAMES


def test_stability_strata_use_only_frozen_b0_predictors() -> None:
    predictors = pl.DataFrame(
        {
            "origin_id": ["a", "b", "c", "d", "e", "f"],
            "b0_session_minute": [5, 129, 130, 259, 260, 360],
            "b0_rv_30m_lag": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
            "rv30": [100.0, 1.0, 80.0, 2.0, 60.0, 3.0],
        }
    )
    lower, upper = development_volatility_cutpoints(predictors)
    changed_target = predictors.with_columns((pl.col("rv30") * -99).alias("rv30"))

    observed = add_stability_strata(predictors, lower=lower, upper=upper)
    target_changed = add_stability_strata(changed_target, lower=lower, upper=upper)

    assert (lower, upper) == pytest.approx((8 / 3, 13 / 3))
    assert observed["session_tercile"].to_list() == [
        "FIRST",
        "FIRST",
        "MIDDLE",
        "MIDDLE",
        "LAST",
        "LAST",
    ]
    assert observed["volatility_regime"].to_list() == [
        "LOW",
        "LOW",
        "MIDDLE",
        "MIDDLE",
        "HIGH",
        "HIGH",
    ]
    assert observed.select("session_tercile", "volatility_regime").equals(
        target_changed.select("session_tercile", "volatility_regime")
    )


def test_timing_sensitivities_replace_only_frozen_predictors() -> None:
    data: dict[str, list[float | str]] = {
        "origin_id": ["one"],
        "asset": ["AAPL"],
        "rv30": [999.0],
        "b0_spot": [1.0],
        "b0_rv_5m_lag": [2.0],
        "b0_rv_30m_lag": [3.0],
        "b0_return_5m_lag": [4.0],
        "b0_volume_5m_lag": [5.0],
        "b0_plus2_spot": [11.0],
        "b0_plus2_rv_5m_lag": [12.0],
        "b0_plus2_rv_30m_lag": [13.0],
        "b0_plus2_return_5m_lag": [14.0],
        "b0_plus2_volume_5m_lag": [15.0],
    }
    for position, feature in enumerate(B2_FEATURE_NAMES):
        data[feature] = [float(position)]
        data[b2_sensitivity_column(feature, 120)] = [float(position + 100)]
        data[b2_sensitivity_column(feature, 300)] = [float(position + 300)]
    frame = pl.DataFrame(data)

    plus2 = apply_fmp_delay(frame, delay_minutes=2)
    b2_120 = apply_b2_delay(frame, delay_seconds=120)

    assert plus2.select(
        "b0_spot",
        "b0_rv_5m_lag",
        "b0_rv_30m_lag",
        "b0_return_5m_lag",
        "b0_volume_5m_lag",
    ).row(0) == (11.0, 12.0, 13.0, 14.0, 15.0)
    assert b2_120.select(B2_FEATURE_NAMES).row(0) == tuple(
        float(position + 100) for position in range(len(B2_FEATURE_NAMES))
    )
    assert plus2["rv30"].to_list() == frame["rv30"].to_list()
    assert b2_120["rv30"].to_list() == frame["rv30"].to_list()
    assert plus2.height == b2_120.height == frame.height


def test_unregistered_timing_variant_fails_closed() -> None:
    frame = pl.DataFrame({"origin_id": ["one"]})

    with pytest.raises(ValueError, match="FMP_DELAY_NOT_PREREGISTERED"):
        apply_fmp_delay(frame, delay_minutes=3)
    with pytest.raises(ValueError, match="B2_DELAY_NOT_PREREGISTERED"):
        apply_b2_delay(frame, delay_seconds=30)
