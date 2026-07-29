"""Contracts for the frozen Phase 5 preregistration."""

from __future__ import annotations

import importlib
import json
from datetime import date
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = (
    ROOT
    / "specs"
    / "001-pit-options-rv30"
    / "contracts"
    / "phase5-preregistration.schema.json"
)
EXPECTED_FEATURES = [
    "b2_log_trade_count",
    "b2_unique_contract_share",
    "b2_log_mean_trade_premium",
    "b2_log_max_trade_premium",
    "b2_call_put_premium_imbalance_scaled",
    "b2_execution_side_premium_imbalance",
    "b2_repeated_contract_premium_share",
    "b2_strike_concentration",
    "b2_expiry_concentration",
]
TEST_PROVENANCE = {
    "branch": "001-pit-options-rv30-recovery",
    "commit": "0" * 40,
    "python_version": "3.12.12",
    "uv_lock_sha256": "1" * 64,
    "design_sha256": "2" * 64,
    "spec_kit_commit": "3" * 40,
    "worktree_dirty": False,
}
EXPECTED_FOLDS = [
    {
        "fold": 1,
        "train_end": "2026-05-19",
        "test_start": "2026-05-20",
        "test_end": "2026-06-03",
    },
    {
        "fold": 2,
        "train_end": "2026-06-03",
        "test_start": "2026-06-04",
        "test_end": "2026-06-17",
    },
    {
        "fold": 3,
        "train_end": "2026-06-17",
        "test_start": "2026-06-18",
        "test_end": "2026-07-02",
    },
    {
        "fold": 4,
        "train_end": "2026-07-02",
        "test_start": "2026-07-06",
        "test_end": "2026-07-17",
    },
]


def _study_design() -> object:
    return importlib.import_module("mds650.study_design")


def _manifests() -> tuple[dict[str, object], dict[str, object]]:
    module = _study_design()
    sessions = module.build_study_sessions("XNYS", date(2026, 7, 17), 80, 10)
    session_manifest = module.build_session_manifest(sessions)
    return session_manifest, module.build_preregistration(
        session_manifest,
        provenance=TEST_PROVENANCE,
    )


def test_preregistration_validates_against_frozen_schema() -> None:
    _, preregistration = _manifests()
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    Draft202012Validator(schema).validate(preregistration)


def test_preregistration_freezes_methods_before_outcomes() -> None:
    session_manifest, preregistration = _manifests()

    assert preregistration["status"] == "FROZEN_BEFORE_MODEL_OR_QLIKE"
    assert preregistration["session_manifest_sha256"] == session_manifest["manifest_sha256"]
    assert preregistration["b2_feature_names"] == EXPECTED_FEATURES
    assert preregistration["holdout_reads"] == 0
    assert preregistration["models"]["confirmatory"]["name"] == "GammaRegressor"
    assert preregistration["models"]["robustness"]["name"] == "LGBMRegressor"
    assert preregistration["outer_folds"] == EXPECTED_FOLDS
    assert preregistration["seed"] == 650
    assert preregistration["estimands"] == {
        "delta_b1": "QLIKE(B0)-QLIKE(B1a)",
        "delta_b2": "QLIKE(B1a)-QLIKE(B2)",
        "primary": "delta_b2",
        "positive_direction": "expanded_information_set_better",
    }
    assert preregistration["metrics"]["primary"] == "QLIKE"
    assert preregistration["inference"]["bootstrap_repetitions"] == 10_000
    assert preregistration["inference"]["multiplicity"] == "Holm"
    assert preregistration["forecast_floor"] == 1e-12
    assert preregistration["missingness"]["strategy"] == "COMMON_COMPLETE_CASE"
    assert preregistration["feature_design_outcome_blind"] is True
    assert "results" not in preregistration
    assert "metric_values" not in preregistration
    assert "forecasts" not in preregistration


def test_session_manifest_has_exact_counts_and_no_overlap() -> None:
    session_manifest, _ = _manifests()

    assert session_manifest["development_count"] == 80
    assert session_manifest["holdout_count"] == 10
    assert session_manifest["disjoint"] is True
    assert session_manifest["manifest_sha256"] == _study_design().canonical_sha256(
        {key: value for key, value in session_manifest.items() if key != "manifest_sha256"}
    )


def test_freeze_json_reuses_identical_content(tmp_path: Path) -> None:
    _, preregistration = _manifests()
    path = tmp_path / "preregistration.json"

    first = _study_design().freeze_json(path, preregistration)
    second = _study_design().freeze_json(path, preregistration)

    assert first == second
    assert json.loads(path.read_text(encoding="utf-8")) == preregistration


def test_freeze_json_rejects_changed_content(tmp_path: Path) -> None:
    _, preregistration = _manifests()
    path = tmp_path / "preregistration.json"
    _study_design().freeze_json(path, preregistration)

    with pytest.raises(ValueError, match="FROZEN_MANIFEST_DRIFT"):
        _study_design().freeze_json(path, {**preregistration, "seed": 651})
