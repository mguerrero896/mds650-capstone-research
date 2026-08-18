"""Append-only registry of frozen evidence (decision 62).

data/FROZEN_ARTIFACTS.json maps each frozen artifact to its SHA-256 at freeze
time. Discipline: a path is added exactly once; re-adding with identical bytes
is a no-op, re-adding with different bytes is an error. There is NO update or
remove operation — a corrected artifact is a NEW path (version suffix), and the
registry keeps the old one so history stays auditable.

Commands:
    uv run python scripts/freeze_registry.py --add <path> [<path> ...]
    uv run python scripts/freeze_registry.py --verify
    uv run python scripts/freeze_registry.py --lock      (set read-only flags)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import stat
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
REGISTRY = REPO / "data" / "FROZEN_ARTIFACTS.json"


def _load() -> dict[str, object]:
    if REGISTRY.is_file():
        return json.loads(REGISTRY.read_text(encoding="utf-8"))  # type: ignore[no-any-return]
    return {
        "schema_version": "frozen-artifacts-v1.0",
        "note": (
            "Append-only registry of frozen evidence. Entries are never edited or "
            "removed; amendments are new paths. Physical mutation of any listed file "
            "fails the test suite (tests/contract/test_frozen_artifacts_registry.py)."
        ),
        "entries": [],
    }


BINARY_SUFFIXES = {".parquet"}


def _sha256(path: Path) -> str:
    """Platform-stable digest: text bytes are LF-normalized (matching the git
    blob under .gitattributes eol=lf), binaries hashed raw. A pure EOL flip is
    checkout smudge, not content mutation."""
    data = path.read_bytes()
    if path.suffix not in BINARY_SUFFIXES:
        data = data.replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


def add(paths: list[str]) -> int:
    registry = _load()
    entries: list[dict[str, object]] = registry["entries"]  # type: ignore[assignment]
    by_path = {str(entry["path"]): entry for entry in entries}
    added = 0
    for raw in paths:
        relative = Path(raw).as_posix()
        absolute = REPO / relative
        if not absolute.is_file():
            print(f"[freeze] MISSING {relative}")
            return 1
        digest = _sha256(absolute)
        existing = by_path.get(relative)
        if existing is not None:
            if existing["sha256"] != digest:
                print(f"[freeze] REGISTRY_ENTRY_CONFLICT {relative}: bytes changed since freeze")
                return 1
            continue
        entry: dict[str, object] = {
            "path": relative,
            "sha256": digest,
            "bytes": absolute.stat().st_size,
        }
        entries.append(entry)
        by_path[relative] = entry
        added += 1
    entries.sort(key=lambda entry: str(entry["path"]))
    REGISTRY.write_text(
        json.dumps(registry, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    print(f"[freeze] registered {added} new, total {len(entries)}")
    return 0


def verify() -> int:
    registry = _load()
    failures = 0
    entries: list[dict[str, object]] = registry["entries"]  # type: ignore[assignment]
    for entry in entries:
        path = REPO / str(entry["path"])
        if not path.is_file():
            print(f"[freeze] MISSING {entry['path']}")
            failures += 1
            continue
        if _sha256(path) != entry["sha256"]:
            print(f"[freeze] MUTATED {entry['path']}")
            failures += 1
    print(f"[freeze] verify: {len(entries) - failures}/{len(entries)} intact")
    return 0 if failures == 0 else 1


def lock() -> int:
    registry = _load()
    entries: list[dict[str, object]] = registry["entries"]  # type: ignore[assignment]
    locked = 0
    for entry in entries:
        path = REPO / str(entry["path"])
        if path.is_file():
            path.chmod(stat.S_IREAD)
            locked += 1
    print(f"[freeze] read-only flag set on {locked}/{len(entries)} files")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--add", nargs="+", metavar="PATH")
    group.add_argument("--verify", action="store_true")
    group.add_argument("--lock", action="store_true")
    args = parser.parse_args()
    if args.add:
        sys.exit(add(args.add))
    sys.exit(verify() if args.verify else lock())


if __name__ == "__main__":
    main()
