"""Contracts for the independent-replication report and evidence index."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import polars as pl

ROOT = Path(__file__).resolve().parents[2]
ARTIFACT = ROOT / "artifacts" / "independent_replication"


def test_independent_results_keep_single_target_read_and_frozen_mde() -> None:
    results = json.loads(
        (ARTIFACT / "independent_results.json").read_text(encoding="utf-8")
    )
    assert results["status"] == "INDEPENDENT_REPLICATION_COMPLETE"
    assert results["target"] == "RV30"
    assert results["target_read_count"] == 1
    assert results["evaluation"]["all_signs_retained"] is True
    assert results["mde_comparison"]["gamma_glm_confirmatory"]["delta_b2v2"][
        "exceeds_mde"
    ] is True


def test_stability_artifact_contains_strata_and_hours() -> None:
    frame = pl.read_parquet(ARTIFACT / "stability.parquet")
    assert frame.height == 72
    assert set(frame["analysis_scope"].unique().to_list()) == {"strata", "hour"}
    assert {"asset", "session_tercile", "volatility_regime"} <= set(
        frame.filter(frame["analysis_scope"] == "strata")["dimension"].unique().to_list()
    )
    assert frame.filter(frame["analysis_scope"] == "hour")["dimension"].unique().to_list() == [
        "session_hour_new_york"
    ]


def test_evidence_index_is_sanitized_and_hashed() -> None:
    with (ARTIFACT / "evidence_index.csv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows
    assert len({row["artifact"] for row in rows}) == len(rows)
    assert all(len(row["sha256"]) == 64 for row in rows)
    text = (ARTIFACT / "evidence_index.csv").read_text(encoding="utf-8").lower()
    assert "c:\\users\\" not in text
    assert "api_key=" not in text
    assert "secret_values_emitted,true" not in text
    assert "personal_paths_emitted,true" not in text


def test_human_report_distinguishes_targeted_from_universal_edge() -> None:
    text = (ROOT / "docs/independent_replication_30_session_results.md").read_text(
        encoding="utf-8"
    )
    assert "model-dependent B2 signal" in text
    assert "model-independent global edge" in text
    assert "All positive, negative and null variants remain registered" in text
