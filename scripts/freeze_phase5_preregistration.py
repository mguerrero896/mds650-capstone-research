"""Freeze the approved Phase 5 sessions and outcome-blind preregistration."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker  # type: ignore[import-untyped]

from mds650.study_design import (
    build_preregistration,
    build_session_manifest,
    build_study_sessions,
    freeze_json,
)

ROOT = Path(__file__).resolve().parents[1]
DESIGN = (
    ROOT
    / "docs"
    / "superpowers"
    / "specs"
    / "2026-07-29-rv30-90-session-champion-challenger-design.md"
)
SCHEMA = (
    ROOT
    / "specs"
    / "001-pit-options-rv30"
    / "contracts"
    / "phase5-preregistration.schema.json"
)
OUTPUT = ROOT / "artifacts" / "phase5"
SESSION_OUTPUT = OUTPUT / "study_sessions_90.json"
PREREGISTRATION_OUTPUT = OUTPUT / "preregistration.json"


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git(*arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def main() -> int:
    """Freeze and schema-validate both deterministic manifests.

    Returns
    -------
    int
        Zero when the existing or newly written manifests match exactly.

    Raises
    ------
    ValueError
        If a frozen artifact drifts or violates its JSON Schema.
    subprocess.CalledProcessError
        If Git provenance cannot be resolved.
    """
    sessions = build_study_sessions("XNYS", date(2026, 7, 17), 80, 10)
    session_manifest = build_session_manifest(sessions)
    provenance = {
        "branch": _git("branch", "--show-current"),
        "commit": _git("rev-parse", "HEAD"),
        "python_version": ".".join(map(str, sys.version_info[:3])),
        "uv_lock_sha256": _file_sha256(ROOT / "uv.lock"),
        "design_sha256": _file_sha256(DESIGN),
        "spec_kit_commit": _git("rev-parse", "e9aaf1a"),
        "worktree_dirty": bool(_git("status", "--porcelain")),
    }
    preregistration = build_preregistration(session_manifest, provenance=provenance)
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(preregistration)

    session_digest = freeze_json(SESSION_OUTPUT, session_manifest)
    preregistration_digest = freeze_json(PREREGISTRATION_OUTPUT, preregistration)
    print(
        json.dumps(
            {
                "status": preregistration["status"],
                "session_manifest_sha256": session_digest,
                "preregistration_sha256": preregistration_digest,
                "holdout_reads": 0,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
