"""Probe FMP and Massive coverage for the independent 30-session block."""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
from exchange_calendars import get_calendar  # type: ignore[import-untyped]

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "artifacts" / "api_audit" / "b2_replication_30_common_probe.json"
ASSETS = ("SPY", "QQQ", "AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "META")
NEW_YORK = ZoneInfo("America/New_York")


def _secret(name: str) -> str:
    """Return a required secret without exposing its value."""
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"MISSING_SECRET:{name}")
    return value


def _dates(warmup_count: int = 0) -> list[date]:
    """Return target sessions and an optional causal warm-up prefix."""
    if warmup_count < 0:
        raise ValueError("WARMUP_COUNT_INVALID")
    calendar = get_calendar("XNYS")
    sessions = calendar.sessions_in_range("2025-01-01", "2025-07-06")
    return [stamp.date() for stamp in sessions.to_pydatetime()][-(30 + warmup_count) :]


def _json(response: httpx.Response) -> object:
    """Decode a JSON response or return an empty sentinel."""
    content_type = response.headers.get("content-type", "")
    if response.status_code != 200 or "json" not in content_type:
        return None
    try:
        return response.json()
    except ValueError:
        return None


def _fmp_day(client: httpx.Client, key: str, asset: str, day: date) -> dict[str, object]:
    """Probe exact-session FMP bars for one asset-day."""
    day_text = day.isoformat()
    response = client.get(
        "https://financialmodelingprep.com/stable/historical-chart/1min",
        params={"symbol": asset, "from": day_text, "to": day_text, "apikey": key},
    )
    payload = _json(response)
    rows = payload if isinstance(payload, list) else []
    exact = [
        row
        for row in rows
        if isinstance(row, dict) and str(row.get("date", ""))[:10] == day_text
    ]
    returned_dates = sorted(
        {str(row.get("date", ""))[:10] for row in rows if isinstance(row, dict)}
    )
    closes = [row.get("close") for row in exact if isinstance(row, dict)]
    spot = next((float(value) for value in closes if isinstance(value, (int, float, str))), None)
    return {
        "http_status": response.status_code,
        "rows_exact_session": len(exact),
        "returned_dates": returned_dates,
        "spot_proxy": spot,
        "exact_session_pass": (
            response.status_code == 200
            and returned_dates == [day_text]
            and bool(exact)
        ),
    }


def _spot_proxy(record: dict[str, object]) -> float | None:
    """Return a numeric FMP spot proxy for the Massive probe."""
    value = record.get("spot_proxy")
    return float(value) if isinstance(value, (int, float)) else None


def _origin_ns(day: date) -> int:
    """Return 12:00 New York as UTC nanoseconds."""
    local = datetime(day.year, day.month, day.day, 12, tzinfo=NEW_YORK)
    return int(local.astimezone(UTC).timestamp() * 1_000_000_000)


def _massive_day(
    client: httpx.Client,
    key: str,
    asset: str,
    day: date,
    spot: float | None,
) -> dict[str, object]:
    """Resolve one historical contract and one PIT quote for an asset-day."""
    lower = (day + timedelta(days=30)).isoformat()
    upper = (day + timedelta(days=60)).isoformat()
    reference_params = {
        "underlying_ticker": asset,
        "as_of": day.isoformat(),
        "expired": "false",
        "expiration_date.gte": lower,
        "expiration_date.lte": upper,
        "limit": "1000",
        "apiKey": key,
    }
    reference = client.get(
        "https://api.massive.com/v3/reference/options/contracts",
        params=reference_params,
    )
    payload = _json(reference)
    candidates = []
    if isinstance(payload, dict):
        candidates = [
            row
            for row in payload.get("results", [])
            if isinstance(row, dict)
            and row.get("underlying_ticker") == asset
            and row.get("ticker")
            and row.get("strike_price") is not None
            and row.get("expiration_date")
        ]
    contract = (
        min(candidates, key=lambda row: abs(float(row["strike_price"]) - float(spot)))
        if candidates and spot is not None
        else None
    )
    quote_status = None
    sip = bid = ask = None
    if contract is not None:
        quote = client.get(
            f"https://api.massive.com/v3/quotes/{contract['ticker']}",
            params={
                "timestamp.lte": str(_origin_ns(day)),
                "sort": "timestamp",
                "order": "desc",
                "limit": "1",
                "apiKey": key,
            },
        )
        quote_status = quote.status_code
        quote_payload = _json(quote)
        quote_rows = quote_payload.get("results", []) if isinstance(quote_payload, dict) else []
        if quote_rows:
            first = quote_rows[0]
            if isinstance(first, dict):
                sip = first.get("sip_timestamp")
                bid = first.get("bid_price")
                ask = first.get("ask_price")
    origin = _origin_ns(day)
    quote_pass = (
        isinstance(sip, int)
        and sip <= origin
        and isinstance(bid, (int, float))
        and isinstance(ask, (int, float))
        and bid > 0
        and ask > bid
    )
    return {
        "reference_http_status": reference.status_code,
        "contract_query_expired": False,
        "contract_candidate_count": len(candidates),
        "contract": contract.get("ticker") if contract else None,
        "underlying_ticker": contract.get("underlying_ticker") if contract else None,
        "expiry": contract.get("expiration_date") if contract else None,
        "quote_http_status": quote_status,
        "selected_sip_timestamp": sip,
        "timestamp_lte_ns": origin,
        "quote_pass": quote_pass,
        "pass": bool(contract and quote_pass),
    }


def main() -> None:
    """Write sanitized common-provider metadata for the 30-session block."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--warmup-count", type=int, default=0)
    arguments = parser.parse_args()
    fmp_key = _secret("FMP_API_KEY")
    massive_key = _secret("MASSIVE_API_KEY")
    dates = _dates(arguments.warmup_count)
    records: list[dict[str, object]] = []
    with httpx.Client(timeout=90, follow_redirects=True) as client:
        for day in dates:
            fmp = {asset: _fmp_day(client, fmp_key, asset, day) for asset in ASSETS}
            massive = {
                asset: _massive_day(
                    client,
                    massive_key,
                    asset,
                    day,
                    _spot_proxy(fmp[asset]),
                )
                for asset in ASSETS
            }
            records.append(
                {
                    "date": day.isoformat(),
                    "fmp_all_assets_pass": all(row["exact_session_pass"] for row in fmp.values()),
                    "massive_all_assets_pass": all(row["pass"] for row in massive.values()),
                    "fmp": fmp,
                    "massive": massive,
                    "full_tape_downloaded": False,
                    "secret_values_emitted": False,
                }
            )
    payload = {
        "schema_version": "b2-replication-30-common-probe-1.0",
        "status": (
            "PASS_METADATA_ONLY"
            if all(
                row["fmp_all_assets_pass"] and row["massive_all_assets_pass"]
                for row in records
            )
            else "FAIL_METADATA_ONLY"
        ),
        "window_start": dates[0].isoformat(),
        "window_end": dates[-1].isoformat(),
        "session_count": len(records),
        "fmp_pass_sessions": sum(bool(row["fmp_all_assets_pass"]) for row in records),
        "massive_pass_sessions": sum(bool(row["massive_all_assets_pass"]) for row in records),
        "full_tape_downloaded": False,
        "pit_claim": False,
        "records": records,
        "secret_values_emitted": False,
    }
    output = OUTPUT.with_name(
        f"b2_replication_{len(dates)}_common_probe.json"
        if arguments.warmup_count
        else OUTPUT.name
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    summary_keys = (
        "status",
        "window_start",
        "window_end",
        "session_count",
        "fmp_pass_sessions",
        "massive_pass_sessions",
        "full_tape_downloaded",
        "secret_values_emitted",
    )
    print(json.dumps({key: payload[key] for key in summary_keys}))


if __name__ == "__main__":
    main()
