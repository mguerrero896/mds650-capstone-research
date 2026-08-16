"""Controlled per-origin Massive quote probe for the Pilot V2 gate."""
# ruff: noqa: E501,UP017

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import httpx


def main() -> None:
    key = os.environ.get("MASSIVE_API_KEY")
    if not key:
        raise RuntimeError("MISSING_SECRET:MASSIVE_API_KEY")
    cases = [
        ("2026-07-20T13:35:00Z", "O:AAPL260731C00335000"),
        ("2026-07-20T16:00:00Z", "O:AAPL260731C00335000"),
        ("2026-07-20T19:30:00Z", "O:AAPL260731C00335000"),
    ]
    results = []
    with httpx.Client(timeout=60) as client:
        for origin, contract in cases:
            origin_dt = datetime.fromisoformat(origin.replace("Z", "+00:00")).astimezone(timezone.utc)
            lte_ns = int(origin_dt.timestamp() * 1_000_000_000)
            params = {"timestamp.lte": str(lte_ns), "sort": "timestamp", "order": "desc", "limit": "1", "apiKey": key}
            response = client.get(f"https://api.massive.com/v3/quotes/{contract}", params=params)
            payload = response.json() if response.headers.get("content-type", "").startswith("application/json") else None
            rows = payload.get("results", []) if isinstance(payload, dict) else []
            quote = rows[0] if rows else None
            sip = quote.get("sip_timestamp") if isinstance(quote, dict) else None
            results.append({"origin": origin, "contract": contract, "http_status": response.status_code,
                            "request_params_sanitized": {k: v for k, v in params.items() if k != "apiKey"},
                            "rows": len(rows), "selected_sip_timestamp": sip,
                            "sip_le_origin": isinstance(sip, int) and sip <= lte_ns,
                            "bid_price": quote.get("bid_price") if isinstance(quote, dict) else None,
                            "ask_price": quote.get("ask_price") if isinstance(quote, dict) else None,
                            "request_id": response.headers.get("x-request-id") or response.headers.get("request_id")})
    output = {"status": "CONTROLLED_AAPL_ORIGIN_PROBE", "timestamp_unit": "nanoseconds since Unix epoch",
              "results": results, "secret_values_emitted": False}
    Path("artifacts/pilot_v2").mkdir(parents=True, exist_ok=True)
    Path("artifacts/pilot_v2/massive_controlled_origin_probe.json").write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
