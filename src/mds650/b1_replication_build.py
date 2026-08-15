"""Target-blind construction primitives for the independent replication."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path, PurePosixPath
from typing import Any, Final
from zoneinfo import ZoneInfo

import exchange_calendars as xcals  # type: ignore[import-untyped]
import polars as pl

from mds650.b1v3_confirmation import canonical_sha256, sha256_file
from mds650.b1v3_confirmation_panel import (
    build_b0_target_blind,
    build_spot_frame,
    normalize_fmp_session_rows,
    validate_fmp_cache_document,
)
from mds650.b1v3_provider_preflight_v2 import validate_json_schema

CANONICAL_ASSETS: Final[tuple[str, ...]] = (
    "AAPL",
    "AMZN",
    "META",
    "MSFT",
    "NVDA",
    "TSLA",
)
FMP_ASSETS: Final[tuple[str, ...]] = (
    "AAPL",
    "AMZN",
    "META",
    "MSFT",
    "NVDA",
    "QQQ",
    "SPY",
    "TSLA",
)
_NEW_YORK: Final[ZoneInfo] = ZoneInfo("America/New_York")
_FORBIDDEN_SERIALIZED_TOKENS: Final[tuple[bytes, ...]] = (
    b"c:\\users\\",
    b"c:/users/",
    b"d:\\mds650",
    b"api_key",
    b"apikey",
    b"authorization",
    b"bearer ",
)


@dataclass(frozen=True, slots=True)
class ReplicationBaseInputs:
    """Hash-bound FMP evidence for the 30-session target-blind base layer."""

    preregistration_sha256: str
    primary_plan_sha256: str
    primary_report_sha256: str
    market_plan_sha256: str
    market_report_sha256: str
    sessions: tuple[date, ...]
    fmp_records: tuple[Mapping[str, Any], ...]


@dataclass(frozen=True, slots=True)
class ReplicationBaseArtifacts:
    """Paths and manifest identity emitted by the base predictor build."""

    origins_path: Path
    fmp_bars_path: Path
    b1_origins_path: Path
    b0_path: Path
    manifest_path: Path
    manifest_sha256: str


def _json_object(path: Path, *, code: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(code) from exc
    if not isinstance(value, dict):
        raise ValueError(code)
    return value


def _valid_self_hash(payload: Mapping[str, object], field: str) -> bool:
    stored = payload.get(field)
    unsigned = {key: value for key, value in payload.items() if key != field}
    return isinstance(stored, str) and stored == canonical_sha256(unsigned)


def _session_dates(plan: Mapping[str, object]) -> tuple[date, ...]:
    raw = plan.get("sessions")
    if not isinstance(raw, list):
        raise ValueError("REPLICATION_BASE_PLAN_SESSION_INVALID")
    parsed = tuple(
        date.fromisoformat(str(item.get("date")))
        for item in raw
        if isinstance(item, Mapping) and item.get("role") == "confirmation"
    )
    if len(parsed) != 30 or parsed != tuple(sorted(set(parsed))):
        raise ValueError("REPLICATION_BASE_PLAN_SESSION_INVALID")
    return parsed


def load_replication_base_inputs(
    *,
    preregistration_path: Path,
    primary_plan_path: Path,
    primary_report_path: Path,
    market_plan_path: Path,
    market_report_path: Path,
) -> ReplicationBaseInputs:
    """Validate the two provider reports without reading any outcome source.

    The primary report supplies six underlyings; the supplement supplies only
    SPY and QQQ, which were already part of the frozen B0 information set.
    Every report and plan is canonically self-hashed and bound to the same
    preregistration.
    """
    prereg = _json_object(preregistration_path, code="REPLICATION_BASE_PREREG_INVALID")
    primary_plan = _json_object(
        primary_plan_path, code="REPLICATION_BASE_PRIMARY_PLAN_INVALID"
    )
    primary_report = _json_object(
        primary_report_path, code="REPLICATION_BASE_PRIMARY_REPORT_INVALID"
    )
    market_plan = _json_object(
        market_plan_path, code="REPLICATION_BASE_MARKET_PLAN_INVALID"
    )
    market_report = _json_object(
        market_report_path, code="REPLICATION_BASE_MARKET_REPORT_INVALID"
    )
    if not _valid_self_hash(prereg, "manifest_sha256"):
        raise ValueError("REPLICATION_BASE_PREREG_HASH_INVALID")
    prereg_hash = str(prereg["manifest_sha256"])
    if (
        prereg.get("status") != "FROZEN_BEFORE_PROVIDER_PAYLOAD"
        or prereg.get("target_blind") is not True
        or prereg.get("replication_target_reads") != 0
    ):
        raise ValueError("REPLICATION_BASE_PREREG_GATE_INVALID")
    plan_report_pairs = (
        (primary_plan, primary_report, "PRIMARY"),
        (market_plan, market_report, "MARKET"),
    )
    for plan, report, label in plan_report_pairs:
        if not _valid_self_hash(plan, "plan_sha256"):
            raise ValueError(f"REPLICATION_BASE_{label}_PLAN_HASH_INVALID")
        if not _valid_self_hash(report, "report_sha256"):
            raise ValueError(f"REPLICATION_BASE_{label}_REPORT_HASH_INVALID")
        if (
            plan.get("source_confirmation_plan_sha256") != prereg_hash
            or plan.get("target_blind") is not True
            or plan.get("outcome_read_count") != 0
            or report.get("plan_sha256") != plan.get("plan_sha256")
            or report.get("status")
            != "PASS_PROVIDER_PREFLIGHT_ASSUMPTION_BOUND"
            or report.get("target_blind") is not True
            or report.get("safe_to_acquire_predictors") is not True
            or report.get("safe_to_read_outcomes") is not False
            or report.get("outcome_read_count") != 0
        ):
            raise ValueError(f"REPLICATION_BASE_{label}_GATE_INVALID")
    sessions = _session_dates(primary_plan)
    if _session_dates(market_plan) != sessions:
        raise ValueError("REPLICATION_BASE_PLAN_SESSION_MISMATCH")
    if tuple(primary_plan.get("assets", ())) != CANONICAL_ASSETS:
        raise ValueError("REPLICATION_BASE_PRIMARY_ASSET_INVALID")
    if tuple(market_plan.get("assets", ())) != ("SPY", "QQQ"):
        raise ValueError("REPLICATION_BASE_MARKET_ASSET_INVALID")
    records: list[Mapping[str, Any]] = []
    for report in (primary_report, market_report):
        container = report.get("records")
        fmp = container.get("fmp") if isinstance(container, Mapping) else None
        if not isinstance(fmp, list) or not all(isinstance(item, Mapping) for item in fmp):
            raise ValueError("REPLICATION_BASE_FMP_RECORD_INVALID")
        records.extend(fmp)
    expected = {
        (day.isoformat(), asset) for day in sessions for asset in FMP_ASSETS
    }
    observed = {
        (str(item.get("session_date")), str(item.get("asset"))) for item in records
    }
    if len(records) != len(expected) or observed != expected:
        raise ValueError("REPLICATION_BASE_FMP_SCOPE_INVALID")
    return ReplicationBaseInputs(
        preregistration_sha256=prereg_hash,
        primary_plan_sha256=str(primary_plan["plan_sha256"]),
        primary_report_sha256=str(primary_report["report_sha256"]),
        market_plan_sha256=str(market_plan["plan_sha256"]),
        market_report_sha256=str(market_report["report_sha256"]),
        sessions=sessions,
        fmp_records=tuple(records),
    )


def build_replication_origin_grid(sessions: Sequence[date]) -> pl.DataFrame:
    """Build every five-minute RV30-safe origin for frozen XNYS sessions.

    Parameters
    ----------
    sessions:
        Sorted, unique XNYS dates in the independent-replication block.

    Returns
    -------
    polars.DataFrame
        Six-asset, target-free origin grid from open plus five minutes through
        close minus thirty minutes. Early closes are handled by the official
        calendar rather than a fixed row count.

    Raises
    ------
    ValueError
        If the allowlist is empty, unordered, duplicated or contains a date
        that is not an XNYS trading session.
    """
    frozen = tuple(sessions)
    if not frozen or frozen != tuple(sorted(set(frozen))):
        raise ValueError("REPLICATION_ORIGIN_ALLOWLIST_INVALID")
    calendar = xcals.get_calendar("XNYS")
    rows: list[dict[str, Any]] = []
    for session in frozen:
        session_date = session.isoformat()
        if not calendar.is_session(session_date):
            raise ValueError("REPLICATION_ORIGIN_NOT_XNYS_SESSION")
        opened = calendar.session_open(session_date).to_pydatetime()
        closed = calendar.session_close(session_date).to_pydatetime()
        origin = opened + timedelta(minutes=5)
        last_origin = closed - timedelta(minutes=30)
        while origin <= last_origin:
            session_minute = int((origin - opened).total_seconds() // 60)
            session_tercile = (
                "first"
                if session_minute < 130
                else "middle"
                if session_minute < 260
                else "last"
            )
            for asset in CANONICAL_ASSETS:
                rows.append(
                    {
                        "origin_id": f"{asset}:{origin.isoformat()}",
                        "asset": asset,
                        "session_date": session_date,
                        "forecast_origin_utc": origin,
                        "forecast_origin_ny": origin.astimezone(_NEW_YORK),
                        "forecast_origin_ns": int(origin.timestamp() * 1_000_000_000),
                        "role": "independent_replication",
                        "session_minute": session_minute,
                        "session_tercile": session_tercile,
                        "session_segment": session_tercile,
                    }
                )
            origin += timedelta(minutes=5)
    frame = pl.DataFrame(rows, infer_schema_length=None).sort(
        "session_date", "forecast_origin_utc", "asset"
    )
    if frame.is_empty() or frame["origin_id"].n_unique() != frame.height:
        raise ValueError("REPLICATION_ORIGIN_GRID_INVALID")
    return frame


def _safe_cache_path(cache_root: Path, evidence_key: object) -> Path:
    if not isinstance(evidence_key, str):
        raise ValueError("REPLICATION_BASE_FMP_EVIDENCE_KEY_INVALID")
    relative = PurePosixPath(evidence_key)
    if relative.is_absolute() or ".." in relative.parts or relative.parts[:1] != ("fmp",):
        raise ValueError("REPLICATION_BASE_FMP_EVIDENCE_KEY_INVALID")
    root = cache_root.resolve()
    candidate = (root / Path(*relative.parts)).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError("REPLICATION_BASE_FMP_EVIDENCE_KEY_INVALID") from exc
    if not candidate.is_file():
        raise FileNotFoundError("REPLICATION_BASE_FMP_CACHE_MISSING")
    return candidate


def _expected_bar_timestamps(session: date) -> tuple[object, ...]:
    calendar = xcals.get_calendar("XNYS")
    opened = calendar.session_open(session.isoformat()).to_pydatetime()
    closed = calendar.session_close(session.isoformat()).to_pydatetime()
    count = int((closed - opened).total_seconds() // 60)
    return tuple(opened + timedelta(minutes=offset) for offset in range(count))


def build_replication_fmp_corpus(
    inputs: ReplicationBaseInputs,
    *,
    cache_root: Path,
) -> tuple[pl.DataFrame, tuple[dict[str, Any], ...]]:
    """Build eight-symbol exact-session OHLCV from authenticated caches only."""
    rows: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
    for report_record in sorted(
        inputs.fmp_records,
        key=lambda item: (str(item["session_date"]), str(item["asset"])),
    ):
        session_date = str(report_record["session_date"])
        asset = str(report_record["asset"])
        cache_path = _safe_cache_path(cache_root, report_record.get("evidence_key"))
        document = _json_object(cache_path, code="REPLICATION_BASE_FMP_CACHE_INVALID")
        payload = validate_fmp_cache_document(document, report_record)
        session_rows, returned_dates = normalize_fmp_session_rows(
            asset=asset,
            session_date=session_date,
            payload=payload,
        )
        expected = _expected_bar_timestamps(date.fromisoformat(session_date))
        observed = tuple(sorted(item["bar_timestamp_raw_utc"] for item in session_rows))
        if observed != expected:
            raise ValueError(
                f"REPLICATION_BASE_FMP_SESSION_GRID_INVALID:{asset}:{session_date}"
            )
        if (
            report_record.get("exact_session_row_count") != len(expected)
            or report_record.get("returned_row_count") != len(payload)
            or report_record.get("provider_over_return_count")
            != len(payload) - len(session_rows)
        ):
            raise ValueError("REPLICATION_BASE_FMP_REPORT_COUNT_MISMATCH")
        rows.extend(session_rows)
        records.append(
            {
                "asset": asset,
                "session_date": session_date,
                "row_count": len(session_rows),
                "returned_dates": list(returned_dates),
                "provider_over_return": any(
                    value != session_date for value in returned_dates
                ),
                "request_fingerprint": str(report_record["request_fingerprint"]),
                "response_sha256": str(report_record["response_sha256"]),
                "cache_self_hash": str(document["cache_self_hash"]),
            }
        )
    frame = pl.DataFrame(rows, infer_schema_length=None).sort(
        "session_date", "bar_timestamp_raw_utc", "asset"
    )
    if (
        frame.is_empty()
        or frame.select(
            pl.struct("asset", "session_date", "bar_timestamp_raw_utc").n_unique()
        ).item()
        != frame.height
    ):
        raise ValueError("REPLICATION_BASE_FMP_CORPUS_IDENTITY_INVALID")
    return frame, tuple(records)


def _write_parquet_if_identical(frame: pl.DataFrame, destination: Path) -> str:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        existing = pl.read_parquet(destination)
        if not existing.equals(frame, null_equal=True):
            raise ValueError(f"REPLICATION_BASE_OUTPUT_CONFLICT:{destination.name}")
        return sha256_file(destination)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".part", dir=destination.parent
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        frame.write_parquet(temporary, compression="zstd", statistics=True)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return sha256_file(destination)


def _json_bytes(document: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(document, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    ).encode()


def _write_json_if_identical(destination: Path, payload: bytes) -> None:
    lowered = payload.lower()
    if any(token in lowered for token in _FORBIDDEN_SERIALIZED_TOKENS):
        raise ValueError("REPLICATION_BASE_MANIFEST_HYGIENE_INVALID")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if destination.read_bytes() != payload:
            raise ValueError(f"REPLICATION_BASE_OUTPUT_CONFLICT:{destination.name}")
        return
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".part", dir=destination.parent
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        temporary.write_bytes(payload)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def build_replication_base_artifacts(
    *,
    inputs: ReplicationBaseInputs,
    fmp_cache_root: Path,
    output_root: Path,
    manifest_path: Path,
    manifest_schema_path: Path,
) -> ReplicationBaseArtifacts:
    """Build and seal FMP, origin, spot and B0 predictors without outcomes."""
    origins = build_replication_origin_grid(inputs.sessions)
    bars, fmp_records = build_replication_fmp_corpus(
        inputs, cache_root=fmp_cache_root
    )
    spots = build_spot_frame(bars, origins)
    if spots.filter(~pl.col("spot_available")).height:
        raise ValueError("REPLICATION_BASE_ORIGIN_SPOT_INCOMPLETE")
    b1_origins = origins.join(
        spots.select(
            "origin_id",
            "spot",
            "spot_bar_timestamp_raw_utc",
            "spot_available_at_utc",
            "spot_available",
            "spot_missing_reason",
        ),
        on="origin_id",
        how="left",
        validate="1:1",
    )
    b0 = build_b0_target_blind(bars, origins)
    if any(frame.height != origins.height for frame in (b1_origins, b0)):
        raise ValueError("REPLICATION_BASE_ORIGIN_PRESERVATION_FAILURE")
    forbidden = ("rv30", "qlike", "prediction", "outcome", "model_result")
    for frame in (origins, bars, b1_origins, b0):
        if any(token in column.lower() for column in frame.columns for token in forbidden):
            raise ValueError("REPLICATION_BASE_FORBIDDEN_COLUMN")
    paths = {
        "origins": output_root / "forecast_origins_target_blind.parquet",
        "fmp_bars": output_root / "underlying_1min_target_blind.parquet",
        "b1_origins": output_root / "b1_origins_target_blind.parquet",
        "b0": output_root / "b0_target_blind.parquet",
    }
    frames = {
        "origins": origins,
        "fmp_bars": bars,
        "b1_origins": b1_origins,
        "b0": b0,
    }
    hashes = {
        name: _write_parquet_if_identical(frames[name], path)
        for name, path in paths.items()
    }
    origin_identity = canonical_sha256(
        {"origin_ids": [str(value) for value in origins["origin_id"].to_list()]}
    )
    document: dict[str, Any] = {
        "schema_version": "b1-independent-replication-base-1.0",
        "status": "PASS_TARGET_BLIND_BASE_PREDICTORS",
        "target_blind": True,
        "outcome_read_count": 0,
        "safe_to_read_outcomes": False,
        "preregistration_sha256": inputs.preregistration_sha256,
        "primary_plan_sha256": inputs.primary_plan_sha256,
        "primary_report_sha256": inputs.primary_report_sha256,
        "market_plan_sha256": inputs.market_plan_sha256,
        "market_report_sha256": inputs.market_report_sha256,
        "session_count": len(inputs.sessions),
        "asset_count": len(CANONICAL_ASSETS),
        "assets": list(CANONICAL_ASSETS),
        "market_controls": ["SPY", "QQQ"],
        "origin_count": origins.height,
        "origin_identity_sha256": origin_identity,
        "fmp": {
            "asset_count": len(FMP_ASSETS),
            "session_asset_count": len(fmp_records),
            "bar_count": bars.height,
            "availability_primary": "timestamp_raw_plus_1_minute",
            "availability_sensitivity": "timestamp_raw_plus_2_minutes",
            "provider_semantics_status": "CONSERVATIVE_RESEARCH_ASSUMPTION",
            "records_sha256": canonical_sha256({"records": list(fmp_records)}),
        },
        "b0": {
            "row_count": b0.height,
            "complete_row_count": b0.filter(pl.col("b0_complete")).height,
            "missing_row_count": b0.filter(~pl.col("b0_complete")).height,
        },
        "outputs": {
            name: {
                "logical_path": f"MDS650_B1_REPLICATION_DATA_ROOT/predictors/{path.name}",
                "sha256": hashes[name],
                "row_count": frames[name].height,
            }
            for name, path in paths.items()
        },
        "security": {
            "secret_values_emitted": False,
            "personal_paths_emitted": False,
        },
    }
    document["manifest_sha256"] = canonical_sha256(document)
    validate_json_schema(
        document,
        schema_path=manifest_schema_path,
        error_code="REPLICATION_BASE_MANIFEST",
    )
    _write_json_if_identical(manifest_path, _json_bytes(document))
    return ReplicationBaseArtifacts(
        origins_path=paths["origins"],
        fmp_bars_path=paths["fmp_bars"],
        b1_origins_path=paths["b1_origins"],
        b0_path=paths["b0"],
        manifest_path=manifest_path,
        manifest_sha256=sha256_file(manifest_path),
    )
