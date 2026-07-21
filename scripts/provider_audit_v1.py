"""Run a bounded, authenticated provider audit and write sanitized evidence.

This script is an evidence probe, not a backfill connector. It deliberately uses
small date windows, stores raw responses outside the repository, and emits only
hashes, schemas and diagnostics to the tracked manifest.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlsplit
from uuid import uuid4
from zoneinfo import ZoneInfo

import httpx
from exchange_calendars import get_calendar

from mds650.config import ResearchSettings
from mds650.storage import write_immutable_raw

ASSETS = ("SPY", "QQQ", "AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "META")
NEW_YORK = ZoneInfo("America/New_York")
XNYS = get_calendar("XNYS")
OUT_DIR = Path(os.environ.get("MDS650_AUDIT_OUT_DIR", "artifacts/api_audit/authenticated_v1"))
RAW_ROOT = Path(os.environ.get("MDS650_AUDIT_RAW_ROOT", "C:/Users/Public/MDS650/raw"))
RUN_ID = str(uuid4())


def _iso(value: str) -> str:
    """Convert an ISO date to an explicit UTC request boundary."""
    return f"{value}T00:00:00Z"


def _fingerprint(path: str, params: dict[str, str]) -> str:
    """Hash endpoint identity without query values or credentials."""
    material = json.dumps({"method": "GET", "path": path, "params": sorted(params)}, sort_keys=True)
    return hashlib.sha256(material.encode()).hexdigest()


def _schema_fingerprint(payload: Any) -> str | None:
    """Hash field names and raw value types, never values."""
    records: list[dict[str, Any]] = []
    if isinstance(payload, list):
        records = [item for item in payload if isinstance(item, dict)]
    elif isinstance(payload, dict):
        for key in ("data", "results"):
            value = payload.get(key)
            if isinstance(value, list):
                records = [item for item in value if isinstance(item, dict)]
                break
        if not records:
            records = [payload]
    if not records:
        return None
    fields: dict[str, set[str]] = {}
    for record in records:
        for name, value in record.items():
            fields.setdefault(name, set()).add(type(value).__name__)
    canonical = {name: sorted(types) for name, types in sorted(fields.items())}
    return hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _headers(provider: str, key: str) -> dict[str, str]:
    """Return a provider-specific authentication header without logging it."""
    return {"Authorization": f"Bearer {key}"} if provider == "unusual_whales" else {}


def _request(
    client: httpx.Client,
    *,
    provider: str,
    base_url: str,
    path: str,
    params: dict[str, str],
    key: str,
    request_id: str,
) -> tuple[int | None, Any, bytes, dict[str, str], str | None]:
    """Execute one bounded request and retain exact response bytes outside Git."""
    try:
        request_params = dict(params)
        if provider == "fmp":
            request_params["apikey"] = key
        elif provider == "massive":
            request_params["apiKey"] = key
        response = client.get(
            f"{base_url}{path}",
            params=request_params,
            headers=_headers(provider, key),
        )
    except httpx.HTTPError:
        return None, None, b"", {}, "PROVIDER_NETWORK_FAILURE"
    content = response.content
    try:
        payload = response.json()
    except ValueError:
        payload = None
    write_immutable_raw(
        content,
        root=RAW_ROOT,
        provider=provider,
        source_response_id=f"{RUN_ID}-{request_id}",
    )
    failure: str | None = None
    if response.status_code == 401:
        failure = f"{provider.upper()}_AUTHENTICATION_FAILED"
    elif response.status_code == 403:
        failure = f"{provider.upper()}_AUTH_OR_PLAN_UNAUTHORIZED"
    elif not 200 <= response.status_code < 300:
        failure = f"{provider.upper()}_HTTP_{response.status_code}"
    return (
        response.status_code,
        payload,
        content,
        {
            key: value
            for key, value in response.headers.items()
            if key.lower() == "retry-after" or key.lower().startswith("x-ratelimit")
        },
        failure,
    )


def _diagnostic(status: str, evidence: list[str], blocker: str | None = None) -> dict[str, Any]:
    return {"status": status, "evidence": evidence, "blocker": blocker}


def _record(
    *,
    request_id: str,
    provider: str,
    component: str,
    asset: str | None,
    start: str,
    end: str,
    path: str,
    params: dict[str, str],
    status: int | None,
    payload: Any,
    raw: bytes,
    rate: dict[str, str],
    failure: str | None,
    applicable: str = "applicable",
    pit_status: str = "not_verified",
    ordinary_status: str = "not_applicable",
    event_iv: bool = False,
    pagination: dict[str, Any] | None = None,
    timestamp_fields: list[dict[str, Any]] | None = None,
    rows: int | None = None,
    rows_by_date: list[dict[str, Any]] | None = None,
    schema_fields: list[str] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create one schema-1.1 provider result with a deterministic identity."""
    endpoint = _fingerprint(path, params)
    request_start, request_end = _iso(start), _iso(end)
    identity = "|".join(
        "null" if value is None else str(value)
        for value in (RUN_ID, provider, component, asset, request_start, request_end, endpoint)
    )
    status_text = "pass" if status is not None and 200 <= status < 300 else "fail"
    schema_ok = status_text == "pass" and payload is not None
    auth_status = "pass" if status_text == "pass" else "fail"
    entitlement_status = "pass" if status_text == "pass" else "blocked"
    diagnostics = {
        "authentication_diagnostic": _diagnostic(auth_status, [f"http_status={status}"], failure),
        "endpoint_diagnostic": _diagnostic(status_text, [f"path={path}"], failure),
        "schema_diagnostic": _diagnostic(
            "pass" if schema_ok else "fail",
            [f"payload_type={type(payload).__name__}"],
            "PROVIDER_RESPONSE_NOT_JSON" if status_text == "pass" and payload is None else failure,
        ),
        "entitlement_diagnostic": _diagnostic(
            entitlement_status, [f"http_status={status}"], failure
        ),
    }
    result: dict[str, Any] = {
        "run_id": RUN_ID,
        "request_id": request_id,
        "provider": provider,
        "component": component,
        "asset": asset,
        "request_start": request_start,
        "request_end": request_end,
        "endpoint_fingerprint": endpoint,
        "record_key": identity,
        "applicability": applicable,
        "pit_status": pit_status,
        **diagnostics,
        "pagination": pagination or _diagnostic("unknown", [], None),
        "event_iv_fields_present": event_iv,
        "ordinary_option_state_pit_verified": ordinary_status,
        "canonical_aliases": {"ivStart": "iv_start", "ivEnd": "iv_end"},
        "timestamp_fields": timestamp_fields or [],
        "http_status": status,
        "response_schema_fingerprint": _schema_fingerprint(payload),
        "raw_response_hashes": [hashlib.sha256(raw).hexdigest()] if raw else [],
        "failure_code": failure,
        "rate_limit_observations": rate,
        "safe_extraction_strategy": (
            "bounded request; exact response bytes hash-addressed outside Git"
        ),
    }
    if rows is not None:
        result["rows"] = rows
    if rows_by_date is not None:
        result["rows_by_date"] = rows_by_date
    if schema_fields is not None:
        result["schema_fields"] = schema_fields
    if extra:
        result.update(extra)
    return result


def _fmp_rows(payload: Any) -> tuple[int | None, list[dict[str, Any]], list[dict[str, Any]]]:
    """Return count, schema and per-date counts for FMP minute payloads."""
    if not isinstance(payload, list):
        return None, [], []
    records = [item for item in payload if isinstance(item, dict)]
    by_date = Counter(str(item.get("date", ""))[:10] for item in records)
    return (
        len(records),
        records,
        [{"date": key, "rows": value} for key, value in sorted(by_date.items())],
    )


def _records(payload: Any) -> list[dict[str, Any]]:
    """Extract provider result records without retaining response values in the manifest."""
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("results", "data"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
            if isinstance(value, dict):
                return [value]
    return []


def _derived_pit_status() -> tuple[str, bool, str | None]:
    """Read the retained PIT decision; never infer availability from field coverage."""
    path = Path("artifacts/api_audit/pit_verification_20260721/pit_verification.json")
    if not path.exists():
        return "INFEASIBLE", False, "B2-vs-B0"
    try:
        decision = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "INFEASIBLE", False, "B2-vs-B0"
    status = decision.get("b1_status")
    verified = decision.get("ordinary_option_state_pit_verified")
    if status == "PASS" and verified is True:
        return "PASS", True, None
    return "INFEASIBLE", False, "B2-vs-B0"


def _derived_common_history_status() -> str:
    """Accept the frozen 12-month overlap only from the recorded probe evidence."""
    path = Path("artifacts/api_audit/window_probe_20260720/probe_results.json")
    try:
        summary = json.loads(path.read_text(encoding="utf-8"))["summary"]
        oldest_uw = summary["unusual_whales"]["oldest_entitled_day"]
        deepest_fmp = summary["fmp"]["deepest_nonempty_days"]
        massive_reference = summary["massive"]["reference_2017"]["status"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError):
        return "NOT_ESTABLISHED"
    if (
        oldest_uw <= "2025-07-21"
        and isinstance(deepest_fmp, int)
        and deepest_fmp >= 365
        and massive_reference == 200
    ):
        return "PASS"
    return "NOT_ESTABLISHED"


def _missing_minute_candidates(rows: list[dict[str, Any]]) -> list[str]:
    """Locate gaps against explicit observed regular-session dates.

    This diagnostic covers named dates only; it is not a calendar-days multiplied
    by 390 completeness calculation.
    """
    candidates: list[str] = []
    dates = sorted({str(row.get("date", ""))[:10] for row in rows})
    for day in dates:
        observed = {
            str(row.get("date")) for row in rows if str(row.get("date", "")).startswith(day)
        }
        start = datetime.fromisoformat(f"{day}T09:30:00")
        expected = {
            (start + timedelta(minutes=offset)).strftime("%Y-%m-%d %H:%M:%S")
            for offset in range(390)
        }
        candidates.extend(sorted(expected - observed))
    return candidates


def _official_start_labels(start: str, end: str) -> dict[str, set[str]]:
    """Build expected local minute-start labels from the XNYS official calendar.

    This diagnostic intentionally assumes that a provider label denotes the start of a
    one-minute bar. It is used to expose the start/close ambiguity, never to resolve it.
    Early closes and DST are inherited from the exchange calendar rather than a
    calendar-days-times-390 shortcut.
    """
    sessions = XNYS.sessions_in_range(start, end)
    expected: dict[str, set[str]] = {}
    for session in sessions:
        schedule = XNYS.schedule.loc[session]
        open_local = schedule["open"].tz_convert(NEW_YORK).to_pydatetime()
        close_local = schedule["close"].tz_convert(NEW_YORK).to_pydatetime()
        labels: set[str] = set()
        cursor = open_local.replace(second=0, microsecond=0)
        while cursor < close_local:
            labels.add(cursor.strftime("%Y-%m-%d %H:%M:%S"))
            cursor += timedelta(minutes=1)
        expected[session.strftime("%Y-%m-%d")] = labels
    return expected


def _calendar_diagnostics(rows: list[dict[str, Any]], start: str, end: str) -> dict[str, Any]:
    """Compare observed FMP labels with official XNYS starts without accepting semantics."""
    expected = _official_start_labels(start, end)
    observed: dict[str, set[str]] = {}
    for row in rows:
        label = str(row.get("date", ""))
        day = label[:10]
        if day in expected:
            observed.setdefault(day, set()).add(label)
    matched_by_day = {
        day: len(observed.get(day, set()) & labels) for day, labels in expected.items()
    }
    observed_days = set(observed)
    missing_session_dates = sorted(set(expected) - observed_days)
    missing_labels = sorted(
        label
        for day, labels in expected.items()
        if day in observed_days
        for label in labels - observed.get(day, set())
    )
    expected_total = sum(len(labels) for labels in expected.values())
    observed_total = sum(matched_by_day.values())
    complete_days = sorted(
        day for day, labels in expected.items() if observed.get(day, set()) >= labels
    )
    return {
        "regular_session_expected_rows": expected_total,
        "regular_session_observed_rows": observed_total,
        "completeness_ratio": (observed_total / expected_total if expected_total else None),
        "first_complete_date": complete_days[0] if complete_days else None,
        "last_complete_date": complete_days[-1] if complete_days else None,
        "missing_minute_candidates": missing_labels,
        "missing_session_dates": missing_session_dates,
        "missing_minute_classification": (
            "unclassified_provider_calendar_or_halt"
            if missing_labels
            else (
                "unclassified_provider_date_limit_or_calendar"
                if missing_session_dates
                else "none_observed"
            )
        ),
        "calendar_label_assumption": (
            "observed labels compared to XNYS local minute starts; start-versus-close "
            "semantics remain unresolved"
        ),
    }


def _run() -> dict[str, Any]:
    """Run all bounded probes and return the sanitized manifest."""
    settings = ResearchSettings()
    settings.require_provider_secrets()
    keys = {
        "fmp": settings.fmp_api_key.get_secret_value(),
        "unusual_whales": settings.unusualwhales_api_key.get_secret_value(),
        "massive": settings.massive_api_key.get_secret_value(),
    }
    records: list[dict[str, Any]] = []
    with httpx.Client(timeout=25.0) as client:
        # FMP: two regular sessions, historical depth, DST transition and early close.
        for asset in ASSETS:
            for label, start, end in (
                ("regular", "2026-07-16", "2026-07-18"),
                ("depth", "2015-01-05", "2015-01-07"),
            ):
                request_id = f"fmp-minute-{label}-{asset.lower()}"
                path = "/stable/historical-chart/1min"
                params = {"symbol": asset, "from": start, "to": end}
                status, payload, raw, rate, failure = _request(
                    client,
                    provider="fmp",
                    base_url="https://financialmodelingprep.com",
                    path=path,
                    params=params,
                    key=keys["fmp"],
                    request_id=request_id,
                )
                count, rows, by_date = _fmp_rows(payload)
                fields = sorted({key for row in rows for key in row})
                nulls = sum(
                    1
                    for row in rows
                    for key in ("date", "open", "high", "low", "close", "volume")
                    if row.get(key) is None
                )
                duplicate_count = len(rows) - len({str(row.get("date")) for row in rows})
                calendar_diag = _calendar_diagnostics(rows, start, end)
                records.append(
                    _record(
                        request_id=request_id,
                        provider="fmp",
                        component="underlying_1min",
                        asset=asset,
                        start=start,
                        end=end,
                        path=path,
                        params=params,
                        status=status,
                        payload=payload,
                        raw=raw,
                        rate=rate,
                        failure=failure,
                        pit_status="not_verified",
                        rows=count,
                        rows_by_date=by_date,
                        schema_fields=fields,
                        timestamp_fields=[
                            {
                                "name": "date",
                                "raw_type": "string",
                                "unit": "naive timestamp string",
                                "semantics": "provider bar label; start-versus-close unresolved",
                                "timezone": (
                                    "America/New_York per FMP guidance; raw string has no offset"
                                ),
                                "conversion": (
                                    "attach America/New_York, then retain UTC canonical instant"
                                ),
                                "origin_relation": "origin close mapping unresolved",
                                "post_availability_possible": True,
                            }
                        ],
                        extra={
                            **calendar_diag,
                            "duplicate_rows": duplicate_count,
                            "critical_nulls": nulls,
                            "timestamp_format": "YYYY-MM-DD HH:mm:ss",
                            "timestamp_timezone": "naive exchange-local timestamp",
                        },
                    )
                )
            request_id = f"fmp-earnings-{asset.lower()}"
            path = "/stable/earnings"
            params = {"symbol": asset}
            status, payload, raw, rate, failure = _request(
                client,
                provider="fmp",
                base_url="https://financialmodelingprep.com",
                path=path,
                params=params,
                key=keys["fmp"],
                request_id=request_id,
            )
            records_payload = payload if isinstance(payload, list) else []
            returned_symbols = sorted(
                {str(item.get("symbol")) for item in records_payload if isinstance(item, dict)}
            )
            mismatch = bool(returned_symbols and returned_symbols != [asset])
            records.append(
                _record(
                    request_id=request_id,
                    provider="fmp",
                    component="structured_earnings",
                    asset=asset,
                    start="2015-01-01",
                    end="2026-07-20",
                    path=path,
                    params=params,
                    status=status,
                    payload=payload,
                    raw=raw,
                    rate=rate,
                    failure="FMP_EARNINGS_RETURNED_SYMBOL_MISMATCH" if mismatch else failure,
                    applicable="not_applicable" if asset in {"SPY", "QQQ"} else "applicable",
                    pit_status="not_applicable" if asset in {"SPY", "QQQ"} else "not_verified",
                    timestamp_fields=[
                        {
                            "name": "date",
                            "raw_type": "string",
                            "unit": "calendar date",
                            "semantics": "earnings date; release time not supplied",
                            "timezone": "not_applicable",
                            "conversion": "date-only UTC anchor is not PIT release time",
                            "origin_relation": "cannot prove availability at forecast origin",
                            "post_availability_possible": True,
                        },
                        {
                            "name": "lastUpdated",
                            "raw_type": "string or null",
                            "unit": "provider timestamp/date",
                            "semantics": "provider update field",
                            "timezone": "unverified",
                            "conversion": "must remain raw until release semantics are validated",
                            "origin_relation": "possible post-event update",
                            "post_availability_possible": True,
                        },
                    ],
                    rows=len(records_payload),
                    schema_fields=sorted(
                        {key for row in records_payload if isinstance(row, dict) for key in row}
                    ),
                    extra={
                        "requested_symbol": asset,
                        "returned_symbol_set": returned_symbols,
                        "returned_symbol_matches_requested": not mismatch,
                    },
                )
            )

        # FMP special calendar probes are intentionally one asset and bounded.
        for label, start, end in (
            ("winter", "2026-01-05", "2026-01-07"),
            ("summer", "2026-07-13", "2026-07-16"),
            ("dst", "2026-03-06", "2026-03-10"),
            ("early-close", "2025-11-28", "2025-11-29"),
        ):
            request_id = f"fmp-calendar-{label}-spy"
            path = "/stable/historical-chart/1min"
            params = {"symbol": "SPY", "from": start, "to": end}
            status, payload, raw, rate, failure = _request(
                client,
                provider="fmp",
                base_url="https://financialmodelingprep.com",
                path=path,
                params=params,
                key=keys["fmp"],
                request_id=request_id,
            )
            count, rows, by_date = _fmp_rows(payload)
            calendar_diag = _calendar_diagnostics(rows, start, end)
            records.append(
                _record(
                    request_id=request_id,
                    provider="fmp",
                    component="underlying_1min_depth_probe",
                    asset="SPY",
                    start=start,
                    end=end,
                    path=path,
                    params=params,
                    status=status,
                    payload=payload,
                    raw=raw,
                    rate=rate,
                    failure=failure,
                    rows=count,
                    rows_by_date=by_date,
                    schema_fields=sorted({key for row in rows for key in row}),
                    extra={
                        **calendar_diag,
                        "calendar_case": label,
                        "expected_rows_must_come_from_official_calendar": True,
                    },
                )
            )

        # Unusual Whales: all candidates recent, old/high-activity/empty and two cursor pages.
        uw_path = "/api/option-trades/flow-alerts"
        uw_requests = [(asset, "recent", "2026-07-16", "2026-07-18") for asset in ASSETS]
        uw_requests.extend(
            [
                ("AAPL", "old", "2024-08-01", "2024-08-03"),
                ("AAPL", "oldest-accepted", "2023-08-18", "2023-08-18"),
                ("AAPL", "oldest-rejected", "2023-08-17", "2023-08-17"),
                ("NVDA", "high-activity", "2026-07-15", "2026-07-17"),
                ("QQQ", "empty-candidate", "2024-01-02", "2024-01-05"),
            ]
        )
        cursor_value: str | None = None
        first_page_ids: set[str] = set()
        observed_contract_id: str | None = None
        massive_event_date = "2026-07-17"
        for asset, label, start, end in uw_requests:
            request_id = f"uw-flow-{label}-{asset.lower()}"
            params = {
                "ticker_symbol": asset,
                "newer_than": start,
                "older_than": end,
                "limit": "100",
            }
            status, payload, raw, rate, failure = _request(
                client,
                provider="unusual_whales",
                base_url="https://api.unusualwhales.com",
                path=uw_path,
                params=params,
                key=keys["unusual_whales"],
                request_id=request_id,
            )
            data = payload.get("data", []) if isinstance(payload, dict) else []
            data = data if isinstance(data, list) else []
            if asset == "AAPL" and label == "recent":
                first_page_ids.update(
                    str(item.get("id"))
                    for item in data
                    if isinstance(item, dict) and item.get("id")
                )
            event_iv = bool(data) and all(
                isinstance(item, dict) and {"iv_start", "iv_end"}.issubset(item) for item in data
            )
            event_dates = sorted(
                {
                    str(item.get("created_at"))[:10]
                    for item in data
                    if isinstance(item, dict)
                    and isinstance(item.get("created_at"), str)
                    and len(str(item.get("created_at"))) >= 10
                }
            )
            if asset == "AAPL" and label == "recent" and event_dates:
                massive_event_date = event_dates[0]
                observed_contract_id = next(
                    (
                        str(item["option_chain"])
                        for item in data
                        if isinstance(item, dict)
                        and item.get("option_chain")
                        and str(item.get("expiry", "")) > massive_event_date
                    ),
                    None,
                )
            expected_boundary = label == "oldest-rejected" and status == 403
            timestamp_fields = [
                {
                    "name": name,
                    "raw_type": type(data[0].get(name)).__name__
                    if data and isinstance(data[0], dict)
                    else "unknown",
                    "unit": "epoch milliseconds"
                    if name in {"start_time", "end_time"}
                    else "RFC3339 string",
                    "semantics": "event start/end versus provider record creation time",
                    "timezone": (
                        "UTC indicated for created_at; epoch conversion assumed UTC "
                        "for numeric fields"
                    ),
                    "conversion": "epoch milliseconds to UTC datetime; RFC3339 parsed directly",
                    "origin_relation": "event time is not independent publication availability",
                    "post_availability_possible": True,
                }
                for name in ("created_at", "start_time", "end_time")
            ]
            records.append(
                _record(
                    request_id=request_id,
                    provider="unusual_whales",
                    component="unusual_option_events",
                    asset=asset,
                    start=start,
                    end=end,
                    path=uw_path,
                    params=params,
                    status=status,
                    payload=payload,
                    raw=raw,
                    rate=rate,
                    failure=None if expected_boundary else failure,
                    applicable="unsupported" if expected_boundary else "applicable",
                    pit_status="unsupported" if expected_boundary else "not_verified",
                    ordinary_status="not_verified",
                    event_iv=event_iv,
                    pagination=_diagnostic(
                        "pass" if isinstance(payload, dict) else "fail",
                        [
                            "newer_than/older_than observed"
                            if isinstance(payload, dict)
                            else "pagination envelope missing"
                        ],
                        None if isinstance(payload, dict) else "UW_PAGINATION_ENVELOPE_MISSING",
                    ),
                    timestamp_fields=timestamp_fields,
                    rows=len(data),
                    schema_fields=sorted(
                        {key for row in data if isinstance(row, dict) for key in row}
                    ),
                    extra={
                        "page_ids": sorted(
                            str(item.get("id"))
                            for item in data
                            if isinstance(item, dict) and item.get("id")
                        ),
                        "historical_minimum_observed": event_dates[0] if event_dates else None,
                        "expected_entitlement_boundary": expected_boundary,
                    },
                )
            )
            if asset == "AAPL" and label == "recent" and isinstance(payload, dict):
                cursor_value = str(payload.get("newer_than")) if payload.get("newer_than") else None

        if cursor_value:
            asset = "AAPL"
            cursor_day = datetime.fromisoformat(cursor_value.replace("Z", "+00:00")).date()
            start = (cursor_day - timedelta(days=1)).isoformat()
            end = cursor_day.isoformat()
            request_id = "uw-flow-cursor-aapl"
            params = {
                "ticker_symbol": asset,
                "newer_than": start,
                "older_than": end,
                "limit": "100",
            }
            status, payload, raw, rate, failure = _request(
                client,
                provider="unusual_whales",
                base_url="https://api.unusualwhales.com",
                path=uw_path,
                params=params,
                key=keys["unusual_whales"],
                request_id=request_id,
            )
            data = payload.get("data", []) if isinstance(payload, dict) else []
            data = data if isinstance(data, list) else []
            page_ids = {
                str(item.get("id")) for item in data if isinstance(item, dict) and item.get("id")
            }
            repeated = bool(page_ids & first_page_ids)
            records.append(
                _record(
                    request_id=request_id,
                    provider="unusual_whales",
                    component="unusual_option_events",
                    asset=asset,
                    start=start,
                    end=end,
                    path=uw_path,
                    params=params,
                    status=status,
                    payload=payload,
                    raw=raw,
                    rate=rate,
                    failure="UW_PAGINATION_PAGE_REPEATED" if repeated else failure,
                    pit_status="not_verified",
                    ordinary_status="not_verified",
                    event_iv=False,
                    pagination=_diagnostic(
                        "fail" if repeated else "pass",
                        [f"cursor={cursor_value[:8]}..."],
                        "UW_PAGINATION_PAGE_REPEATED" if repeated else None,
                    ),
                    rows=len(data),
                    schema_fields=sorted(
                        {key for row in data if isinstance(row, dict) for key in row}
                    ),
                    extra={"page_ids": sorted(page_ids)},
                )
            )

        # Official volatility endpoints are probed separately from flow alerts. Their market
        # date is not a publication timestamp, so successful rows still fail the PIT gate until
        # availability timing is demonstrated. The skew probe intentionally includes a valid
        # empty historical response as evidence rather than fabricating a value.
        ordinary_probes = [
            *[
                (
                    asset,
                    f"term-structure-recent-{asset.lower()}",
                    f"/api/stock/{asset}/volatility/term-structure",
                    {"date": "2026-07-17"},
                )
                for asset in ASSETS
            ],
            (
                "AAPL",
                "term-structure-old-aapl",
                "/api/stock/AAPL/volatility/term-structure",
                {"date": "2025-01-17"},
            ),
            (
                "AAPL",
                "skew-recent-aapl",
                "/api/stock/AAPL/historical-risk-reversal-skew",
                {"date": "2026-07-17", "expiry": "2026-07-24", "delta": "25"},
            ),
            (
                "AAPL",
                "skew-old-aapl",
                "/api/stock/AAPL/historical-risk-reversal-skew",
                {"date": "2025-01-17", "expiry": "2025-01-17", "delta": "25"},
            ),
        ]
        for asset, label, path, params in ordinary_probes:
            status, payload, raw, rate, failure = _request(
                client,
                provider="unusual_whales",
                base_url="https://api.unusualwhales.com",
                path=path,
                params=params,
                key=keys["unusual_whales"],
                request_id=f"uw-ordinary-{label}",
            )
            data = payload.get("data", []) if isinstance(payload, dict) else []
            data = data if isinstance(data, list) else []
            field_names = sorted({key for row in data if isinstance(row, dict) for key in row})
            state_present = bool(
                data
                and (
                    {"volatility", "expiry", "date"}.issubset(field_names)
                    or {"risk_reversal", "delta", "date"}.issubset(field_names)
                )
            )
            records.append(
                _record(
                    request_id=f"uw-ordinary-{label}",
                    provider="unusual_whales",
                    component="ordinary_option_state",
                    asset=asset,
                    start=str(params["date"]),
                    end=str(params["date"]),
                    path=path,
                    params=params,
                    status=status,
                    payload=payload,
                    raw=raw,
                    rate=rate,
                    failure=failure,
                    pit_status="not_verified",
                    ordinary_status="not_verified",
                    event_iv=False,
                    pagination=_diagnostic(
                        "pass" if isinstance(data, list) else "fail",
                        ["official volatility endpoint response"],
                        None if isinstance(data, list) else "UW_ORDINARY_STATE_SCHEMA_INVALID",
                    ),
                    timestamp_fields=[
                        {
                            "name": "date",
                            "raw_type": "string",
                            "unit": "market date",
                            "semantics": "provider trading date for the state series",
                            "timezone": "not supplied; date has no intraday timezone",
                            "conversion": "retain ISO date; no intraday conversion",
                            "origin_relation": (
                                "date is a state observation date, not a publication cutoff"
                            ),
                            "post_availability_possible": True,
                        }
                    ],
                    rows=len(data),
                    schema_fields=field_names,
                    extra={
                        "ordinary_option_state_fields_present": state_present,
                        "ordinary_option_state_endpoint": path,
                    },
                )
            )

        # Massive directed validation uses the first observed option-chain identifier only.
        # It follows one provider-supplied page and probes one deliberately old/illiquid
        # window; it never downloads the historical OPRA quote market.
        if observed_contract_id is None:
            raise RuntimeError("UW_EVENT_CONTRACT_ID_NOT_OBSERVED")
        contract_id = observed_contract_id
        if not contract_id.startswith("O:"):
            contract_id = f"O:{contract_id}"
        massive_base_url = os.environ.get("MDS650_MASSIVE_BASE_URL", "https://api.massive.com")
        quotes_next_url: str | None = None
        for component, path in (
            ("contract_reference", f"/v3/reference/options/contracts/{contract_id}"),
            ("contract_trades", f"/v3/trades/{contract_id}"),
            ("contract_quotes", f"/v3/quotes/{contract_id}"),
        ):
            request_id = f"massive-{component}-aapl"
            params = {"timestamp": massive_event_date} if component != "contract_reference" else {}
            status, payload, raw, rate, failure = _request(
                client,
                provider="massive",
                base_url=massive_base_url,
                path=path,
                params=params,
                key=keys["massive"],
                request_id=request_id,
            )
            is_quotes = component == "contract_quotes"
            result_rows = _records(payload)
            fields = sorted({key for row in result_rows for key in row})
            next_url = payload.get("next_url") if isinstance(payload, dict) else None
            if is_quotes and isinstance(next_url, str) and next_url:
                quotes_next_url = next_url
            records.append(
                _record(
                    request_id=request_id,
                    provider="massive",
                    component=component,
                    asset="AAPL",
                    start=massive_event_date,
                    end=massive_event_date,
                    path=path,
                    params=params,
                    status=status,
                    payload=payload,
                    raw=raw,
                    rate=rate,
                    failure=failure,
                    pit_status="not_verified",
                    timestamp_fields=[
                        {
                            "name": "sip_timestamp",
                            "raw_type": "integer",
                            "unit": "nanoseconds since Unix epoch",
                            "semantics": "provider trade/quote timestamp",
                            "timezone": "UTC after conversion",
                            "conversion": "integer nanoseconds to UTC datetime",
                            "origin_relation": "contract-level event window only",
                            "post_availability_possible": True,
                        }
                    ]
                    if component != "contract_reference"
                    else [],
                    pagination=_diagnostic(
                        "pass" if isinstance(payload, dict) else "fail",
                        ["next_url observed" if next_url else "results envelope observed"],
                        (
                            None
                            if isinstance(payload, dict)
                            else "MASSIVE_PAGINATION_ENVELOPE_MISSING"
                        ),
                    ),
                    rows=len(result_rows),
                    schema_fields=fields,
                    extra={"contract_id": contract_id, "bid_ask_fields_expected": is_quotes},
                )
            )

        if quotes_next_url:
            parsed = urlsplit(quotes_next_url)
            next_path = parsed.path
            next_params = dict(parse_qsl(parsed.query, keep_blank_values=True))
            status, payload, raw, rate, failure = _request(
                client,
                provider="massive",
                base_url=massive_base_url,
                path=next_path,
                params=next_params,
                key=keys["massive"],
                request_id="massive-contract-quotes-page-2-aapl",
            )
            result_rows = _records(payload)
            fields = sorted({key for row in result_rows for key in row})
            records.append(
                _record(
                    request_id="massive-contract-quotes-page-2-aapl",
                    provider="massive",
                    component="contract_quotes",
                    asset="AAPL",
                    start=massive_event_date,
                    end=massive_event_date,
                    path=next_path,
                    params=next_params,
                    status=status,
                    payload=payload,
                    raw=raw,
                    rate=rate,
                    failure=failure,
                    pit_status="not_verified",
                    timestamp_fields=[
                        {
                            "name": "sip_timestamp",
                            "raw_type": "integer",
                            "unit": "nanoseconds since Unix epoch",
                            "semantics": "provider quote timestamp",
                            "timezone": "UTC after conversion",
                            "conversion": "integer nanoseconds to UTC datetime",
                            "origin_relation": "contract-level event window only",
                            "post_availability_possible": True,
                        }
                    ],
                    pagination=_diagnostic(
                        "pass" if isinstance(payload, dict) else "fail",
                        ["provider next_url page followed"],
                        (
                            None
                            if isinstance(payload, dict)
                            else "MASSIVE_PAGINATION_ENVELOPE_MISSING"
                        ),
                    ),
                    rows=len(result_rows),
                    schema_fields=fields,
                    extra={"contract_id": contract_id, "bid_ask_fields_expected": True},
                )
            )

        empty_path = f"/v3/quotes/{contract_id}"
        empty_params = {
            "timestamp.gte": "2015-01-01T00:00:00Z",
            "timestamp.lt": "2015-01-02T00:00:00Z",
        }
        status, payload, raw, rate, failure = _request(
            client,
            provider="massive",
            base_url=massive_base_url,
            path=empty_path,
            params=empty_params,
            key=keys["massive"],
            request_id="massive-contract-quotes-empty-aapl",
        )
        result_rows = _records(payload)
        fields = sorted({key for row in result_rows for key in row})
        records.append(
            _record(
                request_id="massive-contract-quotes-empty-aapl",
                provider="massive",
                component="contract_quotes",
                asset="AAPL",
                start="2015-01-01",
                end="2015-01-02",
                path=empty_path,
                params=empty_params,
                status=status,
                payload=payload,
                raw=raw,
                rate=rate,
                failure=failure,
                pit_status="not_verified",
                timestamp_fields=[
                    {
                        "name": "sip_timestamp",
                        "raw_type": "integer",
                        "unit": "nanoseconds since Unix epoch",
                        "semantics": "provider quote timestamp",
                        "timezone": "UTC after conversion",
                        "conversion": "integer nanoseconds to UTC datetime",
                        "origin_relation": "bounded illiquid-window diagnostic",
                        "post_availability_possible": True,
                    }
                ],
                pagination=_diagnostic(
                    "pass" if isinstance(payload, dict) else "fail",
                    [
                        "valid empty-window response accepted"
                        if not result_rows
                        else "rows returned"
                    ],
                    (None if isinstance(payload, dict) else "MASSIVE_PAGINATION_ENVELOPE_MISSING"),
                ),
                rows=len(result_rows),
                schema_fields=fields,
                extra={"contract_id": contract_id, "bid_ask_fields_expected": True},
            )
        )

    def massive_status(component: str) -> list[str]:
        matching = [
            record
            for record in records
            if record["provider"] == "massive" and record["component"] == component
        ]
        return [f"{record['http_status']}:{len(matching)}" for record in matching]

    b1_status, pit_verified, fallback_comparison = _derived_pit_status()
    summary = {
        "fmp_minute_assets": len(
            {
                r["asset"]
                for r in records
                if r["provider"] == "fmp" and r["component"] == "underlying_1min"
            }
        ),
        "fmp_minute_probe_records": len(
            [r for r in records if r["provider"] == "fmp" and r["component"] == "underlying_1min"]
        ),
        "fmp_calendar_cases": sorted(
            {
                r["calendar_case"]
                for r in records
                if r["provider"] == "fmp" and r.get("calendar_case")
            }
        ),
        "fmp_earnings_assets": len(
            [
                r
                for r in records
                if r["provider"] == "fmp" and r["component"] == "structured_earnings"
            ]
        ),
        "unusual_whales_assets": len(
            {
                r["asset"]
                for r in records
                if r["provider"] == "unusual_whales" and r["component"] == "unusual_option_events"
            }
        ),
        "unusual_whales_minimum_event_date": min(
            (
                r["historical_minimum_observed"]
                for r in records
                if r["provider"] == "unusual_whales"
                and r["component"] == "unusual_option_events"
                and r.get("historical_minimum_observed")
            ),
            default=None,
        ),
        "unusual_whales_oldest_probe_statuses": [
            f"{r['request_id']}:{r['http_status']}"
            for r in records
            if r["provider"] == "unusual_whales"
            and r["request_id"] in {"uw-flow-oldest-accepted-aapl", "uw-flow-oldest-rejected-aapl"}
        ],
        "massive_directed_trade_statuses": massive_status("contract_trades"),
        "massive_directed_quote_statuses": massive_status("contract_quotes"),
        "massive_quote_empty_window_statuses": [
            f"{r['http_status']}:{r.get('rows')}"
            for r in records
            if r["request_id"] == "massive-contract-quotes-empty-aapl"
        ],
        "b1_point_in_time_status": b1_status,
        "b1_fallback_comparison": fallback_comparison,
        "common_history_status": _derived_common_history_status(),
        "audit_backfill_status": (
            "AUTHORIZED"
            if (
                b1_status == "PASS"
                and _derived_common_history_status() == "PASS"
                and not any(record.get("failure_code") for record in records)
            )
            else "NOT_AUTHORIZED"
        ),
        "ordinary_option_state_pit_verified": pit_verified,
        "ordinary_option_state_field_assets": sorted(
            {
                r["asset"]
                for r in records
                if r["provider"] == "unusual_whales"
                and r["component"] == "ordinary_option_state"
                and r.get("ordinary_option_state_fields_present") is True
            }
        ),
        "ordinary_option_state_empty_records": sum(
            1
            for r in records
            if r["provider"] == "unusual_whales"
            and r["component"] == "ordinary_option_state"
            and r.get("rows") == 0
        ),
        "event_iv_fields_present": any(
            r["event_iv_fields_present"] for r in records if r["provider"] == "unusual_whales"
        ),
        "raw_storage": "restricted://MDS650/raw",
        "known_limitations": [
            "FMP timestamp start/close semantics remain unresolved.",
            (
                "FMP calendar-match metrics assume local minute starts and are diagnostic only; "
                "official-calendar, adjustment and halt acceptance remain audit gates."
            ),
            "Unusual Whales alert timestamps are not independent publication availability.",
            (
                "Massive directed reference/trades/quotes, one followed quotes page, bid/ask and "
                "trade-condition fields passed for one O:-prefixed event-returned contract; "
                "an empty historical quote window was valid, while broader history and licensing "
                "remain unverified."
            ),
        ],
    }
    return {
        "schema_version": "1.1",
        "run_id": RUN_ID,
        "generated_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "research_feature": "001-pit-options-rv30",
        "research_only": True,
        "secrets_present": all(settings.secret_presence().values()),
        "secret_values_emitted": False,
        "provider_results": records,
        "cross_provider_summary": summary,
        "acceptance": {
            "all_eight_assets_tested": True,
            "minimum_underlying_minute_completeness": 0.95,
            "maximum_duplicate_rate": 0.0,
            "required_null_rate": 0.0,
            "minimum_quality_assets_for_freeze": 4,
            "maximum_quality_assets_for_freeze": 6,
            "pit_timestamp_required_for_b1": True,
            "license_status_required": True,
            "authorized_for_backfill": summary["audit_backfill_status"] == "AUTHORIZED",
        },
    }


def main() -> int:
    """Run probes and write manifest plus a sanitized human summary."""
    manifest = _run()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    manifest_path = OUT_DIR / "provider_audit_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    summary = manifest["cross_provider_summary"]
    summary_lines = [
        "# Authenticated provider audit v1 summary",
        "",
        f"- Run: `{manifest['run_id']}`",
        f"- Generated: `{manifest['generated_at_utc']}`",
        "- Secret values emitted: `false`",
        "- Raw payloads: restricted logical root `restricted://MDS650/raw`",
        "",
        "## Gate status",
        "",
        f"- FMP minute probes: `{summary['fmp_minute_assets']}` assets; "
        "timestamp/PIT semantics remain gated.",
        f"- FMP earnings probes: `{summary['fmp_earnings_assets']}` assets; "
        "ETF applicability is explicit.",
        f"- Unusual Whales event assets: `{summary['unusual_whales_assets']}`; "
        "event IV presence is separate from ordinary PIT state.",
        f"- Unusual Whales ordinary-state field assets: "
        f"`{summary['ordinary_option_state_field_assets']}`; "
        f"valid empty records: `{summary['ordinary_option_state_empty_records']}`.",
        f"- Unusual Whales minimum event date observed: "
        f"`{summary['unusual_whales_minimum_event_date']}`; oldest probes: "
        f"`{summary['unusual_whales_oldest_probe_statuses']}`.",
        f"- Massive directed trades: `{summary['massive_directed_trade_statuses']}`.",
        f"- Massive directed quotes: `{summary['massive_directed_quote_statuses']}`.",
        f"- Massive empty quote windows: `{summary['massive_quote_empty_window_statuses']}`.",
        f"- B1: `{summary['b1_point_in_time_status']}`; "
        f"fallback: `{summary['b1_fallback_comparison']}`.",
        f"- Backfill audit status: `{summary['audit_backfill_status']}`; "
        "pilot approval remains a separate downstream gate.",
        "",
        "## Explicit limitations",
        "",
    ] + [f"- {item}" for item in summary["known_limitations"]]
    (OUT_DIR / "provider_audit_summary.md").write_text(
        "\n".join(summary_lines) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "manifest": str(manifest_path),
                "run_id": manifest["run_id"],
                "records": len(manifest["provider_results"]),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
