from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_method_freeze_precedes_target_outcome_read() -> None:
    freeze = json.loads(
        (ROOT / "artifacts/independent_replication/method_freeze.json").read_text(
            encoding="utf-8"
        )
    )
    assert freeze["status"] == "FROZEN_BEFORE_TARGET_OUTCOME_READ"
    assert freeze["target_outcome_read"] is False
    assert freeze["target"]["name"] == "RV30"
    assert freeze["target"]["price_count"] == 31
    assert freeze["target"]["return_count"] == 30


def test_acquisition_manifest_is_sanitized_and_reproducible() -> None:
    path = ROOT / "artifacts/independent_replication/acquisition_manifest.json"
    if not path.exists():
        return
    manifest = json.loads(path.read_text(encoding="utf-8"))
    assert manifest["status"] in {"IN_PROGRESS", "PASS", "PASS_WITH_PROVIDER_INCIDENT"}
    if "method_freeze_sha256" not in manifest:
        pause = ROOT / "artifacts/independent_replication/acquisition_pause.json"
        assert pause.exists()
        assert manifest["completed_count"] == 3
        return
    assert manifest["secret_values_emitted"] is False
    assert manifest["personal_paths_emitted"] is False
    assert manifest["method_freeze_sha256"]
    dates = [row["session_date"] for row in manifest["records"]]
    assert len(dates) == len(set(dates))
    assert dates == sorted(dates)
    for row in manifest["records"]:
        assert row["status"] == "PASS"
        assert row["duplicate_event_ids"] == 0
