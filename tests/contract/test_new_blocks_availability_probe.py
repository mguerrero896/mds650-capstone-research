"""Contract checks for the metadata-only historical availability probe."""

from __future__ import annotations

import json

import pytest
from tests.evidence import require_evidence_root

pytestmark = pytest.mark.evidence


def _probe() -> dict:
    root = require_evidence_root(
        "artifacts/api_audit/new_blocks_availability_probe_v2.json",
    )
    path = root / "artifacts" / "api_audit" / "new_blocks_availability_probe_v2.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_new_blocks_are_exactly_two_disjoint_30_session_blocks() -> None:
    payload = _probe()
    blocks = payload["blocks"]
    assert set(blocks) == {
        "block_a_2024_08_02_2024_09_13",
        "block_b_2024_10_01_2024_11_11",
    }
    assert all(len(dates) == 30 for dates in blocks.values())
    assert set(blocks[next(iter(blocks))]).isdisjoint(blocks[next(reversed(blocks))])
    assert len(payload["records"]) == 60


def test_probe_is_metadata_only_and_does_not_claim_pit() -> None:
    payload = _probe()
    assert payload["status"] == "METADATA_ONLY_NO_FULL_TAPE_DOWNLOAD"
    assert payload["full_tape_downloaded"] is False
    assert payload["pit_claim"] is False
    assert payload["secret_values_emitted"] is False
    for record in payload["records"]:
        uw = record["uw"]
        assert uw["http_status"] == 206
        assert uw["content_range_present"] is True
        assert uw["bytes_total"] > 0
        assert uw["full_tape_downloaded"] is False
        assert uw["pit_claim"] is False


def test_sampled_fmp_and_massive_checks_pass_for_each_block() -> None:
    payload = _probe()
    sampled = [record for record in payload["records"] if record["fmp_sample"]]
    assert len(sampled) == 6
    for record in sampled:
        fmp_assets = record["fmp_sample"]["assets"]
        massive_assets = record["massive_sample"]
        assert len(fmp_assets) == 8
        assert len(massive_assets) == 8
        assert all(item["http_status"] == 200 for item in fmp_assets.values())
        assert all(item["rows_exact_session"] == 390 for item in fmp_assets.values())
        assert all(item["spot_available"] is True for item in fmp_assets.values())
        assert all(item["pass"] is True for item in massive_assets.values())
