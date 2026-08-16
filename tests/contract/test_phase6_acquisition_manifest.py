"""Sanitization contract for the Phase 6 acquisition manifest."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

from mds650.study_design import canonical_sha256

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
acquisition = importlib.import_module("acquire_phase6")


def test_in_progress_manifest_is_self_hashed_and_sanitized(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    preregistration: dict[str, object] = {
        "sessions": [{"session_date": "2025-07-07", "role": "warmup"}],
    }
    preregistration["manifest_sha256"] = canonical_sha256(preregistration)
    out = tmp_path / "acquisition_manifest.json"
    monkeypatch.setattr(acquisition, "OUT", out)
    monkeypatch.setattr(acquisition, "CHECKPOINT_ROOT", tmp_path / "checkpoints")
    monkeypatch.setattr(
        acquisition,
        "phase6_sessions",
        lambda: [{"session_date": "2025-07-07", "role": "warmup"}],
    )

    manifest = acquisition._write_manifest(preregistration)
    serialized = json.dumps(manifest, sort_keys=True)
    unsigned = {
        key: value for key, value in manifest.items() if key != "manifest_sha256"
    }

    assert manifest["status"] == "IN_PROGRESS"
    assert manifest["manifest_sha256"] == canonical_sha256(unsigned)
    assert manifest["secret_values_emitted"] is False
    assert manifest["personal_paths_emitted"] is False
    assert "C:\\Users\\" not in serialized
    assert "apiKey" not in serialized
