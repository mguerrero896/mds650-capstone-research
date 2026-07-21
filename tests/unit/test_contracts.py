from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from mds650.contracts import (
    CorporateEvent,
    ForecastOrigin,
    OptionQuote,
    OptionStateSnapshot,
    OptionTrade,
    RealizedVarianceTarget,
    UnderlyingBar,
    UnusualOptionEvent,
)


def _provenance() -> dict[str, object]:
    return {
        "run_id": "run-1",
        "source_provider": "fmp",
        "source_response_id": "resp-1",
        "observed_at_utc": datetime(2026, 7, 16, 14, 30, tzinfo=UTC),
    }


def test_underlying_bar_requires_positive_ohlc_and_utc_timestamp() -> None:
    row = UnderlyingBar(
        **_provenance(),
        asset="SPY",
        bar_start_utc=datetime(2026, 7, 16, 14, 30, tzinfo=UTC),
        open=600.0,
        high=601.0,
        low=599.5,
        close=600.5,
        volume=1000.0,
    )

    assert row.asset == "SPY"
    assert row.bar_start_ny.tzinfo is not None


def test_underlying_bar_rejects_invalid_ohlc_relationship() -> None:
    with pytest.raises(ValueError, match="OHLC_RELATION_INVALID"):
        UnderlyingBar(
            **_provenance(),
            asset="SPY",
            bar_start_utc=datetime(2026, 7, 16, 14, 30, tzinfo=UTC),
            open=602.0,
            high=601.0,
            low=599.5,
            close=600.5,
            volume=1000.0,
        )


def test_six_option_component_records_expose_required_fields() -> None:
    common = _provenance()
    event = CorporateEvent(
        **common,
        asset="AAPL",
        event_type="earnings",
        event_time_utc=datetime(2026, 7, 16, 12, 0, tzinfo=UTC),
        available_at_utc=datetime(2026, 7, 16, 12, 0, tzinfo=UTC),
        event_date_ny=date(2026, 7, 16),
        timestamp_quality="point_in_time",
    )
    unusual = UnusualOptionEvent(
        **common,
        event_id="evt-1",
        asset="AAPL",
        contract_id="O:AAPL260821C00200000",
        event_time_utc=datetime(2026, 7, 16, 14, 31, tzinfo=UTC),
        available_at_utc=datetime(2026, 7, 16, 14, 31, tzinfo=UTC),
        strike=200.0,
        expiry=date(2026, 8, 21),
        option_type="call",
    )
    state_common = {key: value for key, value in common.items() if key != "observed_at_utc"}
    state = OptionStateSnapshot(
        **state_common,
        asset="AAPL",
        contract_or_surface_key="AAPL:30D:ATM",
        observed_at_utc=datetime(2026, 7, 16, 14, 30, tzinfo=UTC),
        available_at_utc=datetime(2026, 7, 16, 14, 30, tzinfo=UTC),
        coverage_flag="observed",
    )
    trade = OptionTrade(
        **common,
        contract_id="O:AAPL260821C00200000",
        trade_time_utc=datetime(2026, 7, 16, 14, 31, 1, 123000, tzinfo=UTC),
        price=2.5,
        size=10.0,
    )
    quote = OptionQuote(
        **common,
        contract_id="O:AAPL260821C00200000",
        quote_time_utc=datetime(2026, 7, 16, 14, 31, 1, 123000, tzinfo=UTC),
        bid=2.4,
        ask=2.6,
    )

    assert event.timestamp_quality == "point_in_time"
    assert unusual.option_type == "call"
    assert state.coverage_flag == "observed"
    assert trade.condition_codes == []
    assert quote.ask == 2.6


def test_forecast_origin_and_target_require_pit_cutoff_and_thirty_closes() -> None:
    origin = ForecastOrigin(
        run_id="run-1",
        source_provider="fmp",
        source_response_id="resp-1",
        observed_at_utc=datetime(2026, 7, 16, 14, 35, tzinfo=UTC),
        origin_id="origin-1",
        asset="SPY",
        origin_start_utc=datetime(2026, 7, 16, 14, 35, tzinfo=UTC),
        predictor_cutoff_utc=datetime(2026, 7, 16, 14, 35, tzinfo=UTC),
        event_presence=False,
        source_trace_ids=["resp-1"],
    )
    target = RealizedVarianceTarget(
        origin_id=origin.origin_id,
        horizon_minutes=30,
        future_close_count=30,
        rv_30m=0.01,
        log_rv_30m=-4.6,
        future_close_start_utc=datetime(2026, 7, 16, 14, 36, tzinfo=UTC),
        future_close_end_utc=datetime(2026, 7, 16, 15, 5, tzinfo=UTC),
        target_formula_version="rv30-v1",
        validity="valid",
    )

    assert origin.origin_start_ny.tzinfo is not None
    assert target.future_close_count == target.horizon_minutes == 30


def test_target_rejects_invalid_primary_horizon() -> None:
    with pytest.raises(ValueError, match="RV30_HORIZON_REQUIRED"):
        RealizedVarianceTarget(
            origin_id="origin-1",
            horizon_minutes=15,
            future_close_count=15,
            rv_30m=0.01,
            log_rv_30m=-4.6,
            future_close_start_utc=datetime(2026, 7, 16, 14, 36, tzinfo=UTC),
            future_close_end_utc=datetime(2026, 7, 16, 14, 50, tzinfo=UTC),
            target_formula_version="rv30-v1",
            validity="valid",
        )
