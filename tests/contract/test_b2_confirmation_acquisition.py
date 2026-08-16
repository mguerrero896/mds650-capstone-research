"""Contract tests for the bounded confirmation-block acquisition."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "acquire_b2_confirmation_blocks.py"
PROBE = ROOT / "artifacts" / "api_audit" / "new_blocks_availability_probe_v2.json"


def _module():
    spec = importlib.util.spec_from_file_location("b2_confirmation_acquisition", SCRIPT)
    if spec is None or spec.loader is None:
        raise AssertionError("SCRIPT_IMPORT_SPEC_MISSING")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_allowlist_is_exactly_two_disjoint_blocks() -> None:
    module = _module()
    probe = json.loads(PROBE.read_text(encoding="utf-8"))
    blocks = module._block_dates(probe)
    assert sorted(map(len, blocks.values())) == [30, 30]
    assert set(blocks[next(iter(blocks))]).isdisjoint(blocks[next(reversed(blocks))])
    module._validate_probe_records(probe, {day for values in blocks.values() for day in values})


def test_manifest_contract_is_metadata_only_before_body_acquisition() -> None:
    payload = json.loads(PROBE.read_text(encoding="utf-8"))
    assert payload["full_tape_downloaded"] is False
    assert payload["pit_claim"] is False
    assert payload["secret_values_emitted"] is False

