from __future__ import annotations

import json
from pathlib import Path

import pytest

from mds650.errors import QualityGateError, SchemaDriftError
from mds650.providers.fmp import parse_earnings_payload, parse_minute_payload
from mds650.providers.massive import parse_directed_quotes, parse_directed_trades
from mds650.providers.unusual_whales import parse_flow_alert_payload

FIXTURES = Path(__file__).parents[1] / "fixtures" / "providers"


def _load(name: str) -> object:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_fmp_contract_parsers_preserve_observed_schema_semantics() -> None:
    bars = parse_minute_payload(
        _load("fmp_minute.json"),
        asset="AAPL",
        run_id="run-1",
        source_response_id="fmp-1",
        source_timezone="America/New_York",
    )
    earnings = parse_earnings_payload(
        _load("fmp_earnings.json"),
        run_id="run-1",
        source_response_id="fmp-2",
    )

    assert bars[0].asset == "AAPL"
    assert earnings[0].timestamp_quality == "date_only"
    assert earnings[0].available_at_utc is None


def test_fmp_contract_parser_fails_on_unexpected_schema() -> None:
    with pytest.raises(SchemaDriftError, match="FMP_EARNINGS_SCHEMA_DRIFT"):
        parse_earnings_payload([{"symbol": "AAPL"}], run_id="r", source_response_id="s")


def test_unusual_whales_parser_keeps_proxies_without_intent_labels() -> None:
    events = parse_flow_alert_payload(
        _load("uw_flow.json"),
        run_id="run-1",
        source_response_id="uw-1",
    )

    assert events[0].contract_id == "AAPL260821C00200000"
    assert events[0].execution_proxy == "mid_or_unknown"
    assert events[0].available_at_utc is None


def test_unusual_whales_time_and_iv_alias_fixture_is_explicit() -> None:
    """Raw aliases and event times are present without inventing executed_at."""
    raw = _load("uw_flow.json")["data"][0]
    assert {"iv_start", "iv_end", "created_at", "start_time", "end_time"}.issubset(raw)
    assert "executed_at" not in raw
    event = parse_flow_alert_payload(
        {"data": [raw]}, run_id="run-1", source_response_id="uw-1"
    )[0]
    assert event.available_at_utc is None


def test_massive_directed_parsers_preserve_precision_and_empty_windows() -> None:
    trades = parse_directed_trades(
        _load("massive_trades.json"),
        contract_id="AAPL260821C00200000",
        source_response_id="massive-1",
        run_id="run-1",
    )
    quotes = parse_directed_quotes(
        _load("massive_quotes.json"),
        contract_id="AAPL260821C00200000",
        source_response_id="massive-2",
        run_id="run-1",
    )

    assert trades[0].trade_time_utc.microsecond == 123456
    assert quotes[0].bid == 2.4
    assert parse_directed_trades({}, contract_id="A", source_response_id="s", run_id="r") == []


def test_massive_parser_rejects_contract_mismatch() -> None:
    with pytest.raises(QualityGateError, match="MASSIVE_CONTRACT_MISMATCH"):
        parse_directed_trades(
            _load("massive_trades.json"),
            contract_id="OTHER",
            source_response_id="massive-1",
            run_id="run-1",
            source_contract_id="AAPL260821C00200000",
        )


def test_fmp_calendar_fixture_preserves_unclassified_missing_minutes() -> None:
    """Calendar gaps remain explicit and are never treated as interpolable data."""
    cases = _load("fmp_calendar_cases.json")
    assert {case["case"] for case in cases} >= {"winter", "summer", "dst", "early-close"}
    missing = {case["asset"]: case for case in cases if case["case"] == "missing-minute"}
    assert missing["AMZN"]["missing_minute_candidates"] == ["2015-01-07 12:15:00"]
    assert missing["TSLA"]["missing_minute_candidates"] == ["2015-01-07 12:34:00"]
    assert all(
        case["classification"] == "unclassified_provider_calendar_or_halt"
        for case in missing.values()
    )
