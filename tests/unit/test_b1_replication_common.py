"""Target-blind panel tests for independent replication."""

from __future__ import annotations

from datetime import UTC, datetime

import polars as pl

from mds650.b1_replication_common import build_replication_common_frame
from mds650.b1v3 import B1V3_FEATURES
from mds650.phase6 import B0V2_FEATURES
from mds650.study_design import B2_FEATURE_NAMES


def test_common_panel_preserves_origins_and_masks_unavailable_b2() -> None:
    origins = pl.DataFrame(
        {
            "origin_id": ["AAPL:1", "AAPL:2"],
            "asset": ["AAPL", "AAPL"],
            "session_date": ["2024-12-10", "2024-12-10"],
            "forecast_origin_utc": [
                datetime(2024, 12, 10, 15, tzinfo=UTC),
                datetime(2024, 12, 10, 15, 5, tzinfo=UTC),
            ],
            "forecast_origin_ns": [1_000_000_000, 2_000_000_000],
            "role": ["independent_replication", "independent_replication"],
            "session_minute": [30, 35],
            "session_tercile": ["first", "first"],
        }
    )
    b0_values: dict[str, list[object]] = {
        feature: (["AAPL", "AAPL"] if feature == "b0v2_asset_identity" else [0.1, 0.2])
        for feature in B0V2_FEATURES
    }
    b0 = pl.DataFrame(
        {
            "origin_id": ["AAPL:1", "AAPL:2"],
            **b0_values,
            "b0_complete": [True, True],
            "b0_missing_reason": [None, None],
            "max_predictor_available_at_utc": [
                datetime(2024, 12, 10, 14, 59, tzinfo=UTC),
                datetime(2024, 12, 10, 15, 4, tzinfo=UTC),
            ],
        }
    )
    b1 = pl.DataFrame(
        {
            "origin_id": ["AAPL:1", "AAPL:2"],
            **{feature: [0.1, 0.2] for feature in B1V3_FEATURES},
            "b1v3a_complete": [True, True],
            "b1v3b_complete": [True, True],
            "b1v3c_complete": [True, True],
            "max_sip_timestamp_ns": [900_000_000, 1_900_000_000],
        }
    )
    cutoff = datetime(2024, 12, 10, 14, 59, tzinfo=UTC)
    b2 = pl.DataFrame(
        {
            "origin_id": ["AAPL:1", "AAPL:2"],
            **{feature: [0.1, None] for feature in B2_FEATURE_NAMES},
            "b2v2_availability_eligible": [True, False],
            "b2v2_availability_status": ["ELIGIBLE", "EXCLUDED_DELAY"],
            "source_temporal_state": ["ON_TIME", "DELAYED"],
            "b2v2_max_created_at_utc": [cutoff, None],
            "b2v2_cutoff_utc": [cutoff, cutoff],
        }
    )

    panel = build_replication_common_frame(origins=origins, b0=b0, b1=b1, b2=b2)

    assert panel.height == 2
    assert panel["role"].unique().to_list() == ["confirmation"]
    assert panel["b1v3a_information_set_complete"].to_list() == [True, True]
    assert panel["b2_information_set_complete"].to_list() == [True, False]
    excluded = panel.filter(~pl.col("b2v2_availability_eligible"))
    assert all(excluded[feature].null_count() == 1 for feature in B2_FEATURE_NAMES)
