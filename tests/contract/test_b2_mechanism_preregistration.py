from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_b2_mechanism_preregistration_is_target_blind_and_frozen() -> None:
    path = ROOT / "artifacts" / "methodology" / "b2_mechanism_search_preregistration.json"
    if not path.exists():
        return
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["status"] == "FROZEN_DEVELOPMENT_ONLY_BEFORE_MECHANISM_FIT"
    assert payload["selection_sample"]["independent_samples_used_for_selection"] is False
    assert payload["oos_guard"]["oos_read_count"] == 0
    assert payload["oos_guard"]["new_blocks_required_after_freeze"] == 2
    assert payload["residual_contract"]["b2_only_predictors"] is True
    assert len(payload["mechanism_variants"]) == 5
    assert all("rv30" not in name.lower() for name in payload["information_sets"]["B2_increment"])
    assert payload["secret_values_emitted"] is False
    assert payload["personal_paths_emitted"] is False
