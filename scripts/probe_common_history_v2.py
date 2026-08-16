"""Corrected monthly common-history probes with exact sessions and as-of contracts."""
# ruff: noqa: E501,E702,UP017

from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx

MONTHS = (date(2024, 1, 16), date(2024, 7, 16), date(2025, 1, 16), date(2025, 7, 16), date(2026, 1, 16), date(2026, 7, 16))


def secret(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"MISSING_SECRET:{name}")
    return value


def main() -> None:
    fmp_key, massive_key, uw_key = secret("FMP_API_KEY"), secret("MASSIVE_API_KEY"), secret("UNUSUALWHALES_API_KEY")
    records = []
    with httpx.Client(timeout=60, follow_redirects=True) as client:
        for month in MONTHS:
            day = month.isoformat()
            fmp = client.get("https://financialmodelingprep.com/stable/historical-chart/1min", params={"symbol": "AAPL", "from": day, "to": day, "apikey": fmp_key})
            payload = fmp.json() if fmp.headers.get("content-type", "").startswith("application/json") else None
            returned_dates = sorted({str(x.get("date", ""))[:10] for x in payload if isinstance(x, dict)}) if isinstance(payload, list) else []
            session_rows = [x for x in payload if isinstance(x, dict) and str(x.get("date", ""))[:10] == day] if isinstance(payload, list) else []
            spot = float(session_rows[0]["close"]) if session_rows else None
            fmp_ok = fmp.status_code == 200 and bool(session_rows) and returned_dates == [day]
            records.append({"month": day, "component": "FMP", "session_available": fmp_ok, "http_status": fmp.status_code,
                            "requested_date": day, "returned_dates": returned_dates, "rows_returned": len(payload) if isinstance(payload, list) else 0,
                            "rows_session": len(session_rows), "spot_sample": spot, "provider_over_return": returned_dates != [day]})

            ref = client.get("https://api.massive.com/v3/reference/options/contracts", params={
                "underlying_ticker": "AAPL", "as_of": day, "expired": "false", "expiration_date.gte": (month + timedelta(days=30)).isoformat(),
                "expiration_date.lte": (month + timedelta(days=60)).isoformat(), "limit": "1000", "apiKey": massive_key})
            ref_payload = ref.json() if ref.headers.get("content-type", "").startswith("application/json") else None
            candidates = ref_payload.get("results", []) if isinstance(ref_payload, dict) else []
            contract = None
            if spot and candidates:
                candidates = [x for x in candidates if x.get("strike_price") is not None and x.get("expiration_date")]
                if candidates:
                    contract = min(candidates, key=lambda x: abs(float(x["strike_price"]) - spot)).get("ticker")
            origin = datetime.combine(month, datetime.min.time(), tzinfo=timezone.utc).replace(hour=14, minute=35)
            lte_ns = int(origin.timestamp() * 1_000_000_000)
            quote_status = None; quote_rows = 0; sip = None; bid = None; ask = None
            if contract:
                quote = client.get(f"https://api.massive.com/v3/quotes/{contract}", params={"timestamp.lte": str(lte_ns), "sort": "timestamp", "order": "desc", "limit": "1", "apiKey": massive_key})
                quote_status = quote.status_code
                q_payload = quote.json() if quote.headers.get("content-type", "").startswith("application/json") else None
                q_rows = q_payload.get("results", []) if isinstance(q_payload, dict) else []
                quote_rows = len(q_rows)
                if q_rows:
                    sip, bid, ask = q_rows[0].get("sip_timestamp"), q_rows[0].get("bid_price"), q_rows[0].get("ask_price")
            valid_quote = bool(isinstance(sip, int) and sip <= lte_ns and bid is not None and ask is not None and bid > 0 and ask > bid)
            records.append({"month": day, "component": "Massive", "historical_contract_resolved": bool(contract), "contract": contract,
                            "reference_http_status": ref.status_code, "quote_http_status": quote_status, "quote_rows": quote_rows,
                            "origin_utc": origin.isoformat(), "timestamp_lte_ns": lte_ns, "selected_sip_timestamp": sip,
                            "valid_quote_before_origin": valid_quote})

            uw = client.get(f"https://api.unusualwhales.com/api/option-trades/full-tape/{day}", headers={"Authorization": f"Bearer {uw_key}", "Accept": "application/json", "Range": "bytes=0-1023"})
            content_range = uw.headers.get("content-range", "")
            total_bytes = int(content_range.rsplit("/", 1)[1]) if "/" in content_range and content_range.rsplit("/", 1)[1].isdigit() else None
            records.append({"month": day, "component": "Unusual Whales", "full_tape_file_available": uw.status_code in {200, 206} and total_bytes is not None,
                            "http_status": uw.status_code, "bytes_total": total_bytes, "bytes_sampled": len(uw.content), "pit_claim": False})

    by_month = {m.isoformat(): [x for x in records if x["month"] == m.isoformat()] for m in MONTHS}
    month_results = []
    for day, items in by_month.items():
        fmp_record = next(x for x in items if x["component"] == "FMP")
        uw_record = next(x for x in items if x["component"] == "Unusual Whales")
        massive_record = next(x for x in items if x["component"] == "Massive")
        month_results.append({"month": day, "fmp_session_available": fmp_record["session_available"], "uw_full_tape_file_available": uw_record["full_tape_file_available"],
                              "massive_historical_contract_resolved": massive_record["historical_contract_resolved"], "massive_valid_quote_before_origin": massive_record["valid_quote_before_origin"],
                              "common_component_pass": all([fmp_record["session_available"], uw_record["full_tape_file_available"], massive_record["historical_contract_resolved"], massive_record["valid_quote_before_origin"]])})
    output = {"status": "COMMON_HISTORY_V2_PROBED", "probe_type": "exact_session_plus_as_of_contract_plus_timestamp_lte_quote", "months": month_results,
              "common_months": [x["month"] for x in month_results if x["common_component_pass"]], "full_history_downloaded": False, "secret_values_emitted": False,
              "records": records}
    Path("artifacts/api_audit/common_history_probe_v2.json").write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(json.dumps({"status": output["status"], "common_months": output["common_months"]}))


if __name__ == "__main__":
    main()
