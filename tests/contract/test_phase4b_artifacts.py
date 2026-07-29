"""Acceptance checks for the local Phase 4B repair package."""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import polars as pl

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "artifacts" / "phase4b"


def _json(name: str) -> dict:
    return json.loads((OUT / name).read_text(encoding="utf-8"))


def test_fmp_variants_are_asof_and_target_identical() -> None:
    plus1 = pl.read_parquet(OUT / "b0_plus1_25d.parquet")
    plus2 = pl.read_parquet(OUT / "b0_plus2_25d.parquet")
    assert plus1.height == plus2.height == 14200
    assert plus1["origin_id"].to_list() == plus2["origin_id"].to_list()
    target_columns = ["origin_id", "rv30", "target_price_count", "target_future_close_count"]
    assert plus1.select(target_columns).equals(plus2.select(target_columns))
    assert plus1.filter(~pl.col("b0_availability_valid")).height == 0
    assert plus2.filter(~pl.col("b0_plus2_availability_valid")).height == 0
    assert plus1.select(
        (pl.col("b0_available_at_utc") <= pl.col("forecast_origin_utc")).all()
    ).item()
    assert plus2.select(
        (pl.col("b0_plus2_available_at_utc") <= pl.col("forecast_origin_utc")).all()
    ).item()


def test_uw_windows_are_exactly_five_minutes_and_nonempty_at_300_seconds() -> None:
    panel = pl.read_parquet(OUT / "b2_panel_25d.parquet")
    assert panel.select(
        (pl.col("b2_window_end") - pl.col("b2_window_start") == timedelta(minutes=5)).all()
    ).item()
    assert set(panel["b2_cutoff_seconds"].unique()) == {60, 120, 300}
    assert panel.filter(pl.col("b2_cutoff_seconds") == 300)["b2_option_activity_present"].any()
    assert panel.select(["origin_id", "b2_cutoff_seconds"]).unique().height == panel.height
    active = panel.filter(pl.col("b2_option_activity_present"))
    assert active.select((pl.col("b2_max_executed_at") < pl.col("b2_window_end")).all()).item()
    assert active.select(
        (pl.col("b2_max_operational_time") <= pl.col("b2_window_end")).all()
    ).item()


def test_optional_iv_does_not_define_b2_core_and_aliases_are_absent() -> None:
    registry = _json("feature_registry_v1.json")
    matrix = pl.read_parquet(OUT / "b2_core_complete_25d.parquet")
    assert registry["aliases"]["implied_volatility_change_within_bin"] == "within_bin_iv_change"
    assert registry["identity_audit"]["exact_duplicate_predictors"] == []
    assert "b2_implied_volatility_change_within_bin" not in matrix.columns
    assert "b2_median_implied_volatility" not in matrix.columns
    optional = {row["canonical_name"] for row in registry["features"] if row["optional"]}
    assert "b2_within_bin_iv_change" in optional
    assert "b2_within_bin_iv_change" not in registry["predictors"]


def test_common_row_sets_and_targets_are_nested_and_identical() -> None:
    row_sets = _json("matrix_row_sets_v1.json")
    assert row_sets["row_set_nesting"] == {"B1Q_subset_B0": True, "B2_subset_B1Q": True}
    assert len(
        {
            row_sets["target_hash_common"],
            row_sets["target_hash_common_in_b0"],
            row_sets["target_hash_common_in_b1q"],
            row_sets["target_hash_common_in_b2"],
        }
    ) == 1


def test_checkpoint_and_holdout_gates_are_fail_closed() -> None:
    restart = _json("checkpoint_restart_v1.json")
    holdout = _json("prospective_10_session_manifest.json")
    assert restart["hashes_identical"] is True
    assert restart["corrupted_checkpoint_detected"] is True
    assert restart["duplicate_output_rows"] == 0
    assert holdout["status"] == "SEALED_NOT_ACQUIRED"
    assert holdout["acquired"] is False
    assert holdout["raw_payloads_written"] is False
    assert len(holdout["session_dates"]) == 10


def test_pilot_exclusions_are_non_iv_and_explicit() -> None:
    diagnostics = _json("pilot_strict_core_diagnostics.json")
    assert diagnostics["pilot_origins"] == 2840
    assert diagnostics["optional_iv_fields_are_non_blocking"] is True
    assert diagnostics["iv_change_not_used_for_b2_core_completeness"] is True
    reasons = {row["exclusion_reason"] for row in diagnostics["exclusions"]}
    assert reasons <= {"B0_MISSING_ASOF_FEATURE_OR_TARGET", "B1Q_PIT_OR_QUOTE_COVERAGE"}
