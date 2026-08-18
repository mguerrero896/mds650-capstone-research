"""Physical-immutability tripwires (decision 62).

The registry data/FROZEN_ARTIFACTS.json pins every frozen artifact to its
SHA-256 at freeze time. Any physical mutation — by any script, any tool, any
direct filesystem write — fails this suite. Hermetic: every registered path is
git-tracked, so the check runs identically on the hosted runner.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from mds650 import storage

REPO = Path(__file__).resolve().parents[2]
REGISTRY = REPO / "data" / "FROZEN_ARTIFACTS.json"


def _entries() -> list[dict[str, object]]:
    return json.loads(REGISTRY.read_text(encoding="utf-8"))["entries"]  # type: ignore[no-any-return]


def _sha(path: Path) -> str:
    """Same platform-stable digest as scripts/freeze_registry.py: text bytes
    LF-normalized (git blob under .gitattributes eol=lf), parquet raw."""
    data = path.read_bytes()
    if path.suffix != ".parquet":
        data = data.replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


def test_registry_exists_and_is_nonempty() -> None:
    entries = _entries()
    assert len(entries) >= 61, "registry lost entries: append-only discipline violated"
    paths = [str(entry["path"]) for entry in entries]
    assert len(paths) == len(set(paths)), "duplicate registry paths"


def test_every_frozen_artifact_is_physically_intact() -> None:
    mutated = []
    for entry in _entries():
        path = REPO / str(entry["path"])
        if not path.is_file():
            mutated.append(f"MISSING {entry['path']}")
            continue
        if _sha(path) != entry["sha256"]:
            mutated.append(f"MUTATED {entry['path']}")
    assert not mutated, mutated


def test_gate_sidecars_agree_with_registry() -> None:
    """Every results.sha256 sidecar value equals the registered digest of its JSON."""
    registered = {str(entry["path"]): str(entry["sha256"]) for entry in _entries()}
    disagreements = []
    for sidecar in REPO.glob("artifacts/**/*.sha256"):
        artifact = sidecar.with_suffix(".json")
        relative = artifact.relative_to(REPO).as_posix()
        if relative not in registered:
            disagreements.append(f"UNREGISTERED {relative}")
            continue
        sidecar_digest = sidecar.read_text(encoding="utf-8").strip()
        actual = _sha(artifact)
        if actual != registered[relative]:
            disagreements.append(f"REGISTRY_MISMATCH {relative}")
        if sidecar_digest and sidecar_digest != actual:
            # sidecars hash the LF payload string at write time; LF-normalized
            # file bytes must agree — divergence means real content drift
            disagreements.append(f"SIDECAR_MISMATCH {relative}")
    assert not disagreements, disagreements


def test_writer_guard_rejects_frozen_output_paths() -> None:
    frozen_example = REPO / "artifacts" / "b2_confirmation" / "b2_manifest.json"
    with pytest.raises(ValueError, match="FROZEN_ARTIFACT_WRITE_REJECTED"):
        storage.assert_outside_frozen(frozen_example)
    with pytest.raises(ValueError, match="FROZEN_ARTIFACT_WRITE_REJECTED"):
        storage.assert_outside_frozen(REGISTRY)


def test_writer_guard_allows_new_version_paths(tmp_path: Path) -> None:
    allowed = REPO / "artifacts" / "b2_confirmation_delay120" / "new_output.json"
    assert storage.assert_outside_frozen(allowed) == allowed
    assert storage.assert_outside_frozen(tmp_path / "anything.json") is not None


def test_content_addressed_writer_cannot_update(tmp_path: Path) -> None:
    first = storage.write_content_addressed(b"payload-v1", root=tmp_path, protocol_id="p1")
    assert first.name == hashlib.sha256(b"payload-v1").hexdigest() + ".bin"
    again = storage.write_content_addressed(b"payload-v1", root=tmp_path, protocol_id="p1")
    assert again == first  # identical bytes: verified no-op
    second = storage.write_content_addressed(b"payload-v2", root=tmp_path, protocol_id="p1")
    assert second != first  # different bytes: NEW file, never an overwrite
    assert first.read_bytes() == b"payload-v1"
