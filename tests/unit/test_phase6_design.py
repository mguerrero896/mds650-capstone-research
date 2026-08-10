"""Unit contracts for the Phase 6 calendar and preregistration."""

from __future__ import annotations

from typing import Any

import pytest

from mds650.phase6 import (
    B2V2_FEATURES,
    build_phase6_preregistration,
    phase6_folds,
    phase6_sessions,
)
from mds650.study_design import canonical_sha256

PROVENANCE: dict[str, Any] = {
    "branch": "001-pit-options-rv30-recovery",
    "repository_commit": "0" * 40,
    "python_version": "3.12.12",
    "uv_lock_sha256": "1" * 64,
    "design_sha256": "2" * 64,
    "spec_sha256": "3" * 64,
    "plan_sha256": "4" * 64,
    "tasks_sha256": "5" * 64,
    "analysis_sha256": "6" * 64,
    "phase6_source_sha256": "7" * 64,
    "schema_sha256": "8" * 64,
    "worktree_dirty": True,
}


def test_phase6_session_roles_are_exact_and_disjoint() -> None:
    """Require the exact owner-approved 20/60/100 XNYS partition."""
    rows = phase6_sessions()

    assert len(rows) == 180
    assert sum(row["role"] == "warmup" for row in rows) == 20
    assert sum(row["role"] == "initial_train" for row in rows) == 60
    assert sum(str(row["role"]).startswith("oos_fold_") for row in rows) == 100
    assert len({row["session_date"] for row in rows}) == 180
    assert rows[0] == {"session_date": "2025-07-07", "role": "warmup"}
    assert rows[-1] == {"session_date": "2026-03-23", "role": "oos_fold_5"}


def test_phase6_folds_expand_without_warmup_or_oos_overlap() -> None:
    """Require 60-to-140-session past-only training histories."""
    folds = phase6_folds()

    assert [len(fold["train_dates"]) for fold in folds] == [60, 80, 100, 120, 140]
    assert all(len(fold["test_dates"]) == 20 for fold in folds)
    for fold in folds:
        assert set(fold["train_dates"]).isdisjoint(fold["test_dates"])
        assert max(fold["train_dates"]) < min(fold["test_dates"])
        assert "2025-07-07" not in fold["train_dates"]


def test_phase6_preregistration_is_target_blind_and_self_hashed() -> None:
    """Freeze registered methods without forecasts, losses or OOS reads."""
    manifest = build_phase6_preregistration(PROVENANCE)
    unsigned = {key: value for key, value in manifest.items() if key != "manifest_sha256"}

    assert manifest["manifest_sha256"] == canonical_sha256(unsigned)
    assert manifest["status"] == "FROZEN_BEFORE_OOS"
    assert manifest["oos_read_count"] == 0
    assert manifest["b2v2_feature_names"] == list(B2V2_FEATURES)
    assert len(manifest["b2v2_feature_names"]) == 9
    assert manifest["estimands"]["primary"] == "delta_b2v2"
    assert manifest["inference"]["global_holm_family"] == ["delta_b1v2", "delta_b2v2"]
    assert "results" not in manifest
    assert "forecasts" not in manifest
    assert "qlike_values" not in manifest


def test_phase6_preregistration_rejects_incomplete_provenance() -> None:
    """Fail closed when a governing source hash is absent."""
    with pytest.raises(ValueError, match="PHASE6_PROVENANCE_INVALID"):
        build_phase6_preregistration(
            {key: value for key, value in PROVENANCE.items() if key != "spec_sha256"}
        )
