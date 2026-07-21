from __future__ import annotations

from datetime import UTC, datetime

import pytest

from mds650.origins import build_forecast_origins


def test_build_forecast_origins_aligns_five_minutes_and_uses_only_prior_events() -> None:
    origins = build_forecast_origins(
        asset="SPY",
        timestamps=[
            datetime(2026, 7, 16, 13, 35, tzinfo=UTC),
            datetime(2026, 7, 16, 13, 36, tzinfo=UTC),
        ],
        run_id="run-1",
        source_trace_ids=["resp-1"],
        event_times=[datetime(2026, 7, 16, 13, 34, tzinfo=UTC)],
    )

    assert len(origins) == 1
    assert origins[0].event_presence is True
    assert origins[0].predictor_cutoff_utc == datetime(2026, 7, 16, 13, 35, tzinfo=UTC)


def test_build_forecast_origins_rejects_naive_timestamps() -> None:
    with pytest.raises(ValueError, match="TIMESTAMP_TIMEZONE_REQUIRED"):
        build_forecast_origins(
            asset="SPY",
            timestamps=[datetime(2026, 7, 16, 13, 35)],
            run_id="run-1",
            source_trace_ids=[],
            event_times=[],
        )
