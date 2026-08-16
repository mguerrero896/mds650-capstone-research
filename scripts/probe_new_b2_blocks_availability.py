"""Probe two new historical blocks without downloading Full Tape payloads."""

from __future__ import annotations

import json
import os
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from exchange_calendars import get_calendar  # type: ignore[import-untyped]

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "artifacts" / "api_audit" / "new_blocks_availability_probe_v2.json"
ASSETS = ("SPY", "QQQ", "AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "META")
NY = ZoneInfo("America/New_York")
BLOCK_WINDOWS = (
    ("block_a_2024_08_02_2024_09_13", "2024-08-02", "2024-09-13"),
    ("block_b_2024_10_01_2024_11_11", "2024-10-01", "2024-11-11"),
)


def secret(name: str) -> str:
    """Return a required secret without emitting its value."""
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"MISSING_SECRET:{name}")
    return value


def block_dates() -> dict[str, list[date]]:
    """Return exactly thirty XNYS sessions in each frozen candidate block."""
    calendar = get_calendar("XNYS")
    result: dict[str, list[date]] = {}
    for block_id, start, end in BLOCK_WINDOWS:
        sessions = [
            stamp.date() for stamp in calendar.sessions_in_range(start, end).to_pydatetime()
        ]
        if len(sessions) < 30:
            raise RuntimeError(f"BLOCK_TOO_SHORT:{block_id}:{len(sessions)}")
        result[block_id] = sessions[:30]
    return result


def _total_bytes(response: httpx.Response) -> int | None:
    """Parse a sanitized Content-Range total byte count."""
    content_range = response.headers.get("content-range", "")
    total = content_range.rsplit("/", 1)[-1] if "/" in content_range else ""
    return int(total) if total.isdigit() else None


def _fmp_day(client: httpx.Client, day: date, key: str) -> dict[str, Any]:
    """Probe exact-session FMP rows for all candidate assets."""
    day_text = day.isoformat()
    assets: dict[str, dict[str, Any]] = {}
    for asset in ASSETS:
        response = client.get(
            "https://financialmodelingprep.com/stable/historical-chart/1min",
            params={"symbol": asset, "from": day_text, "to": day_text, "apikey": key},
        )
        payload = response.json() if response.status_code == 200 else []
        rows = [
            row
            for row in payload
            if isinstance(row, dict) and str(row.get("date", ""))[:10] == day_text
        ] if isinstance(payload, list) else []
        returned = sorted(
            {str(row.get("date", ""))[:10] for row in payload if isinstance(row, dict)}
        ) if isinstance(payload, list) else []
        spot = rows[0].get("close") if rows else None
        assets[asset] = {
            "http_status": response.status_code,
            "rows_exact_session": len(rows),
            "returned_dates": returned,
            "spot_available": isinstance(spot, (int, float, str)),
            "spot": float(spot) if isinstance(spot, (int, float, str)) else None,
        }
    return {"date": day_text, "assets": assets}


def _massive_asset(
    client: httpx.Client,
    day: date,
    asset: str,
    fmp_record: dict[str, Any],
    key: str,
) -> dict[str, Any]:
    """Resolve one historical ATM contract and one valid pre-origin quote."""
    day_text = day.isoformat()
    spot_value = fmp_record["assets"][asset].get("spot")
    origin_local = datetime.combine(day, datetime.min.time(), tzinfo=NY).replace(hour=12)
    origin_ns = int(origin_local.astimezone(UTC).timestamp() * 1_000_000_000)
    reference = client.get(
        "https://api.massive.com/v3/reference/options/contracts",
        params={
            "underlying_ticker": asset,
            "as_of": day_text,
            # The selected 30-60 DTE contracts are still active at the historical
            # as_of date; expired=true would incorrectly exclude them.
            "expired": "false",
            "expiration_date.gte": (day + timedelta(days=30)).isoformat(),
            "expiration_date.lte": (day + timedelta(days=60)).isoformat(),
            "limit": "1000",
            "apiKey": key,
        },
    )
    payload = reference.json() if reference.status_code == 200 else {}
    candidates = [
        row
        for row in payload.get("results", [])
        if isinstance(row, dict)
        and row.get("underlying_ticker") == asset
        and row.get("strike_price") is not None
        and row.get("expiration_date")
    ] if isinstance(payload, dict) else []
    contract = None
    if candidates and isinstance(spot_value, (int, float, str)):
        contract = min(
            candidates,
            key=lambda row: abs(float(row["strike_price"]) - float(spot_value)),
        )
    quote_status: int | None = None
    sip: int | None = None
    bid: float | None = None
    ask: float | None = None
    if contract:
        quote = client.get(
            f"https://api.massive.com/v3/quotes/{contract['ticker']}",
            params={
                "timestamp.lte": str(origin_ns),
                "sort": "timestamp",
                "order": "desc",
                "limit": "1",
                "apiKey": key,
            },
        )
        quote_status = quote.status_code
        q_payload = quote.json() if quote.status_code == 200 else {}
        q_rows = q_payload.get("results", []) if isinstance(q_payload, dict) else []
        if q_rows:
            row = q_rows[0]
            sip = row.get("sip_timestamp")
            bid = row.get("bid_price")
            ask = row.get("ask_price")
    valid_quote = (
        isinstance(sip, int)
        and sip <= origin_ns
        and isinstance(bid, (int, float))
        and isinstance(ask, (int, float))
        and bid > 0
        and ask > bid
    )
    return {
        "reference_http_status": reference.status_code,
        "contract": contract.get("ticker") if contract else None,
        "underlying_ticker": contract.get("underlying_ticker") if contract else None,
        "expiry": contract.get("expiration_date") if contract else None,
        "quote_http_status": quote_status,
        "origin_timestamp_ns": origin_ns,
        "selected_sip_timestamp": sip,
        "valid_quote_before_midday": valid_quote,
        "pass": bool(contract and valid_quote),
    }


def main() -> None:
    """Run a metadata-only probe for two disjoint candidate blocks."""
    uw_key = secret("UNUSUALWHALES_API_KEY")
    fmp_key = secret("FMP_API_KEY")
    massive_key = secret("MASSIVE_API_KEY")
    dates_by_block = block_dates()
    records: list[dict[str, Any]] = []
    with httpx.Client(timeout=90, follow_redirects=True) as client:
        for block_id, dates in dates_by_block.items():
            for index, day in enumerate(dates):
                day_text = day.isoformat()
                uw = client.get(
                    f"https://api.unusualwhales.com/api/option-trades/full-tape/{day_text}",
                    headers={
                        "Authorization": f"Bearer {uw_key}",
                        "Accept": "application/json",
                        "Range": "bytes=0-1023",
                    },
                )
                fmp_probe = _fmp_day(client, day, fmp_key) if index in {0, 14, 29} else None
                massive_probe: dict[str, Any] | None = None
                if fmp_probe is not None:
                    massive_probe = {
                        asset: _massive_asset(client, day, asset, fmp_probe, massive_key)
                        for asset in ASSETS
                    }
                records.append(
                    {
                        "block_id": block_id,
                        "date": day_text,
                        "uw": {
                            "http_status": uw.status_code,
                            "content_range_present": "content-range" in uw.headers,
                            "bytes_total": _total_bytes(uw),
                            "full_tape_downloaded": False,
                            "pit_claim": False,
                        },
                        "fmp_sample": fmp_probe,
                        "massive_sample": massive_probe,
                        "secret_values_emitted": False,
                    }
                )
    output: dict[str, Any] = {
        "schema_version": "new-blocks-availability-probe-2.0",
        "status": "METADATA_ONLY_NO_FULL_TAPE_DOWNLOAD",
        "blocks": {
            block_id: [day.isoformat() for day in dates]
            for block_id, dates in dates_by_block.items()
        },
        "records": records,
        "full_tape_downloaded": False,
        "pit_claim": False,
        "note": (
            "UW Range/Content-Range proves file metadata availability only; it does not "
            "prove row-level PIT."
        ),
        "secret_values_emitted": False,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "status": output["status"],
                "block_counts": {key: len(value) for key, value in output["blocks"].items()},
                "full_tape_downloaded": False,
                "secret_values_emitted": False,
            }
        )
    )


if __name__ == "__main__":
    main()
