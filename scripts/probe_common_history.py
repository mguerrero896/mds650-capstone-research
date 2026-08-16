"""Run small monthly endpoint probes; never download historical provider files."""

# ruff: noqa: E501

from __future__ import annotations

import hashlib
import json
import os
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import httpx

MONTHS = (date(2024, 1, 16), date(2024, 7, 16), date(2025, 1, 16), date(2025, 7, 16), date(2026, 1, 16), date(2026, 7, 16))
OUT = Path("artifacts/api_audit/common_history_probe.json")


def key(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"MISSING_SECRET:{name}")
    return value


def main() -> None:
    fmp_key, massive_key, uw_key = key("FMP_API_KEY"), key("MASSIVE_API_KEY"), key("UNUSUALWHALES_API_KEY")
    records: list[dict[str, Any]] = []
    with httpx.Client(timeout=60, follow_redirects=True) as client:
        for month in MONTHS:
            end = month + timedelta(days=1)
            fmp_params = {"symbol": "AAPL", "from": month.isoformat(), "to": end.isoformat(), "apikey": fmp_key}
            response = client.get("https://financialmodelingprep.com/stable/historical-chart/1min", params=fmp_params)
            try:
                payload = response.json()
            except ValueError:
                payload = None
            fmp_rows = payload if isinstance(payload, list) else []
            records.append({"provider": "FMP", "component": "underlying_1min", "date": month.isoformat(),
                            "endpoint": "/stable/historical-chart/1min", "http_status": response.status_code,
                            "rows": len(fmp_rows), "timestamp_sample_raw": fmp_rows[0].get("date") if fmp_rows else None,
                            "request_id": hashlib.sha256(f"fmp-{month}".encode()).hexdigest()[:16]})

            ref = client.get("https://api.massive.com/v3/reference/options/contracts", params={
                "underlying_ticker": "AAPL", "as_of": month.isoformat(), "expired": "true", "limit": "1", "apiKey": massive_key})
            try:
                ref_payload = ref.json()
            except ValueError:
                ref_payload = None
            result = ref_payload.get("results", []) if isinstance(ref_payload, dict) else []
            contract = result[0].get("ticker") if result else None
            quote_status = None
            quote_rows = 0
            if contract:
                quote = client.get(f"https://api.massive.com/v3/quotes/{contract}", params={
                    "timestamp.gte": f"{month.isoformat()}T00:00:00Z", "timestamp.lt": f"{end.isoformat()}T00:00:00Z", "limit": "1", "apiKey": massive_key})
                quote_status = quote.status_code
                try:
                    q_payload = quote.json()
                except ValueError:
                    q_payload = None
                quote_rows = len(q_payload.get("results", [])) if isinstance(q_payload, dict) and isinstance(q_payload.get("results"), list) else 0
            records.append({"provider": "Massive", "component": "contract_quotes", "date": month.isoformat(),
                            "endpoint": "/v3/reference/options/contracts + /v3/quotes/{contract}", "http_status": quote_status or ref.status_code,
                            "reference_http_status": ref.status_code, "quote_http_status": quote_status, "rows": quote_rows,
                            "contract_present": bool(contract), "request_id": hashlib.sha256(f"massive-{month}".encode()).hexdigest()[:16]})

            uw = client.get(f"https://api.unusualwhales.com/api/option-trades/full-tape/{month.isoformat()}",
                            headers={"Authorization": f"Bearer {uw_key}", "Accept": "application/json", "Range": "bytes=0-1023"})
            records.append({"provider": "Unusual Whales", "component": "full_tape", "date": month.isoformat(),
                            "endpoint": f"/api/option-trades/full-tape/{month.isoformat()}", "http_status": uw.status_code,
                            "content_type": uw.headers.get("content-type"), "content_range": uw.headers.get("content-range"),
                            "bytes_sampled": len(uw.content), "request_id": hashlib.sha256(f"uw-{month}".encode()).hexdigest()[:16]})
    observed = sorted({x["date"] for x in records if x["provider"] == "FMP" and x["http_status"] == 200 and x["rows"] > 0}
                      & {x["date"] for x in records if x["provider"] == "Massive" and x["quote_http_status"] == 200 and x["rows"] > 0}
                      & {x["date"] for x in records if x["provider"] == "Unusual Whales" and x["http_status"] == 200})
    output = {"status": "COMMON_HISTORY_NOT_ESTABLISHED", "probe_type": "monthly_small_endpoint_probes_only",
              "months": [x.isoformat() for x in MONTHS], "observed_intersection_dates": observed,
              "records": records, "full_history_downloaded": False, "secret_values_emitted": False}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(json.dumps({"status": output["status"], "observed_intersection_dates": observed, "records": len(records)}))


if __name__ == "__main__":
    main()
