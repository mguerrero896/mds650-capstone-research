from __future__ import annotations

from datetime import UTC, datetime, timedelta

import polars as pl
import pytest

from mds650.phase6 import (
    B0V2_FEATURES,
    B1V2A_FEATURES,
    B1V2B_FEATURES,
    B1V2C_FEATURES,
    B2V2_FEATURES,
    build_phase6_common_panel,
)


def _inputs() -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    origins = []
    b0_rows = []
    b1_rows = []
    b2_rows = []
    for index in range(2):
        origin = datetime(2025, 10, 28, 14, 35, tzinfo=UTC) + timedelta(minutes=5 * index)
        origin_id = f"AAPL:{origin.isoformat()}"
        key = {
            "origin_id": origin_id,
            "asset": "AAPL",
            "session_date": "2025-10-28",
            "forecast_origin_utc": origin,
        }
        origins.append({**key, "role": "oos_fold_1"})
        b0_rows.append(
            {
                **key,
                "role": "oos_fold_1",
                "target_price_count": 31,
                "target_return_count": 30,
                "rv30": 0.001 + index / 10_000,
                "max_predictor_available_at_utc": origin,
                "drop_reason": None,
                **{
                    name: "AAPL" if name == "b0v2_asset_identity" else 1.0 for name in B0V2_FEATURES
                },
            }
        )
        b1_rows.append(
            {
                **key,
                "role": "oos_fold_1",
                "forecast_origin_ns": int(origin.timestamp() * 1_000_000_000),
                "max_sip_timestamp_ns": int(origin.timestamp() * 1_000_000_000),
                **{name: 0.2 for name in B1V2A_FEATURES},
                **{name: 0.1 for name in B1V2B_FEATURES},
                **{name: 0.05 for name in B1V2C_FEATURES},
                "b1v2a_complete": index == 0,
                "b1v2b_complete": index == 0,
                "b1v2c_complete": index == 0,
            }
        )
        b2_rows.append(
            {
                **key,
                **{name: 0.0 for name in B2V2_FEATURES},
                "b2v2_complete": True,
                "b2v2_cutoff_utc": origin - timedelta(seconds=60),
                "b2v2_max_created_at_utc": origin - timedelta(seconds=90),
            }
        )
    return (
        pl.DataFrame(origins),
        pl.DataFrame(b0_rows),
        pl.DataFrame(b1_rows),
        pl.DataFrame(b2_rows),
    )


def test_phase6_common_panel_uses_identical_nested_rows() -> None:
    origins, b0, b1, b2 = _inputs()

    all_rows, common = build_phase6_common_panel(origins, b0, b1, b2)

    assert all_rows.height == 2
    assert all_rows["exclusion_reason"].to_list() == [
        "NONE",
        "B1V2A_MISSING_OR_PIT_FAILURE",
    ]
    assert common["origin_id"].to_list() == [origins["origin_id"][0]]
    assert common["target_price_count"].to_list() == [31]
    assert common["target_return_count"].to_list() == [30]


@pytest.mark.parametrize("source", ["b0", "b1", "b2"])
def test_phase6_common_panel_rejects_future_predictor(source: str) -> None:
    origins, b0, b1, b2 = _inputs()
    if source == "b0":
        b0 = b0.with_columns(
            (pl.col("forecast_origin_utc") + pl.duration(seconds=1)).alias(
                "max_predictor_available_at_utc"
            )
        )
        error = "PHASE6_B0_AFTER_ORIGIN"
    elif source == "b1":
        b1 = b1.with_columns((pl.col("forecast_origin_ns") + 1).alias("max_sip_timestamp_ns"))
        error = "PHASE6_B1_AFTER_ORIGIN"
    else:
        b2 = b2.with_columns(
            (pl.col("b2v2_cutoff_utc") + pl.duration(seconds=1)).alias("b2v2_max_created_at_utc")
        )
        error = "PHASE6_B2_AFTER_CUTOFF"

    with pytest.raises(ValueError, match=error):
        build_phase6_common_panel(origins, b0, b1, b2)


def test_phase6_common_panel_rejects_key_drift_and_duplicates() -> None:
    origins, b0, b1, b2 = _inputs()
    drifted = b1.with_columns(pl.lit("MSFT").alias("asset"))

    with pytest.raises(ValueError, match="PHASE6_ORIGIN_KEY_MISMATCH:b1"):
        build_phase6_common_panel(origins, b0, drifted, b2)

    with pytest.raises(ValueError, match="PHASE6_DUPLICATE_ORIGIN:b2"):
        build_phase6_common_panel(origins, b0, b1, pl.concat([b2, b2.head(1)]))


def test_phase6_common_panel_separates_valid_target_from_missing_b0() -> None:
    origins, b0, b1, b2 = _inputs()
    b0 = b0.with_columns(
        pl.when(pl.col("origin_id") == origins["origin_id"][0])
        .then(pl.lit("B0V2_UNDERLYING_HISTORY_MISSING"))
        .otherwise(pl.col("drop_reason"))
        .alias("drop_reason")
    )

    all_rows, _ = build_phase6_common_panel(origins, b0, b1, b2)
    row = all_rows.row(0, named=True)

    assert row["target_complete"] is True
    assert row["b0v2_complete"] is False
    assert row["exclusion_reason"] == "B0V2_MISSING_OR_PIT_FAILURE"
