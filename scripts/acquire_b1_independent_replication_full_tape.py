"""Acquire the frozen 30-session Full Tape replication batch without outcomes."""

from __future__ import annotations

import argparse
import importlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from mds650.b1v3_confirmation import canonical_sha256
from mds650.b1v3_provider_preflight_v2 import validate_json_schema
from mds650.phase5_storage import GIB, Phase5StorageConfig, sha256_file, storage_preflight

ROOT = Path(__file__).resolve().parents[1]
PREREGISTRATION_PATH = (
    ROOT
    / "artifacts/b1_diagnostic_replication/preregistration/preregistration.json"
)
PLAN_PATH = (
    ROOT
    / "artifacts/b1_diagnostic_replication/provider_preflight/"
    "candidate_preflight_plan.json"
)
PROVIDER_REPORT_PATH = (
    ROOT
    / "artifacts/b1_diagnostic_replication/provider_preflight/"
    "provider_preflight_report.json"
)
OUT = (
    ROOT
    / "artifacts/b1_diagnostic_replication/acquisition/"
    "full_tape_acquisition_manifest.json"
)
SCHEMA_PATH = (
    ROOT
    / "specs/001-pit-options-rv30/contracts/"
    "b1-independent-replication-full-tape-v1.schema.json"
)
DATA_ROOT = Path("D:/MDS650/b1_diagnostic_replication")
CHECKPOINT_ROOT = DATA_ROOT / "manifests" / "full_tape"
SANITIZED_ENDPOINT = "/api/option-trades/full-tape/{date}"
CANONICAL_ASSETS = ("AAPL", "AMZN", "META", "MSFT", "NVDA", "TSLA")

downloader: Any = importlib.import_module("download_calibration_20d")


@dataclass(frozen=True)
class FrozenAcquisitionContract:
    """Validated target-blind inputs for one immutable Full Tape batch.

    Parameters
    ----------
    sessions:
        Exact replication trading sessions authorized for download.
    excluded_sessions:
        Development sessions that must never enter this batch.
    assets:
        Frozen six-asset research universe.
    preregistration_sha256, provider_plan_sha256, provider_report_sha256:
        Cryptographic identities binding acquisition to the frozen evidence.
    outcome_read_count:
        Must remain zero throughout target-blind acquisition.
    """

    sessions: tuple[date, ...]
    excluded_sessions: frozenset[date]
    assets: tuple[str, ...]
    preregistration_sha256: str
    provider_plan_sha256: str
    provider_report_sha256: str
    outcome_read_count: int = 0


def _load_json(path: Path, *, code: str) -> dict[str, Any]:
    """Load a required JSON object and fail with a stable reason code."""
    if not path.is_file():
        raise RuntimeError(code)
    decoded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(decoded, dict):
        raise RuntimeError(code)
    return decoded


def _valid_self_hash(payload: Mapping[str, object], field: str) -> bool:
    expected = payload.get(field)
    unsigned = {key: value for key, value in payload.items() if key != field}
    return isinstance(expected, str) and expected == canonical_sha256(unsigned)


def _string_dates(values: object, *, code: str) -> tuple[date, ...]:
    if not isinstance(values, list) or not values:
        raise RuntimeError(code)
    try:
        parsed = tuple(date.fromisoformat(str(value)) for value in values)
    except ValueError as exc:
        raise RuntimeError(code) from exc
    if parsed != tuple(sorted(set(parsed))):
        raise RuntimeError(code)
    return parsed


def validate_frozen_contract(
    preregistration: Mapping[str, object],
    plan: Mapping[str, object],
    report: Mapping[str, object],
) -> FrozenAcquisitionContract:
    """Bind the frozen preregistration, provider plan and provider evidence.

    Raises
    ------
    RuntimeError
        If any hash, session, universe, provider-count or target-blind gate is
        invalid. No provider request is made by this validation.
    """
    if not _valid_self_hash(preregistration, "manifest_sha256"):
        raise RuntimeError("PREREGISTRATION_HASH_INVALID")
    if (
        preregistration.get("status") != "FROZEN_BEFORE_PROVIDER_PAYLOAD"
        or preregistration.get("target_blind") is not True
        or preregistration.get("provider_payload_reads_at_freeze") != 0
        or preregistration.get("replication_target_reads") != 0
        or preregistration.get("safe_to_access_replication_targets") != "NO"
    ):
        raise RuntimeError("PREREGISTRATION_GATE_INVALID")
    replication = _string_dates(
        preregistration.get("replication_sessions"),
        code="REPLICATION_SESSION_SET_INVALID",
    )
    development = _string_dates(
        preregistration.get("training_sessions"),
        code="DEVELOPMENT_SESSION_SET_INVALID",
    )
    if set(replication) & set(development):
        raise RuntimeError("DEVELOPMENT_REPLICATION_OVERLAP")

    if not _valid_self_hash(plan, "plan_sha256"):
        raise RuntimeError("PROVIDER_PLAN_HASH_INVALID")
    if (
        plan.get("status") != "FROZEN_TARGET_BLIND_PENDING_PROVIDER_EXECUTION"
        or plan.get("target_blind") is not True
        or plan.get("outcome_read_count") != 0
        or plan.get("source_confirmation_plan_sha256")
        != preregistration.get("manifest_sha256")
    ):
        raise RuntimeError("PROVIDER_PLAN_GATE_INVALID")
    assets_value = plan.get("assets")
    if not isinstance(assets_value, list):
        raise RuntimeError("ASSET_BINDING_INVALID")
    assets = tuple(str(value) for value in assets_value)
    if assets != CANONICAL_ASSETS:
        raise RuntimeError("ASSET_BINDING_INVALID")
    session_rows = plan.get("sessions")
    if not isinstance(session_rows, list):
        raise RuntimeError("SESSION_BINDING_INVALID")
    plan_dates = tuple(
        date.fromisoformat(str(row.get("date")))
        for row in session_rows
        if isinstance(row, Mapping) and row.get("role") == "confirmation"
    )
    if plan_dates != replication:
        raise RuntimeError("SESSION_BINDING_INVALID")

    if not _valid_self_hash(report, "report_sha256"):
        raise RuntimeError("PROVIDER_REPORT_HASH_INVALID")
    if (
        report.get("status") != "PASS_PROVIDER_PREFLIGHT_ASSUMPTION_BOUND"
        or report.get("target_blind") is not True
        or report.get("safe_to_acquire_predictors") is not True
        or report.get("safe_to_read_outcomes") is not False
        or report.get("outcome_read_count") != 0
        or report.get("plan_sha256") != plan.get("plan_sha256")
    ):
        raise RuntimeError("PROVIDER_REPORT_GATE_INVALID")
    counts = report.get("provider_counts")
    expected_counts = {
        "fmp": len(replication) * len(assets),
        "massive": len(replication) * len(assets),
        "unusual_whales": len(replication),
    }
    if not isinstance(counts, Mapping):
        raise RuntimeError("PROVIDER_COUNT_INVALID")
    for provider, expected in expected_counts.items():
        item = counts.get(provider)
        if (
            not isinstance(item, Mapping)
            or item.get("expected") != expected
            or item.get("passed") != expected
        ):
            raise RuntimeError(f"PROVIDER_COUNT_INVALID:{provider}")
    records = report.get("records")
    uw_records = records.get("unusual_whales") if isinstance(records, Mapping) else None
    if not isinstance(uw_records, list):
        raise RuntimeError("UW_METADATA_RECORDS_INVALID")
    uw_dates = tuple(
        date.fromisoformat(str(item.get("session_date")))
        for item in uw_records
        if isinstance(item, Mapping)
    )
    if uw_dates != replication or any(
        not isinstance(item, Mapping)
        or not isinstance(item.get("content_length_bytes"), int)
        or int(item["content_length_bytes"]) <= 0
        for item in uw_records
    ):
        raise RuntimeError("UW_METADATA_RECORDS_INVALID")
    return FrozenAcquisitionContract(
        sessions=replication,
        excluded_sessions=frozenset(development),
        assets=assets,
        preregistration_sha256=str(preregistration["manifest_sha256"]),
        provider_plan_sha256=str(plan["plan_sha256"]),
        provider_report_sha256=str(report["report_sha256"]),
    )


def projected_peak_additional_bytes(report: Mapping[str, object]) -> int:
    """Estimate peak bytes using raw, Parquet, temporary and 30% margin.

    The estimate treats derived Parquet as 20% of raw, reserves two copies of
    the largest daily ZIP for bounded extraction/temporary work, then applies
    a 30% uncertainty margin. This is conservative relative to the observed
    historical Parquet/raw ratio of about 16.75%.
    """
    records = report.get("records")
    uw_records = records.get("unusual_whales") if isinstance(records, Mapping) else None
    if not isinstance(uw_records, list) or not uw_records:
        raise RuntimeError("UW_METADATA_RECORDS_INVALID")
    lengths = [
        int(item["content_length_bytes"])
        for item in uw_records
        if isinstance(item, Mapping)
        and isinstance(item.get("content_length_bytes"), int)
        and int(str(item["content_length_bytes"])) > 0
    ]
    if len(lengths) != len(uw_records):
        raise RuntimeError("UW_METADATA_RECORDS_INVALID")
    raw_total = sum(lengths)
    before_margin = raw_total * 1.20 + max(lengths) * 2
    return math.ceil(before_margin * 1.30)


def session_contract_sha256(
    session_date: str,
    preregistration_sha256: str,
    provider_report_sha256: str,
) -> str:
    """Bind one daily checkpoint to preregistration and provider evidence."""
    return canonical_sha256(
        {
            "session_date": session_date,
            "preregistration_sha256": preregistration_sha256,
            "provider_report_sha256": provider_report_sha256,
        }
    )


def _record_valid(
    record: Mapping[str, object], contract: FrozenAcquisitionContract
) -> bool:
    session_date = record.get("session_date")
    return bool(
        record.get("status") == "PASS"
        and isinstance(session_date, str)
        and record.get("preregistration_sha256")
        == contract.preregistration_sha256
        and record.get("provider_report_sha256")
        == contract.provider_report_sha256
        and record.get("session_contract_sha256")
        == session_contract_sha256(
            session_date,
            contract.preregistration_sha256,
            contract.provider_report_sha256,
        )
        and isinstance(record.get("raw_sha256"), str)
        and len(str(record["raw_sha256"])) == 64
        and isinstance(record.get("raw_bytes"), int)
        and int(str(record["raw_bytes"])) > 0
        and isinstance(record.get("parquet_files"), list)
        and bool(record["parquet_files"])
        and record.get("target_outcome_read") is False
        and record.get("outcome_read_count") == 0
        and record.get("secret_values_emitted") is False
        and record.get("personal_paths_emitted") is False
        and _valid_self_hash(record, "checkpoint_sha256")
    )


def pending_sessions(
    contract: FrozenAcquisitionContract,
    records: Sequence[Mapping[str, object]],
) -> list[str]:
    """Return exact frozen dates without a valid plan-bound checkpoint."""
    by_date: dict[str, Mapping[str, object]] = {}
    for record in records:
        session_date = record.get("session_date")
        if not isinstance(session_date, str):
            continue
        if session_date in by_date:
            raise RuntimeError("DUPLICATE_ACQUISITION_CHECKPOINT")
        by_date[session_date] = record
    return [
        day.isoformat()
        for day in contract.sessions
        if not _record_valid(by_date.get(day.isoformat(), {}), contract)
    ]


def _checkpoint_path(session_date: str) -> Path:
    return CHECKPOINT_ROOT / f"{session_date}.json"


def _safe_data_path(relative: object, config: Phase5StorageConfig) -> Path:
    if not isinstance(relative, str):
        raise RuntimeError("PARQUET_MANIFEST_INVALID")
    path = config.data_root / Path(relative)
    try:
        path.resolve().relative_to(config.data_root.resolve())
    except ValueError as exc:
        raise RuntimeError("PARQUET_PATH_ESCAPE") from exc
    return path


def _verify_checkpoint_files(
    record: Mapping[str, object], config: Phase5StorageConfig
) -> None:
    session_date = str(record["session_date"])
    raw_path = config.raw_root / session_date / f"full_tape_{session_date}.zip"
    if not raw_path.is_file() or sha256_file(raw_path) != record.get("raw_sha256"):
        raise RuntimeError(f"RAW_HASH_MISMATCH:{session_date}")
    parquet_files = record.get("parquet_files")
    if not isinstance(parquet_files, list) or not parquet_files:
        raise RuntimeError("PARQUET_MANIFEST_INVALID")
    for item in parquet_files:
        if not isinstance(item, Mapping):
            raise RuntimeError("PARQUET_MANIFEST_INVALID")
        path = _safe_data_path(item.get("relative_path"), config)
        expected = item.get("sha256")
        if not isinstance(expected, str) or not path.is_file():
            raise RuntimeError("PARQUET_MANIFEST_INVALID")
        if sha256_file(path) != expected:
            raise RuntimeError(f"PARQUET_HASH_MISMATCH:{session_date}")


def _expected_schema_fields() -> set[str] | None:
    for path in sorted(CHECKPOINT_ROOT.glob("*.json")):
        record = _load_json(path, code="ACQUISITION_CHECKPOINT_INVALID")
        fields = record.get("schema_fields")
        if record.get("status") == "PASS" and isinstance(fields, list):
            return {str(field) for field in fields}
    return None


def _parquet_manifest(day: date, config: Phase5StorageConfig) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for path in sorted(
        config.event_root.glob(f"date={day.isoformat()}/asset=*/events.parquet")
    ):
        rows.append(
            {
                "relative_path": path.relative_to(config.data_root).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    if not rows:
        raise RuntimeError(f"PARQUET_OUTPUT_MISSING:{day.isoformat()}")
    return rows


def acquire_session(
    session_date: str,
    contract: FrozenAcquisitionContract,
    config: Phase5StorageConfig,
) -> dict[str, object]:
    """Download, filter and checkpoint one allowlisted session."""
    day = date.fromisoformat(session_date)
    if day not in contract.sessions or day not in config.sessions:
        raise ValueError("ACQUISITION_SESSION_NOT_AUTHORIZED")
    checkpoint_path = _checkpoint_path(session_date)
    if checkpoint_path.exists():
        existing = _load_json(checkpoint_path, code="ACQUISITION_CHECKPOINT_INVALID")
        if not _record_valid(existing, contract):
            raise RuntimeError(f"ACQUISITION_CHECKPOINT_HASH_MISMATCH:{session_date}")
        _verify_checkpoint_files(existing, config)
        return {**existing, "reused_existing": True}

    storage_preflight(config)
    raw_path = config.raw_root / session_date / f"full_tape_{session_date}.zip"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    if raw_path.exists():
        download: dict[str, object] = {
            "http_status": None,
            "attempts": 0,
            "download_seconds": 0.0,
            "bytes": raw_path.stat().st_size,
            "sha256": sha256_file(raw_path),
            "request_id": None,
            "reused_raw_archive": True,
        }
    else:
        key = downloader._secret("UNUSUALWHALES_API_KEY")
        download = downloader._stream_download(day, key, raw_path)
        download["reused_raw_archive"] = False
    filtered = downloader.filter_session(
        day, raw_path, _expected_schema_fields(), config
    )
    parquet_files = _parquet_manifest(day, config)
    record: dict[str, object] = {
        "status": "PASS",
        "session_date": session_date,
        "source_kind": "AUTHENTICATED_DOWNLOAD",
        "completed_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "preregistration_sha256": contract.preregistration_sha256,
        "provider_plan_sha256": contract.provider_plan_sha256,
        "provider_report_sha256": contract.provider_report_sha256,
        "session_contract_sha256": session_contract_sha256(
            session_date,
            contract.preregistration_sha256,
            contract.provider_report_sha256,
        ),
        "raw_sha256": str(download["sha256"]),
        "raw_bytes": int(str(download["bytes"])),
        "http_status": download.get("http_status"),
        "request_id": download.get("request_id"),
        "request_endpoint": SANITIZED_ENDPOINT,
        "download_attempts": int(str(download["attempts"])),
        "download_seconds": float(str(download["download_seconds"])),
        "reused_raw_archive": bool(download["reused_raw_archive"]),
        "schema_fields": filtered["schema_fields"],
        "schema_fingerprint": filtered.get("schema_fingerprint"),
        "rows_seen": int(filtered["rows_seen"]),
        "rows_retained": int(filtered["rows_retained"]),
        "duplicate_event_ids": int(filtered.get("duplicate_event_ids", 0)),
        "parquet_bytes": int(filtered["parquet_bytes"]),
        "filter_seconds": float(filtered.get("filter_seconds", 0.0)),
        "parquet_files": parquet_files,
        "raw_location": "MDS650_B1_DIAGNOSTIC_REPLICATION_DATA_ROOT/raw/full_tape",
        "derived_location": (
            "MDS650_B1_DIAGNOSTIC_REPLICATION_DATA_ROOT/data/option_events"
        ),
        "target_outcome_read": False,
        "outcome_read_count": 0,
        "secret_values_emitted": False,
        "personal_paths_emitted": False,
    }
    record["checkpoint_sha256"] = canonical_sha256(record)
    downloader._atomic_json(checkpoint_path, record)
    return {**record, "reused_existing": False}


def _checkpoint_records(
    contract: FrozenAcquisitionContract,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for day in contract.sessions:
        path = _checkpoint_path(day.isoformat())
        if path.exists():
            rows.append(_load_json(path, code="ACQUISITION_CHECKPOINT_INVALID"))
    return rows


def _write_manifest(
    contract: FrozenAcquisitionContract,
    *,
    peak_bytes: int,
) -> dict[str, Any]:
    records = _checkpoint_records(contract)
    pending = pending_sessions(contract, records)
    payload: dict[str, Any] = {
        "schema_version": "b1-independent-replication-full-tape-1.0",
        "status": "PASS" if not pending else "IN_PROGRESS",
        "target_blind": True,
        "preregistration_sha256": contract.preregistration_sha256,
        "provider_plan_sha256": contract.provider_plan_sha256,
        "provider_report_sha256": contract.provider_report_sha256,
        "authorized_session_count": len(contract.sessions),
        "completed_session_count": len(records),
        "pending_session_count": len(pending),
        "pending_sessions": pending,
        "projected_peak_additional_bytes": peak_bytes,
        "sessions": records,
        "raw_location": "MDS650_B1_DIAGNOSTIC_REPLICATION_DATA_ROOT/raw/full_tape",
        "derived_location": (
            "MDS650_B1_DIAGNOSTIC_REPLICATION_DATA_ROOT/data/option_events"
        ),
        "target_outcome_read": False,
        "outcome_read_count": 0,
        "secret_values_emitted": False,
        "personal_paths_emitted": False,
    }
    payload["manifest_sha256"] = canonical_sha256(payload)
    validate_json_schema(
        payload,
        schema_path=SCHEMA_PATH,
        error_code="B1_REPLICATION_FULL_TAPE_MANIFEST_INVALID",
    )
    downloader._atomic_json(OUT, payload)
    return payload


def run() -> dict[str, object]:
    """Resume the exact 30-session target-blind Full Tape acquisition."""
    preregistration = _load_json(
        PREREGISTRATION_PATH, code="PREREGISTRATION_MISSING"
    )
    plan = _load_json(PLAN_PATH, code="PROVIDER_PLAN_MISSING")
    report = _load_json(PROVIDER_REPORT_PATH, code="PROVIDER_REPORT_MISSING")
    contract = validate_frozen_contract(preregistration, plan, report)
    if len(contract.sessions) != 30:
        raise RuntimeError("EXPECTED_EXACTLY_30_REPLICATION_SESSIONS")
    peak_bytes = projected_peak_additional_bytes(report)
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    CHECKPOINT_ROOT.mkdir(parents=True, exist_ok=True)
    config = Phase5StorageConfig(
        sessions=contract.sessions,
        excluded_dates=contract.excluded_sessions,
        data_root=DATA_ROOT,
        minimum_free_bytes=80 * GIB,
        projected_peak_additional_bytes=peak_bytes,
    )
    storage_preflight(config)
    current = _write_manifest(contract, peak_bytes=peak_bytes)
    pending = tuple(str(value) for value in current["pending_sessions"])
    for index, session_date in enumerate(pending, start=1):
        record = acquire_session(session_date, contract, config)
        current = _write_manifest(contract, peak_bytes=peak_bytes)
        print(
            json.dumps(
                {
                    "status": current["status"],
                    "session_date": session_date,
                    "completed": current["completed_session_count"],
                    "authorized": len(contract.sessions),
                    "reused_existing": record["reused_existing"],
                    "remaining_in_invocation": len(pending) - index,
                    "outcome_read_count": 0,
                    "secret_values_emitted": False,
                },
                sort_keys=True,
            ),
            flush=True,
        )
    return {
        "status": current["status"],
        "completed_session_count": current["completed_session_count"],
        "pending_session_count": current["pending_session_count"],
        "target_outcome_read": False,
        "outcome_read_count": 0,
        "secret_values_emitted": False,
    }


def main(argv: Sequence[str] | None = None) -> int:
    """Require an explicit resume flag before authenticated acquisition."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resume", action="store_true", required=True)
    parser.parse_args(argv)
    result = run()
    print(json.dumps(result, sort_keys=True))
    return int(result["status"] != "PASS")


if __name__ == "__main__":
    raise SystemExit(main())
