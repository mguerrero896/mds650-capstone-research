"""Acquire Phase 6 FMP bars and build the causal B0v2/RV30 table."""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import build_b2_calibration_20d as prior_b0
import exchange_calendars as xcals  # type: ignore[import-untyped]
import httpx
import polars as pl
import run_b1_calibration_20d as b1_builder

from mds650.phase5_storage import sha256_file
from mds650.phase6 import (
    MARKET_CONTROLS,
    OUTCOME_ASSETS,
    aggregate_b2_activity,
    b1v2_coverage_status,
    b2_activity_checkpoint_valid,
    build_b0v2_features,
    build_b1v2_features,
    build_b2v2_from_activity,
    build_phase6_common_panel,
    build_phase6_origins,
    phase6_sessions,
)
from mds650.study_design import canonical_sha256

ROOT = Path(__file__).resolve().parents[1]
PHASE6 = ROOT / "artifacts" / "phase6"
SSD_ROOT = Path("D:/MDS650/phase6")
RAW_ROOT = SSD_ROOT / "raw" / "fmp"
DATA_ROOT = SSD_ROOT / "data" / "fmp"
MANIFEST_PATH = PHASE6 / "fmp_manifest.json"
BARS_PATH = DATA_ROOT / "underlying_1min_180d.parquet"
ORIGINS_PATH = PHASE6 / "origins.parquet"
B0_PATH = PHASE6 / "b0v2.parquet"
B0_SENSITIVITY_PATH = PHASE6 / "b0v2_sensitivities.parquet"
B0_MANIFEST_PATH = PHASE6 / "b0v2_manifest.json"
B1_PATH = PHASE6 / "b1v2.parquet"
B1_COVERAGE_PATH = PHASE6 / "b1v2_coverage.json"
B1_ROOT = SSD_ROOT / "data" / "b1q"
B1_CACHE_ROOT = SSD_ROOT / "cache" / "massive_v4"
B1_ORIGINS_PATH = B1_ROOT / "phase6_b1_origins.parquet"
B2_ROOT = SSD_ROOT / "data" / "b2"
B2_PATH = PHASE6 / "b2v2.parquet"
B2_LEDGER_PATH = PHASE6 / "b2v2_normalization_ledger.parquet"
B2_MANIFEST_PATH = PHASE6 / "b2v2_manifest.json"
B2_SENSITIVITY_PATH = PHASE6 / "b2v2_sensitivities.parquet"
PREREGISTRATION_PATH = PHASE6 / "preregistration.json"
COMMON_ALL_PATH = PHASE6 / "common_panel_all_origins.parquet"
COMMON_PATH = PHASE6 / "common_panel.parquet"
COMMON_MANIFEST_PATH = PHASE6 / "common_panel_manifest.json"
OOS_ACCESS_LEDGER_PATH = PHASE6 / "oos_access_ledger.json"
B2_SPECS = {
    "primary_5m_60s": (5, 60),
    "window_15m_60s": (15, 60),
    "window_30m_60s": (30, 60),
    "latency_5m_120s": (5, 120),
    "latency_5m_300s": (5, 300),
}
ENDPOINT = "https://financialmodelingprep.com/stable/historical-chart/1min"
ASSETS = (*OUTCOME_ASSETS, *MARKET_CONTROLS)


def _read_manifest() -> dict[str, Any]:
    """Return the resumable sanitized manifest or a new empty one."""
    if not MANIFEST_PATH.exists():
        return {
            "schema_version": "phase6-fmp-1.0",
            "status": "IN_PROGRESS",
            "records": [],
            "secret_values_emitted": False,
            "personal_paths_emitted": False,
        }
    payload = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("records"), list):
        raise RuntimeError("PHASE6_FMP_MANIFEST_INVALID")
    return payload


def _atomic_bytes(path: Path, content: bytes) -> None:
    """Persist one immutable raw response without partial-file ambiguity."""
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".part")
    partial.write_bytes(content)
    partial.replace(path)


def _payload(path: Path) -> tuple[list[dict[str, Any]], str]:
    """Load and hash one raw FMP JSON array."""
    content = path.read_bytes()
    payload = json.loads(content)
    if not isinstance(payload, list) or not all(isinstance(row, dict) for row in payload):
        raise RuntimeError("PHASE6_FMP_SCHEMA_DRIFT")
    return payload, hashlib.sha256(content).hexdigest()


def _download(client: httpx.Client, asset: str, day: date, destination: Path) -> None:
    """Download one bounded asset-session response with retry/backoff."""
    key = prior_b0._secret("FMP_API_KEY")
    params = {
        "symbol": asset,
        "from": day.isoformat(),
        "to": (day + timedelta(days=1)).isoformat(),
        "apikey": key,
    }
    for attempt in range(1, 5):
        response = client.get(ENDPOINT, params=params)
        if response.status_code == 200:
            _atomic_bytes(destination, response.content)
            return
        if response.status_code != 429 and response.status_code < 500:
            raise RuntimeError(
                f"PHASE6_FMP_HTTP:{asset}:{day.isoformat()}:{response.status_code}"
            )
        if attempt == 4:
            raise RuntimeError(
                f"PHASE6_FMP_RETRY_EXHAUSTED:{asset}:{day.isoformat()}:{response.status_code}"
            )
        retry_after = response.headers.get("Retry-After")
        time.sleep(float(retry_after) if retry_after else 2 ** (attempt - 1))


def acquire_fmp_bars() -> pl.DataFrame:
    """Acquire or hash-reuse every registered FMP asset-session response.

    Returns
    -------
    polars.DataFrame
        Exact-session normalized OHLCV for all 180 dates and eight assets.

    Raises
    ------
    RuntimeError
        If an HTTP response, raw hash, schema or exact-session payload is invalid.
    """
    session_rows = phase6_sessions()
    dates = [date.fromisoformat(row["session_date"]) for row in session_rows]
    manifest = _read_manifest()
    existing = {
        (str(row["asset"]), str(row["session_date"])): row
        for row in manifest["records"]
    }
    if len(existing) != len(manifest["records"]):
        raise RuntimeError("PHASE6_FMP_MANIFEST_DUPLICATE")

    calendar = xcals.get_calendar("XNYS")
    records: list[dict[str, Any]] = []
    normalized: list[dict[str, Any]] = []
    with httpx.Client(timeout=90.0, follow_redirects=True) as client:
        for asset in ASSETS:
            for day in dates:
                day_text = day.isoformat()
                raw_path = RAW_ROOT / f"date={day_text}" / f"asset={asset}" / "response.json"
                old = existing.get((asset, day_text))
                if not raw_path.exists():
                    if old is not None:
                        raise RuntimeError(f"PHASE6_FMP_RAW_MISSING:{asset}:{day_text}")
                    _download(client, asset, day, raw_path)
                payload, payload_hash = _payload(raw_path)
                if old is not None and old.get("payload_sha256") != payload_hash:
                    raise RuntimeError(f"PHASE6_FMP_RAW_HASH_MISMATCH:{asset}:{day_text}")
                rows, returned_dates = prior_b0._normalize_fmp_session_rows(
                    asset,
                    day,
                    payload,
                )
                if not rows:
                    raise RuntimeError(f"PHASE6_FMP_EXACT_SESSION_EMPTY:{asset}:{day_text}")
                expected_rows = int(
                    (
                        calendar.session_close(day).to_pydatetime()
                        - calendar.session_open(day).to_pydatetime()
                    ).total_seconds()
                    // 60
                )
                record = {
                    "asset": asset,
                    "session_date": day_text,
                    "http_status": 200,
                    "requested_date": day_text,
                    "returned_dates": returned_dates,
                    "provider_over_return": any(value != day_text for value in returned_dates),
                    "rows_exact": len(rows),
                    "expected_calendar_rows": expected_rows,
                    "missing_calendar_rows": max(0, expected_rows - len(rows)),
                    "request_hash": prior_b0._request_hash(
                        {
                            "symbol": asset,
                            "from": day_text,
                            "to": (day + timedelta(days=1)).isoformat(),
                        }
                    ),
                    "payload_sha256": payload_hash,
                    "raw_evidence": f"raw/fmp/date={day_text}/asset={asset}/response.json",
                    "reused_existing": old is not None,
                }
                records.append(record)
                normalized.extend(rows)
                manifest.update(
                    {
                        "status": "IN_PROGRESS",
                        "completed_record_count": len(records),
                        "authorized_record_count": len(ASSETS) * len(dates),
                        "records": records,
                    }
                )
                prior_b0._atomic_json(MANIFEST_PATH, manifest)
                if len(records) % 40 == 0:
                    print(
                        json.dumps(
                            {
                                "status": "IN_PROGRESS",
                                "completed": len(records),
                                "authorized": len(ASSETS) * len(dates),
                                "secret_values_emitted": False,
                            }
                        ),
                        flush=True,
                    )

    frame = pl.DataFrame(normalized, infer_schema_length=None).sort(
        ["session_date", "asset", "bar_timestamp_raw_utc"]
    )
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    frame.write_parquet(BARS_PATH, compression="zstd")
    manifest.update(
        {
            "status": "PASS",
            "completed_record_count": len(records),
            "authorized_record_count": len(ASSETS) * len(dates),
            "records": records,
            "bars_sha256": sha256_file(BARS_PATH),
            "fmp_bar_availability": "CONSERVATIVE_RESEARCH_ASSUMPTION",
            "secret_values_emitted": False,
            "personal_paths_emitted": False,
        }
    )
    prior_b0._atomic_json(MANIFEST_PATH, manifest)
    return frame


def build_b0v2() -> None:
    """Build and persist the Phase 6 B0v2 table without inspecting outcomes."""
    bars = acquire_fmp_bars()
    dates = [row["session_date"] for row in phase6_sessions()]
    origins = build_phase6_origins(dates)
    b0 = build_b0v2_features(bars, origins)
    b0_delayed = build_b0v2_features(bars, origins, delay_minutes=2).with_columns(
        pl.lit("FMP_DELAY_2_MINUTES").alias("sensitivity_spec")
    )
    origins.write_parquet(ORIGINS_PATH, compression="zstd")
    b0.write_parquet(B0_PATH, compression="zstd")
    b0_delayed.write_parquet(B0_SENSITIVITY_PATH, compression="zstd")
    evidence = {
        "schema_version": "phase6-b0v2-1.0",
        "status": "PASS_PHASE6_B0V2",
        "sessions": len(dates),
        "origins": origins.height,
        "rows": b0.height,
        "b0v2_sha256": sha256_file(B0_PATH),
        "sensitivity_sha256": sha256_file(B0_SENSITIVITY_PATH),
        "sensitivity_specs": ["FMP_DELAY_2_MINUTES"],
        "oos_results_inspected": False,
        "secret_values_emitted": False,
        "personal_paths_emitted": False,
    }
    prior_b0._atomic_json(B0_MANIFEST_PATH, evidence)
    print(json.dumps(evidence))


def build_b1v2() -> None:
    """Build B1v2 from resumable Massive contract-day caches without targets."""
    if not ORIGINS_PATH.is_file() or not BARS_PATH.is_file():
        raise RuntimeError("PHASE6_B0_INPUTS_MISSING")
    origins = pl.read_parquet(ORIGINS_PATH)
    spot_rows = (
        pl.read_parquet(BARS_PATH)
        .filter(pl.col("asset").is_in(OUTCOME_ASSETS))
        .select(
            "asset",
            "session_date",
            pl.col("available_at_utc").alias("forecast_origin_utc"),
            pl.col("close").alias("spot"),
        )
    )
    b1_origins = (
        origins.join(
            spot_rows,
            on=["asset", "session_date", "forecast_origin_utc"],
            how="left",
            validate="1:1",
        )
        .with_columns(pl.col("session_tercile").alias("session_segment"))
        .select(
            "origin_id",
            "asset",
            "session_date",
            "forecast_origin_utc",
            "spot",
            "session_segment",
        )
    )
    if b1_origins["spot"].null_count() or b1_origins.height != origins.height:
        raise RuntimeError("PHASE6_B1_SPOT_ALIGNMENT_FAILURE")
    B1_ROOT.mkdir(parents=True, exist_ok=True)
    b1_origins.write_parquet(B1_ORIGINS_PATH, compression="zstd")
    sessions = tuple(row["session_date"] for row in phase6_sessions())
    b1_builder.main(
        b1_builder.B1BuildConfig(
            output_root=B1_ROOT,
            cache_root=B1_CACHE_ROOT,
            sessions=sessions,
            origins_path=B1_ORIGINS_PATH,
        )
    )
    builder_evidence = json.loads(
        (B1_ROOT / "b1_coverage_20d.json").read_text(encoding="utf-8")
    )
    attempts = pl.read_parquet(B1_ROOT / "b1_iv_attempts_20d.parquet").select(
        "origin_id",
        "contract",
        "expiry",
        "strike",
        "option_type",
        "dte",
        "moneyness",
        pl.col("sip_timestamp").alias("sip_timestamp_ns"),
        "bid",
        "ask",
        pl.col("iv").alias("implied_volatility"),
    )
    features = build_b1v2_features(
        origins.select(
            "origin_id",
            "asset",
            "session_date",
            "forecast_origin_utc",
            "session_tercile",
            "role",
        ),
        attempts,
    )
    status = b1v2_coverage_status(features)
    by_asset = (
        features.group_by("asset")
        .agg(pl.col("b1v2a_complete").mean().alias("coverage"))
        .sort("asset")
        .to_dicts()
    )
    by_tercile = (
        features.group_by("session_tercile")
        .agg(pl.col("b1v2a_complete").mean().alias("coverage"))
        .sort("session_tercile")
        .to_dicts()
    )
    features.write_parquet(B1_PATH, compression="zstd")
    evidence = {
        "schema_version": "phase6-b1v2-1.0",
        "status": status,
        "origin_count": features.height,
        "global": {
            "b1v2a": features["b1v2a_complete"].mean(),
            "b1v2b": features["b1v2b_complete"].mean(),
            "b1v2c": features["b1v2c_complete"].mean(),
        },
        "by_asset": by_asset,
        "by_session_tercile": by_tercile,
        "quote_cache_audit": builder_evidence["quote_cache_audit"],
        "contract_resolution_schema": builder_evidence[
            "contract_resolution_schema"
        ],
        "future_quote_rows": features.filter(
            pl.col("max_sip_timestamp_ns").is_not_null()
            & (pl.col("max_sip_timestamp_ns") > pl.col("forecast_origin_ns"))
        ).height,
        "b1v2_sha256": sha256_file(B1_PATH),
        "oos_results_inspected": False,
        "secret_values_emitted": False,
        "personal_paths_emitted": False,
    }
    prior_b0._atomic_json(B1_COVERAGE_PATH, evidence)
    print(json.dumps(evidence))
    if status != "PASS_B1V2A_COVERAGE":
        raise RuntimeError(status)


def build_b2v2() -> None:
    """Build the registered target-blind B2v2 features from Phase 6 Full Tape."""
    if not ORIGINS_PATH.is_file() or not BARS_PATH.is_file():
        raise RuntimeError("PHASE6_B0_INPUTS_MISSING")
    origins = pl.read_parquet(ORIGINS_PATH)
    spot_rows = (
        pl.read_parquet(BARS_PATH)
        .filter(pl.col("asset").is_in(OUTCOME_ASSETS))
        .select(
            "asset",
            "session_date",
            pl.col("available_at_utc").alias("forecast_origin_utc"),
            pl.col("close").alias("spot"),
        )
    )
    b2_origins = origins.join(
        spot_rows,
        on=["asset", "session_date", "forecast_origin_utc"],
        how="left",
        validate="1:1",
    )
    if b2_origins["spot"].null_count() or b2_origins.height != origins.height:
        raise RuntimeError("PHASE6_B2_SPOT_ALIGNMENT_FAILURE")
    B2_ROOT.mkdir(parents=True, exist_ok=True)
    event_root = SSD_ROOT / "data" / "option_events"
    checkpoint_root = B2_ROOT / "raw_activity_by_session"
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
    session_rows = phase6_sessions()
    for index, session in enumerate(session_rows, start=1):
        day = session["session_date"]
        origins_day = b2_origins.filter(pl.col("session_date") == day)
        pending = {
            spec: checkpoint_root / spec / f"date={day}.parquet"
            for spec in B2_SPECS
            if not b2_activity_checkpoint_valid(
                checkpoint_root / spec / f"date={day}.parquet",
                expected_rows=origins_day.height,
            )
        }
        if not pending:
            continue
        paths = [
            event_root / f"date={day}" / f"asset={asset}" / "events.parquet"
            for asset in OUTCOME_ASSETS
        ]
        if not all(path.is_file() for path in paths):
            raise RuntimeError(f"PHASE6_B2_EVENT_PARTITION_MISSING:{day}")
        trades = (
            pl.scan_parquet([str(path) for path in paths])
            .select(selected)
            .with_columns(pl.lit(day).alias("session_date"))
            .collect(engine="streaming")
        )
        for spec, path in pending.items():
            window, delay = B2_SPECS[spec]
            activity = aggregate_b2_activity(
                trades,
                origins_day,
                window_minutes=window,
                delay_seconds=delay,
            )
            if (
                activity.height != origins_day.height
                or activity["origin_id"].n_unique() != origins_day.height
            ):
                raise RuntimeError(f"PHASE6_B2_DAILY_ALIGNMENT_FAILURE:{spec}:{day}")
            path.parent.mkdir(parents=True, exist_ok=True)
            activity.write_parquet(path, compression="zstd")
        del trades
        gc.collect()
        print(
            json.dumps(
                {
                    "status": "IN_PROGRESS_PHASE6_B2V2",
                    "completed_sessions": index,
                    "authorized_sessions": len(session_rows),
                    "session_date": day,
                    "secret_values_emitted": False,
                }
            ),
            flush=True,
        )

    normalized: dict[str, pl.DataFrame] = {}
    for spec in B2_SPECS:
        paths = sorted((checkpoint_root / spec).glob("date=*.parquet"))
        if len(paths) != len(session_rows):
            raise RuntimeError(f"PHASE6_B2_CHECKPOINT_COUNT_INVALID:{spec}")
        activity = pl.scan_parquet(paths).collect(engine="streaming")
        normalized[spec] = build_b2v2_from_activity(activity, origins).with_columns(
            pl.lit(spec).alias("sensitivity_spec")
        )
    features = normalized["primary_5m_60s"].drop("sensitivity_spec")
    if features.height != origins.height or features["origin_id"].n_unique() != origins.height:
        raise RuntimeError("PHASE6_B2_ORIGIN_ALIGNMENT_FAILURE")
    if any(column.lower().startswith("rv30") for column in features.columns):
        raise RuntimeError("PHASE6_B2_TARGET_LEAKAGE")
    features.write_parquet(B2_PATH, compression="zstd")
    pl.concat(
        [frame for spec, frame in normalized.items() if spec != "primary_5m_60s"],
        how="vertical",
    ).write_parquet(B2_SENSITIVITY_PATH, compression="zstd")
    features.select(
        "origin_id",
        "asset",
        "session_date",
        "forecast_origin_utc",
        "b2v2_complete",
        "b2v2_history_sessions",
        "b2v2_normalization_labels",
    ).write_parquet(B2_LEDGER_PATH, compression="zstd")
    evidence = {
        "schema_version": "phase6-b2v2-1.0",
        "status": "PASS_PHASE6_B2V2",
        "origin_count": features.height,
        "complete_origin_count": features.filter(pl.col("b2v2_complete")).height,
        "warmup_origin_count": features.filter(~pl.col("b2v2_complete")).height,
        "b2v2_sha256": sha256_file(B2_PATH),
        "normalization_ledger_sha256": sha256_file(B2_LEDGER_PATH),
        "sensitivity_sha256": sha256_file(B2_SENSITIVITY_PATH),
        "sensitivity_specs": list(B2_SPECS),
        "oos_results_inspected": False,
        "secret_values_emitted": False,
        "personal_paths_emitted": False,
    }
    prior_b0._atomic_json(B2_MANIFEST_PATH, evidence)
    print(json.dumps(evidence))


def build_common() -> None:
    """Seal the identical-origin B0v2/B1v2a/B2v2 panel before OOS use."""
    preregistration = json.loads(PREREGISTRATION_PATH.read_text(encoding="utf-8"))
    unsigned = {
        key: value
        for key, value in preregistration.items()
        if key != "manifest_sha256"
    }
    b0_manifest = json.loads(B0_MANIFEST_PATH.read_text(encoding="utf-8"))
    b1_manifest = json.loads(B1_COVERAGE_PATH.read_text(encoding="utf-8"))
    b2_manifest = json.loads(B2_MANIFEST_PATH.read_text(encoding="utf-8"))
    if (
        preregistration.get("status") != "FROZEN_BEFORE_OOS"
        or preregistration.get("oos_read_count") != 0
        or preregistration.get("manifest_sha256") != canonical_sha256(unsigned)
        or b0_manifest.get("status") != "PASS_PHASE6_B0V2"
        or b0_manifest.get("b0v2_sha256") != sha256_file(B0_PATH)
        or b1_manifest.get("status") != "PASS_B1V2A_COVERAGE"
        or b2_manifest.get("status") != "PASS_PHASE6_B2V2"
        or b2_manifest.get("b2v2_sha256") != sha256_file(B2_PATH)
    ):
        raise RuntimeError("PHASE6_COMMON_PREREQUISITE_FAILURE")
    all_rows, common = build_phase6_common_panel(
        pl.read_parquet(ORIGINS_PATH),
        pl.read_parquet(B0_PATH),
        pl.read_parquet(B1_PATH),
        pl.read_parquet(B2_PATH),
    )
    if common.is_empty():
        raise RuntimeError("PHASE6_COMMON_PANEL_EMPTY")
    all_rows.write_parquet(COMMON_ALL_PATH, compression="zstd")
    common.write_parquet(COMMON_PATH, compression="zstd")
    coverage = common.height / all_rows.height
    evidence = {
        "schema_version": "phase6-common-panel-1.0",
        "status": "SEALED_BEFORE_OOS",
        "all_origin_count": all_rows.height,
        "common_origin_count": common.height,
        "common_coverage": coverage,
        "session_count": common["session_date"].n_unique(),
        "asset_count": common["asset"].n_unique(),
        "common_panel_sha256": sha256_file(COMMON_PATH),
        "all_origins_sha256": sha256_file(COMMON_ALL_PATH),
        "preregistration_manifest_sha256": preregistration["manifest_sha256"],
        "oos_read_count": 0,
        "oos_results_inspected": False,
        "secret_values_emitted": False,
        "personal_paths_emitted": False,
    }
    evidence["manifest_sha256"] = canonical_sha256(evidence)
    prior_b0._atomic_json(COMMON_MANIFEST_PATH, evidence)
    ledger = {
        "schema_version": "phase6-oos-access-1.0",
        "status": "SEALED_BEFORE_OOS",
        "oos_read_count": 0,
        "evaluation_attempt_count": 0,
        "common_panel_sha256": evidence["common_panel_sha256"],
        "preregistration_manifest_sha256": preregistration["manifest_sha256"],
        "results_inspected": False,
    }
    ledger["manifest_sha256"] = canonical_sha256(ledger)
    prior_b0._atomic_json(OOS_ACCESS_LEDGER_PATH, ledger)
    print(json.dumps(evidence))


def main() -> None:
    """Run the requested Phase 6 feature-construction stage."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--stage", choices=("b0", "b1", "b2", "common", "all"), default="b0"
    )
    stage = parser.parse_args().stage
    if stage in {"b0", "all"}:
        build_b0v2()
    if stage in {"b1", "all"}:
        build_b1v2()
    if stage in {"b2", "all"}:
        build_b2v2()
    if stage in {"common", "all"}:
        build_common()


if __name__ == "__main__":
    main()
