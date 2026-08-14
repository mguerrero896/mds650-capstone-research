"""Source-bound, target-blind base construction for the B1v3 confirmation study."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path, PurePosixPath
from typing import Any, Final

import exchange_calendars as xcals  # type: ignore[import-untyped]
import polars as pl

from mds650.b1v3_confirmation import (
    B1V3_PREFLIGHT_ASSETS,
    canonical_sha256,
    sha256_file,
    validate_confirmation_plan_schema,
)
from mds650.b1v3_confirmation_panel import (
    build_b0_target_blind,
    build_origin_grid,
    build_spot_frame,
    normalize_fmp_session_rows,
    validate_fmp_cache_document,
)

B1V3_CANONICAL_ASSETS: Final[tuple[str, ...]] = tuple(
    sorted(("AAPL", "AMZN", "META", "MSFT", "NVDA", "TSLA"))
)
B1V3_FMP_ASSETS: Final[tuple[str, ...]] = tuple(sorted(B1V3_PREFLIGHT_ASSETS))
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
class FrozenBuildInputs:
    """Validated target-blind plan and authenticated FMP report binding."""

    plan_sha256: str
    report_sha256: str
    provider_candidate_plan_sha256: str
    source_confirmation_plan_sha256: str
    training_sessions: tuple[str, ...]
    confirmation_sessions: tuple[str, ...]
    fmp_records: tuple[Mapping[str, Any], ...]

    @property
    def all_sessions(self) -> tuple[str, ...]:
        """Return the frozen 60/30 session sequence."""
        return (*self.training_sessions, *self.confirmation_sessions)


@dataclass(frozen=True, slots=True)
class BasePredictorArtifacts:
    """Immutable paths and hashes emitted by the target-blind base build."""

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


def load_frozen_build_inputs(
    plan_path: Path,
    report_path: Path,
    provider_candidate_plan_path: Path,
    source_confirmation_plan_path: Path,
) -> FrozenBuildInputs:
    """Validate the frozen 60/30 plan and its provider-preflight report.

    Parameters
    ----------
    plan_path, report_path, provider_candidate_plan_path,
    source_confirmation_plan_path:
        Exact target-blind JSON chain.  The passed plan binds the report, the
        report binds the provider candidate, and that candidate binds the
        original confirmation plan. None may authorize outcome access.

    Returns
    -------
    FrozenBuildInputs
        Hash-bound session arrays and the 720 authenticated FMP records.

    Raises
    ------
    ValueError
        If any hash, gate, count, scope, or source identity is inconsistent.
    """
    plan = _json_object(plan_path, code="B1V3_BASE_PLAN_INVALID")
    report = _json_object(report_path, code="B1V3_BASE_PROVIDER_REPORT_INVALID")
    candidate = _json_object(
        provider_candidate_plan_path,
        code="B1V3_BASE_PROVIDER_CANDIDATE_PLAN_INVALID",
    )
    source_plan = _json_object(
        source_confirmation_plan_path,
        code="B1V3_BASE_SOURCE_CONFIRMATION_PLAN_INVALID",
    )
    plan_hash = plan.get("plan_sha256")
    report_hash = report.get("report_sha256")
    candidate_hash = candidate.get("plan_sha256")
    source_plan_hash = source_plan.get("plan_sha256")
    if not isinstance(plan_hash, str) or plan_hash != canonical_sha256(
        {key: value for key, value in plan.items() if key != "plan_sha256"}
    ):
        raise ValueError("B1V3_BASE_PLAN_HASH_INVALID")
    if not isinstance(report_hash, str) or report_hash != canonical_sha256(
        {key: value for key, value in report.items() if key != "report_sha256"}
    ):
        raise ValueError("B1V3_BASE_PROVIDER_REPORT_HASH_INVALID")
    if not isinstance(candidate_hash, str) or candidate_hash != canonical_sha256(
        {key: value for key, value in candidate.items() if key != "plan_sha256"}
    ):
        raise ValueError("B1V3_BASE_PROVIDER_CANDIDATE_PLAN_HASH_INVALID")
    if not isinstance(source_plan_hash, str) or source_plan_hash != canonical_sha256(
        {key: value for key, value in source_plan.items() if key != "plan_sha256"}
    ):
        raise ValueError("B1V3_BASE_SOURCE_CONFIRMATION_PLAN_HASH_INVALID")
    provider_binding = plan.get("provider_preflight")
    if not isinstance(provider_binding, dict):
        raise ValueError("B1V3_BASE_PROVIDER_BINDING_INVALID")
    if (
        plan.get("status") != "PASS_PRISTINE_60_30_FROZEN"
        or plan.get("target_blind") is not True
        or plan.get("safe_to_acquire") is not True
        or plan.get("safe_to_read_outcomes") is not False
        or plan.get("outcome_read_count") != 0
        or provider_binding.get("report_sha256") != report_hash
        or report.get("plan_sha256") != candidate_hash
        or candidate.get("source_confirmation_plan_sha256") != source_plan_hash
        or candidate.get("status") != "FROZEN_TARGET_BLIND_PENDING_PROVIDER_EXECUTION"
        or candidate.get("target_blind") is not True
        or candidate.get("outcome_read_count") != 0
        or source_plan.get("status") != "PENDING_DATE_LEVEL_PROVIDER_PREFLIGHT"
        or source_plan.get("target_blind") is not True
        or source_plan.get("safe_to_read_outcomes") is not False
        or source_plan.get("outcome_read_count") != 0
        or report.get("status") != "PASS_PROVIDER_PREFLIGHT_ASSUMPTION_BOUND"
        or report.get("target_blind") is not True
        or report.get("safe_to_acquire_predictors") is not True
        or report.get("safe_to_read_outcomes") is not False
        or report.get("outcome_read_count") != 0
    ):
        raise ValueError("B1V3_BASE_TARGET_BLIND_GATE_INVALID")
    training = tuple(str(value) for value in plan.get("training_sessions", ()))
    confirmation = tuple(str(value) for value in plan.get("confirmation_sessions", ()))
    if (
        len(training) != 60
        or len(confirmation) != 30
        or training != tuple(sorted(set(training)))
        or confirmation != tuple(sorted(set(confirmation)))
        or set(training) & set(confirmation)
    ):
        raise ValueError("B1V3_BASE_SESSION_SCOPE_INVALID")
    calendar = xcals.get_calendar("XNYS")
    if any(not calendar.is_session(value) for value in (*training, *confirmation)):
        raise ValueError("B1V3_BASE_SESSION_SCOPE_INVALID")
    candidate_sessions = candidate.get("sessions")
    if not isinstance(candidate_sessions, list):
        raise ValueError("B1V3_BASE_PROVIDER_CANDIDATE_SCOPE_INVALID")
    candidate_training = tuple(
        str(row.get("date", ""))
        for row in candidate_sessions
        if isinstance(row, dict) and row.get("role") == "training_warmup"
    )
    candidate_confirmation = tuple(
        str(row.get("date", ""))
        for row in candidate_sessions
        if isinstance(row, dict) and row.get("role") == "confirmation"
    )
    if (
        candidate_training != training
        or candidate_confirmation != confirmation
        or tuple(candidate.get("assets", ())) != B1V3_PREFLIGHT_ASSETS
    ):
        raise ValueError("B1V3_BASE_PROVIDER_CANDIDATE_SCOPE_INVALID")
    records = report.get("records")
    if not isinstance(records, dict) or not isinstance(records.get("fmp"), list):
        raise ValueError("B1V3_BASE_FMP_RECORDS_INVALID")
    fmp_records = tuple(records["fmp"])
    if not all(isinstance(row, dict) for row in fmp_records):
        raise ValueError("B1V3_BASE_FMP_RECORDS_INVALID")
    expected = {(day, asset) for day in (*training, *confirmation) for asset in B1V3_FMP_ASSETS}
    observed = {
        (str(row.get("session_date", "")), str(row.get("asset", "")))
        for row in fmp_records
    }
    if len(fmp_records) != len(expected) or observed != expected:
        raise ValueError("B1V3_BASE_FMP_RECORD_SCOPE_INVALID")
    return FrozenBuildInputs(
        plan_sha256=plan_hash,
        report_sha256=report_hash,
        provider_candidate_plan_sha256=candidate_hash,
        source_confirmation_plan_sha256=source_plan_hash,
        training_sessions=training,
        confirmation_sessions=confirmation,
        fmp_records=fmp_records,
    )


def _safe_cache_path(cache_root: Path, evidence_key: object) -> Path:
    if not isinstance(evidence_key, str):
        raise ValueError("B1V3_BASE_FMP_EVIDENCE_KEY_INVALID")
    relative = PurePosixPath(evidence_key)
    if relative.is_absolute() or ".." in relative.parts or relative.parts[:1] != ("fmp",):
        raise ValueError("B1V3_BASE_FMP_EVIDENCE_KEY_INVALID")
    root = cache_root.resolve()
    candidate = (root / Path(*relative.parts)).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError("B1V3_BASE_FMP_EVIDENCE_KEY_INVALID") from exc
    if not candidate.is_file():
        raise FileNotFoundError("B1V3_BASE_FMP_CACHE_MISSING")
    return candidate


def _expected_bar_timestamps(session_date: str) -> tuple[object, ...]:
    calendar = xcals.get_calendar("XNYS")
    opened = calendar.session_open(session_date).to_pydatetime()
    closed = calendar.session_close(session_date).to_pydatetime()
    count = int((closed - opened).total_seconds() // 60)
    return tuple(opened + timedelta(minutes=offset) for offset in range(count))


def build_fmp_bar_corpus(
    inputs: FrozenBuildInputs,
    *,
    cache_root: Path,
) -> tuple[pl.DataFrame, tuple[dict[str, Any], ...]]:
    """Build exact-session OHLCV solely from hash-bound authenticated caches.

    The function performs no network calls.  Every cache envelope must match
    its provider report row, and every session must equal the official XNYS
    minute grid (390 minutes normally; 210 on the frozen early close).
    """
    rows: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
    for report_record in sorted(
        inputs.fmp_records,
        key=lambda row: (str(row["session_date"]), str(row["asset"])),
    ):
        session_date = str(report_record["session_date"])
        asset = str(report_record["asset"])
        cache_path = _safe_cache_path(cache_root, report_record.get("evidence_key"))
        document = _json_object(cache_path, code="B1V3_BASE_FMP_CACHE_INVALID")
        payload = validate_fmp_cache_document(document, report_record)
        session_rows, returned_dates = normalize_fmp_session_rows(
            asset=asset,
            session_date=session_date,
            payload=payload,
        )
        expected = _expected_bar_timestamps(session_date)
        observed = tuple(sorted(row["bar_timestamp_raw_utc"] for row in session_rows))
        if observed != expected:
            raise ValueError(f"B1V3_BASE_FMP_SESSION_GRID_INVALID:{asset}:{session_date}")
        if (
            report_record.get("exact_session_row_count") != len(expected)
            or report_record.get("returned_row_count") != len(payload)
            or report_record.get("provider_over_return_count") != len(payload) - len(session_rows)
        ):
            raise ValueError("B1V3_BASE_FMP_REPORT_COUNT_MISMATCH")
        rows.extend(session_rows)
        records.append(
            {
                "asset": asset,
                "session_date": session_date,
                "row_count": len(session_rows),
                "returned_dates": list(returned_dates),
                "provider_over_return": any(value != session_date for value in returned_dates),
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
        raise ValueError("B1V3_BASE_FMP_CORPUS_IDENTITY_INVALID")
    return frame, tuple(records)


def _write_parquet_if_identical(frame: pl.DataFrame, destination: Path) -> str:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        existing = pl.read_parquet(destination)
        if not existing.equals(frame, null_equal=True):
            raise ValueError(f"B1V3_BASE_OUTPUT_CONFLICT:{destination.name}")
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


def _pretty_json(document: Mapping[str, Any]) -> bytes:
    return (json.dumps(document, indent=2, sort_keys=True, ensure_ascii=True) + "\n").encode()


def _assert_manifest_hygiene(payload: bytes) -> None:
    lowered = payload.lower()
    if any(token in lowered for token in _FORBIDDEN_SERIALIZED_TOKENS):
        raise ValueError("B1V3_BASE_MANIFEST_HYGIENE_INVALID")


def _write_json_if_identical(destination: Path, payload: bytes) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if destination.read_bytes() != payload:
            raise ValueError(f"B1V3_BASE_OUTPUT_CONFLICT:{destination.name}")
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


def _origin_identity_sha256(frame: pl.DataFrame) -> str:
    payload = {"origin_ids": [str(value) for value in frame["origin_id"].to_list()]}
    return canonical_sha256(payload)


def build_base_predictor_artifacts(
    *,
    inputs: FrozenBuildInputs,
    fmp_cache_root: Path,
    output_root: Path,
    manifest_path: Path,
    manifest_schema_path: Path,
) -> BasePredictorArtifacts:
    """Build and seal the target-blind origin, FMP, spot, and B0 artifacts.

    No RV30, QLIKE, prediction, model, or outcome source is read. Existing
    outputs are retained only when their semantic table content is identical.
    """
    origins = build_origin_grid(
        training_sessions=inputs.training_sessions,
        confirmation_sessions=inputs.confirmation_sessions,
        assets=B1V3_CANONICAL_ASSETS,
    )
    bars, fmp_records = build_fmp_bar_corpus(inputs, cache_root=fmp_cache_root)
    spots = build_spot_frame(bars, origins)
    if spots.filter(~pl.col("spot_available")).height:
        raise ValueError("B1V3_BASE_ORIGIN_SPOT_INCOMPLETE")
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
    expected_origin_count = origins.height
    if any(frame.height != expected_origin_count for frame in (b1_origins, b0)):
        raise ValueError("B1V3_BASE_ORIGIN_PRESERVATION_FAILURE")
    paths = {
        "origins": output_root / "forecast_origins_target_blind.parquet",
        "fmp_bars": output_root / "underlying_1min_target_blind.parquet",
        "b1_origins": output_root / "b1_origins_target_blind.parquet",
        "b0": output_root / "b0_target_blind.parquet",
    }
    hashes = {
        "origins": _write_parquet_if_identical(origins, paths["origins"]),
        "fmp_bars": _write_parquet_if_identical(bars, paths["fmp_bars"]),
        "b1_origins": _write_parquet_if_identical(b1_origins, paths["b1_origins"]),
        "b0": _write_parquet_if_identical(b0, paths["b0"]),
    }
    document: dict[str, Any] = {
        "schema_version": "1.0",
        "status": "PASS_TARGET_BLIND_BASE_PREDICTORS",
        "plan_sha256": inputs.plan_sha256,
        "provider_report_sha256": inputs.report_sha256,
        "provider_candidate_plan_sha256": inputs.provider_candidate_plan_sha256,
        "source_confirmation_plan_sha256": inputs.source_confirmation_plan_sha256,
        "target_blind": True,
        "outcome_read_count": 0,
        "safe_to_read_outcomes": False,
        "training_session_count": len(inputs.training_sessions),
        "confirmation_session_count": len(inputs.confirmation_sessions),
        "asset_count": len(B1V3_CANONICAL_ASSETS),
        "assets": list(B1V3_CANONICAL_ASSETS),
        "origin_count": expected_origin_count,
        "origin_identity_sha256": _origin_identity_sha256(origins),
        "fmp": {
            "asset_count": len(B1V3_FMP_ASSETS),
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
                "logical_path": f"MDS650_B1V3_DATA_ROOT/{path.name}",
                "sha256": hashes[name],
                "row_count": {
                    "origins": origins.height,
                    "fmp_bars": bars.height,
                    "b1_origins": b1_origins.height,
                    "b0": b0.height,
                }[name],
            }
            for name, path in paths.items()
        },
        "security": {
            "secret_values_emitted": False,
            "personal_paths_emitted": False,
        },
    }
    document["manifest_sha256"] = canonical_sha256(document)
    validate_confirmation_plan_schema(document, manifest_schema_path)
    manifest_payload = _pretty_json(document)
    _assert_manifest_hygiene(manifest_payload)
    _write_json_if_identical(manifest_path, manifest_payload)
    return BasePredictorArtifacts(
        origins_path=paths["origins"],
        fmp_bars_path=paths["fmp_bars"],
        b1_origins_path=paths["b1_origins"],
        b0_path=paths["b0"],
        manifest_path=manifest_path,
        manifest_sha256=sha256_file(manifest_path),
    )
