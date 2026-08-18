"""Anti-drift tripwire (decision 63): CANONICAL_STATE.json must equal a fresh
regeneration, STATUS.md must equal its rendering, and every superseded document
must carry its banner. A 'current' document can no longer silently contradict
the repository state."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

_spec = importlib.util.spec_from_file_location(
    "generate_canonical_state", REPO / "scripts" / "generate_canonical_state.py"
)
assert _spec is not None and _spec.loader is not None
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)


def test_state_file_matches_regeneration() -> None:
    committed = json.loads((REPO / "data" / "CANONICAL_STATE.json").read_text(encoding="utf-8"))
    fresh = _module.build_state()
    assert committed == fresh, (
        "CANONICAL_STATE.json is stale — run: uv run python scripts/generate_canonical_state.py"
    )


def test_status_md_matches_rendering() -> None:
    committed = (REPO / "STATUS.md").read_bytes().replace(b"\r\n", b"\n").decode("utf-8")
    fresh = _module.render_status(_module.build_state())
    assert committed == fresh, (
        "STATUS.md is stale — run: uv run python scripts/generate_canonical_state.py"
    )


def test_superseded_documents_carry_their_banner() -> None:
    state = json.loads((REPO / "data" / "CANONICAL_STATE.json").read_text(encoding="utf-8"))
    missing = []
    for entry in state["superseded_documents"]:
        text = (REPO / entry["path"]).read_text(encoding="utf-8", errors="replace")
        if "SUPERSEDED" not in text[:500]:
            missing.append(entry["path"])
    assert not missing, f"superseded docs without banner: {missing}"
