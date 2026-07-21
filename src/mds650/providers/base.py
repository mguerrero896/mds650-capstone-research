"""Shared pagination primitives for provider adapters."""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import httpx

from mds650.errors import (
    AuthenticationError,
    ProviderBlockedError,
    QualityGateError,
    SchemaDriftError,
)


@dataclass(frozen=True, slots=True)
class Page:
    """One bounded provider page and its opaque continuation cursor."""

    records: Sequence[Mapping[str, Any]]
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class ProviderResponse:
    """Sanitized result of one bounded HTTP request."""

    status_code: int
    payload: Any
    request_url: str
    attempts: int
    rate_limit_observations: dict[str, str]


class ProviderHTTPClient:
    """Small retrying HTTP client that keeps provider keys out of URLs."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        max_retries: int = 3,
        backoff_seconds: float = 0.5,
        timeout_seconds: float = 20.0,
        api_key_header: str = "Authorization",
        api_key_prefix: str = "Bearer ",
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        """Create a bounded client using an Authorization header.

        Parameters
        ----------
        base_url:
            Provider origin without credential query parameters.
        api_key:
            Secret retained only in the in-memory request header.
        max_retries:
            Maximum total attempts for one request, including the first.
        backoff_seconds:
            Base exponential delay for retryable responses.
        timeout_seconds:
            Per-request timeout.
        api_key_header, api_key_prefix:
            Header name and prefix used for provider authentication.
        transport:
            Optional test transport; production defaults to httpx networking.

        Raises
        ------
        ValueError
            If configuration is invalid or the base URL contains credentials.
        """
        parsed = httpx.URL(base_url)
        if parsed.params or not api_key or max_retries <= 0 or backoff_seconds < 0:
            raise ValueError("PROVIDER_CLIENT_CONFIGURATION_INVALID")
        self._client = httpx.Client(
            base_url=base_url,
            timeout=timeout_seconds,
            transport=transport,
        )
        self._api_key = api_key
        self._max_retries = max_retries
        self._backoff_seconds = backoff_seconds
        self._api_key_header = api_key_header
        self._api_key_prefix = api_key_prefix

    def close(self) -> None:
        """Close the underlying HTTP connection pool."""
        self._client.close()

    def get_json(
        self,
        path: str,
        *,
        params: Mapping[str, str | int] | None = None,
    ) -> ProviderResponse:
        """GET one bounded JSON response with retry and sanitized observations.

        Parameters
        ----------
        path:
            Relative provider endpoint path.
        params:
            Non-secret query parameters.

        Returns
        -------
        ProviderResponse
            Payload, status, URL without credentials, attempts, and rate headers.

        Raises
        ------
        AuthenticationError
            On a final 401/403 response.
        ProviderBlockedError
            On a final non-success HTTP response or transport error.
        SchemaDriftError
            If a successful response is not valid JSON.
        """
        headers = {self._api_key_header: f"{self._api_key_prefix}{self._api_key}"}
        for attempt in range(1, self._max_retries + 1):
            try:
                response = self._client.get(path, params=params, headers=headers)
            except httpx.HTTPError as exc:
                raise ProviderBlockedError("PROVIDER_NETWORK_FAILURE") from exc
            if 200 <= response.status_code < 300:
                try:
                    payload = response.json()
                except ValueError as exc:
                    raise SchemaDriftError("PROVIDER_RESPONSE_NOT_JSON") from exc
                return ProviderResponse(
                    status_code=response.status_code,
                    payload=payload,
                    request_url=str(response.request.url),
                    attempts=attempt,
                    rate_limit_observations=_rate_headers(response.headers),
                )
            if response.status_code in {401, 403}:
                raise AuthenticationError("PROVIDER_AUTHENTICATION_FAILED")
            if (
                (response.status_code == 429 or response.status_code >= 500)
                and attempt < self._max_retries
            ):
                retry_after = _retry_after(response.headers)
                delay = (
                    retry_after
                    if retry_after is not None
                    else self._backoff_seconds * 2 ** (attempt - 1)
                )
                time.sleep(delay)
                continue
            raise ProviderBlockedError(f"PROVIDER_HTTP_{response.status_code}")
        raise ProviderBlockedError("PROVIDER_RETRY_EXHAUSTED")


def _retry_after(headers: httpx.Headers) -> float | None:
    value = headers.get("retry-after")
    if value is None:
        return None
    try:
        return max(float(value), 0.0)
    except ValueError:
        return None


def _rate_headers(headers: httpx.Headers) -> dict[str, str]:
    return {
        key: value
        for key, value in headers.items()
        if key.lower() == "retry-after" or key.lower().startswith("x-ratelimit")
    }


def schema_fingerprint(records: Sequence[Mapping[str, Any]]) -> str:
    """Hash sorted field names and Python value types from provider records.

    Parameters
    ----------
    records:
        Bounded response records. Only schema metadata is hashed; values are not.

    Returns
    -------
    str
        Stable 64-character SHA-256 fingerprint for contract drift checks.
    """
    fields: dict[str, set[str]] = {}
    for record in records:
        for name, value in record.items():
            fields.setdefault(name, set()).add(type(value).__name__)
    canonical = {
        name: sorted(types)
        for name, types in sorted(fields.items())
    }
    return hashlib.sha256(
        json.dumps(canonical, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()


def paginate(
    fetch_page: Callable[[str | None], Page],
    *,
    max_pages: int = 100,
) -> list[Mapping[str, Any]]:
    """Collect pages while failing closed on loops or unbounded extraction.

    Parameters
    ----------
    fetch_page:
        Function receiving the previous opaque cursor, or ``None`` initially.
    max_pages:
        Positive hard cap on requests in one bounded extraction.

    Returns
    -------
    list[Mapping[str, Any]]
        Concatenated records in provider order.

    Raises
    ------
    QualityGateError
        If a cursor repeats or the page limit is reached before completion.
    ValueError
        If ``max_pages`` is not positive.
    """
    if max_pages <= 0:
        raise ValueError("PAGINATION_CONFIGURATION_INVALID")
    records: list[Mapping[str, Any]] = []
    cursor: str | None = None
    seen_cursors: set[str] = set()
    for page_number in range(max_pages):
        page = fetch_page(cursor)
        records.extend(page.records)
        if page.next_cursor is None:
            return records
        if page.next_cursor in seen_cursors:
            raise QualityGateError("PAGINATION_CURSOR_REPEATED")
        seen_cursors.add(page.next_cursor)
        cursor = page.next_cursor
        if page_number == max_pages - 1:
            raise QualityGateError("PAGINATION_PAGE_LIMIT_EXCEEDED")
    raise QualityGateError("PAGINATION_PAGE_LIMIT_EXCEEDED")
