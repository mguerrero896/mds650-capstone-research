"""Tier-2 validation: the local, licensed-evidence gates (CI cannot run these).

Runs, with true exit codes, everything the hosted hermetic CI deliberately
excludes: the FULL pytest suite (local-store contracts included), SHA-256
verification of every gated file against data/GATED_DATA_POINTERS.json, and the
static gates for parity. Exit code 0 means the tier-2 claim "the complete suite
passes locally against the real evidence" is verified, not asserted.

Run:  uv run python scripts/run_local_evidence_gates.py
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _run(name: str, command: list[str]) -> bool:
    print(f"[tier2] {name}: {' '.join(command)}", flush=True)
    completed = subprocess.run(command, cwd=REPO)
    status = "PASS" if completed.returncode == 0 else f"FAIL (exit {completed.returncode})"
    print(f"[tier2] {name}: {status}", flush=True)
    return completed.returncode == 0


def _verify_gated_hashes() -> bool:
    pointers = json.loads((REPO / "data" / "GATED_DATA_POINTERS.json").read_text())
    failures = []
    for entry in pointers["files"]:
        path = REPO / entry["path"]
        if not path.is_file():
            failures.append(f"MISSING {entry['path']}")
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != entry["sha256"]:
            failures.append(f"HASH_MISMATCH {entry['path']}")
    for failure in failures:
        print(f"[tier2] gated-hashes: {failure}")
    print(f"[tier2] gated-hashes: {'PASS' if not failures else 'FAIL'} "
          f"({len(pointers['files']) - len(failures)}/{len(pointers['files'])} verified)")
    return not failures


def main() -> None:
    results = {
        "ruff": _run("ruff", ["uv", "run", "ruff", "check", "src", "scripts", "tests"]),
        "mypy": _run("mypy", ["uv", "run", "mypy", "src", "scripts"]),
        "full-pytest": _run("full-pytest", ["uv", "run", "pytest", "tests", "-q"]),
        "gated-hashes": _verify_gated_hashes(),
    }
    print("[tier2] summary:", {name: "PASS" if ok else "FAIL" for name, ok in results.items()})
    sys.exit(0 if all(results.values()) else 1)


if __name__ == "__main__":
    main()
