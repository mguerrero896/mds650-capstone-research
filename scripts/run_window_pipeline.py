"""Run the bounded real pilot and the authorized frozen-window backfill.

The script stores exact provider bytes outside Git, normalizes only validated
schemas, and never turns missing PIT availability into a predictor.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import time
from bisect import bisect_left, bisect_right
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import polars as pl
from exchange_calendars import get_calendar

from mds650.asset_selection import AssetQuality, freeze_assets
from mds650.config import ResearchSettings
from mds650.contracts import CANDIDATE_ASSETS, ForecastOrigin, RealizedVarianceTarget
from mds650.normalize import normalize_underlying_bars
from mds650.pilot import PilotResult, build_pilot
from mds650.providers.fmp import parse_earnings_payload
from mds650.providers.unusual_whales import parse_flow_alert_payload
from mds650.storage import write_immutable_raw
from mds650.targets import compute_realized_variance
from mds650.time import to_new_york

ASSETS = tuple(sorted(CANDIDATE_ASSETS))
START = date(2025, 7, 21)
END = date(2026, 7, 21)  # exclusive: last fully closed session is included
PILOT_END = date(2025, 7, 29)
RAW_ROOT = Path(os.environ.get("MDS650_RAW_ROOT", r"C:\Users\Public\MDS650\raw"))
DATA_ROOT = Path(os.environ.get("MDS650_DATA_ROOT", r"C:\Users\Public\MDS650\datasets"))
OUT_ROOT = Path("artifacts/pipeline_runs/window_20260721")
XNYS = get_calendar("XNYS")


def _secret(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"MISSING_SECRET:{name}")
    return value


def _sessions(start: date, end: date) -> list[date]:
    return [
        stamp.date()
        for stamp in XNYS.sessions_in_range(
            start.isoformat(), (end - timedelta(days=1)).isoformat()
        )
    ]


def _request(
    client: httpx.Client,
    *,
    provider: str,
    url: str,
    params: dict[str, str],
    key_name: str,
    run_id: str,
    label: str,
) -> tuple[Any, str]:
    """GET JSON with query authentication and immutable raw persistence."""
    key = _secret(key_name)
    request_params = dict(params)
    if provider == "fmp":
        request_params["apikey"] = key
    elif provider == "massive":
        request_params["apiKey"] = key
    headers = {"Authorization": f"Bearer {key}"} if provider == "unusual_whales" else {}
    for attempt in range(4):
        response = client.get(url, params=request_params, headers=headers)
        if response.status_code == 200:
            reference = write_immutable_raw(
                response.content,
                root=RAW_ROOT,
                provider=provider,
                source_response_id=f"{run_id}-{label}-{hashlib.sha256(response.content).hexdigest()[:16]}",
            )
            return response.json(), reference.raw_sha256
        if response.status_code in {429, 500, 502, 503, 504} and attempt < 3:
            time.sleep(2**attempt)
            continue
        raise RuntimeError(f"{provider.upper()}_HTTP_{response.status_code}:{label}")
    raise RuntimeError(f"{provider.upper()}_RETRY_EXHAUSTED:{label}")


def _fmp_rows(
    client: httpx.Client, *, assets: tuple[str, ...], start: date, end: date, run_id: str
) -> tuple[dict[str, list[dict[str, object]]], list[str]]:
    """Fetch three-session FMP chunks; the endpoint returns at most that depth."""
    sessions = _sessions(start, end)
    rows: dict[str, list[dict[str, object]]] = {asset: [] for asset in assets}
    hashes: list[str] = []
    for asset in assets:
        for offset in range(0, len(sessions), 3):
            chunk = sessions[offset : offset + 3]
            payload, digest = _request(
                client,
                provider="fmp",
                url="https://financialmodelingprep.com/stable/historical-chart/1min",
                params={
                    "symbol": asset,
                    "from": chunk[0].isoformat(),
                    "to": chunk[-1].isoformat(),
                },
                key_name="FMP_API_KEY",
                run_id=run_id,
                label=f"fmp-{asset}-{chunk[0]}-{chunk[-1]}",
            )
            if not isinstance(payload, list):
                raise RuntimeError(f"FMP_SCHEMA_DRIFT:{asset}:{chunk[0]}")
            rows[asset].extend(row for row in payload if isinstance(row, dict))
            hashes.append(digest)
    for asset in assets:
        dedup: dict[str, dict[str, object]] = {}
        for row in rows[asset]:
            key = str(row.get("date"))
            if key in dedup and dedup[key] != row:
                raise RuntimeError(f"FMP_CONFLICTING_DUPLICATE:{asset}:{key}")
            dedup[key] = row
        rows[asset] = [dedup[key] for key in sorted(dedup)]
    return rows, hashes


def _uw_window(
    client: httpx.Client, *, asset: str, start: date, end: date, run_id: str
) -> tuple[list[dict[str, Any]], list[str], bool]:
    """Fetch non-overlapping calendar-session blocks under the 500-row cap."""
    rows: list[dict[str, Any]] = []
    hashes: list[str] = []
    capped = False

    def fetch_block(block: list[date]) -> None:
        nonlocal capped
        if not block:
            return
        block_start, block_end = block[0], block[-1] + timedelta(days=1)
        payload, digest = _request(
            client,
            provider="unusual_whales",
            url="https://api.unusualwhales.com/api/option-trades/flow-alerts",
            params={
                "ticker_symbol": asset,
                "newer_than": f"{block_start}T00:00:00Z",
                "older_than": f"{block_end}T00:00:00Z",
                "limit": "500",
            },
            key_name="UNUSUALWHALES_API_KEY",
            run_id=run_id,
            label=f"uw-{asset}-{block_start}-{block_end}",
        )
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
            raise RuntimeError(f"UW_SCHEMA_DRIFT:{asset}:{block_start}")
        page = [row for row in payload["data"] if isinstance(row, dict)]
        hashes.append(digest)
        if len(page) == 500 and len(block) > 1:
            midpoint = max(len(block) // 2, 1)
            fetch_block(block[:midpoint])
            fetch_block(block[midpoint:])
            return
        rows.extend(page)
        capped = capped or len(page) == 500

    sessions = _sessions(start, end)
    for offset in range(0, len(sessions), 3):
        fetch_block(sessions[offset : offset + 3])
    return rows, hashes, capped


def _earnings(
    client: httpx.Client, *, assets: tuple[str, ...], run_id: str
) -> tuple[list[Any], list[str]]:
    events: list[Any] = []
    hashes: list[str] = []
    for asset in assets:
        payload, digest = _request(
            client,
            provider="fmp",
            url="https://financialmodelingprep.com/stable/earnings",
            params={"symbol": asset},
            key_name="FMP_API_KEY",
            run_id=run_id,
            label=f"earnings-{asset}",
        )
        events.extend(
            parse_earnings_payload(
                payload, run_id=run_id, source_response_id=f"fmp-earnings-{asset}"
            )
        )
        hashes.append(digest)
    return events, hashes


def _write_pilot(
    result: PilotResult,
    *,
    run_id: str,
    raw_hashes: list[str],
    label: str,
    window_start: date,
    window_end: date,
    duplicate_event_count: int,
    capped_windows: list[str],
) -> dict[str, Any]:
    output = DATA_ROOT / "window_20260721" / label
    output.mkdir(parents=True, exist_ok=True)
    tables = {
        "underlying_1min": result.underlying_bars,
        "corporate_events": result.corporate_events,
        "unusual_option_events": result.unusual_events,
        "option_state_snapshots": result.option_states,
        "option_trades": result.option_trades,
        "option_quotes": result.option_quotes,
        "forecast_origins": result.origins,
        "rv30_targets": result.targets,
        "row_trace": result.row_trace,
    }
    counts: dict[str, int] = {}
    for name, values in tables.items():
        rows = [
            value.model_dump(mode="json") if hasattr(value, "model_dump") else dict(value)
            for value in values
        ]
        frame = pl.DataFrame(rows, strict=False)
        frame.write_parquet(output / f"{name}.parquet")
        counts[name] = frame.height
    manifest = {
        "run_id": run_id,
        "mode": label,
        "study_window_start": window_start.isoformat(),
        "study_window_end_exclusive": window_end.isoformat(),
        "candidate_assets": list(ASSETS),
        "frozen_assets": list(result.frozen_assets.assets),
        "row_counts": counts,
        "target_exclusions": len(result.target_exclusions),
        "event_no_event_counts": result.event_no_event_counts,
        "target_contract": {
            "anchor_plus_future_closes": 31,
            "future_log_returns": 30,
            "formula_version": "rv30-v1",
        },
        "raw_response_hash_count": len(raw_hashes),
        "raw_response_hashes": sorted(set(raw_hashes)),
        "duplicate_event_records_removed": duplicate_event_count,
        "capped_uw_windows": capped_windows,
        "event_coverage_complete": not capped_windows,
        "b1_status": "INFEASIBLE",
        "fallback_comparison": "B2-vs-B0",
        "authorized_for_modeling": False,
        "pit_warning": (
            "UW option-event and ordinary-state publication availability is not independently "
            "verified; no B1/B2 predictor claim is authorized."
        ),
    }
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    (OUT_ROOT / f"{label}_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


def _write_backfill(
    *,
    raw_underlying: dict[str, list[dict[str, object]]],
    earnings: list[Any],
    unusual: list[Any],
    run_id: str,
    raw_hashes: list[str],
    capped_windows: list[str],
    duplicate_event_count: int = 0,
) -> dict[str, Any]:
    """Write component tables and vectorized RV30 without the pilot cross-product."""
    normalized: dict[str, list[Any]] = {}
    origins: list[ForecastOrigin] = []
    targets: list[RealizedVarianceTarget] = []
    quality: list[AssetQuality] = []
    events_by_asset: dict[str, list[datetime]] = {asset: [] for asset in ASSETS}
    for event in unusual:
        events_by_asset.setdefault(event.asset, []).append(event.event_time_utc)
    for asset in ASSETS:
        bars = normalize_underlying_bars(
            raw_underlying[asset],
            asset=asset,
            run_id=run_id,
            source_response_id=f"fmp-{asset}",
            source_timezone="America/New_York",
        )
        bars.sort(key=lambda bar: bar.bar_start_utc)
        normalized[asset] = bars
        expected = sum(
            len(XNYS.session_minutes(session))
            for session in XNYS.sessions_in_range(
                START.isoformat(), (END - timedelta(days=1)).isoformat()
            )
        )
        quality.append(
            AssetQuality(
                asset=asset,
                completeness_ratio=min(len(bars) / expected, 1.0) if expected else 0.0,
                duplicate_rate=0.0,
                critical_null_rate=0.0,
                history_start=min(bar.bar_start_utc.date() for bar in bars),
                history_end=max(bar.bar_start_utc.date() for bar in bars),
            )
        )
        by_time = {bar.bar_start_utc: bar for bar in bars}
        event_times = sorted(events_by_asset.get(asset, []))
        for bar in bars:
            local = to_new_york(bar.bar_start_utc)
            if local.minute % 5 or local.second or local.microsecond:
                continue
            future_times = [bar.bar_start_utc + timedelta(minutes=i) for i in range(1, 31)]
            future = [by_time.get(stamp) for stamp in future_times]
            if any(item is None for item in future):
                continue
            event_present = bisect_right(event_times, bar.bar_start_utc) > bisect_left(
                event_times, bar.bar_start_utc - timedelta(minutes=5)
            )
            origin = ForecastOrigin(
                run_id=run_id,
                source_provider="derived",
                source_response_id=f"fmp-{asset}",
                observed_at_utc=bar.bar_start_utc,
                origin_id=f"{asset}:{bar.bar_start_utc.isoformat()}",
                asset=asset,
                origin_start_utc=bar.bar_start_utc,
                predictor_cutoff_utc=bar.bar_start_utc,
                event_presence=event_present,
                source_trace_ids=[bar.source_response_id],
            )
            rv = compute_realized_variance(
                bar.close, [item.close for item in future if item is not None]
            )
            origins.append(origin)
            targets.append(
                RealizedVarianceTarget(
                    origin_id=origin.origin_id,
                    horizon_minutes=30,
                    future_close_count=30,
                    rv_30m=rv,
                    log_rv_30m=math.log(rv + 1e-12),
                    future_close_start_utc=future_times[0],
                    future_close_end_utc=future_times[-1],
                    target_formula_version="rv30-v1",
                    validity="valid",
                )
            )
    frozen = freeze_assets(quality)
    output = DATA_ROOT / "window_20260721" / "backfill"
    output.mkdir(parents=True, exist_ok=True)
    tables = {
        "underlying_1min": [item for values in normalized.values() for item in values],
        "corporate_events": earnings,
        "unusual_option_events": unusual,
        "option_state_snapshots": [],
        "option_trades": [],
        "option_quotes": [],
        "forecast_origins": origins,
        "rv30_targets": targets,
    }
    counts: dict[str, int] = {}
    for name, values in tables.items():
        rows = [
            value.model_dump(mode="json") if hasattr(value, "model_dump") else dict(value)
            for value in values
        ]
        frame = pl.DataFrame(rows, strict=False)
        frame.write_parquet(output / f"{name}.parquet")
        counts[name] = frame.height
    manifest = {
        "run_id": run_id,
        "mode": "backfill",
        "study_window_start": START.isoformat(),
        "study_window_end_exclusive": END.isoformat(),
        "candidate_assets": list(ASSETS),
        "frozen_assets": list(frozen.assets),
        "row_counts": counts,
        "duplicate_event_records_removed": duplicate_event_count,
        "capped_uw_windows": capped_windows,
        "event_coverage_complete": not capped_windows,
        "raw_response_hash_count": len(raw_hashes),
        "target_contract": {
            "anchor_plus_future_closes": 31,
            "future_log_returns": 30,
            "formula_version": "rv30-v1",
        },
        "b1_status": "INFEASIBLE",
        "fallback_comparison": "B2-vs-B0",
        "benchmark_status": "NOT_RUN_PIT_GATE",
        "authorized_for_modeling": False,
        "pit_warning": (
            "Option-event publication availability and ordinary option-state PIT timestamps "
            "remain unverified; no B1/B2 predictor claim is authorized."
        ),
    }
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    (OUT_ROOT / "backfill_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (OUT_ROOT / "benchmark_manifest.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "B0": "NOT_RUN_PIT_GATE",
                "B1": "INFEASIBLE",
                "B2": "NOT_RUN_PIT_GATE",
                "primary_claim": "B2-vs-B1 not authorized",
                "fallback": "B2-vs-B0 declared but not evaluated",
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return manifest


def run(mode: str) -> dict[str, Any]:
    """Run the real bounded pilot or the frozen-window underlying/event backfill."""
    settings = ResearchSettings()
    settings.require_provider_secrets()
    run_id = str(uuid4())
    start, end = (START, PILOT_END) if mode == "pilot" else (START, END)
    with httpx.Client(timeout=60.0) as client:
        raw_underlying, fmp_hashes = _fmp_rows(
            client, assets=ASSETS, start=start, end=end, run_id=run_id
        )
        earnings, earnings_hashes = _earnings(client, assets=ASSETS, run_id=run_id)
        unusual: list[Any] = []
        uw_hashes: list[str] = []
        capped_windows: list[str] = []
        for asset in ASSETS:
            rows, hashes, capped = _uw_window(
                client, asset=asset, start=start, end=end, run_id=run_id
            )
            unusual.extend(
                parse_flow_alert_payload(
                    {"data": rows}, run_id=run_id, source_response_id=f"uw-{asset}-{start}-{end}"
                )
            )
            uw_hashes.extend(hashes)
            if capped:
                capped_windows.append(asset)
    unique_events: dict[str, Any] = {}
    for event in unusual:
        unique_events.setdefault(event.event_id, event)
    duplicate_event_count = len(unusual) - len(unique_events)
    unusual = list(unique_events.values())
    if mode == "backfill":
        return _write_backfill(
            raw_underlying=raw_underlying,
            earnings=earnings,
            unusual=unusual,
            run_id=run_id,
            raw_hashes=fmp_hashes + earnings_hashes + uw_hashes,
            capped_windows=capped_windows,
            duplicate_event_count=duplicate_event_count,
        )
    result = build_pilot(
        raw_underlying=raw_underlying,
        corporate_events=earnings,
        unusual_events=unusual,
        option_states=[],
        option_trades=[],
        option_quotes=[],
        run_id=run_id,
        source_timezone="America/New_York",
        expected_rows_per_asset=None,
    )
    manifest = _write_pilot(
        result,
        run_id=run_id,
        raw_hashes=fmp_hashes + earnings_hashes + uw_hashes,
        label=mode,
        window_start=start,
        window_end=end,
        duplicate_event_count=duplicate_event_count,
        capped_windows=capped_windows,
    )
    (OUT_ROOT / f"{mode}_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


def main() -> int:
    """Parse mode and emit a sanitized summary."""
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("pilot", "backfill"))
    args = parser.parse_args()
    manifest = run(args.mode)
    print(
        json.dumps(
            {
                k: manifest[k]
                for k in (
                    "run_id",
                    "mode",
                    "row_counts",
                    "frozen_assets",
                    "b1_status",
                    "fallback_comparison",
                    "capped_uw_windows",
                )
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
