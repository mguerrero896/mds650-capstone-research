"""Offline contract-resolution checks for the independent Massive route."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import build_independent_b1 as b1_script  # noqa: E402
import run_b1_closure as b1  # noqa: E402


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
