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
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

CI_IGNORES = [
    "--ignore=tests/unit/test_generate_date_level_pit_preflight_plan_v1.py",
    "--ignore=tests/unit/test_independent_replication_panel.py",
    "--ignore=tests/unit/test_date_level_pit_preflight_request_budget_v1.py",
    "--ignore=tests/contract/test_b2_confirmation_inputs.py",
]


def _run(name: str, command: list[str], env: dict[str, str] | None = None) -> bool:
    print(f"[tier2] {name}: {' '.join(command)}", flush=True)
    completed = subprocess.run(command, cwd=REPO, env=env)
    status = "PASS" if completed.returncode == 0 else f"FAIL (exit {completed.returncode})"
    print(f"[tier2] {name}: {status}", flush=True)
    return completed.returncode == 0


def _ci_sim_env() -> dict[str, str]:
    """Approximate the hosted runner: no evidence root, no external drive, no keys.

    Every hermetic-CI platform gap this simulation can catch is caught BEFORE a
    publish, so a red run (and its failure email) never reaches GitHub.
    """
    env = dict(os.environ)
    for name in (
        "MDS650_EVIDENCE_ROOT",
        "MDS650_DATA_ROOT",
        "FMP_API_KEY",
        "UNUSUAL_WHALES_API_KEY",
        "MASSIVE_API_KEY",
    ):
        env.pop(name, None)
    env["MDS650_EXTERNAL_ROOT"] = str(REPO / ".ci-sim-nonexistent")
    return env


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
        "ci-sim": _run(
            "ci-sim (hermetic job replica)",
            ["uv", "run", "pytest", "tests", "-q", *CI_IGNORES,
             "--cov=src/mds650", "--cov-report=term", "--cov-fail-under=80"],
            env=_ci_sim_env(),
        ),
        "gated-hashes": _verify_gated_hashes(),
    }
    print("[tier2] summary:", {name: "PASS" if ok else "FAIL" for name, ok in results.items()})
    sys.exit(0 if all(results.values()) else 1)


if __name__ == "__main__":
    main()
