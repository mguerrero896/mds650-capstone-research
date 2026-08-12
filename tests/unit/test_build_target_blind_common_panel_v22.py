"""Unit tests for the target-blind common-panel builder guardrails."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
builder = importlib.import_module("build_target_blind_common_panel_v22")


def _sensitivity_record(*, status: str = "PASS") -> dict[str, object]:
    """Return a minimum target-free Massive sensitivity record."""
    return {
        "status": status,
        "selection_rule": (
            "last_quote_by_sip_timestamp_then_sequence_at_or_before_origin_minus_delay"
        ),
        "no_targets_or_predictive_metrics_read": True,
    }


def test_massive_sensitivity_guard_accepts_registered_target_free_contract(
    tmp_path: Path,
) -> None:
    """The builder accepts only the documented target-free Massive contract."""
    path = tmp_path / "massive.json"
    path.write_text(json.dumps(_sensitivity_record()), encoding="utf-8")

    builder._validate_massive_sensitivity(path)


def test_massive_sensitivity_guard_rejects_non_pass_status(tmp_path: Path) -> None:
    """A non-PASS sensitivity record fails before panel construction."""
    path = tmp_path / "massive.json"
    path.write_text(json.dumps(_sensitivity_record(status="FAIL")), encoding="utf-8")

    with pytest.raises(ValueError, match="TARGET_BLIND_V22_MASSIVE_SENSITIVITY_NOT_ACCEPTED"):
        builder._validate_massive_sensitivity(path)


def test_combined_b2_digest_binds_name_and_content_deterministically(
    tmp_path: Path,
) -> None:
    """B2 source identity changes when a date partition's content changes."""
    first = tmp_path / "date=2026-01-05.parquet"
    second = tmp_path / "date=2026-01-06.parquet"
    first.write_bytes(b"one")
    second.write_bytes(b"two")

    initial = builder.combined_input_digest([second, first])
    repeat = builder.combined_input_digest([first, second])
    second.write_bytes(b"changed")

    assert initial == repeat
    assert builder.combined_input_digest([first, second]) != initial
