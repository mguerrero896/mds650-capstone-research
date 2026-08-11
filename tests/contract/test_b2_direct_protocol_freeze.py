"""Contract tests for the direct-B2 pre-acquisition freeze."""

from __future__ import annotations

import json
from pathlib import Path

from mds650.study_design import canonical_sha256

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "artifacts" / "methodology" / "b2_direct_protocol_freeze_v1.json"


def test_direct_protocol_freeze_is_target_blind_and_pre_acquisition() -> None:
    """The freeze must exclude OOS outcomes and forbid new downloads."""
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    unsigned = dict(payload)
    manifest_hash = unsigned.pop("manifest_sha256")
    assert canonical_sha256(unsigned) == manifest_hash
    assert payload["status"] == "FROZEN_DIRECT_B2_BEFORE_NEW_BLOCK_ACQUISITION"
    assert payload["selection_sample"]["independent_samples_read"] is False
    assert payload["new_blocks"]["download_started"] is False
    assert payload["new_blocks"]["required_blocks"] == 2
    assert payload["new_blocks"]["minimum_sessions_per_block"] >= 30
    assert payload["secret_values_emitted"] is False
    assert payload["personal_paths_emitted"] is False


def test_direct_protocol_has_nested_information_sets() -> None:
    """B0 is contained in B1 and B1 is contained in direct B2."""
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    sets = payload["information_sets"]
    assert set(sets["B0"]).issubset(sets["B1"])
    assert set(sets["B1"]).issubset(sets["B2"])
    assert set(sets["B2_increment_only"]) == set(sets["B2"]) - set(sets["B1"])
