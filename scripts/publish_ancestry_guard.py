"""Refuse a mirror publish that would erase published history.

``scripts/publish_mirror.sh`` builds a stripped mirror and force-pushes it over
``main`` on a public remote. That is safe only while the mirror is a projection
of the published lineage. It stopped being one when the RP2-v3 gates started
landing as pull requests opened against the public repository directly:
``docs/rp2_v3/MIRROR_HAZARD.md`` measures two disjoint histories with no merge
base, where the force-push would replace 392 published commits.

This guard makes that outcome impossible to reach by accident. It refuses
unless the branch about to be overwritten is an ancestor of what replaces it,
so nothing already published can be dropped. It does not decide the underlying
repository question — adopting the public lineage, or publishing somewhere
other than ``main`` — which is the owner's call.

Everything here is read-only: it resolves the remote tip, fetches that one
object, and compares. It never pushes.

Usage:
    python scripts/publish_ancestry_guard.py --mirror DIR --remote URL --branch main
    python scripts/publish_ancestry_guard.py ... --expect-remote URL --expect-base SHA
"""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

REFUSAL = "PUBLISH REFUSED"


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=False
    )


def _refuse(reason: str) -> None:
    raise SystemExit(f"{REFUSAL}: {reason}")


def guard(
    mirror: Path,
    remote: str,
    branch: str,
    *,
    expect_remote: str | None = None,
    expect_base: str | None = None,
) -> str:
    """Return the remote tip that the push may safely overwrite, or refuse."""
    if expect_remote is not None and expect_remote != remote:
        _refuse(f"remote mismatch: expected {expect_remote}, script would push to {remote}")

    listing = _git(mirror, "ls-remote", remote, f"refs/heads/{branch}")
    if listing.returncode != 0:
        _refuse(f"cannot read remote {remote}: {listing.stderr.strip().splitlines()[-1:]}")
    if not listing.stdout.strip():
        _refuse(f"branch {branch} not found on remote {remote}; refusing to create it blindly")
    tip = listing.stdout.split()[0]

    if expect_base is not None and expect_base != tip:
        _refuse(f"base mismatch: caller expected {expect_base}, remote {branch} is at {tip}")

    local = _git(mirror, "rev-parse", branch)
    if local.returncode != 0:
        _refuse(f"branch {branch} does not exist in the mirror at {mirror}")
    head = local.stdout.strip()

    fetched = _git(mirror, "fetch", "--quiet", remote, branch)
    if fetched.returncode != 0:
        _refuse(f"cannot fetch {branch} from {remote} to compare histories")

    if _git(mirror, "merge-base", "--is-ancestor", tip, head).returncode != 0:
        behind = _git(mirror, "rev-list", "--count", f"{head}..{tip}").stdout.strip() or "?"
        _refuse(
            f"ancestry violation: remote {branch} ({tip[:12]}) is not an ancestor of the "
            f"mirror ({head[:12]}). Pushing would drop {behind} published commit(s). "
            "See docs/rp2_v3/MIRROR_HAZARD.md."
        )
    return tip


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mirror", type=Path, required=True)
    parser.add_argument("--remote", required=True)
    parser.add_argument("--branch", default="main")
    parser.add_argument("--expect-remote", default=None)
    parser.add_argument("--expect-base", default=None)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="validate only; this guard never pushes, the flag documents intent at call sites",
    )
    arguments = parser.parse_args()
    tip = guard(
        arguments.mirror,
        arguments.remote,
        arguments.branch,
        expect_remote=arguments.expect_remote,
        expect_base=arguments.expect_base,
    )
    print(f"[publish-guard] {arguments.branch} at {tip[:12]} is contained; push may proceed")


if __name__ == "__main__":
    main()
