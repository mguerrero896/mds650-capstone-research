"""Run the approved Phase 5 B1Q build for the 55 missing development dates."""

from __future__ import annotations

from pathlib import Path

import download_calibration_20d as acquisition
import run_b1_calibration_20d as b1

ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = Path("D:/MDS650")


def main() -> None:
    """Validate the frozen date partition and build restartable B1Q evidence."""
    storage = acquisition.load_phase5_development_config(
        session_manifest_path=ROOT / "artifacts/phase5/study_sessions_90.json",
        reused_manifest_path=ROOT
        / "artifacts/phase5/reused_25_session_manifest.json",
        output_root=DATA_ROOT,
        projected_peak_additional_bytes=150 * 1024**3,
    )
    acquisition.storage_preflight(storage)
    b1.main(
        b1.B1BuildConfig(
            output_root=DATA_ROOT / "data/b1q/phase5_missing_55",
            cache_root=DATA_ROOT / "cache/massive",
            sessions=tuple(day.isoformat() for day in storage.sessions),
            origins_path=DATA_ROOT
            / "data/fmp/phase5_missing_55/b2_calibration_origins.parquet",
        )
    )


if __name__ == "__main__":
    main()
