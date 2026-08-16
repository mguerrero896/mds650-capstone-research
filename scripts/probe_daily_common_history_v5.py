"""Run a bounded, metadata-only daily common-history continuity audit.

The probe checks exact FMP sessions, Unusual Whales Full Tape file metadata
without downloading ZIP contents, and one historical Massive contract/quote per
asset-day. It is resumable and never writes provider payloads or secrets.
"""
# ruff: noqa: E501

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from contextlib import suppress
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlsplit
from zoneinfo import ZoneInfo

import exchange_calendars as xcals  # type: ignore[import-untyped]
import httpx

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts" / "api_audit" / "common_history_continuity_v5.json"
CHECKPOINT = ROOT / "artifacts" / "api_audit" / ".common_history_continuity_v5.checkpoint.json"
ASSETS = ("SPY", "QQQ", "AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "META")
NY = ZoneInfo("America/New_York")
STUDY_START = date(2025, 7, 21)
STUDY_END_EXCLUSIVE = date(2026, 7, 21)
FMP_URL = "https://financialmodelingprep.com/stable/historical-chart/1min"
MASSIVE_REFERENCE_URL = "https://api.massive.com/v3/reference/options/contracts"
UW_FULL_TAPE_URL = "https://api.unusualwhales.com/api/option-trades/full-tape"


def _secret(name: str) -> str:
    """Return a required secret without exposing it."""
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"MISSING_SECRET:{name}")
    return value


def _sessions() -> list[date]:
    """Return the exact XNYS sessions in the frozen study window."""
    calendar = xcals.get_calendar("XNYS")
    return [
        stamp.date()
        for stamp in calendar.sessions_in_range(
            STUDY_START.isoformat(), (STUDY_END_EXCLUSIVE - timedelta(days=1)).isoformat()
        ).to_pydatetime()
    ]


def _expected_session(day: date) -> dict[str, Any]:
    """Return expected XNYS minute labels for one session."""
    calendar = xcals.get_calendar("XNYS")
    if not calendar.is_session(day.isoformat()):
        return {"is_session": False, "expected_count": 0, "expected_start": None, "expected_end": None}
    minutes = [item.to_pydatetime().astimezone(NY) for item in calendar.session_minutes(day.isoformat())]
    return {
        "is_session": True,
        "expected_count": len(minutes),
        "expected_start": minutes[0].isoformat(),
        "expected_end": minutes[-1].isoformat(),
    }


def _response_meta(response: httpx.Response) -> dict[str, Any]:
    """Return sanitized transport metadata."""
    payload: Any = None
    with suppress(ValueError, json.JSONDecodeError):
        payload = response.json()
    request_id = response.headers.get("x-request-id") or response.headers.get("request-id")
    if isinstance(payload, dict):
        request_id = request_id or payload.get("request_id")
    return {
        "http_status": response.status_code,
        "request_id": request_id,
        "content_type": response.headers.get("content-type"),
        "rate_limit_headers_observed": sorted(
            key.lower()
            for key in response.headers
            if "rate" in key.lower() or "retry" in key.lower()
        ),
    }


def _json(response: httpx.Response) -> Any:
    """Decode JSON and return ``None`` for non-JSON responses."""
    try:
        return response.json()
    except (ValueError, json.JSONDecodeError):
        return None


def _request_params(params: dict[str, Any]) -> dict[str, Any]:
    """Remove credentials from a request parameter mapping."""
    return {key: value for key, value in params.items() if key.lower() not in {"apikey", "api_key"}}


async def _request(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    """Request with bounded retry/backoff for transient provider responses."""
    for attempt in range(4):
        response = await client.request(method, url, params=params, headers=headers)
        if response.status_code not in {429, 500, 502, 503, 504} or attempt == 3:
            return response
        retry_after = response.headers.get("retry-after")
        try:
            delay = min(float(retry_after), 5.0) if retry_after else 1.0 + attempt
        except ValueError:
            delay = 1.0 + attempt
        await asyncio.sleep(delay)
    raise RuntimeError("UNREACHABLE_RETRY_STATE")


def _origin(day: date) -> tuple[datetime, int]:
    """Return the 12:00 New York probe origin and its nanosecond epoch."""
    local = datetime.combine(day, datetime.min.time(), tzinfo=NY).replace(hour=12)
    utc = local.astimezone(UTC)
    return utc, int(utc.timestamp() * 1_000_000_000)


async def _fmp_day(client: httpx.AsyncClient, key: str, asset: str, day: date) -> dict[str, Any]:
    """Probe one exact FMP session and discard the raw response after profiling."""
    day_text = day.isoformat()
    params = {"symbol": asset, "from": day_text, "to": day_text, "apikey": key}
    response = await _request(client, "GET", FMP_URL, params=params)
    payload = _json(response)
    rows = payload if isinstance(payload, list) else []
    raw_dates = sorted(
        str(row.get("date"))
        for row in rows
        if isinstance(row, dict) and isinstance(row.get("date"), str)
    )
    returned_dates = sorted({value[:10] for value in raw_dates})
    exact_rows = [row for row in rows if isinstance(row, dict) and str(row.get("date", ""))[:10] == day_text]
    expected = _expected_session(day)
    target = f"{day_text} 12:00:00"
    midday = next((row for row in exact_rows if row.get("date") == target), None)
    closes_ok = all(isinstance(row.get("close"), (int, float)) for row in exact_rows)
    expected_labels = {
        (datetime.fromisoformat(expected["expected_start"]) + timedelta(minutes=index)).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        for index in range(expected["expected_count"])
    } if expected["is_session"] else set()
    observed_labels = {str(row.get("date")) for row in exact_rows}
    return {
        "asset": asset,
        "date": day_text,
        "request_endpoint": "/stable/historical-chart/1min",
        "request_params_sanitized": _request_params(params),
        **_response_meta(response),
        "returned_dates": returned_dates,
        "rows_returned": len(rows),
        "rows_exact_session": len(exact_rows),
        "expected_xnys_session": expected,
        "raw_timestamp_format": "YYYY-MM-DD HH:mm:ss",
        "raw_timestamp_timezone": "naive; exchange-local interpretation only",
        "first_raw_timestamp": raw_dates[0] if raw_dates else None,
        "last_raw_timestamp": raw_dates[-1] if raw_dates else None,
        "missing_expected_labels": sorted(expected_labels - observed_labels),
        "unexpected_timestamp_labels": sorted(observed_labels - expected_labels),
        "missing_minute_reason": (
            "UNRESOLVED_PROVIDER_CALENDAR_OR_HALT" if expected_labels - observed_labels else None
        ),
        "provider_over_return": returned_dates != [day_text],
        "spot_at_midday": midday.get("close") if isinstance(midday, dict) else None,
        "critical_null_close": not closes_ok,
        "exact_session_pass": (
            response.status_code == 200
            and returned_dates == [day_text]
            and len(exact_rows) == expected["expected_count"]
            and closes_ok
        ),
        "bar_label_semantics": "UNRESOLVED_START_VS_CLOSE",
        "available_at_assumption": "timestamp_raw + 1 minute",
        "raw_payload_retained": False,
    }


async def _fmp_gap_diagnostic(
    client: httpx.AsyncClient, key: str, asset: str, day: date
) -> dict[str, Any]:
    """Test whether a missing minute is recovered by a wider direct FMP request."""
    day_text = day.isoformat()
    params = {
        "symbol": asset,
        "from": (day - timedelta(days=1)).isoformat(),
        "to": (day + timedelta(days=1)).isoformat(),
        "apikey": key,
    }
    response = await _request(client, "GET", FMP_URL, params=params)
    payload = _json(response)
    rows = payload if isinstance(payload, list) else []
    returned_dates = sorted(
        {str(row.get("date", ""))[:10] for row in rows if isinstance(row, dict)}
    )
    exact_rows = [
        row
        for row in rows
        if isinstance(row, dict) and str(row.get("date", ""))[:10] == day_text
    ]
    expected = _expected_session(day)
    expected_labels = {
        (
            datetime.fromisoformat(expected["expected_start"])
            + timedelta(minutes=index)
        ).strftime("%Y-%m-%d %H:%M:%S")
        for index in range(expected["expected_count"])
    }
    observed_labels = {str(row.get("date")) for row in exact_rows}
    missing = sorted(expected_labels - observed_labels)
    return {
        "asset": asset,
        "date": day_text,
        "request_endpoint": "/stable/historical-chart/1min",
        "request_params_sanitized": _request_params(params),
        **_response_meta(response),
        "returned_dates": returned_dates,
        "rows_returned": len(rows),
        "rows_exact_session": len(exact_rows),
        "missing_expected_labels": missing,
        "diagnosis": (
            "RECOVERED_IN_WIDER_RANGE"
            if not missing and response.status_code == 200
            else "PERSISTENT_WIDER_RANGE_GAP"
            if response.status_code == 200
            else "WIDER_RANGE_REQUEST_FAILED"
        ),
        "raw_payload_retained": False,
    }


def _candidate_rows(payload: Any, asset: str, day: date, spot: float) -> list[dict[str, Any]]:
    """Filter historical option contracts to valid, date-relative candidates."""
    if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
        return []
    candidates: list[dict[str, Any]] = []
    for row in payload["results"]:
        if not isinstance(row, dict) or row.get("underlying_ticker") != asset:
            continue
        ticker = row.get("ticker")
        expiry = row.get("expiration_date")
        strike = row.get("strike_price")
        if not isinstance(ticker, str) or not ticker.startswith("O:"):
            continue
        if not isinstance(expiry, str) or expiry <= day.isoformat():
            continue
        if not isinstance(strike, (int, float)):
            continue
        row = dict(row)
        row["_distance_to_spot"] = abs(float(strike) - spot)
        candidates.append(row)
    return candidates


def _next_request(next_url: str, key: str) -> tuple[str, dict[str, str]]:
    """Sanitize a provider next URL and reattach auth only in memory."""
    parsed = urlsplit(next_url)
    path = parsed.path or "/v3/reference/options/contracts"
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query.pop("apiKey", None)
    query.pop("apikey", None)
    query["apiKey"] = key
    return f"https://api.massive.com{path}", query


async def _massive_day(
    client: httpx.AsyncClient,
    key: str,
    asset: str,
    day: date,
    spot: float | None,
    max_pages: int,
) -> dict[str, Any]:
    """Resolve one historical contract and the last valid quote before noon."""
    day_text = day.isoformat()
    origin_utc, origin_ns = _origin(day)
    base = {
        "underlying_ticker": asset,
        "as_of": day_text,
        "expired": "true",
        "contract_type": "call",
        "expiration_date.gte": (day + timedelta(days=30)).isoformat(),
        "expiration_date.lte": (day + timedelta(days=60)).isoformat(),
        "order": "asc",
        "sort": "expiration_date",
        "limit": "1000",
        "apiKey": key,
    }
    pages: list[dict[str, Any]] = []
    candidate_rows: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    next_url: str | None = MASSIVE_REFERENCE_URL
    next_params: dict[str, Any] | None = base
    reference_status: int | None = None
    attempts: list[dict[str, Any]] = []
    for page_number in range(max_pages):
        if next_url is None or next_params is None:
            break
        response = await _request(client, "GET", next_url, params=next_params)
        reference_status = response.status_code
        payload = _json(response)
        page_rows = payload.get("results", []) if isinstance(payload, dict) else []
        if spot is not None:
            candidate_rows.extend(_candidate_rows(payload, asset, day, spot))
        pages.append({"page": page_number + 1, "http_status": response.status_code, "rows": len(page_rows) if isinstance(page_rows, list) else 0})
        attempts.append({"request_endpoint": "/v3/reference/options/contracts", "request_params_sanitized": _request_params(next_params), **_response_meta(response)})
        next_url_value = payload.get("next_url") if isinstance(payload, dict) else None
        if not isinstance(next_url_value, str) or not next_url_value:
            next_url = None
            next_params = None
        else:
            canonical = next_url_value.split("&apiKey=", 1)[0].split("&apikey=", 1)[0]
            if canonical in seen_urls:
                next_url = None
                next_params = None
                pages[-1]["repeated_next_url"] = True
            else:
                seen_urls.add(canonical)
                next_url, next_params = _next_request(next_url_value, key)
    candidates = candidate_rows
    contract = min(candidates, key=lambda row: (row["_distance_to_spot"], row["expiration_date"], row["ticker"])) if candidates else None

    if contract is None and reference_status == 200:
        fallback = dict(base)
        fallback["expired"] = "false"
        fallback_response = await _request(client, "GET", MASSIVE_REFERENCE_URL, params=fallback)
        fallback_payload = _json(fallback_response)
        attempts.append({"request_endpoint": "/v3/reference/options/contracts", "request_params_sanitized": _request_params(fallback), **_response_meta(fallback_response), "fallback": "expired=false"})
        reference_status = fallback_response.status_code
        if spot is not None:
            fallback_candidates = _candidate_rows(fallback_payload, asset, day, spot)
            contract = min(fallback_candidates, key=lambda row: (row["_distance_to_spot"], row["expiration_date"], row["ticker"])) if fallback_candidates else None

    quote_status: int | None = None
    quote: dict[str, Any] | None = None
    quote_attempt: dict[str, Any] | None = None
    if contract is not None:
        ticker = str(contract["ticker"])
        quote_params = {"timestamp.lte": str(origin_ns), "sort": "timestamp", "order": "desc", "limit": "1", "apiKey": key}
        quote_response = await _request(client, "GET", f"https://api.massive.com/v3/quotes/{ticker}", params=quote_params)
        quote_status = quote_response.status_code
        quote_payload = _json(quote_response)
        quote_rows = quote_payload.get("results", []) if isinstance(quote_payload, dict) else []
        quote = quote_rows[0] if isinstance(quote_rows, list) and quote_rows and isinstance(quote_rows[0], dict) else None
        quote_attempt = {"request_endpoint": "/v3/quotes/{optionsTicker}", "request_params_sanitized": _request_params(quote_params), **_response_meta(quote_response)}
    sip = quote.get("sip_timestamp") if quote else None
    bid = quote.get("bid_price") if quote else None
    ask = quote.get("ask_price") if quote else None
    sip_le_origin = isinstance(sip, int) and sip <= origin_ns
    quote_valid = bool(sip_le_origin and isinstance(bid, (int, float)) and isinstance(ask, (int, float)) and bid > 0 and ask > bid)
    return {
        "asset": asset,
        "date": day_text,
        "origin_utc": origin_utc.isoformat(),
        "timestamp_lte_ns": origin_ns,
        "reference_http_status": reference_status,
        "reference_pages_observed": len(pages),
        "reference_pagination_complete": bool(pages and next_url is None),
        "reference_attempts": attempts,
        "contract": contract.get("ticker") if contract else None,
        "underlying_ticker": contract.get("underlying_ticker") if contract else None,
        "expiration_date": contract.get("expiration_date") if contract else None,
        "strike_price": contract.get("strike_price") if contract else None,
        "quote_http_status": quote_status,
        "quote_request": quote_attempt,
        "selected_sip_timestamp": sip,
        "bid_price": bid,
        "ask_price": ask,
        "sip_timestamp_le_origin": sip_le_origin,
        "quote_valid_before_origin": quote_valid,
        "timestamp_unit": "nanoseconds since Unix epoch",
        "raw_payload_retained": False,
        "blocker": None if quote_valid else (
            "NO_SPOT" if spot is None else "NO_HISTORICAL_CONTRACT" if contract is None else "NO_VALID_QUOTE_BEFORE_ORIGIN"
        ),
    }


async def _uw_day(client: httpx.AsyncClient, key: str, day: date) -> dict[str, Any]:
    """Probe Full Tape existence/size using one-byte Range metadata only."""
    day_text = day.isoformat()
    response = await _request(
        client,
        "GET",
        f"{UW_FULL_TAPE_URL}/{day_text}",
        headers={"Authorization": f"Bearer {key}", "Accept": "application/json", "Range": "bytes=0-0"},
    )
    content_range = response.headers.get("content-range", "")
    total: int | None = None
    if "/" in content_range and content_range.rsplit("/", 1)[1].isdigit():
        total = int(content_range.rsplit("/", 1)[1])
    return {
        "date": day_text,
        "request_endpoint": "/api/option-trades/full-tape/{date}",
        "request_headers_sanitized": {"Accept": "application/json", "Range": "bytes=0-0"},
        **_response_meta(response),
        "bytes_sampled": len(response.content),
        "bytes_total": total,
        "file_metadata_pass": response.status_code in {200, 206} and total is not None,
        "pit_claim": False,
        "created_at_used_as_availability": False,
        "full_tape_downloaded": False,
        "raw_payload_retained": False,
    }


def _load_checkpoint() -> dict[str, Any]:
    """Load a resumable checkpoint or return an empty state."""
    if not CHECKPOINT.exists():
        return {
            "fmp": {},
            "massive": {},
            "uw": {},
            "fmp_gap_diagnostics": {},
            "generated_at_utc": None,
        }
    payload = json.loads(CHECKPOINT.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {
        "fmp": {},
        "massive": {},
        "uw": {},
        "fmp_gap_diagnostics": {},
        "generated_at_utc": None,
    }


def _save_checkpoint(state: dict[str, Any]) -> None:
    """Persist checkpoint atomically without provider secrets."""
    state["generated_at_utc"] = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    tmp = CHECKPOINT.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, sort_keys=True), encoding="utf-8")
    tmp.replace(CHECKPOINT)


def _key(asset: str, day: date) -> str:
    return f"{asset}|{day.isoformat()}"


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    """Run the daily audit, resuming completed asset-days from checkpoint."""
    fmp_key, uw_key, massive_key = _secret("FMP_API_KEY"), _secret("UNUSUALWHALES_API_KEY"), _secret("MASSIVE_API_KEY")
    all_sessions = _sessions()
    selected_sessions = all_sessions[: args.max_sessions] if args.max_sessions else all_sessions
    assets = tuple(args.assets) if args.assets else ASSETS
    state = _load_checkpoint()
    state.setdefault("fmp", {})
    state.setdefault("massive", {})
    state.setdefault("uw", {})
    state.setdefault("fmp_gap_diagnostics", {})
    limits = httpx.Limits(max_connections=max(4, args.max_in_flight), max_keepalive_connections=max(4, args.max_in_flight))
    async with httpx.AsyncClient(timeout=httpx.Timeout(45.0), follow_redirects=True, limits=limits) as client:
        for index, day in enumerate(selected_sessions, start=1):
            day_text = day.isoformat()
            if day_text not in state["uw"]:
                state["uw"][day_text] = await _uw_day(client, uw_key, day)
            pending_fmp = [
                asset
                for asset in assets
                if _key(asset, day) not in state["fmp"]
                or (args.repair_fmp_gaps and not state["fmp"][_key(asset, day)].get("exact_session_pass", False))
            ]
            if pending_fmp:
                fmp_results = await asyncio.gather(*( _fmp_day(client, fmp_key, asset, day) for asset in pending_fmp))
                state["fmp"].update({_key(row["asset"], day): row for row in fmp_results})
            pending_massive = [asset for asset in assets if _key(asset, day) not in state["massive"]]
            if pending_massive:
                tasks = []
                for asset in pending_massive:
                    fmp_row = state["fmp"].get(_key(asset, day), {})
                    tasks.append(_massive_day(client, massive_key, asset, day, fmp_row.get("spot_at_midday"), args.max_pages))
                massive_results = await asyncio.gather(*tasks)
                state["massive"].update({_key(row["asset"], day): row for row in massive_results})
            _save_checkpoint(state)
            if index == 1 or index % 10 == 0 or index == len(selected_sessions):
                print(json.dumps({"status": "RUNNING", "session": index, "sessions_total": len(selected_sessions), "date": day_text, "secret_values_emitted": False}), flush=True)
        if args.diagnose_fmp_gaps:
            gap_keys = [
                key
                for key, row in state["fmp"].items()
                if not row.get("exact_session_pass", False)
                and key not in state["fmp_gap_diagnostics"]
            ]
            gap_tasks = [
                _fmp_gap_diagnostic(
                    client,
                    fmp_key,
                    asset,
                    date.fromisoformat(day_text),
                )
                for asset, day_text in (item.split("|", 1) for item in gap_keys)
            ]
            gap_results = await asyncio.gather(*gap_tasks)
            state["fmp_gap_diagnostics"].update(
                {f"{row['asset']}|{row['date']}": row for row in gap_results}
            )
            _save_checkpoint(state)
    records: list[dict[str, Any]] = []
    for day in selected_sessions:
        day_text = day.isoformat()
        uw = state["uw"][day_text]
        for asset in assets:
            key = _key(asset, day)
            fmp = state["fmp"][key]
            massive = state["massive"][key]
            provider_component_pass = bool(fmp["exact_session_pass"] and uw["file_metadata_pass"] and massive["quote_valid_before_origin"])
            records.append({
                "asset": asset,
                "date": day_text,
                "fmp_session_pass": fmp["exact_session_pass"],
                "fmp_rows_exact_session": fmp["rows_exact_session"],
                "fmp_expected_rows": fmp["expected_xnys_session"]["expected_count"],
                "fmp_returned_dates": fmp["returned_dates"],
                "fmp_provider_over_return": fmp["provider_over_return"],
                "fmp_spot_at_midday": fmp["spot_at_midday"],
                "fmp_missing_expected_labels": fmp.get("missing_expected_labels", []),
                "fmp_missing_minute_reason": fmp.get("missing_minute_reason"),
                "fmp_first_raw_timestamp": fmp.get("first_raw_timestamp"),
                "fmp_last_raw_timestamp": fmp.get("last_raw_timestamp"),
                "uw_file_metadata_pass": uw["file_metadata_pass"],
                "uw_http_status": uw["http_status"],
                "uw_bytes_total": uw["bytes_total"],
                "uw_pit_claim": False,
                "massive_contract": massive["contract"],
                "massive_contract_pass": massive["contract"] is not None,
                "massive_quote_pass": massive["quote_valid_before_origin"],
                "massive_reference_http_status": massive["reference_http_status"],
                "massive_quote_http_status": massive["quote_http_status"],
                "massive_selected_sip_timestamp": massive["selected_sip_timestamp"],
                "massive_timestamp_lte_ns": massive["timestamp_lte_ns"],
                "massive_sip_le_origin": massive["sip_timestamp_le_origin"],
                "massive_blocker": massive["blocker"],
                "common_component_pass": provider_component_pass,
                "pit_common_pass": bool(fmp["exact_session_pass"] and massive["quote_valid_before_origin"]),
            })
    by_asset = {
        asset: [row for row in records if row["asset"] == asset] for asset in assets
    }
    expected_count = len(selected_sessions)
    common_dates = [
        day.isoformat()
        for day in selected_sessions
        if all(row["common_component_pass"] for row in records if row["date"] == day.isoformat())
        and len([row for row in records if row["date"] == day.isoformat()]) == len(assets)
    ]
    massive_rows = list(state["massive"].values())
    massive_expired_true_requests = sum(
        sum(
            attempt.get("request_params_sanitized", {}).get("expired") == "true"
            for attempt in row.get("reference_attempts", [])
        )
        for row in massive_rows
    )
    massive_expired_false_fallbacks = sum(
        any(attempt.get("fallback") == "expired=false" for attempt in row.get("reference_attempts", []))
        for row in massive_rows
    )
    payload = {
        "schema_version": "common-history-continuity-v5",
        "generated_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "status": "OBSERVED_DAILY_PROVIDER_CONTINUITY_WITH_UW_PIT_UNVERIFIED",
        "gate": "FAIL_CLOSED",
        "study_window": {"start_inclusive": STUDY_START.isoformat(), "end_exclusive": STUDY_END_EXCLUSIVE.isoformat()},
        "calendar": "XNYS",
        "assets": list(assets),
        "sessions_probed": [day.isoformat() for day in selected_sessions],
        "expected_session_count": len(all_sessions),
        "sessions_probed_count": expected_count,
        "records": sorted(records, key=lambda row: (row["date"], row["asset"])),
        "common_dates_all_assets": common_dates,
        "common_dates_all_assets_count": len(common_dates),
        "logical_request_counts": {
            "fmp_exact_asset_days": len(state["fmp"]),
            "fmp_wider_gap_diagnostics": len(state["fmp_gap_diagnostics"]),
            "uw_file_metadata_days": len(state["uw"]),
            "massive_contract_reference_requests": sum(
                len(row.get("reference_attempts", []))
                for row in state["massive"].values()
            ),
            "massive_quote_requests": sum(
                row.get("quote_request") is not None for row in state["massive"].values()
            ),
        },
        "massive_expired_parameter_behavior": {
            "expired_true_requests": massive_expired_true_requests,
            "expired_true_empty_fallback_false_asset_days": massive_expired_false_fallbacks,
            "expired_false_fallback_requests": massive_expired_false_fallbacks,
            "fallback_was_sanitized_and_recorded": True,
            "not_silent": True,
            "interpretation": "PROVIDER_PARAMETER_BEHAVIOR_RECORDED; direct as_of contract resolution and quote checks retained",
        },
        "coverage_by_asset": {
            asset: {
                "fmp_exact_session_rate": sum(bool(row["fmp_session_pass"]) for row in rows) / expected_count,
                "uw_file_metadata_rate": sum(bool(row["uw_file_metadata_pass"]) for row in rows) / expected_count,
                "massive_quote_pit_rate": sum(bool(row["massive_quote_pass"]) for row in rows) / expected_count,
                "common_component_rate": sum(bool(row["common_component_pass"]) for row in rows) / expected_count,
            }
            for asset, rows in by_asset.items()
        },
        "fmp_gap_diagnostics": state["fmp_gap_diagnostics"],
        "provider_contract_validation": {
            "fmp": {"endpoint": FMP_URL, "docs": "https://site.financialmodelingprep.com/how-to/how-to-get-stock-intraday-data-with-fmp-apis", "timestamp_timezone": "exchange-local", "start_close_semantics": "UNRESOLVED", "available_at": "timestamp_raw + 1 minute", "proxy_used": False},
            "unusual_whales": {"endpoint": UW_FULL_TAPE_URL, "docs": "https://api.unusualwhales.com/docs/operations/PublicApi.OptionTradeController.flow_alerts", "file_range_only": True, "pit_claim": False, "created_at_docs": "https://api.unusualwhales.com/docs/kafka/types/OptionTrade", "created_at_as_publication": False},
            "massive": {"contracts_endpoint": MASSIVE_REFERENCE_URL, "quotes_endpoint": "https://api.massive.com/v3/quotes/{optionsTicker}", "contracts_docs": "https://massive.com/docs/rest/options/contracts", "quotes_docs": "https://massive.com/docs/rest/options/quotes", "as_of_used": True, "sip_timestamp_unit": "nanoseconds", "proxy_used": False},
        },
        "methodological_boundary": "This is a metadata-only continuity audit; it is not a Full Tape download, option backfill, model run, or PIT proof for UW publication availability.",
        "raw_payloads_retained": False,
        "full_tape_downloaded": False,
        "secret_values_emitted": False,
        "personal_paths_emitted": False,
        "checkpoint_sha256": hashlib.sha256(CHECKPOINT.read_bytes()).hexdigest() if CHECKPOINT.exists() else None,
    }
    OUT.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"status": payload["status"], "sessions": expected_count, "records": len(records), "common_dates_all_assets_count": len(common_dates), "full_tape_downloaded": False, "secret_values_emitted": False}


def main() -> int:
    """Parse bounded-run options and execute the audit."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-sessions", type=int, default=0, help="Smoke-test prefix; zero means the full frozen window.")
    parser.add_argument("--assets", nargs="+", choices=ASSETS, default=None)
    parser.add_argument("--max-pages", type=int, default=3, help="Maximum contract-reference pages per request.")
    parser.add_argument("--max-in-flight", type=int, default=8, help="Maximum concurrent provider requests.")
    parser.add_argument("--repair-fmp-gaps", action="store_true", help="Re-probe only cached FMP asset-days that failed exact-session validation.")
    parser.add_argument("--diagnose-fmp-gaps", action="store_true", help="Probe failed FMP asset-days once with a wider direct date range.")
    args = parser.parse_args()
    if args.max_sessions < 0 or args.max_pages < 1 or args.max_in_flight < 1:
        raise SystemExit("max-sessions must be non-negative; max-pages and max-in-flight must be positive")
    result = asyncio.run(_run(args))
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
