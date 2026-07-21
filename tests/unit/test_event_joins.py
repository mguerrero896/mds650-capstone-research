from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from mds650.contracts import CorporateEvent, ForecastOrigin
from mds650.errors import PITError
from mds650.events import eligible_earnings_events, validate_optional_news


def _origin() -> ForecastOrigin:
    return ForecastOrigin(
        run_id="run-1",
        source_provider="derived",
        source_response_id="resp-1",
        observed_at_utc=datetime(2026, 7, 16, 14, 35, tzinfo=UTC),
        origin_id="origin-1",
        asset="AAPL",
        origin_start_utc=datetime(2026, 7, 16, 14, 35, tzinfo=UTC),
        predictor_cutoff_utc=datetime(2026, 7, 16, 14, 35, tzinfo=UTC),
        event_presence=False,
        source_trace_ids=["resp-1"],
    )


def _event(**kwargs: object) -> CorporateEvent:
    values: dict[str, object] = {
        "run_id": "run-1",
        "source_provider": "fmp",
        "source_response_id": "earnings-1",
        "observed_at_utc": datetime(2026, 7, 16, 14, 30, tzinfo=UTC),
        "asset": "AAPL",
        "event_type": "earnings",
        "event_time_utc": datetime(2026, 7, 16, 14, 20, tzinfo=UTC),
        "available_at_utc": datetime(2026, 7, 16, 14, 20, tzinfo=UTC),
        "event_date_ny": date(2026, 7, 16),
        "timestamp_quality": "point_in_time",
    }
    values.update(kwargs)
    return CorporateEvent(**values)


def test_eligible_earnings_events_excludes_future_and_date_only_records() -> None:
    eligible = eligible_earnings_events(
        _origin(),
        [
            _event(),
            _event(event_time_utc=datetime(2026, 7, 16, 15, 0, tzinfo=UTC)),
            _event(timestamp_quality="date_only", available_at_utc=None),
        ],
    )

    assert eligible == (_event(),)


def test_optional_news_is_blocked_without_point_in_time_validation() -> None:
    with pytest.raises(PITError, match="OPTIONAL_NEWS_PIT_UNVALIDATED"):
        validate_optional_news([], validated=False)
