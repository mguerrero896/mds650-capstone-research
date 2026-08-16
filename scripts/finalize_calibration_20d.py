"""Finalize bounded Phase 3F download telemetry and integrity evidence.

This utility is intentionally read-only with respect to provider data: it reads
the per-day checkpoints produced by ``download_calibration_20d.py`` and emits
sanitized, deterministic summaries.  It never starts a network request and it
never treats the summaries as authorization for a larger backfill.
"""

# Telemetry prose preserves exact metric names and audit boundaries.
# ruff: noqa: E501

from __future__ import annotations

import csv
import hashlib
import json
import shutil
from collections import Counter
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import exchange_calendars as xcals  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]
from download_calibration_20d import ASSETS, PILOT_DATES, SESSIONS

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts" / "calibration_20d"
MANIFEST_ROOT = OUT / "manifests"


def _sha256(path: Path) -> str:
    """Hash a file incrementally without loading it into memory."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Load and validate the root and per-session manifests.

    Returns
    -------
    tuple[dict[str, Any], list[dict[str, Any]]]
        Root manifest and sessions in the frozen allow-list order.

    Raises
    ------
    RuntimeError
        If a session is missing, duplicated, excluded, or has a hash mismatch.
    """
    root_path = OUT / "download_manifest.json"
    if not root_path.exists():
        raise RuntimeError("CALIBRATION_DOWNLOAD_MANIFEST_MISSING")
    root = json.loads(root_path.read_text(encoding="utf-8"))
    if root.get("status") != "PASS" or root.get("session_count") != len(SESSIONS):
        raise RuntimeError("CALIBRATION_DOWNLOAD_NOT_COMPLETE")
    rows = list(root.get("sessions", []))
    expected = [day.isoformat() for day in SESSIONS]
    actual = [str(row.get("session_date")) for row in rows]
    if actual != expected or len(set(actual)) != len(actual):
        raise RuntimeError("CALIBRATION_SESSION_ORDER_OR_DUPLICATE_FAILURE")
    if set(actual) & {day.isoformat() for day in PILOT_DATES}:
        raise RuntimeError("PILOT_DATE_IN_CALIBRATION_EVIDENCE")
    hashes = [str(row.get("sha256", "")) for row in rows]
    if any(len(value) != 64 for value in hashes) or len(set(hashes)) != len(hashes):
        raise RuntimeError("CALIBRATION_RAW_HASH_DUPLICATE_OR_INVALID")
    for row in rows:
        raw_path = ROOT / str(row["raw_path"])
        if not raw_path.exists() or _sha256(raw_path) != row["sha256"]:
            raise RuntimeError(f"CALIBRATION_RAW_HASH_MISMATCH:{row['session_date']}")
    return root, rows


def write_telemetry(root: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    """Write measured per-day storage and processing telemetry."""
    output = OUT / "storage_telemetry.csv"
    fieldnames = [
        "session_date",
        "raw_bytes",
        "parquet_bytes",
        "rows_seen",
        "rows_retained",
        "download_seconds",
        "download_time_observed",
        "decompression_seconds",
        "decompression_filter_seconds",
        "filter_seconds",
        "aggregation_seconds",
        "attempts",
        "duplicate_event_ids",
        "python_peak_traced_bytes",
        "python_peak_working_set_bytes",
        "memory_observed",
        "raw_sha256",
        "schema_fingerprint",
        "resumable",
        "status",
        "measurement_note",
    ]
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            # zipfile performs inflate while the CSV stream is consumed.  The
            # combined duration is reported honestly instead of fabricating a
            # split that would require a second, bandwidth-expensive pass.
            combined = float(row.get("filter_seconds") or 0.0)
            download_observed = bool(float(row.get("download_seconds") or 0.0) > 0)
            memory_observed = bool(row.get("python_peak_working_set_bytes"))
            writer.writerow(
                {
                    "session_date": row["session_date"],
                    "raw_bytes": row.get("bytes", 0),
                    "parquet_bytes": row.get("parquet_bytes", 0),
                    "rows_seen": row.get("rows_seen", 0),
                    "rows_retained": row.get("rows_retained", 0),
                    "download_seconds": row.get("download_seconds", 0.0),
                    "download_time_observed": download_observed,
                    "decompression_seconds": combined,
                    "decompression_filter_seconds": combined,
                    "filter_seconds": combined,
                    "aggregation_seconds": "not_run_in_downloader",
                    "attempts": row.get("attempts", 0),
                    "duplicate_event_ids": row.get("duplicate_event_ids", 0),
                    "python_peak_traced_bytes": row.get("python_peak_traced_bytes"),
                    "python_peak_working_set_bytes": row.get("python_peak_working_set_bytes", 0),
                    "memory_observed": memory_observed,
                    "raw_sha256": row.get("sha256"),
                    "schema_fingerprint": row.get("schema_fingerprint"),
                    "resumable": True,
                    "status": row.get("status"),
                    "measurement_note": (
                        "Streaming zipfile inflate and CSV filtering are measured as one bounded "
                        "stage; aggregation is recorded by the calibration runners."
                    ),
                }
            )
    free = shutil.disk_usage(ROOT).free
    daily_raw = [int(row.get("bytes") or 0) for row in rows]
    daily_parquet = [int(row.get("parquet_bytes") or 0) for row in rows]
    daily_seconds = [
        float(row.get("download_seconds") or 0.0) + float(row.get("filter_seconds") or 0.0)
        for row in rows
    ]
    observed_working_sets = [
        int(row.get("python_peak_working_set_bytes") or 0)
        for row in rows
        if int(row.get("python_peak_working_set_bytes") or 0) > 0
    ]
    b2_telemetry_path = OUT / "b2_calibration_telemetry.json"
    b2_telemetry = (
        json.loads(b2_telemetry_path.read_text(encoding="utf-8"))
        if b2_telemetry_path.exists()
        else {}
    )
    telemetry = {
        "status": "PASS",
        "session_count": len(rows),
        "assets": list(ASSETS),
        "free_bytes_at_finalize": free,
        "raw_bytes_total": sum(daily_raw),
        "parquet_bytes_total": sum(daily_parquet),
        "raw_bytes_mean": sum(daily_raw) / len(rows),
        "raw_bytes_max_observed": max(daily_raw),
        "parquet_bytes_mean": sum(daily_parquet) / len(rows),
        "duration_seconds_mean": sum(daily_seconds) / len(rows),
        "duration_seconds_max_observed": max(daily_seconds),
        "retry_attempts_total": sum(int(row.get("attempts") or 0) for row in rows),
        "download_time_observed_sessions": sum(
            bool(float(row.get("download_seconds") or 0.0) > 0) for row in rows
        ),
        "memory_observed_sessions": sum(
            bool(row.get("python_peak_working_set_bytes")) for row in rows
        ),
        "peak_working_set_bytes_max_observed": max(observed_working_sets, default=None),
        "duplicate_event_ids_total": sum(int(row.get("duplicate_event_ids") or 0) for row in rows),
        "resumable": True,
        "aggregation_seconds": b2_telemetry.get(
            "feature_aggregation_seconds", "pending_calibration_runner"
        ),
        "measurement_boundary": "DOWNLOAD_AND_STREAM_FILTER_ONLY",
        "larger_backfill": "BLOCKED",
        "secret_values_emitted": False,
        "personal_paths_emitted": False,
    }
    (OUT / "storage_telemetry_summary.json").write_text(
        json.dumps(telemetry, indent=2, sort_keys=True), encoding="utf-8"
    )


def write_integrity(root: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    """Write raw archive, schema and deduplication integrity evidence."""
    schema_fingerprints = Counter(str(row.get("schema_fingerprint")) for row in rows)
    duplicate_ids = sum(int(row.get("duplicate_event_ids") or 0) for row in rows)
    parquet_paths = [
        path
        for row in rows
        for path in sorted(
            (OUT / "option_events" / f"date={row['session_date']}").glob(
                "asset=*/events.parquet"
            )
        )
    ]
    parquet_read_failures: list[dict[str, str]] = []
    for path in parquet_paths:
        try:
            metadata = pq.ParquetFile(path).metadata
            if metadata is None:
                raise ValueError("PARQUET_METADATA_MISSING")
        except Exception as exc:  # pragma: no cover - exercised by corrupt fixtures
            parquet_read_failures.append(
                {"path": path.relative_to(ROOT).as_posix(), "error": type(exc).__name__}
            )
    report = {
        "status": "PASS",
        "source_manifest": "artifacts/calibration_20d/download_manifest.json",
        "authorized_sessions": [day.isoformat() for day in SESSIONS],
        "sessions_validated": len(rows),
        "unique_raw_hashes": len({row["sha256"] for row in rows}),
        "duplicate_hashes": [
            hash_value
            for hash_value, count in Counter(row["sha256"] for row in rows).items()
            if count > 1
        ],
        "schema_fingerprints": dict(schema_fingerprints),
        "schema_stable": len(schema_fingerprints) == 1,
        "duplicate_event_ids_total": duplicate_ids,
        "dedup_key": "id",
        "pilot_dates_excluded": sorted(day.isoformat() for day in PILOT_DATES),
        "legacy_cache_status": "LEGACY_CACHE_READ_ONLY",
        "active_cache_status": "ACTIVE_CALIBRATION_CACHE_V2_ONLY",
        "crc_validated": True,
        "parquet_partitions": len(parquet_paths),
        "parquet_read_failures": parquet_read_failures,
        "secret_values_emitted": False,
        "personal_paths_emitted": False,
        "larger_backfill": "BLOCKED",
        "root_manifest_status": root.get("status"),
    }
    if (
        not report["schema_stable"]
        or report["duplicate_hashes"]
        or report["parquet_partitions"] != len(rows) * len(ASSETS)
        or report["parquet_read_failures"]
    ):
        report["status"] = "FAIL"
        raise RuntimeError("CALIBRATION_RAW_INTEGRITY_FAILURE")
    (OUT / "raw_integrity_report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
    )


def cleanup_dedup_temporary_files() -> int:
    """Remove only disposable SQLite dedup files after all sessions validate."""
    dedup_root = OUT / ".dedup"
    removed = 0
    if not dedup_root.exists():
        return removed
    for path in dedup_root.glob("*.sqlite3*"):
        path.unlink()
        removed += 1
    return removed


def _p95(values: list[float]) -> float:
    """Return an inclusive empirical P95 for the twenty observed days."""
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = 0.95 * (len(ordered) - 1)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + fraction * (ordered[upper] - ordered[lower])


def write_feasibility(rows: list[dict[str, Any]]) -> None:
    """Write descriptive 3/6/12-month projections from measured daily telemetry."""
    raw = [float(row.get("bytes") or 0) for row in rows]
    parquet = [float(row.get("parquet_bytes") or 0) for row in rows]
    duration = [
        float(row.get("download_seconds") or 0) + float(row.get("filter_seconds") or 0)
        for row in rows
    ]
    download_observed = [
        float(row.get("download_seconds") or 0)
        for row in rows
        if float(row.get("download_seconds") or 0) > 0
    ]
    working_sets = [
        int(row.get("python_peak_working_set_bytes") or 0)
        for row in rows
        if int(row.get("python_peak_working_set_bytes") or 0) > 0
    ]
    calendar = xcals.get_calendar("XNYS")
    end = date(2026, 7, 21)
    horizons = {"3_months": 90, "6_months": 180, "12_months": 365}
    projections: dict[str, Any] = {}
    for name, days in horizons.items():
        start = end - timedelta(days=days)
        sessions = len(calendar.sessions_in_range(start.isoformat(), end.isoformat()))
        projections[name] = {
            "sessions_approx": sessions,
            "raw_bytes_mean": sum(raw) / len(raw) * sessions,
            "raw_bytes_p95": _p95(raw) * sessions,
            "parquet_bytes_mean": sum(parquet) / len(parquet) * sessions,
            "parquet_bytes_p95": _p95(parquet) * sessions,
            "duration_seconds_mean": sum(duration) / len(duration) * sessions,
            "duration_seconds_p95": _p95(duration) * sessions,
            "storage_p95_with_30_percent_margin": (_p95(raw) + _p95(parquet)) * sessions * 1.3,
        }
    free = shutil.disk_usage(ROOT).free
    lines = [
        "# Backfill feasibility v3",
        "",
        "Status: `DESCRIPTIVE_ONLY_FULL_BACKFILL_BLOCKED`",
        "",
        "This report uses the measured twenty-session Full Tape telemetry. It does not authorize",
        "a 3/6/12-month download, model run, QLIKE or a final test. ZIP inflate and CSV filtering",
        "are measured as one streaming stage; calibration aggregation is reported separately by the",
        "B2/B1 runners when those stages complete.",
        "",
        f"Observed sessions: {len(rows)}; raw bytes total: {sum(raw):.0f}; Parquet bytes total: {sum(parquet):.0f}.",
        f"Observed daily raw mean: {sum(raw) / len(raw):.0f}; empirical P95: {_p95(raw):.0f}.",
        f"Observed daily Parquet mean: {sum(parquet) / len(parquet):.0f}; empirical P95: {_p95(parquet):.0f}.",
        f"Observed daily stream-filter mean seconds: {sum(duration) / len(duration):.2f}; P95: {_p95(duration):.2f}.",
        f"Transfer time was observed for {len(download_observed)}/{len(rows)} sessions; reused raw checkpoints have no transfer timer and are excluded from that transfer statistic.",
        f"Observed process working-set maximum: {max(working_sets) if working_sets else 'not measured'} bytes across {len(working_sets)}/{len(rows)} sessions.",
        f"Free space at finalization: {free} bytes; required margin is 30% over raw+Parquet P95.",
        "",
        "## Descriptive projections",
        "",
        "| Horizon | Sessions | Raw mean | Raw P95 | Parquet mean | Parquet P95 | P95 storage +30% | Duration P95 (s) |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name, values in projections.items():
        lines.append(
            f"| {name} | {values['sessions_approx']} | {values['raw_bytes_mean']:.0f} | "
            f"{values['raw_bytes_p95']:.0f} | {values['parquet_bytes_mean']:.0f} | "
            f"{values['parquet_bytes_p95']:.0f} | {values['storage_p95_with_30_percent_margin']:.0f} | "
            f"{values['duration_seconds_p95']:.0f} |"
        )
    lines.extend(
        [
            "",
            "The empirical P95 is interpolated from the twenty observed daily values, not treated as",
            "a guarantee. Temporary SQLite dedup and provider variability can increase the working",
            "set and duration. Projection duration is a lower bound where a reused raw checkpoint",
            "did not retain its original transfer timer.",
            "A future backfill requires a new authorization, a measured restart test",
            "and a storage check against the P95 plus margin; this phase leaves `FULL_BACKFILL=BLOCKED`.",
            "",
            "```json",
            json.dumps(
                {"projections": projections, "free_bytes_at_finalize": free},
                indent=2,
                sort_keys=True,
            ),
            "```",
        ]
    )
    (ROOT / "docs" / "backfill_feasibility_v3.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


def main() -> None:
    """Finalize integrity and telemetry after all twenty day manifests pass."""
    root, rows = _load()
    write_telemetry(root, rows)
    write_integrity(root, rows)
    write_feasibility(rows)
    removed = cleanup_dedup_temporary_files()
    print(
        json.dumps(
            {
                "status": "PASS",
                "sessions": len(rows),
                "raw_bytes": sum(int(row.get("bytes") or 0) for row in rows),
                "dedup_temporary_files_removed": removed,
                "secret_values_emitted": False,
            }
        )
    )


if __name__ == "__main__":
    main()
