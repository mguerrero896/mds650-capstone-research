"""Fail-closed storage configuration and reuse checks for Phase 5."""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from mds650.study_design import canonical_sha256

GIB = 1024**3
MINIMUM_PHASE5_FREE_BYTES = 80 * GIB


@dataclass(frozen=True)
class Phase5StorageConfig:
    """Validated paths and dates for one resumable development batch.

    Parameters
    ----------
    sessions:
        Sorted, unique development dates authorized for this batch.
    excluded_dates:
        Holdout dates that must never enter development acquisition.
    data_root:
        Persistent storage root, normally ``D:/MDS650``.
    minimum_free_bytes:
        Required free-space floor after the projected processing peak.
    projected_peak_additional_bytes:
        Conservative additional bytes needed at peak for the batch.

    Raises
    ------
    ValueError
        If dates are empty, duplicated, unordered, overlap the holdout, or the
        configured safety floor is below 80 GiB.
    """

    sessions: tuple[date, ...]
    excluded_dates: frozenset[date]
    data_root: Path
    minimum_free_bytes: int
    projected_peak_additional_bytes: int

    def __post_init__(self) -> None:
        if not self.sessions:
            raise ValueError("SESSION_ALLOWLIST_EMPTY")
        if tuple(sorted(set(self.sessions))) != self.sessions:
            raise ValueError("SESSION_ALLOWLIST_ORDER_OR_DUPLICATE_INVALID")
        if set(self.sessions) & self.excluded_dates:
            raise ValueError("HOLDOUT_DATE_IN_SESSION_ALLOWLIST")
        if self.minimum_free_bytes < MINIMUM_PHASE5_FREE_BYTES:
            raise ValueError("MINIMUM_FREE_SPACE_BELOW_80_GIB")
        if self.projected_peak_additional_bytes <= 0:
            raise ValueError("PROJECTED_PEAK_BYTES_MUST_BE_POSITIVE")

    @property
    def raw_root(self) -> Path:
        """Return the immutable Full Tape ZIP root."""
        return self.data_root / "raw" / "full_tape"

    @property
    def event_root(self) -> Path:
        """Return the filtered Full Tape Parquet root."""
        return self.data_root / "data" / "option_events"

    @property
    def manifest_root(self) -> Path:
        """Return the resumable per-session manifest root."""
        return self.data_root / "manifests" / "full_tape"

    @property
    def temporary_root(self) -> Path:
        """Return the bounded temporary-processing root."""
        return self.data_root / "tmp"


def build_phase5_storage_config(
    session_manifest: Mapping[str, Any],
    *,
    reused_dates: frozenset[date],
    data_root: Path,
    projected_peak_additional_bytes: int,
) -> Phase5StorageConfig:
    """Derive the exact 55-session acquisition allow-list.

    Parameters
    ----------
    session_manifest:
        Frozen 80/10 manifest generated before provider acquisition.
    reused_dates:
        Twenty-five hash-verified development sessions.
    data_root:
        Persistent Phase 5 data root.
    projected_peak_additional_bytes:
        Conservative batch peak used by :func:`storage_preflight`.

    Returns
    -------
    Phase5StorageConfig
        Validated 55-session configuration with the holdout excluded.

    Raises
    ------
    ValueError
        If the manifest hash/counts are invalid or the reusable set is not the
        exact 25-session subset of development.
    """
    unsigned = {
        key: value for key, value in session_manifest.items() if key != "manifest_sha256"
    }
    if session_manifest.get("manifest_sha256") != canonical_sha256(unsigned):
        raise ValueError("SESSION_MANIFEST_HASH_MISMATCH")
    development = tuple(date.fromisoformat(value) for value in session_manifest["development"])
    holdout = frozenset(date.fromisoformat(value) for value in session_manifest["holdout"])
    if len(development) != 80 or len(holdout) != 10:
        raise ValueError("STUDY_SESSION_COUNT_INVALID")
    if len(reused_dates) != 25 or not reused_dates <= set(development):
        raise ValueError("REUSED_SESSION_COUNT_INVALID")
    missing = tuple(day for day in development if day not in reused_dates)
    if len(missing) != 55:
        raise ValueError("MISSING_DEVELOPMENT_SESSION_COUNT_INVALID")
    return Phase5StorageConfig(
        sessions=missing,
        excluded_dates=holdout,
        data_root=data_root,
        minimum_free_bytes=MINIMUM_PHASE5_FREE_BYTES,
        projected_peak_additional_bytes=projected_peak_additional_bytes,
    )


def storage_preflight(config: Phase5StorageConfig) -> dict[str, Any]:
    """Verify write access and the projected minimum free-space floor.

    Parameters
    ----------
    config:
        Validated Phase 5 storage and batch contract.

    Returns
    -------
    dict[str, Any]
        Sanitized capacity evidence without a personal filesystem path.

    Raises
    ------
    RuntimeError
        If the data root is absent, unwritable, or would fall below the
        configured free-space floor during the projected peak.
    """
    if not config.data_root.is_dir():
        raise RuntimeError("DATA_ROOT_NOT_FOUND")
    usage = shutil.disk_usage(config.data_root)
    projected_minimum = usage.free - config.projected_peak_additional_bytes
    if projected_minimum < config.minimum_free_bytes:
        raise RuntimeError("PROJECTED_MINIMUM_FREE_SPACE_BELOW_FLOOR")
    try:
        with tempfile.NamedTemporaryFile(
            "wb",
            dir=config.data_root,
            prefix=".mds650-write-probe-",
            delete=True,
        ) as handle:
            handle.write(b"MDS650_PHASE5_WRITE_PROBE")
            handle.flush()
    except OSError as error:
        raise RuntimeError("DATA_ROOT_WRITE_PROBE_FAILED") from error
    return {
        "data_root": "MDS650_DATA_ROOT",
        "free_bytes": usage.free,
        "projected_peak_additional_bytes": config.projected_peak_additional_bytes,
        "projected_minimum_free_bytes": projected_minimum,
        "minimum_free_bytes": config.minimum_free_bytes,
        "free_space_pass": True,
        "write_probe_pass": True,
        "authorized_session_count": len(config.sessions),
        "excluded_holdout_count": len(config.excluded_dates),
        "personal_paths_emitted": False,
    }


def sha256_file(path: Path) -> str:
    """Hash a file incrementally without loading it into memory.

    Parameters
    ----------
    path:
        Existing file.

    Returns
    -------
    str
        Lowercase SHA-256 digest.
    """
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_reusable_session(
    raw_path: Path,
    manifest_path: Path,
    expected_sha256: str,
) -> bool:
    """Verify a resumable raw session against both manifest and bytes.

    Parameters
    ----------
    raw_path, manifest_path:
        Candidate immutable archive and its prior PASS checkpoint.
    expected_sha256:
        Previously recorded trusted digest.

    Returns
    -------
    bool
        ``True`` only when all three sources agree; ``False`` when evidence is
        absent and therefore cannot be reused.

    Raises
    ------
    RuntimeError
        If present evidence is malformed or any hash differs.
    """
    if not raw_path.exists() or not manifest_path.exists():
        return False
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise RuntimeError("REUSABLE_MANIFEST_INVALID") from error
    if not isinstance(manifest, dict) or manifest.get("status") != "PASS":
        raise RuntimeError("REUSABLE_MANIFEST_NOT_PASS")
    if manifest.get("sha256") != expected_sha256:
        raise RuntimeError("REUSABLE_MANIFEST_HASH_MISMATCH")
    if sha256_file(raw_path) != expected_sha256:
        raise RuntimeError("REUSABLE_RAW_HASH_MISMATCH")
    return True


def copy_verified_file(
    source: Path,
    destination: Path,
    expected_sha256: str,
) -> dict[str, Any]:
    """Copy retained evidence once and verify both ends by SHA-256.

    Parameters
    ----------
    source, destination:
        Existing source evidence and persistent destination.
    expected_sha256:
        Trusted digest recorded by the source manifest.

    Returns
    -------
    dict[str, Any]
        Sanitized status, byte count and verified digest.

    Raises
    ------
    RuntimeError
        If the source, an existing destination, or the copied temporary file
        differs from the trusted digest.
    """
    if sha256_file(source) != expected_sha256:
        raise RuntimeError("SOURCE_HASH_MISMATCH")
    if destination.exists():
        if sha256_file(destination) != expected_sha256:
            raise RuntimeError("DESTINATION_HASH_MISMATCH")
        return {
            "status": "REUSED_VERIFIED_DESTINATION",
            "bytes": destination.stat().st_size,
            "sha256": expected_sha256,
        }

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part")
    if temporary.exists():
        temporary.unlink()
    shutil.copy2(source, temporary)
    if sha256_file(temporary) != expected_sha256:
        temporary.unlink()
        raise RuntimeError("COPIED_FILE_HASH_MISMATCH")
    temporary.replace(destination)
    return {
        "status": "COPIED_AND_VERIFIED",
        "bytes": destination.stat().st_size,
        "sha256": expected_sha256,
    }
