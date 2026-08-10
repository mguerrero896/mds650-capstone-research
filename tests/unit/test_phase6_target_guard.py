"""Regression test for target-free B0 timing sensitivities."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import polars as pl

from mds650.phase6 import B0V2_FEATURES, build_b0v2_features


def test_b0_target_free_mode_does_not_read_future_closes() -> None:
    start = datetime(2025, 1, 2, 14, 29, tzinfo=UTC)
    rows: list[dict[str, object]] = []
    for asset in ("AAPL", "SPY", "QQQ"):
        for offset in range(31):
            timestamp = start + timedelta(minutes=offset)
            rows.append(
                {
                    "asset": asset,
                    "session_date": "2025-01-02",
                    "bar_timestamp_raw_utc": timestamp,
                    "available_at_utc": timestamp + timedelta(minutes=1),
                    "close": 100.0 + offset,
                    "volume": 1_000.0,
                }
            )
    bars = pl.DataFrame(rows)
    origins = pl.DataFrame(
        {
            "origin_id": ["AAPL:2025-01-02T15:00:00+00:00"],
            "asset": ["AAPL"],
            "session_date": ["2025-01-02"],
            "forecast_origin_utc": [datetime(2025, 1, 2, 15, 0, tzinfo=UTC)],
        }
    )
    frame = build_b0v2_features(bars, origins, include_target=False)
    assert frame.height == 1
    assert frame["rv30"].null_count() == 1
    assert frame["target_price_count"].to_list() == [0]
    assert frame["target_return_count"].to_list() == [0]
    assert all(frame[column].is_not_null().all() for column in B0V2_FEATURES)
