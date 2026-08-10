from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_replication_window_is_disjoint_and_provider_ready() -> None:
    manifest = json.loads(
        (ROOT / "artifacts/independent_replication/window_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert manifest["status"] == "READY_FOR_BOUNDED_BODY_ACQUISITION"
    assert len(manifest["warmup_dates"]) == 60
    assert len(manifest["target_dates"]) == 30
    assert len(set(manifest["all_dates"])) == 90
    assert not manifest["overlap_dates"]
    assert manifest["disjoint_from_phase5_phase6"] is True
    assert manifest["provider_metadata_probe"]["pit_claim"] is False


def test_replication_storage_gate_has_eighty_gib_floor() -> None:
    storage = json.loads(
        (ROOT / "artifacts/independent_replication/storage_preflight.json").read_text(
            encoding="utf-8"
        )
    )
    assert storage["free_space_pass"] is True
    assert storage["minimum_free_bytes"] == 80 * 1024**3
    assert storage["projected_free_bytes_at_peak"] >= storage["minimum_free_bytes"]
    assert storage["secret_values_emitted"] is False
    assert storage["personal_paths_emitted"] is False
