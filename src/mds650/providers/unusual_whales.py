"""Unusual Whales flow-alert parser with conservative PIT semantics."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, date, datetime
from typing import Any, Literal

from mds650.contracts import UnusualOptionEvent
from mds650.errors import SchemaDriftError
from mds650.providers.base import ProviderHTTPClient, ProviderResponse

_REQUIRED_FLOW_FIELDS = frozenset(
    {
        "id",
        "ticker",
        "option_chain",
        "start_time",
        "total_premium",
        "total_size",
        "volume",
        "open_interest",
        "volume_oi_ratio",
        "type",
        "strike",
        "expiry",
        "price",
        "bid",
        "ask",
        "has_sweep",
        "has_floor",
        "has_multileg",
    }
)


class UnusualWhalesProvider:
    """Bounded Unusual Whales client for flow and explicitly directed probes."""

    def __init__(self, api_key: str, *, transport: Any = None, max_retries: int = 3) -> None:
        """Create a bearer-authenticated API client."""
        self._client = ProviderHTTPClient(
            base_url="https://api.unusualwhales.com/api",
            api_key=api_key,
            transport=transport,
            max_retries=max_retries,
        )

    def flow_alerts(
        self,
        *,
        ticker_symbol: str,
        newer_than: str,
        older_than: str,
        limit: int = 100,
    ) -> ProviderResponse:
        """Request one documented time-window flow-alert page for a ticker."""
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 200:
            raise ValueError("UW_FLOW_LIMIT_INVALID")
        params: dict[str, str | int] = {
            "ticker_symbol": ticker_symbol,
            "newer_than": newer_than,
            "older_than": older_than,
            "limit": limit,
        }
        return self._client.get_json("/option-trades/flow-alerts", params=params)

    def close(self) -> None:
        """Close the provider connection pool."""
        self._client.close()


def parse_flow_alert_payload(
    payload: Any,
    *,
    run_id: str,
    source_response_id: str,
) -> list[UnusualOptionEvent]:
    """Parse aggregate flow alerts without labeling execution intent.

    ``available_at_utc`` remains null because the bounded flow endpoint did not
    establish an independent point-in-time publication timestamp. This prevents
    the result from silently entering B1/B2 predictors.

    Raises
    ------
    SchemaDriftError
        If the response envelope or required fields change.
    ValueError
        If timestamps, expiry, or numeric values are malformed.
    """
    if not isinstance(payload, Mapping) or not isinstance(payload.get("data"), list):
        raise SchemaDriftError("UW_FLOW_SCHEMA_DRIFT")
    events: list[UnusualOptionEvent] = []
    for record in payload["data"]:
        if not isinstance(record, Mapping) or not _REQUIRED_FLOW_FIELDS.issubset(record):
            raise SchemaDriftError("UW_FLOW_SCHEMA_REQUIRED_FIELDS_MISSING")
        event_time = _epoch_ms(record["start_time"])
        expiry = _expiry(record["expiry"])
        underlying = _optional_float(record.get("underlying_price"))
        strike = _float(record["strike"])
        moneyness = None if underlying is None or underlying == 0 else strike / underlying - 1.0
        iv_start = _optional_float(record.get("iv_start"))
        iv_end = _optional_float(record.get("iv_end"))
        events.append(
            UnusualOptionEvent(
                run_id=run_id,
                source_provider="unusual_whales",
                source_response_id=source_response_id,
                observed_at_utc=event_time,
                event_id=str(record["id"]),
                asset=str(record["ticker"]),
                contract_id=str(record["option_chain"]),
                event_time_utc=event_time,
                available_at_utc=None,
                premium=_float(record["total_premium"]),
                trade_price=_float(record["price"]),
                size=_float(record["total_size"]),
                volume=_float(record["volume"]),
                open_interest=_float(record["open_interest"]),
                volume_oi_ratio=_float(record["volume_oi_ratio"]),
                option_type=_option_type(record["type"]),
                strike=strike,
                expiry=expiry,
                moneyness=moneyness,
                dte=(expiry - event_time.date()).days,
                sweep=_bool(record["has_sweep"]),
                floor=_bool(record["has_floor"]),
                multileg=_bool(record["has_multileg"]),
                execution_proxy=_execution_proxy(
                    _float(record["price"]),
                    _optional_float(record.get("bid")),
                    _optional_float(record.get("ask")),
                ),
                iv_change=None if iv_start is None or iv_end is None else iv_end - iv_start,
                iv=iv_end,
            )
        )
    return events


def _epoch_ms(value: Any) -> datetime:
    if not isinstance(value, int) or value <= 0:
        raise ValueError("UW_EVENT_TIMESTAMP_INVALID")
    return datetime.fromtimestamp(value / 1000, tz=UTC)


def _expiry(value: Any) -> date:
    if not isinstance(value, str):
        raise ValueError("UW_EXPIRY_INVALID")
    return date.fromisoformat(value)


def _float(value: Any) -> float:
    if isinstance(value, bool):
        raise SchemaDriftError("UW_NUMERIC_FIELD_INVALID")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise SchemaDriftError("UW_NUMERIC_FIELD_INVALID") from exc
    if not parsed == parsed or parsed in {float("inf"), float("-inf")}:
        raise SchemaDriftError("UW_NUMERIC_FIELD_INVALID")
    return parsed


def _optional_float(value: Any) -> float | None:
    return None if value is None else _float(value)


def _bool(value: Any) -> bool | None:
    if value is None:
        return None
    if not isinstance(value, bool):
        raise SchemaDriftError("UW_BOOLEAN_FIELD_INVALID")
    return value


def _option_type(value: Any) -> Literal["call", "put", "unknown"]:
    normalized = str(value).lower()
    if normalized == "call":
        return "call"
    if normalized == "put":
        return "put"
    return "unknown"


def _execution_proxy(price: float, bid: float | None, ask: float | None) -> str | None:
    if bid is None or ask is None or bid > ask:
        return None
    bid_distance = abs(price - bid)
    ask_distance = abs(price - ask)
    if bid_distance == ask_distance:
        return "mid_or_unknown"
    return "near_bid" if bid_distance < ask_distance else "near_ask"
