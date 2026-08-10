"""Safety contracts for resumable independent Full Tape acquisition."""

from __future__ import annotations

import importlib
import json
import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
acquisition = importlib.import_module("acquire_independent_replication_30d")


def test_stable_crc_incident_blocks_automatic_redownload(tmp_path: Path) -> None:
    incident_root = tmp_path / "incidents"
    incident_root.mkdir()
    (incident_root / "2025-04-04_crc_failure.json").write_text(
        json.dumps(
            {
                "status": "BLOCKED_PROVIDER_ARCHIVE_CORRUPT",
                "provider_artifact_stable_across_retries": True,
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="REPLICATION_PROVIDER_ARCHIVE_BLOCKED:2025-04-04"):
        acquisition._raise_if_provider_archive_blocked("2025-04-04", incident_root)


def test_missing_provider_incident_does_not_block(tmp_path: Path) -> None:
    acquisition._raise_if_provider_archive_blocked("2025-04-03", tmp_path)


def test_target_role_selects_only_frozen_target_dates() -> None:
    window = {
        "all_dates": ["2025-04-01", "2025-04-02", "2025-05-21"],
        "warmup_dates": ["2025-04-01", "2025-04-02"],
        "target_dates": ["2025-05-21"],
    }

    assert acquisition._selected_dates(window, "target") == [date(2025, 5, 21)]
    assert acquisition._selected_dates(window, "warmup") == [
        date(2025, 4, 1),
        date(2025, 4, 2),
    ]


def test_invalid_acquisition_role_fails_closed() -> None:
    with pytest.raises(ValueError, match="REPLICATION_ROLE_INVALID"):
        acquisition._selected_dates({"all_dates": []}, "unexpected")


def test_manifest_hash_drift_blocks_acquisition_resume() -> None:
    with pytest.raises(RuntimeError, match="REPLICATION_PROVIDER_MANIFEST_HASH_INVALID"):
        acquisition._validate_acquisition_manifest(
            {
                "status": "PASS",
                "completed_count": 1,
                "records": [
                    {
                        "status": "PASS",
                        "session_date": "2025-04-03",
                        "http_status": 200,
                        "duplicate_event_ids": 0,
                        "secret_values_emitted": False,
                        "personal_paths_emitted": False,
                    }
                ],
                "manifest_sha256": "not-the-real-hash",
            },
            ["2025-04-03"],
        )
