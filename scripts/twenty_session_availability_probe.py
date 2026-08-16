"""Probe twenty pre-Pilot-V2 sessions without downloading Full Tape payloads."""
# ruff: noqa: E501

from __future__ import annotations

import json
import os
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
from exchange_calendars import get_calendar  # type: ignore[import-untyped]

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ("SPY", "QQQ", "AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "META")
PILOT = {date(2026, 7, 13), date(2026, 7, 14), date(2026, 7, 15), date(2026, 7, 16), date(2026, 7, 17)}
NY = ZoneInfo("America/New_York")


def secret(name: str) -> str:
    """Return a required secret without exposing its value."""
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"MISSING_SECRET:{name}")
    return value


def sessions() -> list[date]:
    """Return the twenty XNYS sessions immediately before Pilot V2."""
    calendar = get_calendar("XNYS")
    schedule = calendar.sessions_in_range("2026-05-15", "2026-07-12")
    dates = [stamp.date() for stamp in schedule.to_pydatetime() if stamp.date() not in PILOT]
    return dates[-20:]


def main() -> None:
    """Run bounded FMP/UW/Massive metadata probes and write 20 records."""
    fmp_key, massive_key, uw_key = secret("FMP_API_KEY"), secret("MASSIVE_API_KEY"), secret("UNUSUALWHALES_API_KEY")
    probe_dates = sessions()
    records: list[dict[str, object]] = []
    with httpx.Client(timeout=90, follow_redirects=True) as client:
        for day in probe_dates:
            day_text = day.isoformat()
            fmp_assets: dict[str, dict[str, object]] = {}
            for asset in ASSETS:
                response = client.get("https://financialmodelingprep.com/stable/historical-chart/1min", params={"symbol": asset, "from": day_text, "to": day_text, "apikey": fmp_key})
                payload = response.json() if response.status_code == 200 and response.headers.get("content-type", "").startswith("application/json") else []
                rows = [row for row in payload if isinstance(row, dict) and str(row.get("date", ""))[:10] == day_text] if isinstance(payload, list) else []
                returned_dates = sorted({str(row.get("date", ""))[:10] for row in payload if isinstance(row, dict)}) if isinstance(payload, list) else []
                close = rows[0].get("close") if rows else None
                spot = float(close) if isinstance(close, (int, float, str)) else None
                fmp_assets[asset] = {"http_status": response.status_code, "rows": len(rows), "returned_dates": returned_dates, "pass": response.status_code == 200 and returned_dates == [day_text] and bool(rows), "spot": spot}
            uw = client.get(f"https://api.unusualwhales.com/api/option-trades/full-tape/{day_text}", headers={"Authorization": f"Bearer {uw_key}", "Accept": "application/json", "Range": "bytes=0-1023"})
            content_range = uw.headers.get("content-range", "")
            total_bytes = int(content_range.rsplit("/", 1)[1]) if "/" in content_range and content_range.rsplit("/", 1)[1].isdigit() else None
            uw_pass = uw.status_code in {200, 206} and total_bytes is not None
            massive_assets: dict[str, dict[str, object]] = {}
            for asset in ASSETS:
                asset_spot = fmp_assets[asset]["spot"]
                ref = client.get("https://api.massive.com/v3/reference/options/contracts", params={"underlying_ticker": asset, "as_of": day_text, "expired": "false", "expiration_date.gte": (day + timedelta(days=30)).isoformat(), "expiration_date.lte": (day + timedelta(days=60)).isoformat(), "limit": "1000", "apiKey": massive_key})
                payload = ref.json() if ref.status_code == 200 and ref.headers.get("content-type", "").startswith("application/json") else {}
                candidates = [row for row in payload.get("results", []) if isinstance(row, dict) and row.get("underlying_ticker") == asset and row.get("strike_price") is not None and row.get("expiration_date")] if isinstance(payload, dict) else []
                contract = min(candidates, key=lambda row: abs(float(row["strike_price"]) - float(asset_spot))) if candidates and isinstance(asset_spot, (int, float, str)) else None
                origin_local = datetime.combine(day, datetime.min.time(), tzinfo=NY).replace(hour=12)
                origin_utc = origin_local.astimezone(UTC)
                origin_ns = int(origin_utc.timestamp() * 1_000_000_000)
                quote_status = None
                sip = None
                bid = None
                ask = None
                if contract:
                    quote = client.get(f"https://api.massive.com/v3/quotes/{contract['ticker']}", params={"timestamp.lte": str(origin_ns), "sort": "timestamp", "order": "desc", "limit": "1", "apiKey": massive_key})
                    quote_status = quote.status_code
                    q_payload = quote.json() if quote.status_code == 200 and quote.headers.get("content-type", "").startswith("application/json") else {}
                    q_rows = q_payload.get("results", []) if isinstance(q_payload, dict) else []
                    if q_rows:
                        sip, bid, ask = q_rows[0].get("sip_timestamp"), q_rows[0].get("bid_price"), q_rows[0].get("ask_price")
                quote_pass = isinstance(sip, int) and sip <= origin_ns and isinstance(bid, (int, float)) and isinstance(ask, (int, float)) and bid > 0 and ask > bid
                massive_assets[asset] = {"reference_http_status": ref.status_code, "contract": contract.get("ticker") if contract else None, "underlying_ticker": contract.get("underlying_ticker") if contract else None, "strike": contract.get("strike_price") if contract else None, "expiry": contract.get("expiration_date") if contract else None, "quote_http_status": quote_status, "selected_sip_timestamp": sip, "timestamp_lte_ns": origin_ns, "valid_quote_before_midday": quote_pass, "pass": bool(contract and quote_pass)}
            records.append({"date": day_text, "pilot_v2_excluded": day in PILOT, "fmp_assets": fmp_assets, "fmp_all_assets_pass": all(bool(value["pass"]) for value in fmp_assets.values()), "uw_http_status": uw.status_code, "uw_bytes_total": total_bytes, "uw_bytes_sampled": len(uw.content), "uw_file_exists": uw_pass, "uw_pit_claim": False, "massive_assets": massive_assets, "massive_all_assets_pass": all(bool(value["pass"]) for value in massive_assets.values()), "common_metadata_pass": bool(all(bool(value["pass"]) for value in fmp_assets.values()) and uw_pass and all(bool(value["pass"]) for value in massive_assets.values())), "full_tape_downloaded": False, "secret_values_emitted": False})
    output = {"status": "TWENTY_SESSION_AVAILABILITY_PROBED_NO_DOWNLOAD", "sessions": [row["date"] for row in records], "records": records, "count": len(records), "pilot_v2_dates_excluded": sorted(day.isoformat() for day in PILOT), "full_tape_downloaded": False, "pit_claim": False, "note": "File existence and Range/Content-Range metadata are not PIT proof.", "secret_values_emitted": False}
    destination = ROOT / "artifacts" / "api_audit" / "twenty_session_availability_probe.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(json.dumps({"status": output["status"], "count": output["count"], "full_tape_downloaded": False, "secret_values_emitted": False}))


if __name__ == "__main__":
    main()
