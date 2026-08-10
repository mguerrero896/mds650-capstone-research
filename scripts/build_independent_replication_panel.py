"""Build the independent replication origins, FMP/B0 and target-free B2 inputs.

The script deliberately separates acquisition and outcome access.  ``fmp``
normalizes exact-session bars, ``b0-training`` may read RV30 only for the 60
warm-up sessions, and ``b2`` never reads RV30 or QLIKE.  The target block is
left untouched until the preregistered evaluation command opens it once.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from collections.abc import Mapping
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import exchange_calendars as xcals  # type: ignore[import-untyped]
import httpx
import polars as pl
from build_b2_calibration_20d import _normalize_fmp_session_rows

from mds650.phase5_storage import sha256_file
from mds650.phase6 import (
    B0V2_FEATURES,
    OUTCOME_ASSETS,
    aggregate_b2_activity,
    build_b0v2_features,
    build_b2v2_from_activity,
)
from mds650.study_design import canonical_sha256

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_ROOT = ROOT / "artifacts" / "independent_replication"
WINDOW_PATH = ARTIFACT_ROOT / "window_manifest.json"
ACQUISITION_PATH = ARTIFACT_ROOT / "acquisition_manifest.json"
DATA_ROOT = Path("D:/MDS650/independent_replication_30")
RAW_FMP_ROOT = DATA_ROOT / "raw" / "fmp"
DERIVED_ROOT = DATA_ROOT / "derived"
BARS_PATH = DERIVED_ROOT / "underlying_1min_90d.parquet"
ORIGINS_PATH = DERIVED_ROOT / "origins_90d.parquet"
B0_WARMUP_PATH = DERIVED_ROOT / "b0_warmup_60d.parquet"
B2_ROOT = DERIVED_ROOT / "b2_activity"
B2_PRIMARY_PATH = DERIVED_ROOT / "b2_primary_90d.parquet"
NY = ZoneInfo("America/New_York")
ENDPOINT = "https://financialmodelingprep.com/stable/historical-chart/1min"
MARKET_ASSETS = (*OUTCOME_ASSETS, "SPY", "QQQ")
B2_SPECS = {
    "primary_5m_60s": (5, 60),
    "window_15m_60s": (15, 60),
    "window_30m_60s": (30, 60),
    "latency_5m_120s": (5, 120),
    "latency_5m_300s": (5, 300),
}


def _secret(name: str) -> str:
    """Return a required secret without exposing its value."""
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"MISSING_SECRET:{name}")
    return value


def _load_json(path: Path) -> dict[str, Any]:
    """Load one JSON object and reject malformed manifests."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"JSON_OBJECT_REQUIRED:{path.name}")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    """Write a deterministic JSON manifest atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    unsigned = {key: value for key, value in payload.items() if key != "manifest_sha256"}
    payload = {**unsigned, "manifest_sha256": canonical_sha256(unsigned)}
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _window() -> dict[str, Any]:
    """Validate the frozen 60-warm-up/30-target allow-list."""
    window = _load_json(WINDOW_PATH)
    dates = [date.fromisoformat(str(item)) for item in window.get("all_dates", [])]
    if window.get("status") != "READY_FOR_BOUNDED_BODY_ACQUISITION":
        raise RuntimeError("REPLICATION_WINDOW_NOT_READY")
    if len(dates) != 90 or len(set(dates)) != 90 or dates != sorted(dates):
        raise RuntimeError("REPLICATION_WINDOW_90D_INVALID")
    if len(window.get("warmup_dates", [])) != 60 or len(window.get("target_dates", [])) != 30:
        raise RuntimeError("REPLICATION_WINDOW_ROLE_COUNTS_INVALID")
    return window


def _validate_acquisition_complete(
    manifest: Mapping[str, Any], expected_dates: list[str]
) -> None:
    """Fail closed before B2 writes when any Full Tape day is incomplete.

    Parameters
    ----------
    manifest:
        Sanitized independent-acquisition manifest.
    expected_dates:
        Ordered frozen session allow-list.

    Raises
    ------
    RuntimeError
        If the manifest is not a complete, sanitized PASS for every date.
    """
    records_value = manifest.get("records")
    records = (
        [row for row in records_value if isinstance(row, Mapping)]
        if isinstance(records_value, list)
        else []
    )
    dates = [str(row.get("session_date")) for row in records]
    if (
        manifest.get("status") != "PASS"
        or manifest.get("completed_count") != len(expected_dates)
        or len(records) != len(expected_dates)
        or dates != sorted(set(dates))
        or dates != sorted(expected_dates)
    ):
        raise RuntimeError("REPLICATION_B2_ACQUISITION_INCOMPLETE")
    for row in records:
        if (
            row.get("status") != "PASS"
            or row.get("http_status") != 200
            or row.get("duplicate_event_ids") != 0
            or row.get("secret_values_emitted") is not False
            or row.get("personal_paths_emitted") is not False
        ):
            raise RuntimeError(
                f"REPLICATION_B2_ACQUISITION_RECORD_INVALID:{row.get('session_date')}"
            )


def _origins(window: dict[str, Any]) -> pl.DataFrame:
    """Create every five-minute RV30 origin on the actual XNYS session."""
    calendar = xcals.get_calendar("XNYS")
    warmup = set(str(item) for item in window["warmup_dates"])
    target = set(str(item) for item in window["target_dates"])
    rows: list[dict[str, Any]] = []
    for day_text in window["all_dates"]:
        day = date.fromisoformat(str(day_text))
        opened = calendar.session_open(day).to_pydatetime()
        closed = calendar.session_close(day).to_pydatetime()
        origin = opened + timedelta(minutes=5)
        last_origin = closed - timedelta(minutes=30)
        role = "warmup" if day_text in warmup else "target" if day_text in target else None
        if role is None:
            raise RuntimeError(f"REPLICATION_SESSION_ROLE_MISSING:{day_text}")
        while origin <= last_origin:
            session_minute = int((origin - opened).total_seconds() // 60)
            segment = (
                "first" if session_minute < 130 else "middle" if session_minute < 260 else "last"
            )
            for asset in OUTCOME_ASSETS:
                rows.append(
                    {
                        "origin_id": f"{asset}:{origin.isoformat()}",
                        "asset": asset,
                        "session_date": str(day_text),
                        "forecast_origin_utc": origin,
                        "forecast_origin_ny": origin.astimezone(NY),
                        "session_minute": session_minute,
                        "session_tercile": segment,
                        "role": role,
                    }
                )
            origin += timedelta(minutes=5)
    frame = pl.DataFrame(rows, infer_schema_length=None).sort(
        ["session_date", "forecast_origin_utc", "asset"]
    )
    if frame.height == 0 or frame["origin_id"].n_unique() != frame.height:
        raise RuntimeError("REPLICATION_ORIGIN_ID_INVALID")
    return frame


def build_origins() -> None:
    """Persist the deterministic 90-session origin table without outcomes."""
    window = _window()
    frame = _origins(window)
    DERIVED_ROOT.mkdir(parents=True, exist_ok=True)
    frame.write_parquet(ORIGINS_PATH, compression="zstd")
    _write_json(
        ARTIFACT_ROOT / "origins_manifest.json",
        {
            "schema_version": "b2-independent-replication-origins-1.0",
            "status": "PASS_ORIGINS_NO_OUTCOME_READ",
            "session_count": 90,
            "origin_count": frame.height,
            "asset_count": frame["asset"].n_unique(),
            "origin_table_sha256": sha256_file(ORIGINS_PATH),
            "target_outcome_read": False,
            "secret_values_emitted": False,
            "personal_paths_emitted": False,
        },
    )
    print(json.dumps({"status": "PASS_ORIGINS_NO_OUTCOME_READ", "origins": frame.height}))


def _fmp_request(
    client: httpx.Client, asset: str, day: date, key: str
) -> tuple[bytes, list[dict[str, Any]]]:
    """Fetch one bounded FMP response with retry/backoff and no secret logging."""
    params = {"symbol": asset, "from": day.isoformat(), "to": (day + timedelta(days=1)).isoformat()}
    for attempt in range(1, 5):
        response = client.get(ENDPOINT, params={**params, "apikey": key})
        if response.status_code == 200:
            payload = response.json()
            if not isinstance(payload, list):
                raise RuntimeError(f"FMP_SCHEMA_NOT_LIST:{asset}:{day}")
            return response.content, payload
        if response.status_code not in {429, 500, 502, 503, 504} or attempt == 4:
            raise RuntimeError(f"FMP_HTTP:{asset}:{day}:{response.status_code}")
        retry_after = response.headers.get("Retry-After")
        time.sleep(
            float(retry_after)
            if retry_after and retry_after.replace(".", "", 1).isdigit()
            else 2 ** (attempt - 1)
        )
    raise AssertionError("UNREACHABLE_FMP_RETRY")


def build_fmp() -> None:
    """Acquire/reuse exact-session FMP bars for all eight provider assets."""
    window = _window()
    key = _secret("FMP_API_KEY")
    calendar = xcals.get_calendar("XNYS")
    rows: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
    with httpx.Client(timeout=90.0, follow_redirects=True) as client:
        for asset in MARKET_ASSETS:
            for day_text in window["all_dates"]:
                day = date.fromisoformat(str(day_text))
                raw_path = RAW_FMP_ROOT / f"date={day}" / f"asset={asset}" / "response.json"
                if raw_path.exists():
                    content = raw_path.read_bytes()
                    payload = json.loads(content)
                else:
                    content, payload = _fmp_request(client, asset, day, key)
                    raw_path.parent.mkdir(parents=True, exist_ok=True)
                    temporary = raw_path.with_suffix(".json.part")
                    temporary.write_bytes(content)
                    temporary.replace(raw_path)
                if not isinstance(payload, list):
                    raise RuntimeError(f"FMP_SCHEMA_NOT_LIST:{asset}:{day}")
                normalized, returned_dates = _normalize_fmp_session_rows(asset, day, payload)
                expected = int(
                    (
                        calendar.session_close(day).to_pydatetime()
                        - calendar.session_open(day).to_pydatetime()
                    ).total_seconds()
                    // 60
                )
                if not normalized:
                    raise RuntimeError(f"FMP_EXACT_SESSION_EMPTY:{asset}:{day}")
                rows.extend(normalized)
                records.append(
                    {
                        "asset": asset,
                        "session_date": day.isoformat(),
                        "requested_date": day.isoformat(),
                        "returned_dates": returned_dates,
                        "provider_over_return": any(
                            value != day.isoformat() for value in returned_dates
                        ),
                        "rows_exact": len(normalized),
                        "expected_calendar_rows": expected,
                        "missing_calendar_rows": max(0, expected - len(normalized)),
                        "payload_sha256": hashlib.sha256(content).hexdigest(),
                        "request_params_sanitized": {
                            "symbol": asset,
                            "from": day.isoformat(),
                            "to": (day + timedelta(days=1)).isoformat(),
                        },
                        "secret_values_emitted": False,
                    }
                )
    frame = pl.DataFrame(rows, infer_schema_length=None).sort(
        ["session_date", "asset", "bar_timestamp_raw_utc"]
    )
    DERIVED_ROOT.mkdir(parents=True, exist_ok=True)
    frame.write_parquet(BARS_PATH, compression="zstd")
    _write_json(
        ARTIFACT_ROOT / "fmp_manifest.json",
        {
            "schema_version": "b2-independent-replication-fmp-1.0",
            "status": "PASS_FMP_EXACT_SESSION",
            "record_count": len(records),
            "bar_count": frame.height,
            "records": records,
            "bars_sha256": sha256_file(BARS_PATH),
            "fmp_bar_availability": "CONSERVATIVE_RESEARCH_ASSUMPTION",
            "target_outcome_read": False,
            "secret_values_emitted": False,
            "personal_paths_emitted": False,
        },
    )
    print(
        json.dumps(
            {"status": "PASS_FMP_EXACT_SESSION", "records": len(records), "bars": frame.height}
        )
    )


def build_b0_training() -> None:
    """Build B0/RV30 only for warm-up rows; target outcomes remain unopened."""
    window = _window()
    if not ORIGINS_PATH.exists() or not BARS_PATH.exists():
        raise RuntimeError("REPLICATION_B0_INPUTS_MISSING")
    origins = pl.read_parquet(ORIGINS_PATH).filter(pl.col("role") == "warmup")
    bars = pl.read_parquet(BARS_PATH)
    b0 = build_b0v2_features(bars, origins)
    B0_WARMUP_PATH.parent.mkdir(parents=True, exist_ok=True)
    b0.write_parquet(B0_WARMUP_PATH, compression="zstd")
    _write_json(
        ARTIFACT_ROOT / "b0_training_manifest.json",
        {
            "schema_version": "b2-independent-replication-b0-training-1.0",
            "status": "PASS_B0_WARMUP_ONLY",
            "session_count": len(window["warmup_dates"]),
            "origin_count": b0.height,
            "valid_target_count": b0.filter(pl.col("rv30").is_not_null()).height,
            "b0_features": list(B0V2_FEATURES),
            "b0_sha256": sha256_file(B0_WARMUP_PATH),
            "target_dates_read": [],
            "target_outcome_read": False,
            "secret_values_emitted": False,
            "personal_paths_emitted": False,
        },
    )
    print(json.dumps({"status": "PASS_B0_WARMUP_ONLY", "origins": b0.height}))


def build_b2() -> None:
    """Aggregate all Full Tape rows and normalize B2 without reading RV30."""
    window = _window()
    _validate_acquisition_complete(
        _load_json(ACQUISITION_PATH), [str(item) for item in window["all_dates"]]
    )
    if not ORIGINS_PATH.exists():
        build_origins()
    origins = pl.read_parquet(ORIGINS_PATH)
    event_root = DATA_ROOT / "data" / "option_events"
    selected = [
        "underlying_symbol",
        "executed_at",
        "created_at",
        "option_chain_id",
        "premium",
        "option_type",
        "tags",
        "strike",
        "expiry",
    ]
    expected_dates = [str(item) for item in window["all_dates"]]
    for day in expected_dates:
        origins_day = origins.filter(pl.col("session_date") == day)
        paths = [
            event_root / f"date={day}" / f"asset={asset}" / "events.parquet"
            for asset in OUTCOME_ASSETS
        ]
        if not all(path.is_file() for path in paths):
            raise RuntimeError(f"REPLICATION_B2_EVENT_PARTITION_MISSING:{day}")
        trades = (
            pl.scan_parquet([str(path) for path in paths])
            .select(selected)
            .with_columns(pl.lit(day).alias("session_date"))
            .collect(engine="streaming")
        )
        for spec, (window_minutes, delay_seconds) in B2_SPECS.items():
            path = B2_ROOT / spec / f"date={day}.parquet"
            if path.exists():
                continue
            activity = aggregate_b2_activity(
                trades, origins_day, window_minutes=window_minutes, delay_seconds=delay_seconds
            )
            if (
                activity.height != origins_day.height
                or activity["origin_id"].n_unique() != origins_day.height
            ):
                raise RuntimeError(f"REPLICATION_B2_ORIGIN_ALIGNMENT:{spec}:{day}")
            path.parent.mkdir(parents=True, exist_ok=True)
            activity.write_parquet(path, compression="zstd")
    primary_paths = sorted((B2_ROOT / "primary_5m_60s").glob("date=*.parquet"))
    if len(primary_paths) != len(expected_dates):
        raise RuntimeError("REPLICATION_B2_CHECKPOINT_COUNT_INVALID")
    primary = build_b2v2_from_activity(
        pl.scan_parquet([str(path) for path in primary_paths]).collect(engine="streaming"), origins
    )
    primary.write_parquet(B2_PRIMARY_PATH, compression="zstd")
    _write_json(
        ARTIFACT_ROOT / "b2_manifest.json",
        {
            "schema_version": "b2-independent-replication-b2-1.0",
            "status": "PASS_B2_TARGET_FREE",
            "origin_count": primary.height,
            "complete_origin_count": primary.filter(pl.col("b2v2_complete")).height,
            "session_count": primary["session_date"].n_unique(),
            "primary_cutoff": "created_at <= forecast_origin - 60 seconds",
            "sensitivity_specs": list(B2_SPECS),
            "b2_sha256": sha256_file(B2_PRIMARY_PATH),
            "rv30_or_qlike_columns_present": any(
                str(column).lower().startswith(("rv30", "qlike")) for column in primary.columns
            ),
            "target_outcome_read": False,
            "secret_values_emitted": False,
            "personal_paths_emitted": False,
        },
    )
    print(
        json.dumps(
            {
                "status": "PASS_B2_TARGET_FREE",
                "origins": primary.height,
                "complete": primary.filter(pl.col("b2v2_complete")).height,
            }
        )
    )


def main() -> None:
    """Run one bounded panel stage."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=("origins", "fmp", "b0-training", "b2"), required=True)
    stage = parser.parse_args().stage
    if stage == "origins":
        build_origins()
    elif stage == "fmp":
        build_fmp()
    elif stage == "b0-training":
        build_b0_training()
    else:
        build_b2()


if __name__ == "__main__":
    main()
