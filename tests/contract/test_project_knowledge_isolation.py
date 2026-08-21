"""MDS650 knowledge tooling must exist, and must stay inside its own profile.

``AGENTS.md`` documents ``scripts/query_project_knowledge.ps1`` and
``scripts/sync_project_knowledge.ps1`` and states that
``MDS650_Knowledge_AutoSync`` refreshes both engines every fifteen minutes.
Neither script was present in the working tree, so the documentation asserted a
capability that could not run — and the scheduled task is Disabled with
LastTaskResult 0x00000040.

The authoritative copies are in this repository's own history, tag
``archive-meeting-dirty-20260816`` (commit 89c3f2d, authored by the owner). They
are restored from there. Nothing is copied from Earnings, GenIA, or any global
corpus.

These tests pin the isolation the scripts already enforce, so a later edit
cannot quietly widen it: the only permitted identifiers are the ``.mds650``
profile, ``mds650-research``, ``mds650-code``, and the repository-local
``graphify-out``.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SYNC = ROOT / "scripts" / "sync_project_knowledge.ps1"
QUERY = ROOT / "scripts" / "query_project_knowledge.ps1"

# Corpora this project must never reach. Matching is case-insensitive and
# word-bounded so ordinary English in a comment cannot trip it.
FOREIGN_CORPORA = ("earnings", "genia", "gbrain-global", "global-corpus")


@pytest.mark.parametrize("script", [SYNC, QUERY], ids=["sync", "query"])
def test_script_exists(script: Path) -> None:
    assert script.is_file(), (
        f"{script.name} is documented in AGENTS.md but absent; "
        "restore it from tag archive-meeting-dirty-20260816"
    )


@pytest.mark.parametrize("script", [SYNC, QUERY], ids=["sync", "query"])
def test_script_pins_the_isolated_profile(script: Path) -> None:
    source = script.read_text(encoding="utf-8")
    assert '".mds650"' in source or "'.mds650'" in source, "must resolve the isolated profile"
    assert "USERPROFILE" in source


@pytest.mark.parametrize("script", [SYNC, QUERY], ids=["sync", "query"])
def test_script_names_only_project_sources(script: Path) -> None:
    source = script.read_text(encoding="utf-8")
    assert "mds650-research" in source
    for foreign in FOREIGN_CORPORA:
        assert not re.search(rf"\b{re.escape(foreign)}\b", source, re.IGNORECASE), (
            f"{script.name} references the {foreign} corpus; MDS650 knowledge must stay isolated"
        )


def test_sync_refuses_an_unexpected_source() -> None:
    """The .gbrain-source marker is the gate; a different value must throw."""
    source = SYNC.read_text(encoding="utf-8")
    assert ".gbrain-source" in source
    assert 'if ($primarySourceId -ne "mds650-research")' in source
    assert "throw" in source


def test_sync_confines_the_code_index_to_the_profile() -> None:
    """A path that escapes the profile must abort, not be silently accepted."""
    source = SYNC.read_text(encoding="utf-8")
    assert "StartsWith(" in source, "the code-index path must be checked against the profile root"
    assert "GBRAIN_HOME" in source, "gbrain must be pointed at the isolated home"


def test_repository_marker_declares_the_project_source() -> None:
    marker = ROOT / ".gbrain-source"
    assert marker.is_file(), ".gbrain-source is the marker sync_project_knowledge.ps1 requires"
    assert marker.read_text(encoding="utf-8").strip() == "mds650-research"
