from __future__ import annotations

import httpx
import pytest

from mds650.errors import AuthenticationError, ProviderBlockedError
from mds650.providers.base import ProviderHTTPClient, schema_fingerprint


def test_provider_client_retries_rate_limit_without_putting_key_in_url() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert request.url.params.get("api_key") is None
        assert request.headers["Authorization"] == "Bearer test-secret"
        if calls == 1:
            return httpx.Response(429, headers={"Retry-After": "0"}, request=request)
        return httpx.Response(200, json={"data": [1]}, request=request)

    client = ProviderHTTPClient(
        base_url="https://provider.test",
        api_key="test-secret",
        max_retries=2,
        backoff_seconds=0,
        transport=httpx.MockTransport(handler),
    )

    result = client.get_json("/bounded")

    assert result.payload == {"data": [1]}
    assert result.attempts == 2


def test_provider_client_fails_closed_on_authentication() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, request=request)

    client = ProviderHTTPClient(
        base_url="https://provider.test",
        api_key="test-secret",
        max_retries=1,
        backoff_seconds=0,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(AuthenticationError, match="PROVIDER_AUTHENTICATION_FAILED"):
        client.get_json("/bounded")


def test_schema_fingerprint_changes_when_returned_fields_change() -> None:
    first = schema_fingerprint([{"date": "2026-07-16", "close": 1.0}])
    second = schema_fingerprint([{"date": "2026-07-16", "close": 1.0, "volume": 2}])

    assert first != second
    assert len(first) == 64


def test_provider_client_retries_transport_errors_with_backoff() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise httpx.ConnectTimeout("simulated timeout", request=request)
        return httpx.Response(200, json={"data": [1]}, request=request)

    client = ProviderHTTPClient(
        base_url="https://provider.test",
        api_key="test-secret",
        max_retries=3,
        backoff_seconds=0,
        transport=httpx.MockTransport(handler),
    )

    result = client.get_json("/bounded")

    assert result.attempts == 3
    assert calls == 3


def test_provider_client_transport_exhaustion_keeps_last_cause() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("simulated reset", request=request)

    client = ProviderHTTPClient(
        base_url="https://provider.test",
        api_key="test-secret",
        max_retries=2,
        backoff_seconds=0,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(ProviderBlockedError, match="PROVIDER_NETWORK_FAILURE") as excinfo:
        client.get_json("/bounded")
    assert isinstance(excinfo.value.__cause__, httpx.ConnectError)
