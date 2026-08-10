"""Freeze the disjoint 30-session replication window and storage gate."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

from exchange_calendars import get_calendar  # type: ignore[import-untyped]

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "artifacts"
OUTPUT = ARTIFACTS / "independent_replication" / "window_manifest.json"
STORAGE_OUTPUT = ARTIFACTS / "independent_replication" / "storage_preflight.json"
TARGET_PROBE = ARTIFACTS / "api_audit" / "b2_replication_30_common_probe.json"
ALL_PROBE = ARTIFACTS / "api_audit" / "b2_replication_90_common_probe.json"
UW_PROBE = ARTIFACTS / "api_audit" / "b2_replication_90_uw_metadata_probe.json"


def _json(path: Path) -> dict[str, Any]:
    """Load one JSON object."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"JSON_OBJECT_REQUIRED:{path.name}")
    return payload


def _sha256(path: Path) -> str:
    """Hash one evidence file incrementally."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sessions() -> tuple[list[str], list[str]]:
    """Return 20 causal warm-up and 30 independent target sessions."""
    calendar = get_calendar("XNYS")
    rows = [
        stamp.date().isoformat()
        for stamp in calendar.sessions_in_range("2025-01-01", "2025-07-06").to_pydatetime()
    ]
    return rows[-90:-30], rows[-30:]


def _existing_dates() -> set[str]:
    """Load all Phase 5 and Phase 6 outcome-read dates."""
    phase5 = _json(ARTIFACTS / "phase5" / "study_sessions_90.json")
    phase6 = _json(ARTIFACTS / "phase6" / "acquisition_manifest.json")
    existing = set(phase5.get("development", [])) | set(phase5.get("holdout", []))
    existing |= {
        str(row["session_date"])
        for row in phase6.get("sessions", [])
        if isinstance(row, dict) and isinstance(row.get("session_date"), str)
    }
    return existing


def main() -> None:
    """Write the window manifest and storage preflight without downloading data."""
    warmup, target = _sessions()
    all_probe = _json(ALL_PROBE)
    target_probe = _json(TARGET_PROBE)
    uw_probe = _json(UW_PROBE)
    expected = warmup + target
    common_records = {str(row["date"]): row for row in all_probe["records"]}
    if set(common_records) != set(expected):
        raise RuntimeError("REPLICATION_COMMON_PROBE_DATE_SET_INVALID")
    if (
        all_probe.get("status") != "PASS_METADATA_ONLY"
        or uw_probe.get("status") != "PASS_METADATA_ONLY"
    ):
        raise RuntimeError("REPLICATION_PROVIDER_METADATA_GATE_FAILED")
    if target_probe.get("status") != "PASS_METADATA_ONLY":
        raise RuntimeError("REPLICATION_TARGET_METADATA_GATE_FAILED")
    existing = _existing_dates()
    overlap = sorted(set(expected) & existing)
    if overlap:
        raise RuntimeError(f"REPLICATION_DATE_OVERLAP:{','.join(overlap)}")
    raw_bytes = sum(int(row["bytes_total"]) for row in uw_probe["records"])
    parquet_estimate = int(raw_bytes * 0.18)
    peak_bytes = int((raw_bytes + parquet_estimate) * 1.30)
    usage = shutil.disk_usage(Path("D:/MDS650"))
    floor = 80 * 1024**3
    storage = {
        "schema_version": "b2-replication-30-storage-preflight-1.0",
        "data_root": "MDS650_DATA_ROOT",
        "raw_bytes_metadata_estimate": raw_bytes,
        "parquet_bytes_estimate": parquet_estimate,
        "projected_peak_additional_bytes": peak_bytes,
        "free_bytes_before": usage.free,
        "projected_free_bytes_at_peak": usage.free - peak_bytes,
        "minimum_free_bytes": floor,
        "free_space_pass": usage.free - peak_bytes >= floor,
        "raw_and_parquet_path": "MDS650_DATA_ROOT/independent_replication_30",
        "secret_values_emitted": False,
        "personal_paths_emitted": False,
    }
    STORAGE_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    STORAGE_OUTPUT.write_text(
        json.dumps(storage, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    manifest = {
        "schema_version": "b2-independent-replication-window-1.0",
        "status": "READY_FOR_BOUNDED_BODY_ACQUISITION",
        "calendar": "XNYS",
        "warmup_dates": warmup,
        "target_dates": target,
        "target_count": len(target),
        "warmup_count": len(warmup),
        "all_dates": expected,
        "provider_metadata_probe": {
            "fmp_massive_sha256": _sha256(ALL_PROBE),
            "uw_sha256": _sha256(UW_PROBE),
            "target_common_sha256": _sha256(TARGET_PROBE),
            "pit_claim": False,
        },
        "disjoint_from_phase5_phase6": True,
        "overlap_dates": overlap,
        "purpose": (
            "Use warm-up only for causal trailing B2 state; score only the 30 "
            "target sessions."
        ),
        "download_scope": (
            "Full Tape for all_dates; target sessions are the independent "
            "evaluation block."
        ),
        "storage_preflight_sha256": _sha256(STORAGE_OUTPUT),
        "secret_values_emitted": False,
        "personal_paths_emitted": False,
    }
    unsigned = dict(manifest)
    manifest["manifest_sha256"] = hashlib.sha256(
        json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "status": manifest["status"],
                "warmup_count": manifest["warmup_count"],
                "target_count": manifest["target_count"],
                "free_space_pass": storage["free_space_pass"],
                "secret_values_emitted": False,
            }
        )
    )


if __name__ == "__main__":
    main()
