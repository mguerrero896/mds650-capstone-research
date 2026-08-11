"""Contract checks for the development-only B2 mechanism evidence."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_residual_search_records_all_variants_without_retaining_any() -> None:
    """Retention must be read from candidate records, not the legacy flag."""
    path = ROOT / "artifacts" / "methodology" / "b2_mechanism_results.json"
    if not path.exists():
        return
    payload = json.loads(path.read_text(encoding="utf-8"))
    candidates = payload["candidate_records"]
    assert payload["primary_variant_count"] == 25
    assert len(candidates) == 25
    assert payload["retained_candidates"] == []
    assert all(record["retained"] is False for record in candidates)
    assert len(payload["placebo_results"]) == 25
    assert len(payload["lag_sensitivity_results"]) == 25
    assert payload["independent_samples_read"] is False
    assert payload["oos_read_count"] == 0

