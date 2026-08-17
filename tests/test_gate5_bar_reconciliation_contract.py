"""Standing tripwire: the cross-provider bar reconciliation must stay clean.

If the Gate 5.1 artifact exists, the winning label convention must remain
``same_label`` with exact median agreement; a future acquisition that breaks
this indicates provider drift in bar semantics and must fail loudly before any
panel is rebuilt on top of it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ARTIFACT = (
    Path(__file__).resolve().parents[1] / "artifacts" / "gate5_pit" / "bar_reconciliation.json"
)


def test_bar_label_convention_pinned() -> None:
    if not ARTIFACT.exists():
        pytest.skip("gate5 reconciliation artifact not present")
    payload = json.loads(ARTIFACT.read_text(encoding="utf-8"))
    assert payload["winning_convention"] == "same_label"
    medians = payload["median_of_median_rel_diff"]
    assert medians["same_label"] < 1e-4
    assert medians["same_label"] < medians["fmp_plus_1m"] / 10
    populated = [
        cell
        for cell in payload["cells"].values()
        if isinstance(cell.get("same_label"), dict) and cell["same_label"].get("matched")
    ]
    assert len(populated) >= 30
