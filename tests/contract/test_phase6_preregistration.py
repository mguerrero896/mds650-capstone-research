"""JSON Schema and determinism contracts for Phase 6 preregistration."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from mds650.phase6 import build_phase6_preregistration
from mds650.study_design import freeze_json

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = (
    ROOT
    / "specs"
    / "001-pit-options-rv30"
    / "contracts"
    / "phase6-preregistration.schema.json"
)
PROVENANCE: dict[str, Any] = {
    "branch": "001-pit-options-rv30-recovery",
    "repository_commit": "0" * 40,
    "python_version": "3.12.12",
    "uv_lock_sha256": "1" * 64,
    "design_sha256": "2" * 64,
    "spec_sha256": "3" * 64,
    "plan_sha256": "4" * 64,
    "tasks_sha256": "5" * 64,
    "analysis_sha256": "6" * 64,
    "phase6_source_sha256": "7" * 64,
    "schema_sha256": "8" * 64,
    "worktree_dirty": True,
}


def test_phase6_preregistration_validates_against_schema() -> None:
    """Validate every required field and enum against Draft 2020-12."""
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(
        build_phase6_preregistration(PROVENANCE)
    )


def test_phase6_preregistration_freezes_identically(tmp_path: Path) -> None:
    """Require identical content to reuse the same frozen file and digest."""
    path = tmp_path / "preregistration.json"
    manifest = build_phase6_preregistration(PROVENANCE)

    assert freeze_json(path, manifest) == freeze_json(path, manifest)
