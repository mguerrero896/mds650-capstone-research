"""FMP response parsers for bounded OHLCV and earnings probes."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, date, datetime, time
from typing import Any

from mds650.contracts import CorporateEvent, UnderlyingBar
from mds650.errors import SchemaDriftError
from mds650.normalize import normalize_underlying_bars
from mds650.providers.base import ProviderHTTPClient, ProviderResponse

_EARNINGS_FIELDS = frozenset(
    {
        "symbol",
        "date",
        "epsActual",
        "epsEstimated",
        "revenueActual",
        "revenueEstimated",
        "lastUpdated",
    }
)


class FMPProvider:
    """Bounded FMP Ultimate client for minute bars and earnings probes."""

    def __init__(
        self,
        api_key: str,
        *,
        transport: Any = None,
        max_retries: int = 3,
    ) -> None:
        """Create an FMP client using the documented ``apikey`` header."""
        self._client = ProviderHTTPClient(
            base_url="https://financialmodelingprep.com/stable",
            api_key=api_key,
            api_key_header="apikey",
            api_key_prefix="",
            transport=transport,
            max_retries=max_retries,
        )

    def minute_bars(self, symbol: str, *, from_date: str, to_date: str) -> ProviderResponse:
        """Request one-minute bars for one symbol and bounded date window."""
        return self._client.get_json(
            "/historical-chart/1min",
            params={"symbol": symbol, "from": from_date, "to": to_date},
        )

    def earnings(self, symbol: str) -> ProviderResponse:
        """Request structured earnings observations for one symbol."""
        return self._client.get_json("/earnings", params={"symbol": symbol})

    def close(self) -> None:
        """Close the provider connection pool."""
        self._client.close()


def parse_minute_payload(
    payload: Any,
    *,
    asset: str,
    run_id: str,
    source_response_id: str,
    source_timezone: str | None,
) -> list[UnderlyingBar]:
    """Parse an observed FMP one-minute array through the canonical normalizer.

    Raises
    ------
    SchemaDriftError
        If the payload is not an array of mappings.
    """
    if not isinstance(payload, list) or not all(isinstance(row, Mapping) for row in payload):
        raise SchemaDriftError("FMP_UNDERLYING_SCHEMA_DRIFT")
    return normalize_underlying_bars(
        payload,
        asset=asset,
        run_id=run_id,
        source_response_id=source_response_id,
        source_timezone=source_timezone,
    )


def parse_earnings_payload(
    payload: Any,
    *,
    run_id: str,
    source_response_id: str,
) -> list[CorporateEvent]:
    """Parse structured earnings while preserving date-only timestamp quality.

    The observed FMP response contains a date and update field but no verified
    release timestamp. The resulting event is therefore explicitly ``date_only``
    and cannot enter a PIT earnings join.

    Raises
    ------
    SchemaDriftError
        If the response does not match the audited field set.
    ValueError
        If an earnings date is not ISO formatted.
    """
    if not isinstance(payload, list) or not all(isinstance(row, Mapping) for row in payload):
        raise SchemaDriftError("FMP_EARNINGS_SCHEMA_DRIFT")
    events: list[CorporateEvent] = []
    for row in payload:
        if set(row) != _EARNINGS_FIELDS:
            raise SchemaDriftError("FMP_EARNINGS_SCHEMA_DRIFT")
        raw_date = row.get("date")
        if not isinstance(raw_date, str):
            raise SchemaDriftError("FMP_EARNINGS_DATE_MISSING")
        event_date = date.fromisoformat(raw_date)
        observed_anchor = datetime.combine(event_date, time.min, tzinfo=UTC)
        symbol = row.get("symbol")
        if not isinstance(symbol, str) or not symbol:
            raise SchemaDriftError("FMP_EARNINGS_SYMBOL_MISSING")
        events.append(
            CorporateEvent(
                run_id=run_id,
                source_provider="fmp",
                source_response_id=source_response_id,
                observed_at_utc=observed_anchor,
                asset=symbol,
                event_type="earnings",
                event_date_ny=event_date,
                timestamp_quality="date_only",
            )
        )
    return events
