from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_development_comparison_artifacts_have_required_contract() -> None:
    result_path = ROOT / "artifacts/methodology/development_model_comparison.json"
    ledger_path = ROOT / "artifacts/methodology/development_contrasts_v2.json"
    variants_path = ROOT / "artifacts/methodology/development_model_variant_ledger.json"
    if not result_path.exists() or not ledger_path.exists() or not variants_path.exists():
        return
    result = json.loads(result_path.read_text(encoding="utf-8"))
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    variants = json.loads(variants_path.read_text(encoding="utf-8"))
    assert result["status"] == "PASS_DEVELOPMENT_MODEL_COMPARISON"
    assert set(result["models"]) == {
        "persistence",
        "har_rv",
        "ridge",
        "gamma_glm",
        "lightgbm",
    }
    assert result["information_sets"] == ["B0", "B1a", "B2"]
    assert ledger["all_variants_retained"] is True
    assert ledger["oos_reads"] == 0
    assert any(
        row["model_name"] == "elastic_net" and row["status"] == "REGISTERED_NOT_RUN_RUNTIME_BUDGET"
        for row in variants["variants"]
    )
