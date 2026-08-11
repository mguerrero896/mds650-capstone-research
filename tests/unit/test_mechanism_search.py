from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import polars as pl
import pytest

from mds650.mechanism_search import (
    B2_FEATURES,
    MECHANISM_VARIANTS,
    add_predeclared_strata,
    build_mechanism_matrix,
    combine_base_and_residual,
    fit_residual_learner,
    lag_b2_one_session,
    permute_residual_target,
)


def _frame(rows: int = 12) -> pl.DataFrame:
    values = np.arange(1.0, rows + 1.0)
    payload: dict[str, object] = {
        "asset": ["AAPL", "MSFT", "AAPL"] * (rows // 3),
        "session_date": ["2026-03-24" if i < rows // 2 else "2026-03-25" for i in range(rows)],
        "forecast_origin_utc": [
            datetime(2026, 3, 24 + (i // 6), 14, 5, tzinfo=UTC) + timedelta(minutes=5 * i)
            for i in range(rows)
        ],
        "b0_session_minute": [35 if i % 2 == 0 else 180 for i in range(rows)],
        "b0_rv_30m_lag": 0.0001 + values / 1_000_000,
    }
    for index, name in enumerate(B2_FEATURES):
        payload[name] = 0.1 + values / (100.0 + index)
    return pl.DataFrame(payload)


def test_registered_mechanisms_are_small_and_b2_only() -> None:
    assert MECHANISM_VARIANTS == (
        "global_ridge",
        "asset_ridge",
        "hour_ridge",
        "regime_ridge",
        "global_elastic_net",
    )
    assert len(B2_FEATURES) == 9
    assert all("rv30" not in name.lower() for name in B2_FEATURES)


def test_conditional_matrix_is_deterministic_and_explicit() -> None:
    frame = add_predeclared_strata(_frame())
    first, names = build_mechanism_matrix(frame, "hour_ridge")
    second, same_names = build_mechanism_matrix(frame, "hour_ridge")
    assert names == same_names
    assert np.array_equal(first, second)
    assert len(names) == len(B2_FEATURES) * (1 + frame["session_tercile"].n_unique())
    assert any("session_tercile__first" in name for name in names)


def test_residual_learner_predicts_signed_correction_without_target_column() -> None:
    frame = add_predeclared_strata(_frame())
    residuals = np.linspace(-0.001, 0.001, frame.height)
    fitted = fit_residual_learner(
        frame.select([*B2_FEATURES, "asset", "session_tercile", "volatility_regime"]),
        residuals,
        mechanism_id="asset_ridge",
    )
    correction = fitted.predict_correction(frame)
    assert correction.shape == (frame.height,)
    assert np.isfinite(correction).all()
    assert np.isfinite(combine_base_and_residual(np.ones(frame.height), correction)).all()
    with pytest.raises(ValueError, match="TARGET_COLUMN_FORBIDDEN"):
        build_mechanism_matrix(frame.with_columns(pl.lit(1.0).alias("rv30")), "global_ridge")


def test_placebo_and_lag_are_reproducible() -> None:
    frame = add_predeclared_strata(_frame(18))
    placebo_a = permute_residual_target(np.arange(18.0), seed=650)
    placebo_b = permute_residual_target(np.arange(18.0), seed=650)
    assert np.array_equal(placebo_a, placebo_b)
    lagged = lag_b2_one_session(frame)
    assert 0 < lagged.height < frame.height
    assert set(B2_FEATURES) <= set(lagged.columns)


def test_invalid_base_and_correction_shapes_fail_closed() -> None:
    with pytest.raises(ValueError, match="SHAPE_OR_FINITE"):
        combine_base_and_residual([1.0, 2.0], [0.1])
