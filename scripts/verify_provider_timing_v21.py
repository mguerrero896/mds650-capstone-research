"""Verify PIT v2.1 evidence hygiene and byte-level canonical integrity."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CANONICAL_INDEX = ROOT / "artifacts" / "canonical_validation_v1" / "evidence_index.csv"
PROTECTED_PATHS = (
    "artifacts/canonical_validation_v1",
    "artifacts/phase6",
    "artifacts/independent_replication",
    "reports/CODEX_PHASE6_FINAL_HANDOFF.md",
    "reports/CODEX_FINAL_VALIDATION_HANDOFF.md",
)
SECRET_PATTERN = re.compile(
    r"(?i)(UNUSUALWHALES_API_KEY|MASSIVE_API_KEY|FMP_API_KEY)\s*[:=]\s*[^\s,;]+"
)
PERSONAL_PATH_PATTERN = re.compile(r"(?i)[a-z]:\\users\\")


def _sha256(path: Path) -> str:
    """Return a byte-level SHA-256 without parsing a research payload."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1_048_576), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_repository_hash_check(index_path: Path) -> list[str]:
    """Compare repository-only canonical files with their recorded byte hashes."""
    mismatches: list[str] = []
    with index_path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            logical_path = str(row["logical_path"])
            if not logical_path.startswith("artifacts/canonical_validation_v1/"):
                continue
            path = ROOT / logical_path
            if not path.is_file() or _sha256(path) != str(row["sha256"]):
                mismatches.append(logical_path)
    return sorted(mismatches)


def _protected_git_diff(base_ref: str) -> list[str]:
    """Return changed tracked protected paths relative to a supplied local base."""
    completed = subprocess.run(
        ["git", "diff", "--name-only", base_ref, "--", *PROTECTED_PATHS],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return sorted(line for line in completed.stdout.splitlines() if line)


def _hygiene_violations(artifact_dir: Path) -> dict[str, list[str]]:
    """Detect personal paths and credential assignments in compact v2.1 outputs."""
    path_violations: list[str] = []
    secret_violations: list[str] = []
    for path in sorted(item for item in artifact_dir.rglob("*") if item.is_file()):
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if PERSONAL_PATH_PATTERN.search(content):
            path_violations.append(path.name)
        if SECRET_PATTERN.search(content):
            secret_violations.append(path.name)
    return {"personal_path_files": path_violations, "secret_assignment_files": secret_violations}


def main(argv: Sequence[str] | None = None) -> int:
    """Verify v2.1 integrity and write only compact machine-readable evidence.

    Parameters
    ----------
    argv:
        Optional CLI arguments for reproducible local verification.

    Returns
    -------
    int
        Zero when source hygiene and canonical integrity checks pass; one otherwise.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--artifact-dir", type=Path, default=ROOT / "artifacts" / "provider_timing_v21"
    )
    parser.add_argument("--canonical-index", type=Path, default=CANONICAL_INDEX)
    parser.add_argument("--base-ref", default="9914bb46f42fb1efab7db941267a767c6a3de7b7")
    args = parser.parse_args(argv)
    if not args.artifact_dir.is_dir():
        raise FileNotFoundError("TIMING_V21_ARTIFACT_DIR_MISSING")
    if not args.canonical_index.is_file():
        raise FileNotFoundError("TIMING_V21_CANONICAL_INDEX_MISSING")
    canonical_mismatches = _canonical_repository_hash_check(args.canonical_index)
    protected_changes = _protected_git_diff(args.base_ref)
    hygiene = _hygiene_violations(args.artifact_dir)
    passed = not canonical_mismatches and not protected_changes and not any(hygiene.values())
    result: dict[str, Any] = {
        "schema_version": "provider-timing-v2.1",
        "status": "PASS" if passed else "FAIL",
        "byte_level_canonical_hash_check_only": True,
        "canonical_repository_hash_mismatches": canonical_mismatches,
        "protected_tracked_changes_since_base": protected_changes,
        "hygiene": hygiene,
    }
    (args.artifact_dir / "integrity_check_v21.json").write_text(
        json.dumps(result, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(json.dumps(result, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
