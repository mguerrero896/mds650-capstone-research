from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from mds650.contracts import (
    CorporateEvent,
    OptionQuote,
    OptionStateSnapshot,
    OptionTrade,
    UnusualOptionEvent,
)
from mds650.errors import QualityGateError
from mds650.pilot import build_pilot

ASSETS = ("SPY", "QQQ", "AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "META")


def _raw_bars(asset_index: int) -> list[dict[str, object]]:
    start = datetime(2026, 7, 16, 9, 30)
    return [
        {
            "date": (start + timedelta(minutes=index)).strftime("%Y-%m-%d %H:%M:%S"),
            "open": 100.0 + asset_index,
            "high": 101.0 + asset_index,
            "low": 99.5 + asset_index,
            "close": 100.0 + asset_index + index * 0.01,
            "volume": 1000 + index,
        }
        for index in range(40)
    ]


def _event(asset: str, index: int) -> UnusualOptionEvent:
    timestamp = datetime(2026, 7, 16, 13, 34, tzinfo=UTC)
    return UnusualOptionEvent(
        run_id="run-1",
        source_provider="unusual_whales",
        source_response_id=f"uw-{asset}",
        observed_at_utc=timestamp,
        event_id=f"event-{asset}",
        asset=asset,
        contract_id=f"{asset}-CONTRACT",
        event_time_utc=timestamp,
        available_at_utc=timestamp,
        premium=1000.0 + index,
        size=10,
        volume=20,
        open_interest=30,
        volume_oi_ratio=2 / 3,
        option_type="call",
        strike=100,
        expiry=date(2026, 8, 21),
    )


def test_pilot_builds_all_assets_origins_targets_and_trace() -> None:
    raw = {asset: _raw_bars(index) for index, asset in enumerate(ASSETS)}
    events = [_event(asset, index) for index, asset in enumerate(ASSETS)]
    states = [
        OptionStateSnapshot(
            run_id="run-1",
            source_provider="unusual_whales",
            source_response_id=f"state-{asset}",
            observed_at_utc=datetime(2026, 7, 16, 13, 35, tzinfo=UTC),
            asset=asset,
            contract_or_surface_key=f"{asset}:ATM",
            available_at_utc=datetime(2026, 7, 16, 13, 35, tzinfo=UTC),
            coverage_flag="observed",
            iv=0.2,
        )
        for asset in ASSETS
    ]
    trades = [
        OptionTrade(
            run_id="run-1",
            source_provider="massive",
            source_response_id=f"trade-{asset}",
            observed_at_utc=datetime(2026, 7, 16, 13, 35, tzinfo=UTC),
            contract_id=f"{asset}-CONTRACT",
            trade_time_utc=datetime(2026, 7, 16, 13, 35, tzinfo=UTC),
            price=1.0,
            size=1.0,
        )
        for asset in ASSETS
    ]
    quotes = [
        OptionQuote(
            run_id="run-1",
            source_provider="massive",
            source_response_id=f"quote-{asset}",
            observed_at_utc=datetime(2026, 7, 16, 13, 35, tzinfo=UTC),
            contract_id=f"{asset}-CONTRACT",
            quote_time_utc=datetime(2026, 7, 16, 13, 35, tzinfo=UTC),
            bid=0.9,
            ask=1.1,
        )
        for asset in ASSETS
    ]
    earnings = [
        CorporateEvent(
            run_id="run-1",
            source_provider="fmp",
            source_response_id=f"earnings-{asset}",
            observed_at_utc=datetime(2026, 7, 16, 0, 0, tzinfo=UTC),
            asset=asset,
            event_type="earnings",
            event_date_ny=date(2026, 7, 16),
            timestamp_quality="date_only",
        )
        for asset in ASSETS
    ]

    result = build_pilot(
        raw_underlying=raw,
        corporate_events=earnings,
        unusual_events=events,
        option_states=states,
        option_trades=trades,
        option_quotes=quotes,
        run_id="run-1",
        source_timezone="America/New_York",
    )

    assert len(result.frozen_assets.assets) == 6
    assert set(result.covered_assets) == set(ASSETS)
    assert all(
        result.event_no_event_counts[asset][0] >= 1
        and result.event_no_event_counts[asset][1] >= 1
        for asset in ASSETS
    )
    assert len(result.targets) > 0
    assert result.row_trace[0]["future_close_count"] == 30


def test_pilot_fails_if_one_candidate_is_absent() -> None:
    raw = {asset: _raw_bars(index) for index, asset in enumerate(ASSETS[:-1])}

    with pytest.raises(QualityGateError, match="PILOT_CANDIDATE_COVERAGE_MISSING"):
        build_pilot(
            raw_underlying=raw,
            corporate_events=[],
            unusual_events=[],
            option_states=[],
            option_trades=[],
            option_quotes=[],
            run_id="run-1",
            source_timezone="America/New_York",
        )
