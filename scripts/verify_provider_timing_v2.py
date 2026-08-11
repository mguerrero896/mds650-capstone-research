"""Verify deterministic equality between two compact provider-timing v2 bundles."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Sequence
from pathlib import Path


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse two evidence directories and one compact verification output path.

    Parameters
    ----------
    argv:
        Optional arguments; ``None`` uses the process command line.

    Returns
    -------
    argparse.Namespace
        Paths only. No market-data, credential, or target option exists.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-dir", type=Path, required=True)
    parser.add_argument("--replay-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Compare compact artifact hashes and write a sanitized determinism result.

    Parameters
    ----------
    argv:
        Optional deterministic-verification arguments.

    Returns
    -------
    int
        Zero only when both artifact trees have identical relative files and
        SHA-256 hashes. A non-deterministic replay raises ``ValueError``.

    Raises
    ------
    FileNotFoundError
        If either evidence directory is unavailable.
    ValueError
        If the replay differs or the output would contain a personal path.
    """
    args = parse_args(argv)
    expected = _hash_tree(args.expected_dir)
    replay = _hash_tree(args.replay_dir)
    deterministic = expected == replay
    payload = {
        "schema_version": "provider-timing-v2-determinism-1.0",
        "scope": "compact_sanitized_artifacts_only",
        "expected_file_count": len(expected),
        "replay_file_count": len(replay),
        "expected_artifact_sha256": expected,
        "replay_artifact_sha256": replay,
        "deterministic": deterministic,
    }
    serialized = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True)
    if _contains_personal_path(serialized):
        raise ValueError("TIMING_V2_PERSONAL_PATH_IN_DETERMINISM_OUTPUT")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(serialized + "\n", encoding="utf-8")
    if not deterministic:
        raise ValueError("TIMING_V2_REPLAY_HASH_MISMATCH")
    return 0


def _hash_tree(root: Path) -> dict[str, str]:
    """Hash only evidence payloads by logical relative file name.

    Replay directories may contain operational stdout/stderr logs created by a
    launcher.  Those logs are not part of the sanitized evidence contract and
    therefore cannot participate in deterministic-equivalence decisions.
    """
    if not root.is_dir():
        raise FileNotFoundError("TIMING_V2_DETERMINISM_DIRECTORY_MISSING")
    files = sorted(
        path
        for path in root.rglob("*")
        if path.is_file()
        and path.name != "determinism_check_v2.json"
        and path.suffix.lower() in {".csv", ".json"}
    )
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in files
    }


def _contains_personal_path(value: str) -> bool:
    """Reject Windows user-profile paths in generated evidence."""
    normalized = value.replace("/", "\\").lower()
    return "c:\\users\\" in normalized or "d:\\users\\" in normalized


if __name__ == "__main__":  # pragma: no cover - command entry point
    raise SystemExit(main())
