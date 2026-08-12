from __future__ import annotations

import httpx
import pytest

from mds650.providers.unusual_whales import UnusualWhalesProvider


def test_flow_alerts_uses_documented_time_window_params_and_sanitized_url() -> None:
    observed: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        observed.append(request)
        return httpx.Response(200, json={"data": []}, request=request)

    provider = UnusualWhalesProvider(
        "test-api-key-not-for-url",
        transport=httpx.MockTransport(handler),
        max_retries=1,
    )
    try:
        response = provider.flow_alerts(
            ticker_symbol="AAPL",
            newer_than="2026-03-06",
            older_than="2026-03-09",
            limit=100,
        )
    finally:
        provider.close()

    assert response.status_code == 200
    assert len(observed) == 1
    request = observed[0]
    assert request.url.path == "/api/option-trades/flow-alerts"
    assert dict(request.url.params) == {
        "ticker_symbol": "AAPL",
        "newer_than": "2026-03-06",
        "older_than": "2026-03-09",
        "limit": "100",
    }
    assert request.headers["authorization"] == "Bearer test-api-key-not-for-url"
    assert "test-api-key-not-for-url" not in response.request_url


def test_flow_alerts_rejects_cursor_and_limit_above_documented_maximum() -> None:
    provider = UnusualWhalesProvider("test-api-key", transport=httpx.MockTransport(lambda _: None))
    try:
        with pytest.raises(TypeError, match="cursor"):
            provider.flow_alerts(
                ticker_symbol="AAPL",
                newer_than="2026-03-06",
                older_than="2026-03-09",
                limit=100,
                cursor="opaque-cursor",
            )
        with pytest.raises(ValueError, match="UW_FLOW_LIMIT_INVALID"):
            provider.flow_alerts(
                ticker_symbol="AAPL",
                newer_than="2026-03-06",
                older_than="2026-03-09",
                limit=201,
            )
    finally:
        provider.close()
