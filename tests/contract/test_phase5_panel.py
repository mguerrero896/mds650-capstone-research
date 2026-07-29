"""Fail-closed contracts for the common Phase 5 development panel."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import polars as pl
import pytest

from mds650.phase5_panel import build_common_panel, target_sha256
from mds650.study_design import B2_FEATURE_NAMES


def _inputs() -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    first = datetime(2026, 3, 24, 13, 35, tzinfo=UTC)
    second = datetime(2026, 3, 24, 13, 40, tzinfo=UTC)
    ids = ["AAPL|2026-03-24|13:35", "AAPL|2026-03-24|13:40"]
    origins = pl.DataFrame(
        {
            "origin_id": ids,
            "asset": ["AAPL", "AAPL"],
            "session_date": ["2026-03-24", "2026-03-24"],
            "forecast_origin_utc": [first, second],
            "rv30": [0.001, 0.002],
            "target_price_count": [31, 31],
            "target_future_close_count": [30, 30],
            "target_validity": ["valid", "valid"],
        }
    )
    b0 = pl.DataFrame(
        {
            "origin_id": ids,
            "b0_spot": [100.0, 101.0],
            "b0_rv_5m_lag": [0.0001, 0.0002],
            "b0_rv_30m_lag": [0.0004, 0.0005],
            "b0_return_5m_lag": [0.01, 0.02],
            "b0_volume_5m_lag": [1000.0, 1200.0],
            "b0_session_minute": [5, 10],
            "b0_available_at_utc": [first, second],
        }
    )
    b1 = pl.DataFrame(
        {
            "origin_id": ids,
            "b1q_atm_iv": [0.25, None],
            "b1a_complete": [True, False],
            "b1q_pit_evidence_valid": [True, True],
            "b1q_quote_not_after_origin": [True, True],
        }
    )
    b2_values = {name: [0.1, 0.2] for name in B2_FEATURE_NAMES}
    b2 = pl.DataFrame(
        {
            "origin_id": ids,
            **b2_values,
            "b2_window_end": [first - timedelta(seconds=60), second - timedelta(seconds=60)],
            "b2_max_operational_time": [
                first - timedelta(seconds=61),
                second - timedelta(seconds=61),
            ],
        }
    )
    return origins, b0, b1, b2


def test_common_panel_uses_identical_nested_origin_rows() -> None:
    origins, b0, b1, b2 = _inputs()

    all_rows, common = build_common_panel(
        origins,
        b0,
        b1,
        b2,
        excluded_dates=frozenset({"2026-07-20"}),
    )

    assert all_rows.height == 2
    assert all_rows["origin_id"].n_unique() == 2
    assert common["origin_id"].to_list() == ["AAPL|2026-03-24|13:35"]
    assert common["target_price_count"].to_list() == [31]
    assert common["target_future_close_count"].to_list() == [30]
    assert all_rows["exclusion_reason"].to_list() == [
        "NONE",
        "B1A_MISSING_OR_PIT_FAILURE",
    ]
    assert target_sha256(common) == target_sha256(
        common.select(
            [
                "origin_id",
                "rv30",
                "target_price_count",
                "target_future_close_count",
                "target_validity",
            ]
        )
    )


def test_target_hash_changes_when_rv30_changes() -> None:
    origins, *_ = _inputs()

    assert target_sha256(origins) != target_sha256(
        origins.with_columns((pl.col("rv30") + 0.001).alias("rv30"))
    )


def test_common_panel_rejects_future_b2_state() -> None:
    origins, b0, b1, b2 = _inputs()
    b2 = b2.with_columns(
        (pl.col("b2_window_end") + pl.duration(minutes=1)).alias(
            "b2_max_operational_time"
        )
    )

    with pytest.raises(ValueError, match="B2_PREDICTOR_AFTER_WINDOW_END"):
        build_common_panel(
            origins,
            b0,
            b1,
            b2,
            excluded_dates=frozenset(),
        )


def test_common_panel_rejects_future_b0_or_b2_window() -> None:
    origins, b0, b1, b2 = _inputs()
    b0 = b0.with_columns(
        (pl.col("b0_available_at_utc") + pl.duration(seconds=1)).alias(
            "b0_available_at_utc"
        )
    )
    with pytest.raises(ValueError, match="B0_PREDICTOR_AFTER_FORECAST_ORIGIN"):
        build_common_panel(
            origins,
            b0,
            b1,
            b2,
            excluded_dates=frozenset(),
        )

    origins, b0, b1, b2 = _inputs()
    b2 = b2.with_columns(
        (pl.col("forecast_origin_utc") + pl.duration(seconds=1)).alias(
            "b2_window_end"
        )
        if "forecast_origin_utc" in b2.columns
        else pl.Series(
            "b2_window_end",
            [
                value + timedelta(seconds=1)
                for value in origins["forecast_origin_utc"].to_list()
            ],
        )
    )
    with pytest.raises(ValueError, match="B2_WINDOW_END_AFTER_FORECAST_ORIGIN"):
        build_common_panel(
            origins,
            b0,
            b1,
            b2,
            excluded_dates=frozenset(),
        )


def test_common_panel_rejects_holdout_or_duplicate_origin() -> None:
    origins, b0, b1, b2 = _inputs()
    holdout = origins.with_columns(pl.lit("2026-07-20").alias("session_date"))
    with pytest.raises(ValueError, match="HOLDOUT_DATE_IN_DEVELOPMENT_PANEL"):
        build_common_panel(
            holdout,
            b0,
            b1,
            b2,
            excluded_dates=frozenset({"2026-07-20"}),
        )

    with pytest.raises(ValueError, match="DUPLICATE_FORECAST_ORIGIN"):
        build_common_panel(
            pl.concat([origins, origins.head(1)]),
            b0,
            b1,
            b2,
            excluded_dates=frozenset(),
        )
