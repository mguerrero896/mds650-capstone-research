from __future__ import annotations

import httpx
import pytest

from mds650.errors import AuthenticationError
from mds650.providers.massive import MassiveProvider


def test_directed_quotes_uses_massive_query_auth_and_as_of_selection_params() -> None:
    observed: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        observed.append(request)
        return httpx.Response(200, json={"results": []}, request=request)

    provider = MassiveProvider(
        "synthetic-query-key",
        transport=httpx.MockTransport(handler),
        max_retries=1,
    )
    try:
        response = provider.directed_quotes(
            "O:AAPL260821C00200000",
            forecast_origin_ns=1_773_000_000_000_000_000,
        )
    finally:
        provider.close()

    assert response.status_code == 200
    assert len(observed) == 1
    request = observed[0]
    assert str(request.url.copy_with(query=None)) == "https://api.massive.com/v3/quotes/O:AAPL260821C00200000"
    assert dict(request.url.params) == {
        "timestamp.lte": "1773000000000000000",
        "sort": "timestamp",
        "order": "desc",
        "limit": "1",
        "apiKey": "synthetic-query-key",
    }
    assert request.headers.get("authorization") is None
    assert response.request_url == (
        "https://api.massive.com/v3/quotes/O:AAPL260821C00200000?"
        "timestamp.lte=1773000000000000000&sort=timestamp&order=desc&limit=1"
    )
    assert "synthetic-query-key" not in response.request_url


@pytest.mark.parametrize(
    "forecast_origin_ns",
    [
        True,
        "2026-03-09T13:30:00Z",
        0,
        -1,
        999_999_999_999_999_999,
        10_000_000_000_000_000_000,
    ],
)
def test_directed_quotes_rejects_invalid_forecast_origin_ns_without_transport(
    forecast_origin_ns: object,
) -> None:
    def unexpected_handler(_: httpx.Request) -> httpx.Response:
        raise AssertionError("transport called")

    provider = MassiveProvider(
        "synthetic-query-key",
        transport=httpx.MockTransport(unexpected_handler),
    )
    try:
        with pytest.raises(ValueError, match="MASSIVE_CONTRACT_ID_REQUIRED"):
            provider.directed_quotes("", forecast_origin_ns=1_773_000_000_000_000_000)
        with pytest.raises(ValueError, match="MASSIVE_FORECAST_ORIGIN_NS_REQUIRED"):
            provider.directed_quotes(
                "O:AAPL260821C00200000",
                forecast_origin_ns=forecast_origin_ns,
            )
        with pytest.raises(TypeError, match="cursor"):
            provider.directed_quotes(
                "O:AAPL260821C00200000",
                forecast_origin_ns=1_773_000_000_000_000_000,
                cursor="legacy-cursor",
            )
    finally:
        provider.close()


def test_massive_authentication_error_does_not_emit_query_key() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, request=request)

    provider = MassiveProvider(
        "synthetic-query-key",
        transport=httpx.MockTransport(handler),
        max_retries=1,
    )
    try:
        with pytest.raises(AuthenticationError) as error:
            provider.directed_quotes(
                "O:AAPL260821C00200000",
                forecast_origin_ns=1_773_000_000_000_000_000,
            )
    finally:
        provider.close()

    assert str(error.value) == "PROVIDER_AUTHENTICATION_FAILED"
    assert "synthetic-query-key" not in str(error.value)
