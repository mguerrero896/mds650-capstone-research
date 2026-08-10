"""Safety contracts for resumable independent Full Tape acquisition."""

from __future__ import annotations

import importlib
import json
import sys
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
