"""Emit a sanitized index of Phase 3F evidence artifacts after all gates pass."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts" / "calibration_20d"

REQUIRED = (
    "download_manifest.json",
    "storage_telemetry.csv",
    "raw_integrity_report.json",
    "b2_calibration_panel.parquet",
    "b2_calibration_parameters.json",
    "b2_feature_distributions.csv",
    "unusual_score_distribution.csv",
    "pilot_v2_unusual_scores.parquet",
    "unusual_event_prevalence.csv",
    "b1_coverage_20d.json",
    "b1_coverage_by_asset.csv",
    "b1_coverage_by_session_segment.csv",
    "test_report.txt",
)


def _sha256(path: Path) -> str:
    """Hash a completed artifact incrementally."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    """Validate required artifacts and write a repository-relative index."""
    missing = [name for name in REQUIRED if not (OUT / name).exists()]
    if missing:
        raise RuntimeError(f"PHASE_3F_REQUIRED_ARTIFACTS_MISSING:{','.join(missing)}")
    records = []
    for name in REQUIRED:
        path = OUT / name
        record = {
            "artifact": f"artifacts/calibration_20d/{name}",
            "bytes": path.stat().st_size,
            "sha256": _sha256(path),
            "secret_values_emitted": False,
            "personal_paths_emitted": False,
        }
        if path.suffix == ".json":
            payload = json.loads(path.read_text(encoding="utf-8"))
            record["status"] = payload.get("status") if isinstance(payload, dict) else "UNKNOWN"
        else:
            record["status"] = "PRESENT"
        records.append(record)
    target = OUT / "evidence_index.csv"
    target.write_text(
        "artifact,bytes,sha256,status,secret_values_emitted,personal_paths_emitted\n"
        + "\n".join(
            f"{row['artifact']},{row['bytes']},{row['sha256']},{row['status']},False,False"
            for row in records
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"status": "PASS", "artifacts": len(records), "secret_values_emitted": False}))


if __name__ == "__main__":
    main()
