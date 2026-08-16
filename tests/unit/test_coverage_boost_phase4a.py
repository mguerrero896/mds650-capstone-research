"""Focused branch tests for provider and research-contract utilities."""

# ruff: noqa: E501

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import httpx
import pytest

from mds650.asset_selection import AssetQuality, freeze_assets
from mds650.contracts import CorporateEvent, ForecastOrigin
from mds650.errors import OverlapError, PITError, QualityGateError, SchemaDriftError
from mds650.events import (
    earnings_instrument_contract,
    eligible_earnings_events,
    validate_optional_news,
)
from mds650.logging import configure_logging, redact_mapping
from mds650.providers.base import ProviderHTTPClient
from mds650.providers.fmp import FMPProvider, parse_earnings_payload, parse_minute_payload
from mds650.providers.massive import (
    MassiveProvider,
    assert_directed_only,
    parse_directed_quotes,
    parse_directed_trades,
)
from mds650.providers.unusual_whales import UnusualWhalesProvider, parse_flow_alert_payload


def _quality(asset: str, start: date = date(2026, 1, 1), end: date = date(2026, 7, 1)) -> AssetQuality:
    return AssetQuality(asset, 0.99, 0.0, 0.0, start, end)


def test_asset_freeze_success_and_fail_closed_paths() -> None:
    frozen = freeze_assets([_quality(name) for name in ("AAPL", "AMZN", "META", "MSFT")])
    assert frozen.assets == ("AAPL", "AMZN", "META", "MSFT")
    with pytest.raises(QualityGateError, match="QUALITY_ASSET_COUNT_BELOW_MINIMUM"):
        freeze_assets([_quality("AAPL")])
    with pytest.raises(QualityGateError, match="ASSET_QUALITY_GATE_FAILED"):
        freeze_assets([_quality("AAPL"), _quality("AAPL"), _quality("AMZN"), _quality("META")])
    with pytest.raises(OverlapError, match="COMMON_HISTORY_OVERLAP_INSUFFICIENT"):
        freeze_assets([_quality("AAPL", date(2026, 1, 1), date(2026, 1, 2)), _quality("AMZN", date(2026, 2, 1), date(2026, 2, 2)), _quality("META"), _quality("MSFT")])


def test_events_contract_and_optional_pit_filtering() -> None:
    assert earnings_instrument_contract("SPY")["earnings_applicable"] is False
    assert earnings_instrument_contract("AAPL")["earnings_applicable"] is True
    with pytest.raises(ValueError, match="ASSET_NOT_IN_CANDIDATE_UNIVERSE"):
        earnings_instrument_contract("UNKNOWN")
    origin_time = datetime(2026, 7, 13, 14, 0, tzinfo=UTC)
    origin = ForecastOrigin(run_id="r", source_provider="fmp", source_response_id="s", observed_at_utc=origin_time, origin_id="x", asset="AAPL", origin_start_utc=origin_time, predictor_cutoff_utc=origin_time, event_presence=False)
    event = CorporateEvent(run_id="r", source_provider="fmp", source_response_id="s", observed_at_utc=origin_time, asset="AAPL", event_type="earnings", event_time_utc=origin_time - timedelta(minutes=1), available_at_utc=origin_time - timedelta(minutes=2), event_date_ny=date(2026, 7, 13), timestamp_quality="point_in_time")
    assert eligible_earnings_events(origin, [event]) == (event,)
    with pytest.raises(PITError, match="OPTIONAL_NEWS_PIT_UNVALIDATED"):
        validate_optional_news([event], validated=False)
    assert validate_optional_news([event], validated=True) == (event,)


def test_logging_redacts_keys_and_messages() -> None:
    assert redact_mapping({"api_key": "secret", "asset": "AAPL"}) == {"api_key": "[REDACTED]", "asset": "AAPL"}
    logger = configure_logging("INFO")
    logger.info("token=hidden")
    with pytest.raises(ValueError, match="LOG_LEVEL_INVALID"):
        configure_logging("not-a-level")


def test_fmp_parser_and_client_paths() -> None:
    payload = [{"date": "2026-07-13 13:30:00", "open": 1, "high": 2, "low": 1, "close": 1.5, "volume": 10}]
    bars = parse_minute_payload(payload, asset="AAPL", run_id="r", source_response_id="s", source_timezone="America/New_York")
    assert len(bars) == 1
    earnings = [{"symbol": "AAPL", "date": "2026-07-13", "epsActual": None, "epsEstimated": None, "revenueActual": None, "revenueEstimated": None, "lastUpdated": None}]
    assert parse_earnings_payload(earnings, run_id="r", source_response_id="s")[0].timestamp_quality == "date_only"
    with pytest.raises(SchemaDriftError):
        parse_minute_payload({}, asset="AAPL", run_id="r", source_response_id="s", source_timezone=None)
    fmp = FMPProvider("dummy", transport=httpx.MockTransport(lambda request: httpx.Response(200, json=[], request=request)))
    assert fmp.minute_bars("AAPL", from_date="2026-07-13", to_date="2026-07-13").status_code == 200
    assert fmp.earnings("AAPL").status_code == 200
    fmp.close()


def test_massive_parser_and_directed_provider_paths() -> None:
    ts = 1_752_427_800_000_000_000
    trade = parse_directed_trades({"results": [{"sip_timestamp": ts, "price": 1.2, "size": 3, "conditions": ["A"]}]}, contract_id="O:AAPL260717C00100000", source_response_id="s", run_id="r")
    quote = parse_directed_quotes({"results": [{"sip_timestamp": ts, "bid_price": 1.0, "ask_price": 1.2, "conditions": ["A"]}]}, contract_id="O:AAPL260717C00100000", source_response_id="s", run_id="r")
    assert trade[0].provider_timestamp_ns == ts and quote[0].bid == 1.0
    assert parse_directed_quotes({}, contract_id="O:AAPL260717C00100000", source_response_id="s", run_id="r") == []
    with pytest.raises(QualityGateError, match="MASSIVE_CONTRACT_MISMATCH"):
        parse_directed_quotes({}, contract_id="O:AAPL260717C00100000", source_contract_id="O:MSFT260717C00100000", source_response_id="s", run_id="r")
    with pytest.raises(QualityGateError, match="MASSIVE_FULL_OPRA_DOWNLOAD_FORBIDDEN"):
        assert_directed_only(full_market_download=True)
    massive = MassiveProvider("dummy", transport=httpx.MockTransport(lambda request: httpx.Response(200, json={}, request=request)))
    assert massive.contract_reference("O:AAPL260717C00100000").status_code == 200
    assert massive.directed_trades("O:AAPL260717C00100000", timestamp="1").status_code == 200
    assert massive.directed_quotes("O:AAPL260717C00100000", timestamp="1", cursor="c").status_code == 200
    massive.close()


def test_unusual_whales_parser_and_provider_paths() -> None:
    record = {"id": "e1", "ticker": "AAPL", "option_chain": "O:AAPL260717C00100000", "start_time": 1_752_427_800_000, "total_premium": 100, "total_size": 2, "volume": 3, "open_interest": 4, "volume_oi_ratio": 0.75, "type": "call", "strike": 100, "expiry": "2026-07-17", "price": 1, "bid": 0.8, "ask": 1.2, "has_sweep": True, "has_floor": False, "has_multileg": False, "underlying_price": 100, "iv_start": 0.2, "iv_end": 0.21}
    event = parse_flow_alert_payload({"data": [record]}, run_id="r", source_response_id="s")[0]
    assert event.iv_change == pytest.approx(0.01, abs=1e-6) and event.execution_proxy == "mid_or_unknown"
    with pytest.raises(SchemaDriftError, match="UW_FLOW_SCHEMA_DRIFT"):
        parse_flow_alert_payload({}, run_id="r", source_response_id="s")
    uw = UnusualWhalesProvider("dummy", transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"data": []}, request=request)))
    assert uw.flow_alerts(ticker="AAPL", start_date="2026-07-13", end_date="2026-07-14").status_code == 200
    uw.close()


def test_provider_client_rejects_invalid_config_and_bad_json() -> None:
    with pytest.raises(ValueError, match="PROVIDER_CLIENT_CONFIGURATION_INVALID"):
        ProviderHTTPClient(base_url="https://provider.test?token=x", api_key="dummy")
    client = ProviderHTTPClient(base_url="https://provider.test", api_key="dummy", transport=httpx.MockTransport(lambda request: httpx.Response(200, text="not-json", request=request)))
    with pytest.raises(SchemaDriftError, match="PROVIDER_RESPONSE_NOT_JSON"):
        client.get_json("/bad")
    client.close()
