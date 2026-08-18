"""Hermetic e2e: the public reproducibility demo must run the whole pipeline
(PIT join, features, purge/embargo, three families, QLIKE, bootstrap, MCS,
claim ledger) from a clean checkout — no keys, no external drives."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def test_demo_runs_end_to_end(tmp_path: Path, monkeypatch: object) -> None:
    spec = importlib.util.spec_from_file_location(
        "run_public_repro_demo", REPO / "scripts" / "run_public_repro_demo.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    argv = ["run_public_repro_demo.py", "--output-root", str(tmp_path)]
    original = sys.argv
    sys.argv = argv
    try:
        module.main()
    finally:
        sys.argv = original

    results = json.loads((tmp_path / "results.json").read_text(encoding="utf-8"))
    ledger = json.loads((tmp_path / "claim_ledger.json").read_text(encoding="utf-8"))

    assert results["synthetic"] is True
    assert 0.0 < results["pit_join_share_valid"] < 1.0  # late quotes really excluded
    assert results["train_rows_after_purge_embargo"] > 0
    assert set(results["b0_to_b1_contrasts"]) == {"gamma_glm", "lightgbm", "har_rv"}
    assert results["mcs_survivors"], "MCS returned no survivors"
    for model, adjusted in results["holm_adjusted_p"].items():
        assert 0.0 < adjusted <= 1.0, model
    assert len(ledger["claims"]) == 4
    assert len(ledger["results_sha256"]) == 64
