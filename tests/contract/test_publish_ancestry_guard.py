"""A publish that would erase published history must abort before the push.

``scripts/publish_mirror.sh`` ends in ``git push --force`` twice, against a
public remote, with no ancestry validation. ``docs/rp2_v3/MIRROR_HAZARD.md``
measures the consequence: the canonical tree and ``origin/main`` have no merge
base, and running the script as it stood would replace 392 published commits
with a lineage that never contained them.

These tests build real git repositories under ``tmp_path`` and exercise the
guard against them. No test contacts the real remote; the valid case reaches a
dry run at most.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
GUARD = ROOT / "scripts" / "publish_ancestry_guard.py"
PUBLISH = ROOT / "scripts" / "publish_mirror.sh"


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
        env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
             "GIT_COMMITTER_EMAIL": "t@t", "PATH": __import__("os").environ["PATH"]},
    )
    return result.stdout.strip()


def _commit(repo: Path, name: str) -> str:
    (repo / name).write_text(name, encoding="utf-8")
    _git(repo, "add", name)
    _git(repo, "commit", "-q", "-m", name)
    return _git(repo, "rev-parse", "HEAD")


def _repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-q", "-b", "main")
    return path


def _remote_with_history(tmp_path: Path) -> tuple[Path, Path]:
    """A bare 'public' remote holding two published commits."""
    source = _repo(tmp_path / "source")
    _commit(source, "published-one")
    _commit(source, "published-two")
    bare = tmp_path / "remote.git"
    _git(tmp_path, "clone", "-q", "--bare", str(source), str(bare))
    return bare, source


REFUSAL = "PUBLISH REFUSED"
LF = chr(10)


def _bash_runs() -> bool:
    """Git Bash is not reliably invocable from a Windows subprocess; CI's is."""
    try:
        probe = subprocess.run(
            ["bash", "-c", "echo ok"], capture_output=True, text=True, check=False
        )  # single-line -c is safe on every platform
    except OSError:
        return False
    return probe.stdout.strip() == "ok"


NEEDS_BASH = pytest.mark.skipif(not _bash_runs(), reason="bash not invocable here")


def _run_guard(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["python", str(GUARD), *args], capture_output=True, text=True, check=False
    )


def _refusal(result: subprocess.CompletedProcess[str]) -> str:
    """The guard's own refusal text, never an interpreter error about the guard.

    Asserting on a substring of the script's own filename would let a missing
    script pass: "publish_ancestry_guard.py" contains "ancestr".
    """
    combined = result.stdout + result.stderr
    assert REFUSAL in combined, f"expected a guard refusal, got: {combined[:400]}"
    return combined[combined.index(REFUSAL) :].lower()


def test_unrelated_history_aborts_before_push(tmp_path: Path) -> None:
    """The MIRROR_HAZARD scenario: disjoint lineages, force-push would erase 392 commits."""
    remote, _ = _remote_with_history(tmp_path)
    mirror = _repo(tmp_path / "mirror")
    _commit(mirror, "unrelated-one")

    result = _run_guard("--mirror", str(mirror), "--remote", str(remote), "--branch", "main")
    assert result.returncode != 0
    assert "ancestr" in _refusal(result)


def test_wrong_remote_aborts(tmp_path: Path) -> None:
    remote, source = _remote_with_history(tmp_path)
    mirror = tmp_path / "mirror"
    _git(tmp_path, "clone", "-q", str(source), str(mirror))
    _commit(mirror, "new-work")
    other = tmp_path / "other.git"
    _git(tmp_path, "clone", "-q", "--bare", str(source), str(other))

    result = _run_guard(
        "--mirror", str(mirror), "--remote", str(other),
        "--branch", "main", "--expect-remote", str(remote),
    )
    assert result.returncode != 0
    assert "remote" in _refusal(result)


def test_missing_branch_on_remote_aborts(tmp_path: Path) -> None:
    remote, source = _remote_with_history(tmp_path)
    mirror = tmp_path / "mirror"
    _git(tmp_path, "clone", "-q", str(source), str(mirror))

    result = _run_guard(
        "--mirror", str(mirror), "--remote", str(remote), "--branch", "no-such-branch"
    )
    assert result.returncode != 0
    assert "branch" in _refusal(result)


def test_related_history_reaches_dry_run_only(tmp_path: Path) -> None:
    """A descendant of the published tip is allowed — and the guard still must not push."""
    remote, source = _remote_with_history(tmp_path)
    mirror = tmp_path / "mirror"
    _git(tmp_path, "clone", "-q", str(source), str(mirror))
    _commit(mirror, "new-work")
    before = _git(Path(remote), "rev-parse", "main")

    result = _run_guard(
        "--mirror", str(mirror), "--remote", str(remote), "--branch", "main"
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert _git(Path(remote), "rev-parse", "main") == before, "dry run must not move the remote"


def test_explicit_base_mismatch_aborts(tmp_path: Path) -> None:
    """Naming a base that is not the remote tip means the caller's view is stale."""
    remote, source = _remote_with_history(tmp_path)
    mirror = tmp_path / "mirror"
    _git(tmp_path, "clone", "-q", str(source), str(mirror))
    _commit(mirror, "new-work")

    result = _run_guard(
        "--mirror", str(mirror), "--remote", str(remote), "--branch", "main",
        "--expect-base", "0" * 40,
    )
    assert result.returncode != 0
    assert "base" in _refusal(result)


PUSH_LINES = ['push --force "$REMOTE" main', 'push --force "$REMOTE" --tags']


@pytest.mark.parametrize("push_line", PUSH_LINES)
def test_publish_script_guards_before_every_push(push_line: str) -> None:
    """The guard is worthless if publish_mirror.sh can still reach a push without it."""
    source = PUBLISH.read_text(encoding="utf-8")
    assert "publish_ancestry_guard.py" in source, "publish_mirror.sh must invoke the guard"
    guard_at = source.index("publish_ancestry_guard.py")
    assert source.index(push_line) > guard_at, f"guard must run before: {push_line}"


# ---------------------------------------------------------------------------
# The tag push. publish_mirror.sh runs `git push --force "$REMOTE" --tags`
# immediately after the branch push. Check 4 as first written resolved
# refs/heads/<branch> only, so every tag ref went out unguarded — and with two
# disjoint lineages, a same-named tag on the remote would be silently replaced
# by a commit from an unrelated history. The tags are the frozen-evidence
# anchors, so that is the worst possible ref to leave uncovered.
# ---------------------------------------------------------------------------


def _tag(repo: Path, name: str) -> None:
    _git(repo, "tag", name)


def test_tag_moving_to_unrelated_commit_aborts(tmp_path: Path) -> None:
    """Branch is a clean descendant; only the tag is off-lineage.

    The branch must be related, or the branch ancestry check fires first and
    the tag rule is never exercised.
    """
    remote, source = _remote_with_history(tmp_path)
    _tag(source, "evidence-freeze")
    _git(source, "push", "-q", str(remote), "evidence-freeze")

    mirror = tmp_path / "mirror"
    _git(tmp_path, "clone", "-q", str(source), str(mirror))
    _commit(mirror, "new-work")
    # A parentless commit built with plumbing: shares no history with anything
    # the remote published, and leaves the working tree untouched.
    tree = _git(mirror, "rev-parse", "HEAD^{tree}")
    orphan = _git(mirror, "commit-tree", tree, "-m", "orphan lineage")
    _git(mirror, "tag", "-f", "evidence-freeze", orphan)

    result = _run_guard(
        "--mirror", str(mirror), "--remote", str(remote), "--branch", "main", "--check-tags"
    )
    assert result.returncode != 0
    assert "tag" in _refusal(result)


def test_tag_advancing_on_the_same_lineage_is_allowed(tmp_path: Path) -> None:
    remote, source = _remote_with_history(tmp_path)
    _tag(source, "evidence-freeze")
    _git(source, "push", "-q", str(remote), "evidence-freeze")

    mirror = tmp_path / "mirror"
    _git(tmp_path, "clone", "-q", str(source), str(mirror))
    _commit(mirror, "new-work")
    _git(mirror, "tag", "-f", "evidence-freeze")

    result = _run_guard(
        "--mirror", str(mirror), "--remote", str(remote), "--branch", "main", "--check-tags"
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_local_only_tag_is_allowed(tmp_path: Path) -> None:
    """A tag the remote does not have yet cannot destroy anything."""
    remote, source = _remote_with_history(tmp_path)
    mirror = tmp_path / "mirror"
    _git(tmp_path, "clone", "-q", str(source), str(mirror))
    _git(mirror, "tag", "brand-new-tag")

    result = _run_guard(
        "--mirror", str(mirror), "--remote", str(remote), "--branch", "main", "--check-tags"
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_publish_script_guards_the_tag_push() -> None:
    """--tags force-updates every tag ref; the guard call must cover them."""
    source = PUBLISH.read_text(encoding="utf-8")
    assert "--check-tags" in source, "check 4 must validate tags, not only the branch"
    assert source.index("--check-tags") < source.index('push --force "$REMOTE" --tags')


def test_publish_script_does_not_compare_the_remote_to_itself() -> None:
    """--expect-remote "$REMOTE" alongside --remote "$REMOTE" can never fire."""
    source = PUBLISH.read_text(encoding="utf-8")
    assert '--remote "$REMOTE" --branch main \\n    --expect-remote "$REMOTE"' not in source


# ---------------------------------------------------------------------------
# Check 1's leak detector. It used to end in `| head -1` inside an `if`. Under
# `set -o pipefail`, closing the pipe early makes grep die on SIGPIPE (141), the
# pipeline reports non-zero, and the `if` reads that as "no leak". Measured on
# this machine: detection at 1,000 leaked paths, silent false pass from ~4,000.
# The more that leaked, the likelier the publish proceeded.
# ---------------------------------------------------------------------------


def _run_leak_check(tmp_path: Path, leaked_paths: int) -> str:
    """Run the current check-1 construction against a synthetic path list.

    bash runs with cwd=tmp_path and bare filenames: Git Bash cannot resolve a
    Windows-drive path. Files are written with explicit LF newlines because
    grep -Fx would otherwise compare CRLF-terminated lines and match nothing.
    """
    paths = LF.join(f"artifacts/gated/panel_{i}.parquet" for i in range(leaked_paths))
    for name in ("all.txt", "excludes.txt"):
        with (tmp_path / name).open("w", encoding="utf-8", newline=LF) as handle:
            handle.write(paths + LF)
    script = LF.join(
        [
            "set -euo pipefail",
            "LEAKED=$(cat all.txt | sort -u | grep -Fxf excludes.txt || true)",
            'if [ -n "$LEAKED" ]; then echo DETECTED; else echo FALSE_PASS; fi',
        ]
    )
    # Windows builds a command line rather than an argv array, so a multi-line
    # -c argument is split at its newlines. Run it from a file instead.
    runner = tmp_path / "check.sh"
    with runner.open("w", encoding="utf-8", newline=LF) as handle:
        handle.write(script + LF)
    result = subprocess.run(
        ["bash", runner.name], cwd=tmp_path, capture_output=True, text=True, check=False
    )
    return result.stdout.strip()


@NEEDS_BASH
@pytest.mark.parametrize("leaked", [10, 4_000, 20_000])
def test_leak_check_detects_at_every_volume(tmp_path: Path, leaked: int) -> None:
    assert _run_leak_check(tmp_path, leaked) == "DETECTED"


def test_leak_check_decision_does_not_flow_through_head() -> None:
    """`head` may format the report; it must not gate the verdict."""
    source = PUBLISH.read_text(encoding="utf-8")
    check_one = source[source.index("# Check 1:") : source.index("# Check 2:")]
    assert 'grep -Fxf "$EXCLUDES_EXPANDED" | head' not in check_one
    assert "LEAKED=$(" in check_one, "the match set must be collected before the decision"


def test_empty_exclude_list_refuses_the_publish() -> None:
    """An empty expansion strips nothing; publishing on it is not a clean pass."""
    source = PUBLISH.read_text(encoding="utf-8")
    assert '[ ! -s "$EXCLUDES_EXPANDED" ]' in source
