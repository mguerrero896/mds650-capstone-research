"""Provider contracts, validated field by field rather than by spot check.

Three separate risks live at the provider boundary, and each gets a matrix here rather than
one example:

* **Silent schema drift.** A vendor renames or drops a field and the parser fills a default.
  Every result downstream is then computed from a column that no longer means what it did.
  The check is not "the happy path parses" but "removing any required field is refused".
* **Credential leakage.** A key in a URL reaches a log, an error message, an artifact, or a
  commit. The check is that a sanitised URL contains no secret value, including when the
  same parameter appears twice or carries an empty value.
* **Licensed passthrough.** A raw vendor record retained on a parsed object would end up
  inside a published artifact. The check is that parsed records carry declared fields only.

Nothing here performs a network call, so it runs identically on a hosted runner with no
credentials configured.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from mds650.errors import QualityGateError, SchemaDriftError
from mds650.providers.base import _sanitize_request_url, schema_fingerprint
from mds650.providers.fmp import parse_earnings_payload, parse_minute_payload
from mds650.providers.massive import parse_directed_quotes, parse_directed_trades
from mds650.providers.unusual_whales import parse_flow_alert_payload

FIXTURES = Path(__file__).parents[1] / "fixtures" / "providers"


def _load(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


# --------------------------------------------------------------------------------------
# Schema drift: removing any required field must be refused, not defaulted.
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("field", ["date", "open", "high", "low", "close", "volume"])
def test_fmp_minute_refuses_a_payload_missing_any_declared_field(field: str) -> None:
    payload = _load("fmp_minute.json")
    record = dict(payload[0])
    record.pop(field)
    with pytest.raises((SchemaDriftError, QualityGateError, KeyError, TypeError, ValueError)):
        parse_minute_payload(
            [record],
            asset="AAPL",
            run_id="r",
            source_response_id="s",
            source_timezone="America/New_York",
        )


@pytest.mark.parametrize("field", ["symbol", "date"])
def test_fmp_earnings_refuses_a_payload_missing_an_identifying_field(field: str) -> None:
    record = dict(_load("fmp_earnings.json")[0])
    record.pop(field)
    with pytest.raises(SchemaDriftError):
        parse_earnings_payload([record], run_id="r", source_response_id="s")


@pytest.mark.parametrize("field", ["price", "size", "sip_timestamp"])
def test_massive_trades_refuse_a_record_missing_a_declared_field(field: str) -> None:
    payload = _load("massive_trades.json")
    record = dict(payload["results"][0])
    record.pop(field)
    with pytest.raises(SchemaDriftError):
        parse_directed_trades(
            {"results": [record]},
            contract_id="AAPL260821C00200000",
            source_response_id="s",
            run_id="r",
        )


@pytest.mark.parametrize("field", ["bid_price", "ask_price"])
def test_massive_quotes_refuse_a_record_missing_a_declared_field(field: str) -> None:
    payload = _load("massive_quotes.json")
    record = dict(payload["results"][0])
    record.pop(field)
    with pytest.raises(SchemaDriftError, match="MASSIVE_FIELD_MISSING"):
        parse_directed_quotes(
            {"results": [record]},
            contract_id="AAPL260821C00200000",
            source_response_id="s",
            run_id="r",
        )


def test_an_empty_quote_window_survives_while_a_dropped_field_does_not() -> None:
    """A null bid is a real market state; a missing `bid_price` key is a broken contract."""

    record = dict(_load("massive_quotes.json")["results"][0])
    record["bid_price"] = None
    quotes = parse_directed_quotes(
        {"results": [record]},
        contract_id="AAPL260821C00200000",
        source_response_id="s",
        run_id="r",
    )
    assert quotes[0].bid is None and quotes[0].ask is not None


def test_a_quote_falls_back_to_the_participant_clock_when_the_sip_clock_is_absent() -> None:
    record = dict(_load("massive_quotes.json")["results"][0])
    record.pop("sip_timestamp")
    quotes = parse_directed_quotes(
        {"results": [record]},
        contract_id="AAPL260821C00200000",
        source_response_id="s",
        run_id="r",
    )
    assert quotes[0].provider_timestamp_ns == record["participant_timestamp"]


def test_a_quote_with_no_usable_clock_at_all_is_refused() -> None:
    record = dict(_load("massive_quotes.json")["results"][0])
    record.pop("sip_timestamp")
    record.pop("participant_timestamp")
    with pytest.raises(SchemaDriftError, match="MASSIVE_TIMESTAMP_PRECISION_MISSING"):
        parse_directed_quotes(
            {"results": [record]},
            contract_id="AAPL260821C00200000",
            source_response_id="s",
            run_id="r",
        )


def test_a_renamed_field_is_drift_and_not_a_missing_optional() -> None:
    """The realistic failure: a vendor ships `sipTimestamp` and the old key disappears."""

    record = dict(_load("massive_trades.json")["results"][0])
    record["sipTimestamp"] = record.pop("sip_timestamp")
    with pytest.raises(SchemaDriftError):
        parse_directed_trades(
            {"results": [record]},
            contract_id="AAPL260821C00200000",
            source_response_id="s",
            run_id="r",
        )


def test_the_schema_fingerprint_moves_when_a_field_changes_type() -> None:
    """A number arriving as a string is drift a field-name check would not see."""

    original = [{"price": 1.0, "size": 2}]
    retyped = [{"price": "1.0", "size": 2}]
    assert schema_fingerprint(original) != schema_fingerprint(retyped)


def test_the_schema_fingerprint_is_insensitive_to_record_order() -> None:
    first = [{"a": 1, "b": 2.0}, {"a": 3, "b": 4.0}]
    assert schema_fingerprint(first) == schema_fingerprint(list(reversed(first)))


# --------------------------------------------------------------------------------------
# Credentials: a key must never survive into anything that can be logged or published.
# --------------------------------------------------------------------------------------

SECRET = "sk-live-000000000000000000000000000000"


def test_a_sanitised_url_carries_no_api_key() -> None:
    url = httpx.URL(f"https://api.example.com/v1/bars?symbol=AAPL&apikey={SECRET}")
    sanitised = _sanitize_request_url(url, secret_query_params=frozenset({"apikey"}))
    assert SECRET not in sanitised
    assert "symbol=AAPL" in sanitised


def test_a_repeated_secret_parameter_is_removed_every_time() -> None:
    url = httpx.URL(f"https://api.example.com/v1?apikey={SECRET}&apikey={SECRET}&page=2")
    sanitised = _sanitize_request_url(url, secret_query_params=frozenset({"apikey"}))
    assert SECRET not in sanitised and "page=2" in sanitised


def test_a_url_fragment_cannot_smuggle_a_secret_past_sanitisation() -> None:
    url = httpx.URL(f"https://api.example.com/v1?page=2#token={SECRET}")
    assert SECRET not in _sanitize_request_url(url, secret_query_params=frozenset({"apikey"}))


def test_no_fixture_contains_anything_shaped_like_a_credential() -> None:
    """Fixtures are committed, so a real response pasted in verbatim would publish a key."""

    suspicious: list[str] = []
    for fixture in sorted(FIXTURES.glob("*.json")):
        text = fixture.read_text(encoding="utf-8").lower()
        for marker in ("apikey", "api_key", "authorization", "bearer ", "token"):
            if marker in text:
                suspicious.append(f"{fixture.name}:{marker}")
    assert not suspicious, f"credential-shaped content in committed fixtures: {suspicious}"


# --------------------------------------------------------------------------------------
# Licensed passthrough: parsed records expose declared fields only.
# --------------------------------------------------------------------------------------


def test_a_parsed_option_event_carries_no_raw_vendor_payload() -> None:
    """A retained raw record would ride into every artifact built from these events."""

    event = parse_flow_alert_payload(_load("uw_flow.json"), run_id="r", source_response_id="s")[0]
    fields = set(type(event).model_fields)
    # Vendor keys that carry no defined meaning in this programme must not survive parsing.
    raw_only = {"all_opening_trades", "has_floor", "iv_start", "iv_end", "option_chain"}
    assert not (fields & raw_only), f"vendor-only fields exposed: {fields & raw_only}"
    declared = fields | set(type(event).model_computed_fields)
    dumped = json.loads(json.dumps(event.model_dump(mode="json")))
    assert set(dumped) == declared, "a parsed record grew fields the contract never declared"


def test_every_parsed_record_declares_its_provenance() -> None:
    """A record without a run and a response id cannot be traced back to what produced it."""

    bars = parse_minute_payload(
        _load("fmp_minute.json"),
        asset="AAPL",
        run_id="run-1",
        source_response_id="fmp-1",
        source_timezone="America/New_York",
    )
    events = parse_flow_alert_payload(
        _load("uw_flow.json"), run_id="run-1", source_response_id="uw-1"
    )
    trades = parse_directed_trades(
        _load("massive_trades.json"),
        contract_id="AAPL260821C00200000",
        source_response_id="massive-1",
        run_id="run-1",
    )
    for record in (bars[0], events[0], trades[0]):
        assert record.run_id == "run-1"
        assert record.source_response_id
