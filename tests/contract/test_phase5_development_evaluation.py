"""Fail-closed contracts for the Phase 5 development-only evaluation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from mds650.study_design import canonical_sha256, source_sha256

ROOT = Path(__file__).resolve().parents[2]
PHASE5 = ROOT / "artifacts" / "phase5"
FORECASTS = PHASE5 / "development_forecasts.parquet"
RESULTS = PHASE5 / "development_results.json"
LEDGER = PHASE5 / "variant_ledger.json"
FREEZE = PHASE5 / "method_freeze.json"
PANEL = PHASE5 / "common_development_80d.parquet"
QUALITY = PHASE5 / "development_panel_quality.json"
PREREGISTRATION = PHASE5 / "preregistration.json"
STABILITY_INPUTS = Path("D:/MDS650/data/phase5_stability/development_stability_inputs_80d.parquet")
STABILITY_MANIFEST = PHASE5 / "development_stability_input_manifest.json"
STABILITY_VALIDATION = PHASE5 / "development_stability_validation.json"


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def test_development_forecasts_are_positive_paired_and_holdout_free() -> None:
    forecasts = pl.read_parquet(FORECASTS)
    preregistration = _json(PREREGISTRATION)
    selected_assets = _json(QUALITY)["selected_assets"]
    expected = pl.read_parquet(PANEL).filter(
        pl.col("asset").is_in(selected_assets)
        & pl.any_horizontal(
            [
                pl.col("session_date").is_between(
                    pl.lit(fold["test_start"]),
                    pl.lit(fold["test_end"]),
                )
                for fold in preregistration["outer_folds"]
            ]
        )
    )

    assert forecasts["origin_id"].n_unique() == expected["origin_id"].n_unique()
    assert forecasts.height == expected.height * 6
    assert set(forecasts["information_set"]) == {"B0", "B1a", "B2"}
    assert set(forecasts["model_role"]) == {
        "gamma_glm_confirmatory",
        "lightgbm_robustness",
    }
    assert forecasts.group_by(["origin_id", "model_role"]).agg(
        pl.col("information_set").n_unique().alias("sets")
    )["sets"].to_list() == [3] * (expected.height * 2)
    assert np.isfinite(forecasts["forecast"].to_numpy()).all()
    assert (forecasts["forecast"] > 0).all()
    assert not set(forecasts["session_date"]) & set(preregistration["holdout_sessions"])
    expected_targets = expected.select("origin_id", "rv30").sort("origin_id")
    actual_targets = forecasts.select("origin_id", "rv30").unique().sort("origin_id")
    assert actual_targets.equals(expected_targets)


def test_results_retain_both_nested_contrasts_and_all_signs() -> None:
    results = _json(RESULTS)
    contrasts = results["contrasts"]

    assert results["status"] == "PASS_DEVELOPMENT_ONLY"
    assert results["holdout_reads"] == 0
    assert results["bootstrap_repetitions"] == 10_000
    assert {(row["model_role"], row["contrast"]) for row in contrasts} == {
        ("gamma_glm_confirmatory", "delta_b1"),
        ("gamma_glm_confirmatory", "delta_b2"),
        ("lightgbm_robustness", "delta_b1"),
        ("lightgbm_robustness", "delta_b2"),
    }
    assert all(row["result_sign"] in {"POSITIVE", "NEGATIVE", "ZERO"} for row in contrasts)
    gamma = [row for row in contrasts if row["model_role"] == "gamma_glm_confirmatory"]
    assert all(0 <= row["p_value_holm"] <= 1 for row in gamma)
    assert results["manifest_sha256"] == canonical_sha256(
        {key: value for key, value in results.items() if key != "manifest_sha256"}
    )


def test_variant_ledger_preserves_grid_primary_and_timing_variants() -> None:
    ledger = _json(LEDGER)

    assert ledger["outcome_reporting"] == ("RETAIN_ALL_POSITIVE_NEGATIVE_AND_NULL_RESULTS")
    assert len(ledger["tuning_variants"]) == 4 * 3 * (4 + 16)
    assert sum(row["selected"] for row in ledger["tuning_variants"]) == 4 * 3 * 2
    assert len(ledger["holdout_method_candidates"]) == 3 * (4 + 16)
    assert len(ledger["holdout_method_selection"]) == 3 * 2
    assert sum(row["selected"] for row in ledger["holdout_method_candidates"]) == 3 * 2
    assert len({row["variant_id"] for row in ledger["tuning_variants"]}) == len(
        ledger["tuning_variants"]
    )
    assert all(row["status"] == "RUN" for row in ledger["tuning_variants"])
    assert {row["variant_id"] for row in ledger["timing_variants"]} == {
        "FMP_DELAY_1_MINUTE",
        "FMP_DELAY_2_MINUTES",
        "B2_DELAY_60_SECONDS",
        "B2_DELAY_120_SECONDS",
        "B2_DELAY_300_SECONDS",
    }
    assert ledger["manifest_sha256"] == canonical_sha256(
        {key: value for key, value in ledger.items() if key != "manifest_sha256"}
    )


def test_method_freeze_hashes_exact_development_evidence() -> None:
    freeze = _json(FREEZE)

    assert freeze["status"] == "FROZEN_AFTER_DEVELOPMENT_BEFORE_HOLDOUT"
    assert freeze["holdout_reads"] == 0
    assert len(freeze["holdout_hyperparameters"]) == 6
    assert {
        "scripts/build_phase5_stability_inputs.py",
        "scripts/run_phase4b.py",
        "scripts/run_phase5_holdout.py",
        "src/mds650/holdout.py",
        "src/mds650/stability.py",
        "src/mds650/study_design.py",
    } <= set(freeze["source_code_hashes"])
    drift_path = PHASE5 / "historical_source_drift.json"
    drift = _json(drift_path)
    observed_drift = [
        {
            "path": relative_path,
            "frozen_sha256": digest,
            "current_sha256": source_sha256(ROOT / relative_path),
        }
        for relative_path, digest in freeze["source_code_hashes"].items()
        if digest != source_sha256(ROOT / relative_path)
    ]
    assert drift["status"] == "ACKNOWLEDGED_POST_HOLDOUT_SOURCE_DRIFT"
    assert drift["phase5_method_freeze_rewritten"] is False
    assert drift["phase6_requires_independent_source_freeze"] is True
    assert drift["mismatch_count"] == len(observed_drift)
    assert drift["records"] == observed_drift
    assert drift["manifest_sha256"] == canonical_sha256(
        {key: value for key, value in drift.items() if key != "manifest_sha256"}
    )
    assert freeze["input_hashes"]["common_development_80d.parquet"] == _sha256(PANEL)
    assert freeze["input_hashes"]["development_stability_inputs_80d.parquet"] == _sha256(
        STABILITY_INPUTS
    )
    assert freeze["input_hashes"]["development_stability_input_manifest.json"] == _sha256(
        STABILITY_MANIFEST
    )
    assert freeze["input_hashes"]["development_stability_validation.json"] == _sha256(
        STABILITY_VALIDATION
    )
    assert freeze["input_hashes"]["preregistration.json"] == _sha256(PREREGISTRATION)
    assert freeze["stability_definition"]["fmp_delay_minutes"] == [1, 2]
    assert freeze["stability_definition"]["b2_delay_seconds"] == [60, 120, 300]
    assert freeze["stability_definition"]["confirmatory_family_expanded"] is False
    assert (
        freeze["stability_definition"]["operationalization_timing"]
        == "AFTER_DEVELOPMENT_BEFORE_HOLDOUT"
    )
    assert freeze["output_hashes"]["development_forecasts.parquet"] == _sha256(FORECASTS)
    assert freeze["output_hashes"]["development_results.json"] == _sha256(RESULTS)
    assert freeze["output_hashes"]["variant_ledger.json"] == _sha256(LEDGER)
    assert freeze["manifest_sha256"] == canonical_sha256(
        {key: value for key, value in freeze.items() if key != "manifest_sha256"}
    )
