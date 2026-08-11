"""Explicit routing for tests that inspect non-versioned research evidence."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

EVIDENCE_ROOT_ENV = "MDS650_EVIDENCE_ROOT"


def require_evidence_root(*required_relative_paths: str) -> Path:
    """Return an explicitly configured evidence root or skip transparently.

    Commercial provider payloads and their derived historical artifacts are not
    committed to a clean worktree.  A test that asserts facts about those exact
    artifacts must therefore opt into a separately mounted, verified evidence
    root.  If an operator supplies one but it is incomplete, the test fails;
    only an absent opt-in is skipped.
    """
    configured = os.environ.get(EVIDENCE_ROOT_ENV)
    if not configured:
        pytest.skip("MDS650_EVIDENCE_ROOT_REQUIRED_FOR_EVIDENCE_TEST")
    root = Path(configured).expanduser().resolve()
    if not root.is_dir() or any(
        not (root / relative_path).is_file()
        for relative_path in required_relative_paths
    ):
        pytest.fail("MDS650_EVIDENCE_ROOT_INCOMPLETE")
    return root
