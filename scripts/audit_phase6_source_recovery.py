"""Recover and verify the exact frozen Phase 6 source objects.

This script makes only already-validated Git blob objects reachable through local refs.  It
never rewrites Phase 6 evidence or emits local filesystem paths in its JSON manifest.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any

FROZEN_BLOBS: Mapping[str, str] = {
    "src/mds650/phase6.py": "eae0ff2075a84a94c1e15896fcdfa8341391969e",
    "scripts/finalize_phase6_evidence.py": "b6cd4c30cb4d9c696b4a50438c3154ddf465de2a",
}
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_GIT_OBJECT = re.compile(r"^[0-9a-f]{40}$")


def _sha256(payload: bytes) -> str:
    """Return a lower-case SHA-256 digest for bytes.

    Parameters
    ----------
    payload
        Exact bytes to hash.

    Returns
    -------
    str
        Hexadecimal SHA-256 digest.
    """

    return hashlib.sha256(payload).hexdigest()


def _load_frozen_hashes(evidence_root: Path) -> Mapping[str, str]:
    """Load the frozen source-hash contract from external evidence.

    Parameters
    ----------
    evidence_root
        Read-only root containing ``artifacts/phase6/method_freeze.json``.

    Returns
    -------
    Mapping[str, str]
        Relative source paths mapped to frozen SHA-256 digests.

    Raises
    ------
    RuntimeError
        If the freeze artifact is missing, malformed, or lacks valid hashes.
    """

    freeze_path = evidence_root / "artifacts" / "phase6" / "method_freeze.json"
    try:
        payload: Any = json.loads(freeze_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("PHASE6_METHOD_FREEZE_UNAVAILABLE") from exc
    hashes = payload.get("source_code_hashes") if isinstance(payload, dict) else None
    if not isinstance(hashes, dict):
        raise RuntimeError("PHASE6_SOURCE_HASH_CONTRACT_INVALID")
    normalized = {str(name): str(value) for name, value in hashes.items()}
    if any(not _SHA256.fullmatch(value) for value in normalized.values()):
        raise RuntimeError("PHASE6_SOURCE_HASH_CONTRACT_INVALID")
    return normalized


def _read_git_blob(repository_root: Path, blob: str) -> bytes:
    """Read a validated Git blob without exposing command diagnostics.

    Parameters
    ----------
    repository_root
        Repository or linked worktree whose Git object database holds the blob.
    blob
        Forty-character Git object identifier.

    Returns
    -------
    bytes
        Exact blob content.

    Raises
    ------
    RuntimeError
        If the object identifier is invalid or the object cannot be read as a blob.
    """

    if not _GIT_OBJECT.fullmatch(blob):
        raise RuntimeError("PHASE6_FROZEN_BLOB_IDENTIFIER_INVALID")
    result = subprocess.run(
        ["git", "-C", str(repository_root), "cat-file", "blob", blob],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError("PHASE6_FROZEN_BLOB_UNAVAILABLE")
    return result.stdout


def _create_ref(repository_root: Path, artifact: str, blob: str) -> str:
    """Create a local, content-addressed ref for a verified source blob.

    Parameters
    ----------
    repository_root
        Repository or linked worktree that owns the Git object database.
    artifact
        Repository-relative source artifact name.
    blob
        Verified Git blob object identifier.

    Returns
    -------
    str
        Local Git ref name.

    Raises
    ------
    RuntimeError
        If Git cannot install the local evidence ref.
    """

    ref = "refs/mds650/phase6-frozen/" + artifact.replace("/", "--")
    result = subprocess.run(
        ["git", "-C", str(repository_root), "update-ref", ref, blob],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError("PHASE6_FROZEN_REF_WRITE_FAILED")
    return ref


def audit_phase6_source_recovery(
    *,
    evidence_root: Path,
    repository_root: Path,
    frozen_blobs: Mapping[str, str] | None = None,
    create_refs: bool,
) -> dict[str, object]:
    """Verify and preserve exact frozen Phase 6 source blobs.

    The external evidence root is read-only.  Every selected blob is compared byte-for-byte to
    the method-freeze source hash before any local evidence ref is created.  The returned object
    deliberately stores artifact-relative names and hashes only; it contains no filesystem path.

    Parameters
    ----------
    evidence_root
        Root containing the immutable Phase 6 method-freeze artifact.
    repository_root
        Worktree with access to the identified Git objects.
    frozen_blobs
        Optional artifact-to-blob mapping.  Defaults to the two historical mismatches recovered
        during the forensic audit.
    create_refs
        Whether verified blobs should be protected from garbage collection with local Git refs.

    Returns
    -------
    dict[str, object]
        Sanitized recovery manifest with a PASS status and one item per verified blob.

    Raises
    ------
    RuntimeError
        If a freeze hash is absent, a blob cannot be read, or a recovered byte hash mismatches.
    """

    expected_hashes = _load_frozen_hashes(evidence_root)
    selected = dict(FROZEN_BLOBS if frozen_blobs is None else frozen_blobs)
    records: list[dict[str, object]] = []
    for artifact, blob in sorted(selected.items()):
        expected = expected_hashes.get(artifact)
        if expected is None:
            raise RuntimeError("PHASE6_SOURCE_HASH_NOT_FROZEN")
        recovered = _read_git_blob(repository_root, blob)
        recovered_hash = _sha256(recovered)
        if recovered_hash != expected:
            raise RuntimeError("PHASE6_FROZEN_SOURCE_RECOVERY_FAILED")
        current_path = repository_root / artifact
        current_hash = _sha256(current_path.read_bytes()) if current_path.is_file() else None
        records.append(
            {
                "artifact": artifact,
                "expected_sha256": expected,
                "recovered_sha256": recovered_hash,
                "current_sha256": current_hash,
                "frozen_blob": blob,
                "recovery_ref": None,
                "status": "PASS",
            }
        )

    if create_refs:
        for record in records:
            artifact = str(record["artifact"])
            blob = str(record["frozen_blob"])
            record["recovery_ref"] = _create_ref(repository_root, artifact, blob)

    return {
        "schema_version": "1.0",
        "status": "PASS",
        "scope": "FROZEN_SOURCE_MISMATCH_RECOVERY_ONLY",
        "audited_source_count": len(records),
        "artifacts": records,
        "personal_paths_emitted": False,
        "secret_values_emitted": False,
    }


def _parse_args() -> argparse.Namespace:
    """Parse command-line arguments for source recovery."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--evidence-root",
        type=Path,
        default=Path(os.environ["MDS650_EVIDENCE_ROOT"])
        if "MDS650_EVIDENCE_ROOT" in os.environ
        else None,
    )
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/canonical_validation_v1/phase6_source_recovery.json"),
    )
    parser.add_argument("--no-create-refs", action="store_true")
    return parser.parse_args()


def main() -> None:
    """Write a sanitized Phase 6 frozen-source recovery manifest.

    Raises
    ------
    SystemExit
        If the external evidence root is not explicitly supplied.
    """

    args = _parse_args()
    if args.evidence_root is None:
        raise SystemExit("MDS650_EVIDENCE_ROOT_REQUIRED")
    payload = audit_phase6_source_recovery(
        evidence_root=args.evidence_root,
        repository_root=args.repository_root,
        create_refs=not args.no_create_refs,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
