"""Contract tests for the bounded Phase 4A evidence builder."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from phase4a_common import (  # noqa: E402
    availability_is_valid,
    build_origin_id,
    checkpoint_payload,
    nested_benchmark_flags,
    validate_checkpoint,
)


def test_fmp_availability_respects_one_and_two_minute_conventions() -> None:
    raw = datetime(2026, 7, 13, 13, 34, tzinfo=UTC)
    origin = datetime(2026, 7, 13, 13, 35, tzinfo=UTC)
    assert availability_is_valid(raw, origin, delay_minutes=1)
    assert not availability_is_valid(raw, origin, delay_minutes=2)


def test_origin_id_is_deterministic_and_uses_contract_key() -> None:
    origin = datetime(2026, 7, 13, 13, 35, tzinfo=UTC)
    expected = "AAPL|2026-07-13|2026-07-13T13:35:00+00:00"
    assert build_origin_id("AAPL", "2026-07-13", origin) == expected
    assert build_origin_id("AAPL", "2026-07-13", origin) == expected


def test_nested_benchmark_flags_cannot_violate_monotonicity() -> None:
    flags = nested_benchmark_flags(atm=True, skew=False, term=True)
    assert flags == {
        "atm_iv_available": True,
        "skew_available": False,
        "term_structure_available": True,
        "b1a_complete": True,
        "b1b_complete": False,
        "b1c_complete": False,
    }


def test_checkpoint_detects_corruption_and_round_trip_is_stable() -> None:
    payload = checkpoint_payload("session-1", ["a", "b"], "abc123")
    assert validate_checkpoint(payload)
    corrupted = {**payload, "rows": 99}
    with pytest.raises(ValueError, match="CHECKPOINT_CORRUPTED"):
        validate_checkpoint(corrupted)


def test_phase4a_profile_has_no_duplicate_join_suffix_columns() -> None:
    """Provider rechecks must not leave duplicate ``*_right`` columns."""
    profile_path = ROOT / "artifacts" / "common_sample" / "common_matrix_profile_v1.json"
    if not profile_path.exists():
        pytest.skip("Phase 4A artifacts not built")
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    duplicate_keys = [key for key in profile.get("missingness", {}) if key.endswith("_right")]
    assert duplicate_keys == []


def test_phase4a_secret_scan_records_history_gate() -> None:
    """The compact scan must state whether the Git-history name-pattern gate ran."""
    scan_path = ROOT / "artifacts" / "repository" / "secret_scan_v1.json"
    if not scan_path.exists():
        pytest.skip("Phase 4A artifacts not built")
    scan = json.loads(scan_path.read_text(encoding="utf-8"))
    assert scan.get("git_history_scan") == "PASS_NAME_PATTERN_NO_HITS"
