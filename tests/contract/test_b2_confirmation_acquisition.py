"""Contract tests for the bounded confirmation-block acquisition."""

from __future__ import annotations

import json

import pytest
from tests.evidence import require_evidence_root

pytestmark = pytest.mark.evidence

# superseded: the legacy test_allowlist_is_exactly_two_disjoint_blocks was
# dropped because scripts/acquire_b2_confirmation_blocks.py (its module under
# test, providing _block_dates and _validate_probe_records) is not tracked on
# main; only the archived pre-consolidation worktree carried that script.
# The remaining contract checks the acquisition probe evidence directly.


def _probe() -> dict:
    root = require_evidence_root(
        "artifacts/api_audit/new_blocks_availability_probe_v2.json",
    )
    path = root / "artifacts" / "api_audit" / "new_blocks_availability_probe_v2.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_manifest_contract_is_metadata_only_before_body_acquisition() -> None:
    payload = _probe()
    assert payload["full_tape_downloaded"] is False
    assert payload["pit_claim"] is False
    assert payload["secret_values_emitted"] is False
