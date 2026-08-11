"""Build target-free inputs and the frozen RV30 target for two new blocks.

Stages are intentionally separate so acquisition, predictors and outcome
construction leave independent manifests. The first four stages never inspect
future closes; ``target`` is permitted only after the direct protocol freeze.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from collections.abc import Mapping
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import exchange_calendars as xcals  # type: ignore[import-untyped]
import httpx
import polars as pl

from mds650.phase5_features import add_compact_b2_features
from mds650.phase5_storage import sha256_file
from mds650.phase6 import (
    B0V2_FEATURES,
    OUTCOME_ASSETS,
    aggregate_b2_activity,
    build_b0v2_features,
)
from mds650.study_design import B2_FEATURE_NAMES, canonical_sha256

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from build_b2_calibration_20d import _normalize_fmp_session_rows  # noqa: E402

ARTIFACT_ROOT = ROOT / "artifacts" / "b2_confirmation"
DATA_ROOT = Path("D:/MDS650/b2_confirmation")
PROBE = ROOT / "artifacts" / "api_audit" / "new_blocks_availability_probe_v2.json"
ACQUISITION = ROOT / "artifacts" / "methodology" / "b2_confirmation_acquisition_manifest_v1.json"
ORIGINS = DATA_ROOT / "derived" / "origins_60d.parquet"
BARS = DATA_ROOT / "derived" / "underlying_1min_60d.parquet"
B0_PREDICTORS = DATA_ROOT / "derived" / "b0_predictors_60d.parquet"
B1_ORIGINS = DATA_ROOT / "derived" / "b1_origins_60d.parquet"
B0_TARGET = DATA_ROOT / "derived" / "b0_target_60d.parquet"
B2_ROOT = DATA_ROOT / "derived" / "b2_direct"
B2_COMBINED = DATA_ROOT / "derived" / "b2_direct_60d.parquet"
PANEL = DATA_ROOT / "derived" / "panel_60d.parquet"
RAW_FMP = DATA_ROOT / "raw" / "fmp"
ASSETS = tuple(OUTCOME_ASSETS)
MARKET_ASSETS = (*ASSETS, "SPY", "QQQ")
NY = ZoneInfo("America/New_York")
ENDPOINT = "https://financialmodelingprep.com/stable/historical-chart/1min"


def _json(path: Path) -> dict[str, Any]:
    """Load a JSON object and reject malformed evidence."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"JSON_OBJECT_REQUIRED:{path.name}")
    return payload


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    """Write deterministic self-hashed evidence atomically."""
    unsigned = {key: value for key, value in payload.items() if key != "manifest_sha256"}
    output = {**unsigned, "manifest_sha256": canonical_sha256(unsigned)}
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_text(
        json.dumps(output, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def _dates() -> tuple[date, ...]:
    """Return the frozen 60-session allow-list in chronological order."""
    probe = _json(PROBE)
    blocks = probe.get("blocks")
    if not isinstance(blocks, Mapping):
        raise RuntimeError("B2_CONFIRMATION_BLOCKS_MISSING")
    values = [date.fromisoformat(str(item)) for items in blocks.values() for item in items]
    if len(values) != 60 or tuple(sorted(set(values))) != tuple(sorted(values)):
        raise RuntimeError("B2_CONFIRMATION_DATE_ALLOWLIST_INVALID")
    return tuple(sorted(values))


def _block_id(day: date) -> str:
    """Return the frozen block identifier for one session date."""
    probe = _json(PROBE)
    for block, values in probe.get("blocks", {}).items():
        if day.isoformat() in {str(item) for item in values}:
            return str(block)
    raise RuntimeError(f"B2_CONFIRMATION_BLOCK_UNKNOWN:{day}")


def _secret(name: str) -> str:
    """Return a required secret without exposing its value."""
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"MISSING_SECRET:{name}")
    return value


def _origins_frame() -> pl.DataFrame:
    """Create every five-minute origin for the six registered outcome assets."""
    calendar = xcals.get_calendar("XNYS")
    rows: list[dict[str, Any]] = []
    for day in _dates():
        opened = calendar.session_open(day).to_pydatetime()
        closed = calendar.session_close(day).to_pydatetime()
        origin = opened + timedelta(minutes=5)
        last_origin = closed - timedelta(minutes=30)
        while origin <= last_origin:
            minute = int((origin - opened).total_seconds() // 60)
            segment = "first" if minute < 130 else "middle" if minute < 260 else "last"
            for asset in ASSETS:
                rows.append(
                    {
                        "origin_id": f"{asset}:{origin.isoformat()}",
                        "asset": asset,
                        "session_date": day.isoformat(),
                        "forecast_origin_utc": origin,
                        "forecast_origin_ny": origin.astimezone(NY),
                        "session_minute": minute,
                        "session_tercile": segment,
                        "role": _block_id(day),
                    }
                )
            origin += timedelta(minutes=5)
    frame = pl.DataFrame(rows, infer_schema_length=None).sort(
        ["session_date", "forecast_origin_utc", "asset"]
    )
    if frame.height == 0 or frame["origin_id"].n_unique() != frame.height:
        raise RuntimeError("B2_CONFIRMATION_ORIGINS_INVALID")
    return frame


def build_origins() -> None:
    """Persist the deterministic target-free origin table."""
    frame = _origins_frame()
    ORIGINS.parent.mkdir(parents=True, exist_ok=True)
    frame.write_parquet(ORIGINS, compression="zstd")
    _write_json(
        ARTIFACT_ROOT / "origins_manifest.json",
        {
            "schema_version": "b2-confirmation-origins-1.0",
            "status": "PASS_ORIGINS_TARGET_FREE",
            "session_count": len(_dates()),
            "origin_count": frame.height,
            "asset_count": frame["asset"].n_unique(),
            "origin_sha256": sha256_file(ORIGINS),
            "target_outcome_read": False,
            "secret_values_emitted": False,
            "personal_paths_emitted": False,
        },
    )
    print(json.dumps({"status": "PASS_ORIGINS_TARGET_FREE", "origins": frame.height}))


def _fmp_request(
    client: httpx.Client, asset: str, day: date, key: str
) -> tuple[bytes, list[dict[str, Any]]]:
    """Fetch one exact-session FMP response with bounded retries."""
    params = {"symbol": asset, "from": day.isoformat(), "to": (day + timedelta(days=1)).isoformat()}
    for attempt in range(1, 5):
        response = client.get(ENDPOINT, params={**params, "apikey": key})
        if response.status_code == 200 and isinstance(response.json(), list):
            return response.content, response.json()
        if response.status_code not in {429, 500, 502, 503, 504} or attempt == 4:
            raise RuntimeError(f"FMP_HTTP_OR_SCHEMA:{asset}:{day}:{response.status_code}")
        time.sleep(2 ** (attempt - 1))
    raise AssertionError("UNREACHABLE_FMP_RETRY")


def build_fmp() -> None:
    """Acquire/reuse exact-session FMP bars for eight assets."""
    if not ORIGINS.exists():
        build_origins()
    key = _secret("FMP_API_KEY")
    calendar = xcals.get_calendar("XNYS")
    rows: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
    with httpx.Client(timeout=90.0, follow_redirects=True) as client:
        for asset in MARKET_ASSETS:
            for day in _dates():
                raw_path = RAW_FMP / f"date={day.isoformat()}" / f"asset={asset}" / "response.json"
                if raw_path.exists():
                    content = raw_path.read_bytes()
                    payload = json.loads(content)
                else:
                    content, payload = _fmp_request(client, asset, day, key)
                    raw_path.parent.mkdir(parents=True, exist_ok=True)
                    temporary = raw_path.with_suffix(".json.part")
                    temporary.write_bytes(content)
                    temporary.replace(raw_path)
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
                            item != day.isoformat() for item in returned_dates
                        ),
                        "rows_exact": len(normalized),
                        "expected_calendar_rows": expected,
                        "payload_sha256": hashlib.sha256(content).hexdigest(),
                        "secret_values_emitted": False,
                    }
                )
    frame = pl.DataFrame(rows, infer_schema_length=None).sort(
        ["session_date", "asset", "bar_timestamp_raw_utc"]
    )
    frame.write_parquet(BARS, compression="zstd")
    _write_json(
        ARTIFACT_ROOT / "fmp_manifest.json",
        {
            "schema_version": "b2-confirmation-fmp-1.0",
            "status": "PASS_FMP_EXACT_SESSION",
            "record_count": len(records),
            "bar_count": frame.height,
            "records": records,
            "bars_sha256": sha256_file(BARS),
            "fmp_bar_availability": "CONSERVATIVE_RESEARCH_ASSUMPTION",
            "target_outcome_read": False,
            "secret_values_emitted": False,
            "personal_paths_emitted": False,
        },
    )
    print(
        json.dumps(
            {"status": "PASS_FMP_EXACT_SESSION", "bars": frame.height, "records": len(records)}
        )
    )


def build_b0_predictors() -> None:
    """Build B0 predictors without inspecting future closes."""
    if not ORIGINS.exists() or not BARS.exists():
        raise RuntimeError("B2_CONFIRMATION_B0_INPUTS_MISSING")
    origins = pl.read_parquet(ORIGINS)
    bars = pl.read_parquet(BARS)
    frame = build_b0v2_features(bars, origins, include_target=False)
    frame = frame.with_columns(
        pl.col("b0v2_log_spot").exp().alias("spot"),
        pl.col("session_tercile").alias("session_segment"),
    )
    frame.write_parquet(B0_PREDICTORS, compression="zstd")
    _write_json(
        ARTIFACT_ROOT / "b0_predictor_manifest.json",
        {
            "schema_version": "b2-confirmation-b0-predictors-1.0",
            "status": "PASS_B0_TARGET_FREE",
            "origin_count": frame.height,
            "rv30_non_null": int(frame["rv30"].drop_nulls().len()),
            "b0_features": list(B0V2_FEATURES),
            "predictor_sha256": sha256_file(B0_PREDICTORS),
            "target_outcome_read": False,
            "secret_values_emitted": False,
            "personal_paths_emitted": False,
        },
    )
    print(json.dumps({"status": "PASS_B0_TARGET_FREE", "origins": frame.height}))


def _check_acquisition() -> None:
    """Require a complete, sanitized Full Tape acquisition before B2 build."""
    manifest = _json(ACQUISITION)
    unsigned = {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    if manifest.get("manifest_sha256") != canonical_sha256(unsigned):
        raise RuntimeError("B2_CONFIRMATION_ACQUISITION_HASH_INVALID")
    if manifest.get("status") != "PASS" or manifest.get("completed_count") != 60:
        raise RuntimeError("B2_CONFIRMATION_ACQUISITION_INCOMPLETE")
    if manifest.get("oos_read_count") != 0 or manifest.get("target_outcome_read") is not False:
        raise RuntimeError("B2_CONFIRMATION_ACQUISITION_OUTCOME_READ")
    for row in manifest.get("records", []):
        if row.get("status") != "PASS" or row.get("duplicate_event_ids") != 0:
            raise RuntimeError(
                f"B2_CONFIRMATION_ACQUISITION_RECORD_INVALID:{row.get('session_date')}"
            )


def build_b2_direct() -> None:
    """Aggregate Full Tape into direct, target-blind B2 features."""
    _check_acquisition()
    if not ORIGINS.exists():
        build_origins()
    origins = pl.read_parquet(ORIGINS)
    outputs: list[pl.DataFrame] = []
    for day in _dates():
        origins_day = origins.filter(pl.col("session_date") == day.isoformat())
        paths = [
            DATA_ROOT
            / "data"
            / "option_events"
            / f"date={day.isoformat()}"
            / f"asset={asset}"
            / "events.parquet"
            for asset in ASSETS
        ]
        if not all(path.is_file() for path in paths):
            raise RuntimeError(f"B2_CONFIRMATION_EVENT_PARTITION_MISSING:{day}")
        trades = _load_b2_trade_partitions(paths, day)
        activity = aggregate_b2_activity(trades, origins_day, window_minutes=5, delay_seconds=60)
        if (
            activity.height != origins_day.height
            or activity["origin_id"].n_unique() != activity.height
        ):
            raise RuntimeError(f"B2_CONFIRMATION_ORIGIN_ALIGNMENT:{day}")
        if activity.filter(
            pl.col("b2v2_max_created_at_utc").is_not_null()
            & (pl.col("b2v2_max_created_at_utc") > pl.col("b2v2_cutoff_utc"))
        ).height:
            raise RuntimeError(f"B2_CONFIRMATION_FUTURE_CREATED_AT:{day}")
        direct = add_compact_b2_features(activity)
        direct = direct.with_columns(pl.lit(_block_id(day)).alias("block_id"))
        path = B2_ROOT / f"date={day.isoformat()}.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        direct.write_parquet(path, compression="zstd")
        outputs.append(direct)
    combined = pl.concat(outputs, how="diagonal_relaxed").sort(
        ["session_date", "forecast_origin_utc", "asset"]
    )
    combined.write_parquet(B2_COMBINED, compression="zstd")
    _write_json(
        ARTIFACT_ROOT / "b2_manifest.json",
        {
            "schema_version": "b2-confirmation-direct-b2-1.0",
            "status": "PASS_B2_TARGET_FREE",
            "origin_count": combined.height,
            "session_count": combined["session_date"].n_unique(),
            "b2_features": list(B2_FEATURE_NAMES),
            "primary_cutoff": "created_at <= forecast_origin - 60 seconds",
            "max_created_at_after_cutoff": int(
                combined.filter(
                    pl.col("b2v2_max_created_at_utc").is_not_null()
                    & (pl.col("b2v2_max_created_at_utc") > pl.col("b2v2_cutoff_utc"))
                ).height
            ),
            "b2_sha256": sha256_file(B2_COMBINED),
            "target_outcome_read": False,
            "secret_values_emitted": False,
            "personal_paths_emitted": False,
        },
    )
    print(json.dumps({"status": "PASS_B2_TARGET_FREE", "origins": combined.height}))


def _load_b2_trade_partitions(paths: list[Path], day: date) -> pl.DataFrame:
    """Load one session's filtered trades and attach the partition date.

    Parameters
    ----------
    paths:
        The eight immutable asset partitions for one Full Tape session.
    day:
        Session date encoded by the partition path.  The provider schema does
        not repeat this value as a column, so it is added locally rather than
        inferred from an event timestamp.

    Returns
    -------
    polars.DataFrame
        Selected target-free trade fields with a string ``session_date``.

    Raises
    ------
    ValueError
        If no partitions are supplied.
    polars.exceptions.PolarsError
        If a partition is missing a required provider field.
    """
    if not paths:
        raise ValueError("B2_CONFIRMATION_TRADE_PARTITIONS_EMPTY")
    return (
        pl.scan_parquet([str(path) for path in paths])
        .select(
            "underlying_symbol",
            "executed_at",
            "created_at",
            "option_chain_id",
            "premium",
            "option_type",
            "tags",
            "strike",
            "expiry",
        )
        .collect(engine="streaming")
        .with_columns(pl.lit(day.isoformat()).alias("session_date"))
    )


def _prepare_b1_origins() -> tuple[pl.DataFrame, pl.DataFrame, dict[str, int]]:
    """Persist B1-eligible origins while retaining explicit B0 missingness.

    Returns
    -------
    tuple[polars.DataFrame, polars.DataFrame, dict[str, int]]
        Eligible origins, excluded origins, and counts by exclusion reason.

    Raises
    ------
    RuntimeError
        If the target-free B0 predictor table is missing or contains no
        unique finite-spot origins suitable for the Massive resolver.
    """
    if not B0_PREDICTORS.exists():
        raise RuntimeError("B2_CONFIRMATION_B1_ORIGINS_MISSING")
    # B0v2 deliberately marks the first origins of each session as missing
    # because no 30-minute *past* underlying window exists yet.  Massive's
    # contract resolver requires a finite spot and otherwise fails before it
    # can emit a coverage diagnosis.  Exclude only those rows from the B1Q
    # input, preserving the complete origin table and a machine-readable
    # missingness ledger so the resulting coverage is never overstated.
    origins = pl.read_parquet(B0_PREDICTORS)
    eligible = origins.filter(
        pl.col("spot").is_not_null() & pl.col("drop_reason").is_null()
    )
    excluded = origins.join(
        eligible.select("origin_id"), on="origin_id", how="anti"
    )
    if eligible.height == 0 or eligible["origin_id"].n_unique() != eligible.height:
        raise RuntimeError("B2_CONFIRMATION_B1_ELIGIBLE_ORIGINS_INVALID")
    B1_ORIGINS.parent.mkdir(parents=True, exist_ok=True)
    eligible.write_parquet(B1_ORIGINS, compression="zstd")
    exclusion_counts = {
        str(row["drop_reason"]): int(row["count"])
        for row in excluded.group_by("drop_reason")
        .len(name="count")
        .sort("drop_reason")
        .iter_rows(named=True)
    }
    _write_json(
        ARTIFACT_ROOT / "b1_input_manifest.json",
        {
            "schema_version": "b2-confirmation-b1-input-1.0",
            "status": "PASS_B1_INPUT_MISSINGNESS_EXPLICIT",
            "total_origin_count": origins.height,
            "eligible_origin_count": eligible.height,
            "excluded_origin_count": excluded.height,
            "exclusion_reason_counts": exclusion_counts,
            "excluded_reason_policy": (
                "B1 requires finite spot; no rows are imputed or silently dropped"
            ),
            "origin_sha256": sha256_file(B1_ORIGINS),
            "target_outcome_read": False,
            "secret_values_emitted": False,
            "personal_paths_emitted": False,
        },
    )
    return eligible, excluded, exclusion_counts


def build_b1() -> None:
    """Run the existing Massive B1Q builder over the frozen 60 sessions."""
    import run_b1_calibration_20d as b1

    _prepare_b1_origins()

    output = ARTIFACT_ROOT / "b1"
    config = b1.B1BuildConfig(
        output_root=output,
        cache_root=DATA_ROOT / "cache" / "massive",
        sessions=tuple(day.isoformat() for day in _dates()),
        origins_path=B1_ORIGINS,
    )
    b1.main(config)


def build_target() -> None:
    """Open the RV30 outcome exactly once after the protocol freeze."""
    if not ORIGINS.exists() or not BARS.exists():
        raise RuntimeError("B2_CONFIRMATION_TARGET_INPUTS_MISSING")
    freeze = _json(ROOT / "artifacts" / "methodology" / "b2_direct_protocol_freeze_v1.json")
    if freeze.get("status") != "FROZEN_DIRECT_B2_BEFORE_NEW_BLOCK_ACQUISITION":
        raise RuntimeError("B2_CONFIRMATION_METHOD_NOT_FROZEN")
    frame = build_b0v2_features(
        pl.read_parquet(BARS), pl.read_parquet(ORIGINS), include_target=True
    )
    frame.write_parquet(B0_TARGET, compression="zstd")
    _write_json(
        ARTIFACT_ROOT / "target_manifest.json",
        {
            "schema_version": "b2-confirmation-rv30-target-1.0",
            "status": "PASS_RV30_TARGET_31_CLOSES_30_RETURNS",
            "origin_count": frame.height,
            "valid_target_count": int(frame.filter(pl.col("rv30").is_not_null()).height),
            "target_definition": (
                "C(i,t) plus C(i,t+1)..C(i,t+30), exactly 30 one-minute log returns"
            ),
            "target_sha256": sha256_file(B0_TARGET),
            "target_outcome_read": True,
            "secret_values_emitted": False,
            "personal_paths_emitted": False,
        },
    )
    print(json.dumps({"status": "PASS_RV30_TARGET_31_CLOSES_30_RETURNS", "origins": frame.height}))


def build_panel() -> None:
    """Join target, B0, B1Q and direct B2 into one auditable panel."""
    required = (B0_TARGET, B2_COMBINED, ARTIFACT_ROOT / "b1" / "b1_origin_matrix_20d.parquet")
    if not all(path.exists() for path in required):
        raise RuntimeError("B2_CONFIRMATION_PANEL_INPUTS_MISSING")
    b0 = pl.read_parquet(B0_TARGET)
    b1 = pl.read_parquet(required[2])
    b2 = pl.read_parquet(B2_COMBINED)
    b0 = b0.with_columns(
        pl.col("b0v2_log_spot").exp().alias("b0_spot"),
        pl.col("b0v2_underlying_rv_5m").alias("b0_rv_5m_lag"),
        pl.col("b0v2_underlying_rv_30m").alias("b0_rv_30m_lag"),
        pl.col("b0v2_underlying_return_5m").alias("b0_return_5m_lag"),
        pl.col("b0v2_log_dollar_volume_5m").alias("b0_volume_5m_lag"),
        pl.col("session_minute").alias("b0_session_minute"),
    )
    b1 = b1.select(
        "origin_id",
        "b1q_atm_iv",
        "b1a_complete",
        "b1q_pit_evidence_valid",
        "b1q_quote_not_after_origin",
    )
    b2 = b2.select(
        "origin_id", *B2_FEATURE_NAMES, "b2v2_cutoff_utc", "b2v2_max_created_at_utc", "block_id"
    )
    panel = b0.join(b1, on="origin_id", how="inner", validate="1:1").join(
        b2, on="origin_id", how="inner", validate="1:1"
    )
    panel = panel.with_columns(
        pl.col("b1q_atm_iv").is_not_null().alias("b1_complete"),
        pl.all_horizontal([pl.col(feature).is_finite() for feature in B2_FEATURE_NAMES]).alias(
            "b2_features_finite"
        ),
    )
    if panel.filter(
        pl.col("b2v2_max_created_at_utc").is_not_null()
        & (pl.col("b2v2_max_created_at_utc") > pl.col("b2v2_cutoff_utc"))
    ).height:
        raise RuntimeError("B2_CONFIRMATION_PANEL_FUTURE_B2")
    panel.write_parquet(PANEL, compression="zstd")
    _write_json(
        ARTIFACT_ROOT / "panel_manifest.json",
        {
            "schema_version": "b2-confirmation-panel-1.0",
            "status": "PASS_PANEL_READY_FOR_FROZEN_EVALUATION",
            "origin_count": panel.height,
            "valid_rv30_count": int(panel.filter(pl.col("rv30").is_not_null()).height),
            "b1_complete_count": int(panel.filter(pl.col("b1_complete")).height),
            "b2_finite_count": int(panel.filter(pl.col("b2_features_finite")).height),
            "panel_sha256": sha256_file(PANEL),
            "target_outcome_read": True,
            "independent_samples_read": True,
            "secret_values_emitted": False,
            "personal_paths_emitted": False,
        },
    )
    print(json.dumps({"status": "PASS_PANEL_READY_FOR_FROZEN_EVALUATION", "origins": panel.height}))


def main() -> None:
    """Run one explicitly selected build stage."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--stage", choices=("origins", "fmp", "b0", "b2", "b1", "target", "panel"), required=True
    )
    stage = parser.parse_args().stage
    if stage == "origins":
        build_origins()
    elif stage == "fmp":
        build_fmp()
    elif stage == "b0":
        build_b0_predictors()
    elif stage == "b2":
        build_b2_direct()
    elif stage == "b1":
        build_b1()
    elif stage == "target":
        build_target()
    else:
        build_panel()


if __name__ == "__main__":
    main()
