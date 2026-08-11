"""Contract checks for the portable canonical RV30 defense notebook."""

from __future__ import annotations

import json
from pathlib import Path

NOTEBOOK = Path("notebooks/MDS650_Canonical_RV30_Defense.ipynb")


def _read_notebook() -> dict[str, object]:
    assert NOTEBOOK.exists(), "canonical defense notebook is missing"
    return json.loads(NOTEBOOK.read_text(encoding="utf-8"))


def test_notebook_is_small_offline_and_references_canonical_evidence() -> None:
    notebook = _read_notebook()
    cells = notebook["cells"]
    assert isinstance(cells, list)
    assert 7 <= len(cells) <= 12
    code = "\n".join(
        "".join(cell.get("source", []))
        for cell in cells
        if cell.get("cell_type") == "code"
    )
    assert "artifacts/canonical_validation_v1" in code
    assert "load_validated_contrasts" in code
    assert (
        "provider" not in code.lower()
        or "provider calls" in code.lower()
        or "provider_calls" in code.lower()
    )
    assert "UNUSUALWHALES_API_KEY" not in code
    assert "MASSIVE_API_KEY" not in code
    assert "FMP_API_KEY" not in code
    assert "pipeline_runs" not in code
    assert "authenticated_v1x" not in code
    assert "C:\\Users\\" not in json.dumps(notebook)


def test_notebook_does_not_duplicate_model_or_target_logic() -> None:
    notebook = _read_notebook()
    text = json.dumps(notebook).lower()
    assert "lightgbm.lgbmregressor" not in text
    assert "fit(" not in text
    assert "qlike(" not in text
    assert "download" not in text
    assert "backfill" not in text
