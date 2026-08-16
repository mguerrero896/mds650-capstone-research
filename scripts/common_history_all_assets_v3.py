"""Probe sampled common history for all eight candidate assets.

The probe is intentionally sparse (six dates) and never downloads Full Tape
content. A successful Range response proves file existence/size only, not PIT
availability.
"""
# ruff: noqa: E501,UP017,I001

from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ("SPY", "QQQ", "AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "META")
DATES = (date(2024, 1, 16), date(2024, 7, 16), date(2025, 1, 16), date(2025, 7, 16), date(2026, 1, 16), date(2026, 7, 16))
NY = ZoneInfo("America/New_York")


def secret(name: str) -> str:
    """Return a required secret without exposing its value."""
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"MISSING_SECRET:{name}")
    return value


def main() -> None:
    """Run the 48 asset-date probes and write a sanitized JSON artifact."""
    fmp_key, massive_key, uw_key = secret("FMP_API_KEY"), secret("MASSIVE_API_KEY"), secret("UNUSUALWHALES_API_KEY")
    records: list[dict[str, object]] = []
    uw_by_date: dict[str, dict[str, object]] = {}
    with httpx.Client(timeout=90, follow_redirects=True) as client:
        for day in DATES:
            day_text = day.isoformat()
            uw = client.get(
                f"https://api.unusualwhales.com/api/option-trades/full-tape/{day_text}",
                headers={"Authorization": f"Bearer {uw_key}", "Accept": "application/json", "Range": "bytes=0-1023"},
            )
            content_range = uw.headers.get("content-range", "")
            total_bytes = int(content_range.rsplit("/", 1)[1]) if "/" in content_range and content_range.rsplit("/", 1)[1].isdigit() else None
            uw_by_date[day_text] = {"http_status": uw.status_code, "bytes_total": total_bytes, "bytes_sampled": len(uw.content), "full_tape_file_available": uw.status_code in {200, 206} and total_bytes is not None, "pit_claim": False}

        for asset in ASSETS:
            for day in DATES:
                day_text = day.isoformat()
                fmp = client.get("https://financialmodelingprep.com/stable/historical-chart/1min", params={"symbol": asset, "from": day_text, "to": day_text, "apikey": fmp_key})
                payload = fmp.json() if fmp.headers.get("content-type", "").startswith("application/json") else None
                returned_dates = sorted({str(row.get("date", ""))[:10] for row in payload if isinstance(row, dict)}) if isinstance(payload, list) else []
                session_rows = [row for row in payload if isinstance(row, dict) and str(row.get("date", ""))[:10] == day_text] if isinstance(payload, list) else []
                spot = float(session_rows[0]["close"]) if session_rows and session_rows[0].get("close") is not None else None
                fmp_pass = fmp.status_code == 200 and bool(session_rows) and returned_dates == [day_text]
                origin_local = datetime.combine(day, datetime.min.time(), tzinfo=NY).replace(hour=9, minute=35)
                origin_utc = origin_local.astimezone(timezone.utc)
                origin_ns = int(origin_utc.timestamp() * 1_000_000_000)
                # The entitlement returns historical contracts through the
                # as_of filter; expired=true is not accepted for this route and
                # would silently return an empty result, so preserve the
                # observed false setting and record the HTTP/status evidence.
                ref = client.get("https://api.massive.com/v3/reference/options/contracts", params={"underlying_ticker": asset, "as_of": day_text, "expired": "false", "expiration_date.gte": (day + timedelta(days=30)).isoformat(), "expiration_date.lte": (day + timedelta(days=60)).isoformat(), "limit": "1000", "apiKey": massive_key})
                ref_payload = ref.json() if ref.headers.get("content-type", "").startswith("application/json") else {}
                candidates = [row for row in ref_payload.get("results", []) if isinstance(row, dict) and row.get("underlying_ticker") == asset] if isinstance(ref_payload, dict) else []
                contract_row = None
                if spot is not None:
                    viable = [row for row in candidates if row.get("strike_price") is not None and row.get("expiration_date")]
                    if viable:
                        contract_row = min(viable, key=lambda row: abs(float(row["strike_price"]) - spot))
                contract = contract_row.get("ticker") if contract_row else None
                quote_status: int | None = None
                quote_rows = 0
                sip: int | None = None
                bid: float | None = None
                ask: float | None = None
                if contract:
                    quote = client.get(f"https://api.massive.com/v3/quotes/{contract}", params={"timestamp.lte": str(origin_ns), "sort": "timestamp", "order": "desc", "limit": "1", "apiKey": massive_key})
                    quote_status = quote.status_code
                    q_payload = quote.json() if quote.headers.get("content-type", "").startswith("application/json") else {}
                    q_rows = q_payload.get("results", []) if isinstance(q_payload, dict) else []
                    quote_rows = len(q_rows)
                    if q_rows:
                        sip, bid, ask = q_rows[0].get("sip_timestamp"), q_rows[0].get("bid_price"), q_rows[0].get("ask_price")
                quote_pass = isinstance(sip, int) and sip <= origin_ns and isinstance(bid, (int, float)) and isinstance(ask, (int, float)) and bid > 0 and ask > bid
                uw_record = uw_by_date[day_text]
                common = bool(fmp_pass and uw_record["full_tape_file_available"] and bool(contract_row) and quote_pass)
                blocker = None if common else ";".join(name for name, ok in (("fmp", fmp_pass), ("uw_file", bool(uw_record["full_tape_file_available"])), ("massive_contract", bool(contract_row)), ("massive_quote", quote_pass)) if not ok)
                records.append({"asset": asset, "date": day_text, "fmp_pass": fmp_pass, "fmp_http_status": fmp.status_code, "fmp_returned_dates": returned_dates, "fmp_rows_session": len(session_rows), "fmp_regular_session_390_bars": len(session_rows) == 390, "spot_available_at_origin": spot is not None, "uw_file_pass": uw_record["full_tape_file_available"], "uw_http_status": uw_record["http_status"], "uw_bytes_total": uw_record["bytes_total"], "uw_pit_claim": False, "massive_contract_pass": bool(contract_row), "massive_contract": contract, "massive_contract_expiry": contract_row.get("expiration_date") if contract_row else None, "massive_contract_strike": contract_row.get("strike_price") if contract_row else None, "massive_reference_http_status": ref.status_code, "massive_quote_pass": quote_pass, "massive_quote_http_status": quote_status, "massive_quote_rows": quote_rows, "origin_utc": origin_utc.isoformat(), "timestamp_lte_ns": origin_ns, "selected_sip_timestamp": sip, "common_pass": common, "blocker": blocker})
    by_asset: dict[str, list[dict[str, object]]] = {asset: [row for row in records if row["asset"] == asset] for asset in ASSETS}
    by_date: dict[str, list[dict[str, object]]] = {day.isoformat(): [row for row in records if row["date"] == day.isoformat()] for day in DATES}
    output = {"status": "COMMON_HISTORY_ALL_ASSETS_V3_PROBED", "assets": ASSETS, "dates": [day.isoformat() for day in DATES], "records": records, "earliest_observed_common_date_by_asset": {asset: next((row["date"] for row in sorted(rows, key=lambda x: str(x["date"])) if row["common_pass"]), None) for asset, rows in by_asset.items()}, "latest_observed_common_date_by_asset": {asset: next((row["date"] for row in sorted(rows, key=lambda x: str(x["date"]), reverse=True) if row["common_pass"]), None) for asset, rows in by_asset.items()}, "common_assets_per_date": {day: sum(bool(row["common_pass"]) for row in rows) for day, rows in by_date.items()}, "candidate_common_window": None, "monthly_points_do_not_prove_daily_continuity": True, "full_history_downloaded": False, "secret_values_emitted": False}
    common_dates = [day for day, rows in by_date.items() if all(bool(row["common_pass"]) for row in rows)]
    output["candidate_common_window"] = {"type": "sampled_points_only", "dates": common_dates, "daily_continuity_established": False}
    destination = ROOT / "artifacts" / "api_audit" / "common_history_all_assets_v3.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(json.dumps({"status": output["status"], "records": len(records), "common_dates": common_dates, "secret_values_emitted": False}))


if __name__ == "__main__":
    main()
