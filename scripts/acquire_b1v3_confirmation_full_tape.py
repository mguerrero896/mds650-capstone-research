"""Acquire only the missing B1v3 Full Tape sessions with resumable checkpoints."""

from __future__ import annotations

import argparse
import importlib
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from mds650.b1v3_confirmation import canonical_sha256
from mds650.b1v3_confirmation_acquisition import reusable_records_from_manifest
from mds650.b1v3_provider_preflight_v2 import validate_json_schema
from mds650.phase5_storage import GIB, Phase5StorageConfig, sha256_file, storage_preflight

ROOT = Path(__file__).resolve().parents[1]
PLAN_PATH = (
    ROOT
    / "artifacts/b1v3_confirmation_plan/confirmation_plan_provider_passed.json"
)
STORAGE_REUSE_PATH = (
    ROOT
    / "artifacts/b1v3_confirmation_panel/storage_and_reuse_preflight.json"
)
SOURCE_MANIFEST_PATH = (
    ROOT / "artifacts/methodology/b2_confirmation_acquisition_manifest_v1.json"
)
OUT = ROOT / "artifacts/b1v3_confirmation_panel/full_tape_acquisition_manifest.json"
SCHEMA_PATH = (
    ROOT
    / "specs/001-pit-options-rv30/contracts/"
    "b1v3-full-tape-acquisition-manifest-v1.schema.json"
)
DATA_ROOT = Path("D:/MDS650/b1v3_confirmation")
CHECKPOINT_ROOT = DATA_ROOT / "manifests" / "full_tape"
SANITIZED_ENDPOINT = "/api/option-trades/full-tape/{date}"

downloader: Any = importlib.import_module("download_calibration_20d")


def _load_json(path: Path, *, code: str) -> dict[str, Any]:
    """Load a required JSON object or fail with a stable reason code."""
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


def _plan_sessions(plan: Mapping[str, object]) -> tuple[str, ...]:
    if not _valid_self_hash(plan, "plan_sha256"):
        raise RuntimeError("B1V3_ACQUISITION_PLAN_HASH_INVALID")
    training = plan.get("training_sessions")
    confirmation = plan.get("confirmation_sessions")
    if (
        plan.get("status") != "PASS_PRISTINE_60_30_FROZEN"
        or plan.get("target_blind") is not True
        or plan.get("safe_to_acquire") is not True
        or plan.get("safe_to_read_outcomes") is not False
        or plan.get("outcome_read_count") != 0
        or not isinstance(training, list)
        or not isinstance(confirmation, list)
    ):
        raise RuntimeError("B1V3_ACQUISITION_PLAN_GATE_INVALID")
    sessions = tuple(str(value) for value in (*training, *confirmation))
    if not sessions or sessions != tuple(sorted(set(sessions))):
        raise RuntimeError("B1V3_ACQUISITION_PLAN_SESSION_INVALID")
    return sessions


def session_contract_sha256(session_date: str, plan_sha256: str) -> str:
    """Bind one immutable session checkpoint to the frozen B1v3 plan."""
    return canonical_sha256(
        {
            "session_date": session_date,
            "confirmation_plan_sha256": plan_sha256,
        }
    )


def _record_valid(record: Mapping[str, object], plan_sha256: str) -> bool:
    session_date = record.get("session_date")
    return bool(
        record.get("status") == "PASS"
        and isinstance(session_date, str)
        and record.get("confirmation_plan_sha256") == plan_sha256
        and record.get("session_contract_sha256")
        == session_contract_sha256(session_date, plan_sha256)
        and isinstance(record.get("raw_sha256"), str)
        and len(str(record["raw_sha256"])) == 64
        and isinstance(record.get("raw_bytes"), int)
        and isinstance(record.get("parquet_files"), list)
        and bool(record["parquet_files"])
        and record.get("target_outcome_read") is False
        and record.get("oos_read_count") == 0
        and record.get("secret_values_emitted") is False
        and record.get("personal_paths_emitted") is False
        and _valid_self_hash(record, "checkpoint_sha256")
    )


def pending_sessions(
    plan: Mapping[str, object], records: Sequence[Mapping[str, object]]
) -> list[str]:
    """Return plan dates without a valid plan-bound acquisition checkpoint."""
    sessions = _plan_sessions(plan)
    plan_sha256 = str(plan["plan_sha256"])
    by_date: dict[str, Mapping[str, object]] = {}
    for record in records:
        session_date = record.get("session_date")
        if not isinstance(session_date, str):
            continue
        if session_date in by_date:
            raise RuntimeError("B1V3_ACQUISITION_DUPLICATE_CHECKPOINT")
        by_date[session_date] = record
    return [
        session_date
        for session_date in sessions
        if not _record_valid(by_date.get(session_date, {}), plan_sha256)
    ]


def _checkpoint_path(session_date: str) -> Path:
    return CHECKPOINT_ROOT / f"{session_date}.json"


def _safe_data_path(relative: object, config: Phase5StorageConfig) -> Path:
    if not isinstance(relative, str):
        raise RuntimeError("B1V3_ACQUISITION_PARQUET_MANIFEST_INVALID")
    path = config.data_root / Path(relative)
    try:
        path.resolve().relative_to(config.data_root.resolve())
    except ValueError as exc:
        raise RuntimeError("B1V3_ACQUISITION_PARQUET_PATH_ESCAPE") from exc
    return path


def _verify_checkpoint_files(
    record: Mapping[str, object], config: Phase5StorageConfig
) -> None:
    session_date = str(record["session_date"])
    raw_path = config.raw_root / session_date / f"full_tape_{session_date}.zip"
    if not raw_path.is_file() or sha256_file(raw_path) != record.get("raw_sha256"):
        raise RuntimeError(f"B1V3_ACQUISITION_RAW_HASH_MISMATCH:{session_date}")
    parquet_files = record.get("parquet_files")
    if not isinstance(parquet_files, list) or not parquet_files:
        raise RuntimeError("B1V3_ACQUISITION_PARQUET_MANIFEST_INVALID")
    for item in parquet_files:
        if not isinstance(item, Mapping):
            raise RuntimeError("B1V3_ACQUISITION_PARQUET_MANIFEST_INVALID")
        expected = item.get("sha256")
        path = _safe_data_path(item.get("relative_path"), config)
        if not isinstance(expected, str) or not path.is_file():
            raise RuntimeError("B1V3_ACQUISITION_PARQUET_MANIFEST_INVALID")
        if sha256_file(path) != expected:
            raise RuntimeError(f"B1V3_ACQUISITION_PARQUET_HASH_MISMATCH:{session_date}")


def _expected_schema_fields() -> set[str] | None:
    for path in sorted(CHECKPOINT_ROOT.glob("*.json")):
        record = _load_json(path, code="B1V3_ACQUISITION_CHECKPOINT_INVALID")
        fields = record.get("schema_fields")
        if record.get("status") == "PASS" and isinstance(fields, list):
            return {str(field) for field in fields}
    return None


def _parquet_manifest(day: date, config: Phase5StorageConfig) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    pattern = f"date={day.isoformat()}/asset=*/events.parquet"
    for path in sorted(config.event_root.glob(pattern)):
        rows.append(
            {
                "relative_path": path.relative_to(config.data_root).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    if not rows:
        raise RuntimeError(f"B1V3_ACQUISITION_PARQUET_OUTPUT_MISSING:{day}")
    return rows


def acquire_session(session_date: str, config: Phase5StorageConfig) -> dict[str, object]:
    """Acquire, filter and checkpoint one explicitly allowlisted session."""
    day = date.fromisoformat(session_date)
    if day not in config.sessions:
        raise ValueError("B1V3_ACQUISITION_SESSION_NOT_AUTHORIZED")
    plan = _load_json(PLAN_PATH, code="B1V3_ACQUISITION_PLAN_INVALID")
    _plan_sessions(plan)
    plan_sha256 = str(plan["plan_sha256"])
    checkpoint_path = _checkpoint_path(session_date)
    if checkpoint_path.exists():
        existing = _load_json(
            checkpoint_path, code="B1V3_ACQUISITION_CHECKPOINT_INVALID"
        )
        if not _record_valid(existing, plan_sha256):
            raise RuntimeError(f"B1V3_ACQUISITION_CHECKPOINT_HASH_MISMATCH:{session_date}")
        _verify_checkpoint_files(existing, config)
        return {**existing, "reused_existing": True}

    storage_preflight(config)
    raw_path = config.raw_root / session_date / f"full_tape_{session_date}.zip"
    if raw_path.exists():
        raw_sha256 = sha256_file(raw_path)
        download: dict[str, object] = {
            "http_status": None,
            "attempts": 0,
            "download_seconds": 0.0,
            "bytes": raw_path.stat().st_size,
            "sha256": raw_sha256,
            "request_id": None,
            "reused_raw_archive": True,
        }
    else:
        key = downloader._secret("UNUSUALWHALES_API_KEY")
        download = downloader._stream_download(day, key, raw_path)
        raw_sha256 = str(download["sha256"])
        download["reused_raw_archive"] = False

    filtered = downloader.filter_session(day, raw_path, _expected_schema_fields(), config)
    record: dict[str, object] = {
        "status": "PASS",
        "session_date": session_date,
        "source_kind": "AUTHENTICATED_DOWNLOAD",
        "completed_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "confirmation_plan_sha256": plan_sha256,
        "session_contract_sha256": session_contract_sha256(
            session_date, plan_sha256
        ),
        "raw_sha256": raw_sha256,
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
        "parquet_files": _parquet_manifest(day, config),
        "raw_location": "MDS650_B1V3_DATA_ROOT/raw/full_tape",
        "derived_location": "MDS650_B1V3_DATA_ROOT/data/option_events",
        "target_outcome_read": False,
        "oos_read_count": 0,
        "secret_values_emitted": False,
        "personal_paths_emitted": False,
    }
    record["checkpoint_sha256"] = canonical_sha256(record)
    downloader._atomic_json(checkpoint_path, record)
    return {**record, "reused_existing": False}


def _import_reused_checkpoints(
    plan: Mapping[str, object],
    source_manifest: Mapping[str, object],
    config: Phase5StorageConfig,
) -> int:
    sessions = _plan_sessions(plan)
    plan_sha256 = str(plan["plan_sha256"])
    reusable = reusable_records_from_manifest(
        source_manifest,
        allowed_sessions=sessions,
    )
    CHECKPOINT_ROOT.mkdir(parents=True, exist_ok=True)
    for session_date, source in reusable.items():
        checkpoint_path = _checkpoint_path(session_date)
        if checkpoint_path.exists():
            existing = _load_json(
                checkpoint_path, code="B1V3_ACQUISITION_CHECKPOINT_INVALID"
            )
            if not _record_valid(existing, plan_sha256):
                raise RuntimeError(
                    f"B1V3_ACQUISITION_CHECKPOINT_HASH_MISMATCH:{session_date}"
                )
            _verify_checkpoint_files(existing, config)
            continue
        record: dict[str, object] = {
            "status": "PASS",
            "session_date": session_date,
            "source_kind": "HASH_VERIFIED_NTFS_REUSE",
            "confirmation_plan_sha256": plan_sha256,
            "session_contract_sha256": session_contract_sha256(
                session_date, plan_sha256
            ),
            "source_checkpoint_sha256": source["checkpoint_sha256"],
            "raw_sha256": source["raw_sha256"],
            "raw_bytes": source["raw_bytes"],
            "schema_fields": source.get("schema_fields", []),
            "schema_fingerprint": source.get("schema_fingerprint"),
            "rows_seen": source.get("rows_seen", 0),
            "rows_retained": source.get("rows_retained", 0),
            "duplicate_event_ids": source.get("duplicate_event_ids", 0),
            "parquet_bytes": source["parquet_bytes"],
            "parquet_files": source["parquet_files"],
            "raw_location": "MDS650_B1V3_DATA_ROOT/raw/full_tape",
            "derived_location": "MDS650_B1V3_DATA_ROOT/data/option_events",
            "target_outcome_read": False,
            "oos_read_count": 0,
            "secret_values_emitted": False,
            "personal_paths_emitted": False,
        }
        record["checkpoint_sha256"] = canonical_sha256(record)
        _verify_checkpoint_files(record, config)
        downloader._atomic_json(checkpoint_path, record)
    return len(reusable)


def _checkpoint_records(plan: Mapping[str, object]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for session_date in _plan_sessions(plan):
        path = _checkpoint_path(session_date)
        if path.exists():
            rows.append(
                _load_json(path, code="B1V3_ACQUISITION_CHECKPOINT_INVALID")
            )
    return rows


def _write_manifest(plan: dict[str, Any]) -> dict[str, Any]:
    records = _checkpoint_records(plan)
    pending = pending_sessions(plan, records)
    payload: dict[str, Any] = {
        "schema_version": "b1v3-full-tape-acquisition-1.0",
        "status": "PASS" if not pending else "IN_PROGRESS",
        "target_blind": True,
        "confirmation_plan_sha256": plan["plan_sha256"],
        "authorized_session_count": len(_plan_sessions(plan)),
        "completed_session_count": len(records),
        "pending_session_count": len(pending),
        "pending_sessions": pending,
        "sessions": records,
        "raw_location": "MDS650_B1V3_DATA_ROOT/raw/full_tape",
        "derived_location": "MDS650_B1V3_DATA_ROOT/data/option_events",
        "target_outcome_read": False,
        "oos_read_count": 0,
        "secret_values_emitted": False,
        "personal_paths_emitted": False,
    }
    payload["manifest_sha256"] = canonical_sha256(payload)
    validate_json_schema(
        payload,
        schema_path=SCHEMA_PATH,
        error_code="B1V3_FULL_TAPE_ACQUISITION_MANIFEST",
    )
    downloader._atomic_json(OUT, payload)
    return payload


def build_missing_session_config(
    *,
    sessions: Sequence[str],
    pending: Sequence[str],
    data_root: Path,
    projected_peak_additional_bytes: int,
) -> Phase5StorageConfig:
    """Build the exact missing-date allowlist and exclude every reusable date."""
    all_dates = tuple(date.fromisoformat(value) for value in sessions)
    pending_dates = tuple(date.fromisoformat(value) for value in pending)
    if not set(pending_dates) < set(all_dates):
        raise RuntimeError("B1V3_ACQUISITION_PENDING_SET_INVALID")
    return Phase5StorageConfig(
        sessions=pending_dates,
        excluded_dates=frozenset(set(all_dates) - set(pending_dates)),
        data_root=data_root,
        minimum_free_bytes=80 * GIB,
        projected_peak_additional_bytes=projected_peak_additional_bytes,
    )


def run() -> dict[str, object]:
    """Import 60 verified sessions, then resume only the frozen 30 missing dates."""
    plan = _load_json(PLAN_PATH, code="B1V3_ACQUISITION_PLAN_INVALID")
    sessions = _plan_sessions(plan)
    if len(sessions) != 90:
        raise RuntimeError("B1V3_ACQUISITION_EXPECTED_90_SESSIONS")
    storage = _load_json(
        STORAGE_REUSE_PATH,
        code="B1V3_ACQUISITION_STORAGE_REUSE_MISSING",
    )
    if (
        not _valid_self_hash(storage, "manifest_sha256")
        or storage.get("status") != "PASS_STORAGE_AND_REUSE_PREPARED"
        or storage.get("target_blind") is not True
        or storage.get("safe_to_continue") is not True
        or storage.get("outcome_read_count") != 0
    ):
        raise RuntimeError("B1V3_ACQUISITION_STORAGE_REUSE_GATE_INVALID")
    source_bindings = storage.get("source_bindings")
    if not isinstance(source_bindings, Mapping) or source_bindings.get(
        "confirmation_plan_sha256"
    ) != plan.get("plan_sha256"):
        raise RuntimeError("B1V3_ACQUISITION_STORAGE_REUSE_BINDING_INVALID")
    source_manifest = _load_json(
        SOURCE_MANIFEST_PATH,
        code="B1V3_ACQUISITION_SOURCE_MANIFEST_INVALID",
    )
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    all_config = Phase5StorageConfig(
        sessions=tuple(date.fromisoformat(value) for value in sessions),
        excluded_dates=frozenset(),
        data_root=DATA_ROOT,
        minimum_free_bytes=80 * GIB,
        projected_peak_additional_bytes=int(storage["peak_additional_bytes"]),
    )
    reused_count = _import_reused_checkpoints(plan, source_manifest, all_config)
    current = _write_manifest(plan)
    pending = tuple(str(value) for value in current["pending_sessions"])
    expected_pending = tuple(str(value) for value in storage["missing_sessions"])
    if reused_count != 60 or pending != expected_pending or len(pending) != 30:
        raise RuntimeError("B1V3_ACQUISITION_REUSE_OR_PENDING_SET_INVALID")
    missing_config = build_missing_session_config(
        sessions=sessions,
        pending=pending,
        data_root=DATA_ROOT,
        projected_peak_additional_bytes=int(storage["peak_additional_bytes"]),
    )
    for index, session_date in enumerate(pending, start=1):
        record = acquire_session(session_date, missing_config)
        current = _write_manifest(plan)
        print(
            json.dumps(
                {
                    "status": current["status"],
                    "session_date": session_date,
                    "completed": current["completed_session_count"],
                    "authorized": 90,
                    "reused_existing": record["reused_existing"],
                    "remaining_in_invocation": len(pending) - index,
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
