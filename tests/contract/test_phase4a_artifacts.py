"""Acceptance tests for the local-only Phase 4A evidence package."""

# ruff: noqa: E501

from __future__ import annotations

import json
from pathlib import Path

import polars as pl
import pytest
from tests.evidence import require_evidence_root

pytestmark = pytest.mark.evidence


def _evidence_root() -> Path:
    """Return the mounted evidence package for the historical Phase 4A gates."""
    return require_evidence_root(
        "artifacts/common_sample/common_matrix_strict_25d.parquet",
        "artifacts/common_sample/common_matrix_available_25d.parquet",
        "artifacts/common_sample/common_matrix_targets_25d.parquet",
        "artifacts/common_sample/common_matrix_profile_v1.json",
        "artifacts/pit/pit_sensitivity_grid_v1.parquet",
        "artifacts/pit/pit_sensitivity_summary_v1.csv",
        "artifacts/backfill/restart_dry_run_v1.json",
        "artifacts/repository/secret_scan_v1.json",
        "artifacts/repository/reproducibility_manifest_v1.json",
        "artifacts/methodology/model_candidate_decision_matrix_v1.csv",
        "artifacts/methodology/inference_candidate_decision_matrix_v1.csv",
        "artifacts/methodology/collinearity_diagnostics_v1.json",
    )


def _common() -> Path:
    return _evidence_root() / "artifacts" / "common_sample"


def test_common_matrices_have_deterministic_ids_and_equal_targets() -> None:
    common = _common()
    strict = pl.read_parquet(common / "common_matrix_strict_25d.parquet")
    available = pl.read_parquet(common / "common_matrix_available_25d.parquet")
    targets = pl.read_parquet(common / "common_matrix_targets_25d.parquet")
    assert strict["origin_id"].n_unique() == strict.height
    assert available["origin_id"].n_unique() == available.height
    assert set(strict["origin_id"]) <= set(available["origin_id"])
    assert strict.select("origin_id").to_series().to_list() == sorted(strict["origin_id"].to_list())
    assert strict.select("origin_id", "rv30").join(targets.select("origin_id", "rv30"), on="origin_id", suffix="_target").select((pl.col("rv30") == pl.col("rv30_target")).all()).item()


def test_target_contract_and_leakage_flags_are_explicit() -> None:
    strict = pl.read_parquet(_common() / "common_matrix_strict_25d.parquet")
    assert strict["target_price_count"].unique().to_list() == [31]
    assert strict["target_future_close_count"].unique().to_list() == [30]
    assert strict["b0_predictors_observed"].all()
    assert strict["b2_predictors_observed"].all()
    assert strict.filter(~pl.col("b2_pit_recheck_failed")).height == strict.height
    predictor_names = {column for column in strict.columns if column.startswith(("b0_", "b1q_", "b2_"))}
    assert not predictor_names.intersection({"rv30", "target_price_count", "target_future_close_count"})


def test_pit_grid_contains_primary_and_sensitivities_without_silent_imputation() -> None:
    pit = _evidence_root() / "artifacts" / "pit"
    grid = pl.read_parquet(pit / "pit_sensitivity_grid_v1.parquet")
    summary = pl.read_csv(pit / "pit_sensitivity_summary_v1.csv")
    assert grid.select(["fmp_delay_minutes", "uw_cutoff_seconds"]).unique().height == 6
    assert set(summary["fmp_delay_minutes"]) == {1, 2}
    assert set(summary["uw_cutoff_seconds"]) == {60, 120, 300}
    primary = summary.filter((pl.col("fmp_delay_minutes") == 1) & (pl.col("uw_cutoff_seconds") == 60)).row(0, named=True)
    assert primary["strict_rows"] == 9589
    assert summary.filter(pl.col("fmp_delay_minutes") == 2)["strict_rows"].max() == 0


def test_phase4a_profile_records_zero_post_origin_and_no_duplicate_suffixes() -> None:
    profile = json.loads((_common() / "common_matrix_profile_v1.json").read_text(encoding="utf-8"))
    assert {row["sample_role"]: row["len"] for row in profile["nominal_rows_by_role"]} == {"CALIBRATION": 11360, "PILOT": 2840}
    assert {row["sample_role"]: row["len"] for row in profile["availability_aware_rows_by_role"]} == {"CALIBRATION": 10400, "PILOT": 2840}
    assert profile["leakage_checks"]["b0_predictor_after_origin_rows"] == 0
    assert profile["leakage_checks"]["massive_quote_after_origin_rows"] == 0
    assert profile["leakage_checks"]["b2_panel_count_mismatch_rows"] == 0
    assert not any(key.endswith("_right") for key in profile["missingness"])
    assert profile["no_imputation"] is True
    assert profile["no_interpolation"] is True
    assert profile["no_artificial_balancing"] is True


def test_restart_and_repository_scans_fail_closed() -> None:
    root = _evidence_root()
    restart = json.loads((root / "artifacts" / "backfill" / "restart_dry_run_v1.json").read_text(encoding="utf-8"))
    scan = json.loads((root / "artifacts" / "repository" / "secret_scan_v1.json").read_text(encoding="utf-8"))
    assert restart["hashes_identical"] is True
    assert restart["corrupted_checkpoint_detected"] is True
    assert restart["duplicate_output_rows"] == 0
    assert scan["secret_value_hits"] == 0
    assert scan["personal_path_file_hits"] == 0
    assert scan["git_history_scan"] == "PASS_NAME_PATTERN_NO_HITS"
    assert scan["large_file_count"] == len(scan["large_files"])
    assert {"DERIVED_LARGE_DATA", "TEMPORARY", "LEGACY"} <= set(scan["category_counts"])


def test_reproducibility_manifest_separates_environment_telemetry() -> None:
    manifest = json.loads((_evidence_root() / "artifacts" / "repository" / "reproducibility_manifest_v1.json").read_text(encoding="utf-8"))
    deterministic_paths = {item["path"] for item in manifest["artifacts"]}
    environment_paths = {item["path"] for item in manifest["environment_dependent_artifacts"]}
    assert "artifacts/backfill/backfill_resource_projection_v2.json" not in deterministic_paths
    assert environment_paths == {"artifacts/backfill/backfill_resource_projection_v2.json"}
    assert "MUST match SHA-256" in manifest["deterministic_hash_scope"]


def test_methodology_dossiers_are_complete_without_implementation() -> None:
    methodology = _evidence_root() / "artifacts" / "methodology"
    models = pl.read_csv(methodology / "model_candidate_decision_matrix_v1.csv")
    inference = pl.read_csv(methodology / "inference_candidate_decision_matrix_v1.csv")
    diagnostics = json.loads((methodology / "collinearity_diagnostics_v1.json").read_text(encoding="utf-8"))
    assert {"sample_size_requirement", "computational_cost", "primary_literature_support", "recommendation_status"} <= set(models.columns)
    assert {"assumptions", "finite_sample_risks", "cross_asset_dependence_treatment", "recommendation_status"} <= set(inference.columns)
    assert models["implementation_status"].unique().to_list() == ["DOSSIER_ONLY"]
    assert inference["implementation_status"].unique().to_list() == ["DOSSIER_ONLY"]
    assert diagnostics["no_model_selection"] is True
    assert diagnostics["predictor_count"] == 31
