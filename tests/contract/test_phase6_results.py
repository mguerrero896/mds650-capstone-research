"""Post-OOS contracts for the sole preregistered Phase 6 evaluation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import polars as pl
import pytest
from tests.evidence import require_evidence_root

from mds650.study_design import canonical_sha256

pytestmark = pytest.mark.evidence

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
HANDOFF = REPOSITORY_ROOT / "reports" / "CODEX_PHASE6_FINAL_HANDOFF.md"
DECISIONS = {
    "GLOBAL_B1V2_EDGE_CONFIRMED",
    "GLOBAL_B2V2_EDGE_CONFIRMED",
    "TARGETED_B2V2_REPLICATION_CONFIRMED",
    "GLOBAL_EDGE_NOT_CONFIRMED",
}
TIMING_VARIANTS = {
    "FMP_DELAY_2_MINUTES",
    "window_15m_60s",
    "window_30m_60s",
    "latency_5m_120s",
    "latency_5m_300s",
}


def _phase6() -> Path:
    """Return the mounted evidence package for the consumed Phase 6 OOS run."""
    root = require_evidence_root(
        "artifacts/phase6/results.json",
        "artifacts/phase6/oos_predictions.parquet",
        "artifacts/phase6/oos_sensitivity_predictions.parquet",
        "artifacts/phase6/stability_results.parquet",
        "artifacts/phase6/oos_access_ledger.json",
    )
    return root / "artifacts" / "phase6"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def test_phase6_result_is_self_hashed_single_read_and_sanitized() -> None:
    phase6 = _phase6()
    results_path = phase6 / "results.json"
    result = _json(results_path)
    ledger = _json(phase6 / "oos_access_ledger.json")
    serialized = results_path.read_text(encoding="utf-8")

    assert result["status"] == "PASS_REGISTERED_EVALUATION_COMPLETE"
    assert result["decision"] in DECISIONS
    assert result["all_signs_retained"] is True
    assert result["manifest_sha256"] == canonical_sha256(
        {key: value for key, value in result.items() if key != "manifest_sha256"}
    )
    assert ledger["status"] == "OOS_CONSUMED_RESULTS_REPORTED"
    assert ledger["oos_read_count"] == 1
    assert ledger["results_sha256"] == _sha256(results_path)
    assert "C:\\Users\\" not in serialized
    assert "apiKey" not in serialized


def test_phase6_primary_predictions_are_positive_and_strictly_paired() -> None:
    predictions = pl.read_parquet(_phase6() / "oos_predictions.parquet")

    assert set(predictions["model_role"]) == {
        "gamma_glm_confirmatory",
        "lightgbm_robustness",
    }
    assert set(predictions["information_set"]) == {"B0v2", "B1v2a", "B2v2"}
    assert predictions.filter(
        ~pl.col("forecast").is_finite()
        | (pl.col("forecast") <= 0)
        | ~pl.col("qlike_loss").is_finite()
    ).is_empty()
    assert predictions.group_by("origin_id", "model_role").agg(
        pl.col("information_set").n_unique().alias("sets")
    ).filter(pl.col("sets") != 3).is_empty()


def test_phase6_timing_and_stability_views_are_complete() -> None:
    phase6 = _phase6()
    sensitivity = pl.read_parquet(phase6 / "oos_sensitivity_predictions.parquet")
    stability = pl.read_parquet(phase6 / "stability_results.parquet")

    assert set(sensitivity["timing_variant"]) == TIMING_VARIANTS
    assert sensitivity.filter(
        ~pl.col("forecast").is_finite()
        | (pl.col("forecast") <= 0)
        | ~pl.col("qlike_loss").is_finite()
    ).is_empty()
    assert set(stability["dimension"]) == {
        "asset",
        "session_tercile",
        "volatility_regime",
    }
    assert set(stability["contrast"]) == {"delta_b1v2", "delta_b2v2"}


def test_phase6_global_and_targeted_families_are_exact() -> None:
    result = _json(_phase6() / "results.json")
    global_results = result["global"]

    assert isinstance(global_results, dict)
    assert set(global_results) == {
        "gamma_glm_confirmatory",
        "lightgbm_robustness",
    }
    assert all(
        set(rows) == {"delta_b1v2", "delta_b2v2"}
        for rows in global_results.values()
        if isinstance(rows, dict)
    )
    assert set(result["global_holm"]) == {"delta_b1v2", "delta_b2v2"}
    assert set(result["targeted_holm"]) == {
        "META",
        "MSFT",
        "last_session_tercile",
    }


def test_phase6_handoff_distinguishes_significance_from_frozen_mde() -> None:
    """Prevent a positive estimate from being mislabeled as globally confirmed."""
    _phase6()  # The handoff narrates the consumed OOS evidence package.
    report = HANDOFF.read_text(encoding="utf-8")

    assert "## Frozen MDE and confirmation status" in report
    assert "Global confirmed contrasts: none" in report
    assert "Delta_B1v2 MDE: 0.02168577518" in report
    assert "Delta_B2v2 MDE: 0.005035098377" in report
