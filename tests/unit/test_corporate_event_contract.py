from datetime import UTC, datetime

from mds650.contracts import CorporateEvent, ForecastOrigin
from mds650.events import earnings_instrument_contract, eligible_earnings_events


def test_etf_earnings_contract_is_not_applicable() -> None:
    assert earnings_instrument_contract("SPY") == {
        "instrument_type": "ETF",
        "earnings_applicable": False,
        "earnings_bmo_today": 0,
        "earnings_amc_today": 0,
        "days_to_next_earnings": None,
    }


def test_etf_cannot_receive_corporate_earnings_event() -> None:
    origin = ForecastOrigin(
        run_id="r",
        source_provider="fixture",
        source_response_id="origin",
        observed_at_utc=datetime(2026, 7, 13, 13, 35, tzinfo=UTC),
        origin_id="QQQ:2026-07-13T13:35:00+00:00",
        asset="QQQ",
        origin_start_utc=datetime(2026, 7, 13, 13, 35, tzinfo=UTC),
        predictor_cutoff_utc=datetime(2026, 7, 13, 13, 34, tzinfo=UTC),
        event_presence=False,
    )
    event = CorporateEvent(
        run_id="r",
        source_provider="fmp",
        source_response_id="e",
        observed_at_utc=datetime(2026, 7, 13, 12, tzinfo=UTC),
        asset="QQQ",
        event_type="earnings",
        event_time_utc=datetime(2026, 7, 13, 12, tzinfo=UTC),
        available_at_utc=datetime(2026, 7, 13, 12, tzinfo=UTC),
        timestamp_quality="point_in_time",
    )
    assert eligible_earnings_events(origin, [event]) == ()
