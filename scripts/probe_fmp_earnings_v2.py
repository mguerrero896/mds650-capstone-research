"""Probe symbol-specific FMP earnings timing without retaining EPS/revenue values."""
# ruff: noqa: E501

from __future__ import annotations

import json
import os
from pathlib import Path

import httpx

ASSETS = ("SPY", "QQQ", "AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "META")


def main() -> None:
    key = os.environ.get("FMP_API_KEY")
    if not key:
        raise RuntimeError("MISSING_SECRET:FMP_API_KEY")
    rows = []
    with httpx.Client(timeout=60) as client:
        for symbol in ASSETS:
            response = client.get(
                f"https://financialmodelingprep.com/api/v3/historical/earning_calendar/{symbol}",
                params={"apikey": key},
            )
            payload = response.json() if response.headers.get("content-type", "").startswith("application/json") else None
            events = payload if isinstance(payload, list) else []
            rows.append({
                "requested_symbol": symbol,
                "returned_symbols": sorted({str(x["symbol"]) for x in events if isinstance(x, dict) and x.get("symbol")}),
                "http_status": response.status_code,
                "schema_fields": sorted({k for x in events if isinstance(x, dict) for k in x}),
                "event_count": len(events),
                "sample_timing": [{"date": x.get("date"), "time": x.get("time"), "symbol": x.get("symbol")} for x in events[:3]],
                "applicability": "not_applicable" if symbol in {"SPY", "QQQ"} else "applicable",
            })
    output = {"status": "FMP_SYMBOL_SPECIFIC_EARNINGS_TIMING_PROBED", "window": ["2026-07-13", "2026-07-18"],
              "rows": rows, "actual_eps_revenue_retained": False, "secret_values_emitted": False}
    Path("artifacts/pilot_v2").mkdir(parents=True, exist_ok=True)
    Path("artifacts/pilot_v2/fmp_timestamp_validation_v2.json").write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(json.dumps({"status": output["status"], "assets": len(rows), "http_200": sum(x["http_status"] == 200 for x in rows)}))


if __name__ == "__main__":
    main()
