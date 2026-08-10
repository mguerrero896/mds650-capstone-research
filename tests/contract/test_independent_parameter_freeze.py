"""Contracts for the independent replication parameter and target gates."""

from __future__ import annotations

import json
from pathlib import Path

from mds650.study_design import canonical_sha256

ROOT = Path(__file__).resolve().parents[2]


def test_parameter_freeze_is_hashed_and_target_free() -> None:
    path = ROOT / "artifacts/independent_replication/parameter_freeze.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    unsigned = {key: value for key, value in payload.items() if key != "manifest_sha256"}
    assert payload["manifest_sha256"] == canonical_sha256(unsigned)
    assert payload["status"] == "FROZEN_BEFORE_INDEPENDENT_TARGET_OUTCOME_READ"
    assert payload["target_outcome_read"] is False
    assert payload["no_new_tuning_after_acquisition"] is True
    assert set(payload["parameters"]) == {
        f"{information_set}:{role}"
        for information_set in ("B0v2", "B1v2a", "B2v2")
        for role in ("gamma_glm_confirmatory", "lightgbm_robustness")
    }
    assert payload["secret_values_emitted"] is False
    assert payload["personal_paths_emitted"] is False


def test_target_access_cannot_be_marked_complete_twice() -> None:
    path = ROOT / "artifacts/independent_replication/target_access_ledger.json"
    if not path.exists():
        return
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload["status"] == "TARGET_READ_COMPLETE":
        assert payload["target_read_count"] == 1
        assert payload["target_outcome_read"] is True
