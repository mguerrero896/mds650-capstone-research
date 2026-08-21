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
    """A descendant of the published tip is allowed — and still must not push."""
    remote, source = _remote_with_history(tmp_path)
    mirror = tmp_path / "mirror"
    _git(tmp_path, "clone", "-q", str(source), str(mirror))
    _commit(mirror, "new-work")
    before = _git(Path(remote), "rev-parse", "main")

    result = _run_guard(
        "--mirror", str(mirror), "--remote", str(remote), "--branch", "main", "--dry-run"
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
        "--expect-base", "0" * 40, "--dry-run",
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
