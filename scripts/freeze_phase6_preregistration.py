"""Freeze and validate the owner-approved Phase 6 preregistration."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker  # type: ignore[import-untyped]

from mds650.phase6 import build_phase6_preregistration
from mds650.study_design import freeze_json, source_sha256

ROOT = Path(__file__).resolve().parents[1]
DESIGN = (
    ROOT
    / "docs"
    / "superpowers"
    / "specs"
    / "2026-08-01-rv30-mechanism-aware-replication-design.md"
)
SPEC_DIR = ROOT / "specs" / "001-pit-options-rv30"
SCHEMA = SPEC_DIR / "contracts" / "phase6-preregistration.schema.json"
OUTPUT = ROOT / "artifacts" / "phase6" / "preregistration.json"


def _git(*arguments: str) -> str:
    """Return one sanitized Git value for preregistration provenance."""
    result = subprocess.run(
        ["git", *arguments],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def main() -> int:
    """Build, schema-validate and immutably freeze Phase 6.

    Returns
    -------
    int
        Zero when the new or existing preregistration matches exactly.

    Raises
    ------
    ValueError
        If JSON Schema validation or immutable-content validation fails.
    subprocess.CalledProcessError
        If Git provenance cannot be resolved.
    """
    provenance = {
        "branch": _git("branch", "--show-current"),
        "repository_commit": _git("rev-parse", "HEAD"),
        "python_version": ".".join(map(str, sys.version_info[:3])),
        "uv_lock_sha256": source_sha256(ROOT / "uv.lock"),
        "design_sha256": source_sha256(DESIGN),
        "spec_sha256": source_sha256(SPEC_DIR / "spec.md"),
        "plan_sha256": source_sha256(SPEC_DIR / "plan.md"),
        "tasks_sha256": source_sha256(SPEC_DIR / "tasks.md"),
        "analysis_sha256": source_sha256(ROOT / "docs" / "recovery" / "phase6_spec_analysis.md"),
        "phase6_source_sha256": source_sha256(ROOT / "src" / "mds650" / "phase6.py"),
        "schema_sha256": source_sha256(SCHEMA),
        "worktree_dirty": bool(_git("status", "--porcelain")),
    }
    preregistration = build_phase6_preregistration(provenance)
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(preregistration)
    content_sha256 = freeze_json(OUTPUT, preregistration)
    print(
        json.dumps(
            {
                "content_sha256": content_sha256,
                "manifest_sha256": preregistration["manifest_sha256"],
                "oos_read_count": preregistration["oos_read_count"],
                "session_manifest_sha256": preregistration["session_manifest_sha256"],
                "status": preregistration["status"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
