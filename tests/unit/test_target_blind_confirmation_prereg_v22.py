"""Tests for the v2.2 target-blind confirmation preflight seal."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
prereg_script = importlib.import_module("create_target_blind_confirmation_prereg_v22")


def _panel_manifest() -> dict[str, object]:
    """Return a valid minimal target-blind common-panel manifest fixture."""
    return {
        "schema_version": "target-blind-common-predictor-manifest-v2.2",
        "status": "PASS_TARGET_BLIND_INPUTS_RECONCILIATION_REMAINS_BLOCKED",
        "no_target_or_metric_payload_read": True,
        "model_fit_performed": False,
        "safe_to_reconcile_existing_results": "NO",
        "source_hashes": {"origins_sha256": "a" * 64},
        "builder_hashes": {"script_sha256": "b" * 64},
        "timing_rules": {"fmp_primary_delay_minutes": 1},
        "output": {
            "panel_sha256": "c" * 64,
            "row_count": 100,
            "common_complete_row_count": 80,
        },
    }


def test_preregistration_binds_panel_and_self_hashes_before_oos_access() -> None:
    """The successor preflight binds inputs without authorising OOS access."""
    preregistration = prereg_script.build_preregistration(_panel_manifest())
    self_hash = preregistration.pop("preregistration_sha256")

    assert preregistration["safe_to_open_or_evaluate_oos"] == "NO"
    assert preregistration["model_fit_performed"] is False
    assert preregistration["bound_panel"]["panel_sha256"] == "c" * 64
    assert self_hash == prereg_script.canonical_sha256(preregistration)


def test_preregistration_rejects_non_target_blind_source() -> None:
    """A source that permits reconciliation cannot seed a successor protocol."""
    manifest = _panel_manifest()
    manifest["safe_to_reconcile_existing_results"] = "YES"

    with pytest.raises(
        ValueError, match="TARGET_BLIND_V22_PREREGISTRATION_PANEL_MANIFEST_INVALID"
    ):
        prereg_script.build_preregistration(manifest)
