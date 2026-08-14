"""Download and filter an explicitly authorized Unusual Whales session batch.

The no-argument mode retains the Phase 3F twenty-session allow-list. Phase 5
loads its development-only allow-list from frozen, hash-validated manifests.
"""
# ruff: noqa: E501

from __future__ import annotations

import argparse
import csv
import ctypes
import ctypes.wintypes
import hashlib
import io
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import time as time_module
import zipfile
from collections import Counter
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import exchange_calendars as xcals  # type: ignore[import-untyped]
import httpx
import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from mds650.contracts import CANDIDATE_ASSETS
from mds650.phase5_storage import (
    Phase5StorageConfig,
    build_phase5_holdout_storage_config,
    build_phase5_storage_config,
)
from mds650.phase5_storage import (
    storage_preflight as phase5_storage_preflight,
)
from mds650.study_design import canonical_sha256

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts" / "calibration_20d"
RAW_ROOT = OUT / "raw" / "full_tape"
EVENT_ROOT = OUT / "option_events"
MANIFEST_ROOT = OUT / "manifests"
MIN_FREE_BYTES = 90 * 1024**3
PILOT_DATES = frozenset(date(2026, 7, day) for day in range(13, 18))
SESSIONS: tuple[date, ...] = (
    date(2026, 6, 11),
    date(2026, 6, 12),
    date(2026, 6, 15),
    date(2026, 6, 16),
    date(2026, 6, 17),
    date(2026, 6, 18),
    date(2026, 6, 22),
    date(2026, 6, 23),
    date(2026, 6, 24),
    date(2026, 6, 25),
    date(2026, 6, 26),
    date(2026, 6, 29),
    date(2026, 6, 30),
    date(2026, 7, 1),
    date(2026, 7, 2),
    date(2026, 7, 6),
    date(2026, 7, 7),
    date(2026, 7, 8),
    date(2026, 7, 9),
    date(2026, 7, 10),
)
ASSETS = tuple(sorted(CANDIDATE_ASSETS))
XNYS = xcals.get_calendar("XNYS")
ENDPOINT = "https://api.unusualwhales.com/api/option-trades/full-tape/{day}"
EVENT_FIELDS = (
    "id",
    "underlying_symbol",
    "executed_at",
    "nbbo_bid",
    "nbbo_ask",
    "size",
    "price",
    "option_chain_id",
    "created_at",
    "report_flags",
    "tags",
    "expiry",
    "option_type",
    "open_interest",
    "strike",
    "premium",
    "volume",
    "implied_volatility",
    "exchange",
    "ask_vol",
    "bid_vol",
    "no_side_vol",
    "mid_vol",
    "multi_vol",
    "upstream_condition_detail",
)
EVENT_SCHEMA = pa.schema(
    [
        pa.field("id", pa.string()),
        pa.field("underlying_symbol", pa.string()),
        pa.field("option_chain_id", pa.string()),
        pa.field("executed_at", pa.timestamp("us", tz="UTC")),
        pa.field("created_at", pa.timestamp("us", tz="UTC")),
        pa.field("nbbo_bid", pa.float64()),
        pa.field("nbbo_ask", pa.float64()),
        pa.field("price", pa.float64()),
        pa.field("size", pa.float64()),
        pa.field("premium", pa.float64()),
        pa.field("volume", pa.int64()),
        pa.field("open_interest", pa.int64()),
        pa.field("implied_volatility", pa.float64()),
        pa.field("expiry", pa.date32()),
        pa.field("strike", pa.float64()),
        pa.field("option_type", pa.string()),
        pa.field("report_flags", pa.string()),
        pa.field("tags", pa.string()),
        pa.field("ask_vol", pa.int64()),
        pa.field("bid_vol", pa.int64()),
        pa.field("no_side_vol", pa.int64()),
        pa.field("mid_vol", pa.int64()),
        pa.field("multi_vol", pa.int64()),
        pa.field("exchange", pa.string()),
        pa.field("upstream_condition_detail", pa.string()),
    ]
)


class _ProcessMemoryCounters(ctypes.Structure):
    """Minimal Windows working-set structure used for bounded telemetry."""

    _fields_ = [
        ("cb", ctypes.c_ulong),
        ("PageFaultCount", ctypes.c_ulong),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


def _working_set_bytes() -> int | None:
    """Return current process working set on Windows without tracking allocations."""
    if os.name != "nt":
        return None
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    get_current_process = kernel32.GetCurrentProcess
    get_current_process.restype = ctypes.wintypes.HANDLE
    get_memory_info = psapi.GetProcessMemoryInfo
    get_memory_info.argtypes = [
        ctypes.wintypes.HANDLE,
        ctypes.POINTER(_ProcessMemoryCounters),
        ctypes.wintypes.DWORD,
    ]
    get_memory_info.restype = ctypes.wintypes.BOOL
    counters = _ProcessMemoryCounters()
    counters.cb = ctypes.sizeof(counters)
    success = get_memory_info(
        get_current_process(), ctypes.byref(counters), ctypes.sizeof(counters)
    )
    return int(counters.WorkingSetSize) if success else None


def _secret(name: str) -> str:
    """Return a required secret without logging its value.

    Raises
    ------
    RuntimeError
        If the environment variable is absent or blank.
    """
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"MISSING_SECRET:{name}")
    return value


def _relative(path: Path, base: Path = ROOT) -> str:
    """Return a configured-root-relative path for sanitized evidence."""
    return path.resolve().relative_to(base.resolve()).as_posix()


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    """Write a JSON checkpoint atomically beside its final path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        json.dump(payload, handle, indent=2, sort_keys=True, default=str)
        temporary = Path(handle.name)
    temporary.replace(path)


def _dt(value: str) -> datetime:
    """Parse an ISO timestamp and normalize it to UTC."""
    normalized = value.strip().replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("TIMESTAMP_TIMEZONE_REQUIRED")
    return parsed.astimezone(UTC)


def _number(value: str | None, *, integer: bool = False) -> int | float | None:
    """Parse a nullable numeric CSV field without coercing invalid values."""
    if value is None or value == "":
        return None
    try:
        return int(float(value)) if integer else float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("NUMERIC_FIELD_INVALID") from exc


def _regular(timestamp: datetime, session_date: date) -> bool:
    """Return whether a UTC timestamp is inside the official XNYS session.

    The calendar-derived close is material for early-close sessions. A static
    16:00 New York bound would otherwise retain trades that occurred after the
    regular session and contaminate the point-in-time feature window.
    """
    session = XNYS.date_to_session(session_date.isoformat())
    session_open = XNYS.session_open(session).to_pydatetime()
    session_close = XNYS.session_close(session).to_pydatetime()
    return session_open <= timestamp.astimezone(UTC) < session_close


def _event_row(row: dict[str, str]) -> dict[str, Any]:
    """Normalize one retained Full Tape row to the stable Parquet schema."""
    expiry = date.fromisoformat(row["expiry"]) if row.get("expiry") else None
    return {
        "id": row.get("id"),
        "underlying_symbol": row.get("underlying_symbol"),
        "option_chain_id": row.get("option_chain_id"),
        "executed_at": _dt(row["executed_at"]),
        "created_at": _dt(row["created_at"]),
        "nbbo_bid": _number(row.get("nbbo_bid")),
        "nbbo_ask": _number(row.get("nbbo_ask")),
        "price": _number(row.get("price")),
        "size": _number(row.get("size")),
        "premium": _number(row.get("premium")),
        "volume": _number(row.get("volume"), integer=True),
        "open_interest": _number(row.get("open_interest"), integer=True),
        "implied_volatility": _number(row.get("implied_volatility")),
        "expiry": expiry,
        "strike": _number(row.get("strike")),
        "option_type": row.get("option_type"),
        "report_flags": row.get("report_flags"),
        "tags": row.get("tags"),
        "ask_vol": _number(row.get("ask_vol"), integer=True),
        "bid_vol": _number(row.get("bid_vol"), integer=True),
        "no_side_vol": _number(row.get("no_side_vol"), integer=True),
        "mid_vol": _number(row.get("mid_vol"), integer=True),
        "multi_vol": _number(row.get("multi_vol"), integer=True),
        "exchange": row.get("exchange"),
        "upstream_condition_detail": row.get("upstream_condition_detail"),
    }


def storage_preflight(config: Phase5StorageConfig | None = None) -> dict[str, Any]:
    """Validate storage, write access, secret presence and cache boundaries.

    Returns
    -------
    dict
        Sanitized preflight evidence; secret values are never returned.

    Raises
    ------
    RuntimeError
        If storage is below the configured minimum or the destination is not writable.
    """
    if config is None:
        OUT.mkdir(parents=True, exist_ok=True)
        usage = shutil.disk_usage(ROOT)
        with tempfile.NamedTemporaryFile("wb", dir=OUT, delete=True) as handle:
            handle.write(b"MDS650_PHASE_3F_WRITE_PROBE")
            handle.flush()
        capacity = {
            "free_bytes": usage.free,
            "required_min_free_bytes": MIN_FREE_BYTES,
            "free_space_pass": usage.free >= MIN_FREE_BYTES,
            "write_probe_pass": True,
        }
        sessions = SESSIONS
        excluded_dates = PILOT_DATES
    else:
        capacity = phase5_storage_preflight(config)
        sessions = config.sessions
        excluded_dates = config.excluded_dates
    legacy_root = ROOT / "artifacts" / "b1_full_origin" / "massive_contract_day_cache"
    legacy = list(legacy_root.glob("*.json")) if legacy_root.exists() else []
    evidence: dict[str, Any] = {
        **capacity,
        "secret_presence": {
            name: bool(os.environ.get(name))
            for name in ("UNUSUALWHALES_API_KEY", "MASSIVE_API_KEY", "FMP_API_KEY")
        },
        "legacy_cache_status": "LEGACY_CACHE_READ_ONLY",
        "legacy_cache_files": len(legacy),
        "active_cache_status": (
            "ACTIVE_PHASE5_SSD_CACHE_ONLY"
            if config is not None
            else "ACTIVE_CALIBRATION_CACHE_V2_ONLY"
        ),
        "authorized_sessions": [day.isoformat() for day in sessions],
        "excluded_dates": sorted(day.isoformat() for day in excluded_dates),
        "network_calls_started": False,
        "secret_values_emitted": False,
        "personal_paths_emitted": False,
    }
    if not evidence["free_space_pass"]:
        raise RuntimeError("INSUFFICIENT_STORAGE_FOR_PHASE_3F")
    if not all(evidence["secret_presence"].values()):
        missing = [key for key, present in evidence["secret_presence"].items() if not present]
        raise RuntimeError(f"MISSING_SECRET:{','.join(missing)}")
    return evidence


def _stream_download(day: date, key: str, destination: Path) -> dict[str, Any]:
    """Stream one ZIP to disk with retries and an incremental SHA-256."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(destination.suffix + ".part")
    started = time_module.perf_counter()
    attempts = 0
    for attempt in range(1, 5):
        attempts = attempt
        if partial.exists():
            partial.unlink()
        digest = hashlib.sha256()
        try:
            with (
                httpx.Client(
                    timeout=httpx.Timeout(180.0, connect=30.0), follow_redirects=True
                ) as client,
                client.stream(
                    "GET",
                    ENDPOINT.format(day=day.isoformat()),
                    headers={
                        "Authorization": f"Bearer {key}",
                        "Accept": "application/json",
                    },
                ) as response,
            ):
                status = response.status_code
                if status == 429 or status >= 500:
                    raise httpx.HTTPStatusError(
                        "RETRYABLE_PROVIDER_STATUS", request=response.request, response=response
                    )
                response.raise_for_status()
                with partial.open("wb") as handle:
                    for chunk in response.iter_bytes(8 * 1024 * 1024):
                        if chunk:
                            digest.update(chunk)
                            handle.write(chunk)
            partial.replace(destination)
            return {
                "http_status": status,
                "attempts": attempts,
                "download_seconds": time_module.perf_counter() - started,
                "bytes": destination.stat().st_size,
                "sha256": digest.hexdigest(),
                "endpoint": ENDPOINT.format(day=day.isoformat()),
                "request_id": None,
            }
        except (httpx.HTTPError, OSError) as exc:
            if partial.exists():
                partial.unlink()
            if attempt == 4:
                raise RuntimeError(f"FULL_TAPE_DOWNLOAD_FAILED:{day}:{type(exc).__name__}") from exc
            time_module.sleep(2 ** (attempt - 1))
    raise AssertionError("UNREACHABLE_DOWNLOAD_LOOP")


def _validate_zip(path: Path, expected_fields: set[str] | None) -> tuple[str, set[str], int]:
    """Validate ZIP CRC and return its CSV member, header and compressed bytes."""
    with zipfile.ZipFile(path) as archive:
        if archive.testzip() is not None:
            raise RuntimeError("FULL_TAPE_ZIP_CRC_FAILURE")
        members = [info for info in archive.infolist() if info.filename.lower().endswith(".csv")]
        if len(members) != 1:
            raise RuntimeError("FULL_TAPE_CSV_MEMBER_AMBIGUOUS")
        member = members[0]
        with archive.open(member) as raw:
            header_line = raw.readline().decode("utf-8", "strict").strip()
        fields = set(next(csv.reader([header_line])))
        missing = set(EVENT_FIELDS) - fields
        if missing:
            raise RuntimeError(f"FULL_TAPE_SCHEMA_DRIFT_MISSING:{','.join(sorted(missing))}")
        if expected_fields is not None and fields != expected_fields:
            raise RuntimeError("FULL_TAPE_SCHEMA_DRIFT_CHANGED_HEADER")
        return member.filename, fields, member.file_size


def _flush(
    writers: dict[str, pq.ParquetWriter],
    batches: dict[str, list[dict[str, Any]]],
    asset: str,
    event_root: Path | None = None,
) -> None:
    """Write and clear one bounded Parquet batch."""
    if not batches[asset]:
        return
    root = EVENT_ROOT if event_root is None else event_root
    target = (
        root / f"date={batches[asset][0]['_session_date']}" / f"asset={asset}" / "events.parquet"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    writer = writers.get(asset)
    if writer is None:
        writer = pq.ParquetWriter(target, EVENT_SCHEMA, compression="zstd")
        writers[asset] = writer
    rows = [
        {key: value for key, value in row.items() if key != "_session_date"}
        for row in batches[asset]
    ]
    writer.write_table(pa.Table.from_pylist(rows, schema=EVENT_SCHEMA))
    batches[asset].clear()


def filter_session(
    day: date,
    zip_path: Path,
    expected_fields: set[str] | None,
    config: Phase5StorageConfig | None = None,
) -> dict[str, Any]:
    """Stream-filter one validated archive into date/asset Parquet partitions."""
    if config is not None and day not in config.sessions:
        raise RuntimeError("SESSION_NOT_IN_EXPLICIT_ALLOWLIST")
    event_root = EVENT_ROOT if config is None else config.event_root
    dedup_root = OUT / ".dedup" if config is None else config.temporary_root / ".dedup"
    started = time_module.perf_counter()
    member, fields, csv_bytes = _validate_zip(zip_path, expected_fields)
    counts: Counter[str] = Counter()
    duplicates = 0
    rows_seen = 0
    writers: dict[str, pq.ParquetWriter] = {}
    batches: dict[str, list[dict[str, Any]]] = {asset: [] for asset in ASSETS}
    dedup_root.mkdir(parents=True, exist_ok=True)
    dedup_path = dedup_root / f"{day.isoformat()}.sqlite3"
    for stale_path in (dedup_path, Path(f"{dedup_path}-journal")):
        if stale_path.exists():
            stale_path.unlink()
    dedup = sqlite3.connect(dedup_path)
    # The table is disposable and reconstructed from the immutable ZIP after
    # interruption; disabling its journal avoids a second multi-hundred-MB
    # temporary copy while retaining a disk-backed primary-key dedup boundary.
    dedup.execute("PRAGMA journal_mode=OFF")
    dedup.execute("PRAGMA synchronous=OFF")
    dedup.execute("PRAGMA temp_store=FILE")
    dedup.execute("PRAGMA cache_size=-65536")
    dedup.execute("CREATE TABLE seen (event_id TEXT PRIMARY KEY)")
    dedup.commit()
    pending_rows: list[dict[str, str]] = []

    def consume_batch(rows: list[dict[str, str]]) -> None:
        """Deduplicate a bounded CSV batch and normalize eligible rows."""
        nonlocal duplicates
        if not rows:
            return
        ids = [row["id"] for row in rows]
        existing: set[str] = set()
        for start_index in range(0, len(ids), 400):
            chunk = ids[start_index : start_index + 400]
            placeholders = ",".join("?" for _ in chunk)
            query = f"SELECT event_id FROM seen WHERE event_id IN ({placeholders})"
            existing.update(str(item[0]) for item in dedup.execute(query, chunk))
        unique_rows: list[dict[str, str]] = []
        batch_seen = set(existing)
        for row in rows:
            event_id = row["id"]
            if event_id in batch_seen:
                duplicates += 1
                continue
            batch_seen.add(event_id)
            unique_rows.append(row)
        dedup.executemany(
            "INSERT INTO seen(event_id) VALUES (?)",
            ((row["id"],) for row in unique_rows),
        )
        dedup.commit()
        for row in unique_rows:
            executed = _dt(row["executed_at"])
            _dt(row["created_at"])
            if not _regular(executed, day):
                continue
            asset = row["underlying_symbol"]
            normalized = _event_row(row)
            normalized["_session_date"] = day.isoformat()
            batches[asset].append(normalized)
            counts[asset] += 1
            if len(batches[asset]) >= 25_000:
                _flush(writers, batches, asset, event_root)

    peak_working_set = _working_set_bytes() or 0
    try:
        with zipfile.ZipFile(zip_path) as archive, archive.open(member) as raw:
            reader = csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8", newline=""))
            if set(reader.fieldnames or []) != fields:
                raise RuntimeError("FULL_TAPE_SCHEMA_DRIFT_DURING_READ")
            for row in reader:
                rows_seen += 1
                if rows_seen % 100_000 == 0:
                    peak_working_set = max(peak_working_set, _working_set_bytes() or 0)
                asset = row.get("underlying_symbol")
                if asset not in ASSETS:
                    continue
                event_id = row.get("id")
                if not event_id:
                    raise RuntimeError("FULL_TAPE_EVENT_ID_MISSING")
                pending_rows.append(row)
                if len(pending_rows) >= 5_000:
                    consume_batch(pending_rows)
                    pending_rows.clear()
            consume_batch(pending_rows)
            pending_rows.clear()
        for asset in ASSETS:
            _flush(writers, batches, asset, event_root)
            if asset not in writers:
                target = (
                    event_root / f"date={day.isoformat()}" / f"asset={asset}" / "events.parquet"
                )
                target.parent.mkdir(parents=True, exist_ok=True)
                pq.write_table(
                    pa.Table.from_pylist([], schema=EVENT_SCHEMA), target, compression="zstd"
                )
    finally:
        dedup.commit()
        dedup.close()
        if dedup_path.exists():
            dedup_path.unlink()
        for writer in writers.values():
            writer.close()
        peak_working_set = max(peak_working_set, _working_set_bytes() or 0)
    parquet_bytes = sum(
        path.stat().st_size
        for path in event_root.glob(f"date={day.isoformat()}/asset=*/events.parquet")
    )
    return {
        "session_date": day.isoformat(),
        "csv_member": member,
        "csv_uncompressed_bytes": csv_bytes,
        "schema_fingerprint": hashlib.sha256("\n".join(sorted(fields)).encode()).hexdigest(),
        "schema_fields": sorted(fields),
        "rows_seen": rows_seen,
        "rows_retained": sum(counts.values()),
        "retained_by_asset": dict(sorted(counts.items())),
        "duplicate_event_ids": duplicates,
        "parquet_bytes": parquet_bytes,
        "filter_seconds": time_module.perf_counter() - started,
        "python_peak_traced_bytes": None,
        "python_peak_working_set_bytes": peak_working_set,
        "dedup_key": "id",
        "dedup_storage": "disk_backed_sqlite_primary_key",
        "dedup_memory_bound": True,
        "timestamp_fields_validated": ["executed_at", "created_at"],
    }


def _load_manifest(path: Path) -> dict[str, Any]:
    """Load a per-day manifest or return an empty record."""
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def load_phase5_development_config(
    *,
    session_manifest_path: Path,
    reused_manifest_path: Path,
    output_root: Path,
    projected_peak_additional_bytes: int,
) -> Phase5StorageConfig:
    """Load the frozen manifests and derive the missing development dates.

    Parameters
    ----------
    session_manifest_path:
        Frozen 80-development/10-holdout session manifest.
    reused_manifest_path:
        Verified manifest for the 25 retained development sessions.
    output_root:
        Persistent Phase 5 data root.
    projected_peak_additional_bytes:
        Conservative additional storage required during this batch.

    Returns
    -------
    Phase5StorageConfig
        Validated configuration containing only the 55 missing dates.

    Raises
    ------
    ValueError
        If either frozen manifest is untrusted or internally inconsistent.
    """
    session_manifest = json.loads(session_manifest_path.read_text(encoding="utf-8"))
    reused_manifest = json.loads(reused_manifest_path.read_text(encoding="utf-8"))
    if reused_manifest.get("status") != "PASS":
        raise ValueError("REUSED_SESSION_MANIFEST_NOT_PASS")
    unsigned_reused = {
        key: value for key, value in reused_manifest.items() if key != "manifest_sha256"
    }
    if reused_manifest.get("manifest_sha256") != canonical_sha256(unsigned_reused):
        raise ValueError("REUSED_SESSION_MANIFEST_HASH_MISMATCH")
    reused_dates = frozenset(date.fromisoformat(value) for value in reused_manifest["sessions"])
    return build_phase5_storage_config(
        session_manifest,
        reused_dates=reused_dates,
        data_root=output_root,
        projected_peak_additional_bytes=projected_peak_additional_bytes,
    )


def load_phase5_holdout_config(
    *,
    session_manifest_path: Path,
    output_root: Path,
    projected_peak_additional_bytes: int,
) -> Phase5StorageConfig:
    """Load the frozen manifest and derive the isolated holdout allow-list."""
    session_manifest = json.loads(session_manifest_path.read_text(encoding="utf-8"))
    return build_phase5_holdout_storage_config(
        session_manifest,
        data_root=output_root,
        projected_peak_additional_bytes=projected_peak_additional_bytes,
    )


def _sha256_file(path: Path) -> str:
    """Hash a completed archive incrementally without loading it into memory."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main(
    config: Phase5StorageConfig | None = None,
    *,
    phase_label: str | None = None,
) -> None:
    """Run the bounded twenty-session download and emit sanitized checkpoints."""
    phase = phase_label or ("5_DEVELOPMENT" if config is not None else "3F")
    if phase not in {"3F", "5_DEVELOPMENT", "5_HOLDOUT"}:
        raise ValueError("DOWNLOAD_PHASE_LABEL_INVALID")
    out_root = OUT if config is None else config.data_root
    raw_root = RAW_ROOT if config is None else config.raw_root
    manifest_root = MANIFEST_ROOT if config is None else config.manifest_root
    sessions = SESSIONS if config is None else config.sessions
    excluded_dates = PILOT_DATES if config is None else config.excluded_dates
    batch_manifest_path = (
        OUT / "download_manifest.json"
        if config is None
        else config.manifest_root / "batch_manifest.json"
    )
    out_root.mkdir(parents=True, exist_ok=True)
    raw_root.mkdir(parents=True, exist_ok=True)
    manifest_root.mkdir(parents=True, exist_ok=True)
    preflight = storage_preflight(config)
    key = _secret("UNUSUALWHALES_API_KEY")
    expected_fields: set[str] | None = None
    day_records: list[dict[str, Any]] = []
    for day in sessions:
        if day in excluded_dates:
            raise RuntimeError("EXCLUDED_DATE_IN_DOWNLOAD_ALLOWLIST")
        day_manifest_path = manifest_root / f"{day.isoformat()}.json"
        existing = _load_manifest(day_manifest_path)
        zip_path = raw_root / day.isoformat() / f"full_tape_{day.isoformat()}.zip"
        if existing.get("status") == "PASS" and existing.get("sha256") and zip_path.exists():
            if _sha256_file(zip_path) != existing["sha256"]:
                raise RuntimeError(f"FULL_TAPE_HASH_MISMATCH:{day}")
            record = existing
            record["reused_existing"] = True
            day_records.append(record)
            if expected_fields is None and existing.get("schema_fields"):
                expected_fields = set(existing["schema_fields"])
            continue
        zip_path.parent.mkdir(parents=True, exist_ok=True)
        if zip_path.exists():
            existing_hash = _sha256_file(zip_path)
            download = {
                "http_status": None,
                "attempts": 0,
                "download_seconds": 0.0,
                "bytes": zip_path.stat().st_size,
                "sha256": existing_hash,
                "endpoint": ENDPOINT.format(day=day.isoformat()),
                "request_id": None,
                "reused_raw_archive": True,
            }
        else:
            download = _stream_download(day, key, zip_path)
        filtered = filter_session(day, zip_path, expected_fields, config)
        expected_fields = set(filtered["schema_fields"])
        record = {
            "status": "PASS",
            **download,
            **filtered,
            "raw_path": _relative(zip_path, ROOT if config is None else config.data_root),
            "schema_fields": sorted(expected_fields),
            "legacy_cache_status": "LEGACY_CACHE_READ_ONLY",
            "active_cache_status": "ACTIVE_CALIBRATION_CACHE_V2_ONLY",
            "reused_existing": False,
            "secret_values_emitted": False,
            "personal_paths_emitted": False,
        }
        _atomic_json(day_manifest_path, record)
        day_records.append(record)
        _atomic_json(
            batch_manifest_path,
            {
                "status": "IN_PROGRESS",
                "phase": phase,
                "session_count": len(day_records),
                "authorized_session_count": len(sessions),
                "sessions": day_records,
                "preflight": preflight,
                "full_backfill": "BLOCKED",
                "modeling": "BLOCKED",
                "qlike": "BLOCKED",
                "final_test": "BLOCKED",
                "asset_freeze": "BLOCKED",
                "secret_values_emitted": False,
                "personal_paths_emitted": False,
            },
        )
    _atomic_json(
        batch_manifest_path,
        {
            "status": "PASS",
            "phase": phase,
            "session_count": len(day_records),
            "authorized_session_count": len(sessions),
            "sessions": day_records,
            "preflight": preflight,
            "full_backfill": "BLOCKED",
            "modeling": "BLOCKED",
            "qlike": "BLOCKED",
            "final_test": "BLOCKED",
            "asset_freeze": "BLOCKED",
            "pit_claim": False,
            "secret_values_emitted": False,
            "personal_paths_emitted": False,
        },
    )
    print(
        json.dumps(
            {
                "status": "PASS",
                "sessions": len(day_records),
                "reused": sum(bool(x.get("reused_existing")) for x in day_records),
                "secret_values_emitted": False,
            }
        )
    )


def cli(argv: list[str] | None = None) -> None:
    """Run the legacy batch or frozen Phase 5 development acquisition.

    Parameters
    ----------
    argv:
        Optional command arguments. ``None`` reads the process arguments; an
        empty list retains the legacy twenty-session behavior.
    """
    arguments = sys.argv[1:] if argv is None else argv
    if not arguments:
        main()
        return
    parser = argparse.ArgumentParser()
    parser.add_argument("--session-manifest", type=Path, required=True)
    parser.add_argument("--reused-manifest", type=Path)
    parser.add_argument(
        "--role",
        choices=("development_acquisition", "holdout_acquisition"),
        required=True,
    )
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument(
        "--projected-peak-additional-gib",
        type=int,
        default=150,
    )
    parsed = parser.parse_args(arguments)
    if parsed.role == "development_acquisition":
        if parsed.reused_manifest is None:
            parser.error("--reused-manifest is required for development_acquisition")
        config = load_phase5_development_config(
            session_manifest_path=parsed.session_manifest,
            reused_manifest_path=parsed.reused_manifest,
            output_root=parsed.output_root,
            projected_peak_additional_bytes=parsed.projected_peak_additional_gib * 1024**3,
        )
        main(config, phase_label="5_DEVELOPMENT")
    else:
        config = load_phase5_holdout_config(
            session_manifest_path=parsed.session_manifest,
            output_root=parsed.output_root,
            projected_peak_additional_bytes=parsed.projected_peak_additional_gib * 1024**3,
        )
        main(config, phase_label="5_HOLDOUT")


if __name__ == "__main__":
    cli()
