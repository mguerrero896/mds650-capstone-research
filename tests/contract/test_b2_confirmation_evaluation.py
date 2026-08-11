"""Contract tests for the one-shot, development-frozen confirmation evaluation."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import polars as pl

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "evaluate_b2_confirmation_blocks.py"


def test_independent_panel_is_opened_after_development_fit() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    fit_position = source.index("fit_development_candidate(")
    independent_read_position = source.index(
        'new_raw = pl.read_parquet(NEW_PANEL)'
    )
    assert fit_position < independent_read_position
    assert "frozen above" in source


def test_evaluation_keeps_frozen_model_and_information_set_lists() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert 'MODEL_NAMES = ("gamma_glm", "lightgbm", "har_rv", "ridge", "elastic_net")' in source
    assert 'INFORMATION_SET_NAMES = ("B0", "B1a", "B2")' in source
    assert "BOOTSTRAP_REPETITIONS = 10_000" in source


def test_evaluation_uses_positive_mde_from_frozen_b2_protocol() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    protocol = json.loads(
        (ROOT / "artifacts" / "methodology" / "b2_direct_protocol_freeze_v1.json").read_text(
            encoding="utf-8"
        )
    )
    mechanism = json.loads(
        (ROOT / "artifacts" / "methodology" / "b2_mechanism_search_preregistration.json").read_text(
            encoding="utf-8"
        )
    )
    assert float(protocol["inference"]["mde"]) > 0
    assert protocol["inference"]["mde"] == mechanism["inference"]["mde"]
    assert '"mde_source": "artifacts/methodology/b2_direct_protocol_freeze_v1.json"' in source


def test_independent_contract_requires_two_blocks_and_no_future_created_at() -> None:
    spec = importlib.util.spec_from_file_location("b2_eval", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    rows = [
        {
            "origin_id": f"{block}:{index}",
            "block_id": block,
            "session_date": f"2024-08-{index + 1:02d}",
            "target_price_count": 31,
            "target_return_count": 30,
            "b2v2_cutoff_utc": "2024-08-01T14:00:00Z",
            "b2v2_max_created_at_utc": None,
        }
        for block, offset in (("a", 0), ("b", 30))
        for index in range(30)
    ]
    for row in rows:
        offset = 0 if row["block_id"] == "a" else 30
        row["session_date"] = f"2024-08-{int(row['origin_id'].split(':')[1]) + 1 + offset:02d}"
    module._validate_independent_panel(pl.DataFrame(rows))
