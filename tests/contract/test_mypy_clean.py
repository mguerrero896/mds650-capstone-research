"""Prevent typed-code regressions across the repository."""

from __future__ import annotations

import subprocess
import sys


def test_src_and_scripts_pass_mypy() -> None:
    """Require the same repository-wide Mypy gate used for release validation."""
    result = subprocess.run(
        [sys.executable, "-m", "mypy", "src", "scripts"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
