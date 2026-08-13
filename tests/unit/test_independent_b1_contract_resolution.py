"""Offline contract-resolution checks for the independent Massive route."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from typing import Any

import httpx
import polars as pl
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import build_independent_b1 as b1_script  # noqa: E402
import run_b1_closure as b1  # noqa: E402


def test_fmp_historical_ranges_are_chunked_without_truncation() -> None:
    """Broad FMP requests are split so the provider's range cap is observable."""
    calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        start = request.url.params["from"]
        end = request.url.params["to"]
        calls.append((start, end))
        return httpx.Response(200, json=[{"date": start, "month3": 4.0}], request=request)

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport) as client:
        rows = b1_script._fmp_date_range_rows(
            client,
            "https://example.test/treasury-rates",
            "secret",
            date(2024, 1, 1),
            date(2024, 3, 15),
            {},
            "TEST_FMP",
        )

    assert calls == [("2024-01-01", "2024-03-01"), ("2024-03-02", "2024-03-15")]
    assert len(rows) == 2


def test_fmp_historical_ranges_deduplicate_provider_over_return() -> None:
    """Repeated rows from an endpoint that ignores date bounds are retained once."""
    repeated = {
        "symbol": "MSFT",
        "date": "2025-02-20",
        "declarationDate": "2024-12-04",
        "adjDividend": 0.83,
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[repeated], request=request)

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport) as client:
        rows = b1_script._fmp_date_range_rows(
            client,
            "https://example.test/dividends",
            "secret",
            date(2024, 1, 1),
            date(2024, 3, 15),
            {"symbol": "MSFT"},
            "TEST_FMP_DIVIDENDS",
        )

    assert rows == [repeated]


def test_dividend_yield_uses_only_prior_declaration_dates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A past ex-date cannot reveal a dividend declared after the session."""

    def fake_rows(
        _client: httpx.Client,
        _endpoint: str,
        _key: str,
        _start: date,
        _end: date,
        _base_params: dict[str, str],
        label: str,
    ) -> list[dict[str, Any]]:
        if label == "FMP_TREASURY":
            return [{"date": "2025-01-02", "month3": 4.0}]
        return [
            {
                "date": "2025-01-03",
                "declarationDate": "2025-01-07",
                "adjDividend": 1.0,
            }
        ]

    monkeypatch.setattr(b1_script, "ASSETS", ("AAPL",))
    monkeypatch.setattr(b1_script, "_fmp_date_range_rows", fake_rows)
    spots = pl.DataFrame({"asset": ["AAPL"], "session_date": ["2025-01-06"], "spot": [100.0]})

    with httpx.Client() as client:
        _, yields, labels = b1_script._rates_and_dividends(
            client, "secret", spots, "2025-01-06", "2025-01-06"
        )

    assert yields[("AAPL", "2025-01-06")] == 0.0
    assert labels[("AAPL", "2025-01-06")] == "NO_PRE_ORIGIN_DIVIDEND_Q_ZERO"


def test_contract_day_cache_loader_reads_each_contract_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One asset-day reuses each quote cache across all forecast origins."""
    calls: list[str] = []

    def fake_json(path: Path) -> dict[str, Any]:
        calls.append(str(path))
        return {"cache_path": str(path)}

    monkeypatch.setattr(b1_script, "_json", fake_json)
    contracts = [
        {"contract": "O:AAPL250415C00100000"},
        {"contract": "O:AAPL250415P00100000"},
    ]
    cache_paths = {
        ("AAPL", "2025-03-03", row["contract"]): f"D:/cache/{index}.json"
        for index, row in enumerate(contracts)
    }

    loaded = b1_script._load_contract_day_caches("AAPL", "2025-03-03", contracts, cache_paths)

    assert calls == [str(Path("D:/cache/0.json")), str(Path("D:/cache/1.json"))]
    assert sorted(loaded) == sorted(row["contract"] for row in contracts)


def test_historical_contract_resolution_records_expired_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An empty expired=true route must be followed by explicit expired=false."""
    calls: list[str] = []

    def fake_request(
        _client: httpx.Client,
        _endpoint: str,
        params: dict[str, str],
        _key: str,
    ) -> tuple[int, dict[str, Any], str]:
        expired = str(params.get("expired"))
        calls.append(expired)
        if expired == "true":
            return 200, {"results": []}, "request-expired-true"
        return (
            200,
            {
                "results": [
                    {
                        "underlying_ticker": "AAPL",
                        "contract_type": "call",
                        "expiration_date": "2025-04-15",
                        "strike_price": 100.0,
                        "ticker": "O:AAPL250415C00100000",
                    }
                ]
            },
            "request-expired-false",
        )

    monkeypatch.setattr(b1, "_request_json", fake_request)
    with httpx.Client() as client:
        rows = b1_script._resolve_medium(client, "secret", "AAPL", "2025-03-03", 100.0)

    assert calls == ["true", "false"]
    assert len(rows) == 1
    assert rows[0]["expired_parameter_behavior"] == "EXPIRED_TRUE_EMPTY_FALLBACK_FALSE"
    assert [item["expired"] for item in rows[0]["reference_attempts"]] == ["true", "false"]
