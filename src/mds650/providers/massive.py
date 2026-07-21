"""Directed Massive/Polygon-compatible option trade and quote parsers."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from mds650.contracts import OptionQuote, OptionTrade
from mds650.errors import QualityGateError, SchemaDriftError
from mds650.providers.base import ProviderHTTPClient, ProviderResponse


def parse_directed_trades(
    payload: Any,
    *,
    contract_id: str,
    source_response_id: str,
    run_id: str,
    source_contract_id: str | None = None,
) -> list[OptionTrade]:
    """Parse only trades for a contract returned by the event source.

    Empty or missing ``results`` is retained as an empty illiquid window. No
    attempt is made to expand the request into a historical OPRA download.
    """
    _validate_contract(contract_id, source_contract_id)
    records = _results(payload, "MASSIVE_TRADES_SCHEMA_DRIFT")
    trades: list[OptionTrade] = []
    for record in records:
        timestamp_ns = _timestamp_ns(record)
        trades.append(
            OptionTrade(
                run_id=run_id,
                source_provider="massive",
                source_response_id=source_response_id,
                observed_at_utc=_timestamp(timestamp_ns),
                contract_id=contract_id,
                trade_time_utc=_timestamp(timestamp_ns),
                provider_timestamp_ns=timestamp_ns,
                price=_number(record, "price"),
                size=_number(record, "size"),
                condition_codes=_conditions(record),
            )
        )
    return trades


def parse_directed_quotes(
    payload: Any,
    *,
    contract_id: str,
    source_response_id: str,
    run_id: str,
    source_contract_id: str | None = None,
) -> list[OptionQuote]:
    """Parse directed bid/ask quotes and preserve null/empty windows."""
    _validate_contract(contract_id, source_contract_id)
    records = _results(payload, "MASSIVE_QUOTES_SCHEMA_DRIFT")
    quotes: list[OptionQuote] = []
    for record in records:
        timestamp_ns = _timestamp_ns(record)
        quotes.append(
            OptionQuote(
                run_id=run_id,
                source_provider="massive",
                source_response_id=source_response_id,
                observed_at_utc=_timestamp(timestamp_ns),
                contract_id=contract_id,
                quote_time_utc=_timestamp(timestamp_ns),
                provider_timestamp_ns=timestamp_ns,
                bid=_optional_number(record, "bid_price"),
                ask=_optional_number(record, "ask_price"),
                condition_codes=_conditions(record),
            )
        )
    return quotes


def assert_directed_only(*, full_market_download: bool) -> None:
    """Reject an extraction request that would download all historical OPRA quotes."""
    if full_market_download:
        raise QualityGateError("MASSIVE_FULL_OPRA_DOWNLOAD_FORBIDDEN")


class MassiveProvider:
    """Directed Massive Options Advanced client; never a full OPRA downloader."""

    def __init__(self, api_key: str, *, transport: Any = None, max_retries: int = 3) -> None:
        """Create a bearer-authenticated Massive/Polygon REST client."""
        self._client = ProviderHTTPClient(
            base_url="https://api.polygon.io",
            api_key=api_key,
            transport=transport,
            max_retries=max_retries,
        )

    def contract_reference(self, contract_id: str) -> ProviderResponse:
        """Request reference metadata for one event-source contract."""
        return self._client.get_json(f"/v3/reference/options/contracts/{contract_id}")

    def directed_trades(
        self,
        contract_id: str,
        *,
        timestamp: str,
        cursor: str | None = None,
    ) -> ProviderResponse:
        """Request a bounded historical trade window for one contract."""
        params: dict[str, str] = {"timestamp": timestamp}
        if cursor is not None:
            params["cursor"] = cursor
        return self._client.get_json(f"/v3/trades/{contract_id}", params=params)

    def directed_quotes(
        self,
        contract_id: str,
        *,
        timestamp: str,
        cursor: str | None = None,
    ) -> ProviderResponse:
        """Request a bounded historical quote window for one contract."""
        params: dict[str, str] = {"timestamp": timestamp}
        if cursor is not None:
            params["cursor"] = cursor
        return self._client.get_json(f"/v3/quotes/{contract_id}", params=params)

    def close(self) -> None:
        """Close the provider connection pool."""
        self._client.close()


def _results(payload: Any, error_code: str) -> list[Mapping[str, Any]]:
    if payload == {}:
        return []
    if not isinstance(payload, Mapping):
        raise SchemaDriftError(error_code)
    results = payload.get("results", [])
    if not isinstance(results, list) or not all(isinstance(item, Mapping) for item in results):
        raise SchemaDriftError(error_code)
    return list(results)


def _validate_contract(contract_id: str, source_contract_id: str | None) -> None:
    if source_contract_id is not None and source_contract_id != contract_id:
        raise QualityGateError("MASSIVE_CONTRACT_MISMATCH")
    if not contract_id:
        raise QualityGateError("MASSIVE_CONTRACT_ID_REQUIRED")


def _timestamp_ns(record: Mapping[str, Any]) -> int:
    value = record.get("sip_timestamp", record.get("participant_timestamp"))
    if not isinstance(value, int) or value <= 0:
        raise SchemaDriftError("MASSIVE_TIMESTAMP_PRECISION_MISSING")
    return value


def _timestamp(value_ns: int) -> datetime:
    seconds, remainder_ns = divmod(value_ns, 1_000_000_000)
    return datetime.fromtimestamp(seconds, tz=UTC).replace(microsecond=remainder_ns // 1_000)


def _number(record: Mapping[str, Any], key: str) -> float:
    value = record.get(key)
    if not isinstance(value, int | float):
        raise SchemaDriftError(f"MASSIVE_FIELD_MISSING:{key}")
    return float(value)


def _optional_number(record: Mapping[str, Any], key: str) -> float | None:
    value = record.get(key)
    if value is None:
        return None
    if not isinstance(value, int | float):
        raise SchemaDriftError(f"MASSIVE_FIELD_INVALID:{key}")
    return float(value)


def _conditions(record: Mapping[str, Any]) -> list[str]:
    value = record.get("conditions", [])
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise SchemaDriftError("MASSIVE_CONDITION_CODES_INVALID")
    return list(value)
