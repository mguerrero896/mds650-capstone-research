"""Build a sanitized SHA-256 index for canonical RV30 validation evidence."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import uuid
from collections.abc import Sequence
from pathlib import Path

_REPOSITORY_ARTIFACTS = (
    Path("artifacts/canonical_validation_v1/phase6_source_recovery.json"),
    Path("artifacts/canonical_validation_v1/phase6/causal_audit.parquet"),
    Path("artifacts/canonical_validation_v1/phase6/model_variant_ledger.json"),
    Path("artifacts/canonical_validation_v1/phase6/origin_set_audit.json"),
    Path("artifacts/canonical_validation_v1/phase6/summary.json"),
    Path("artifacts/canonical_validation_v1/independent_replication/causal_audit.parquet"),
    Path("artifacts/canonical_validation_v1/independent_replication/model_variant_ledger.json"),
    Path("artifacts/canonical_validation_v1/independent_replication/origin_set_audit.json"),
    Path("artifacts/canonical_validation_v1/independent_replication/summary.json"),
    Path("artifacts/canonical_validation_v1/metrics.json"),
    Path("artifacts/canonical_validation_v1/contrasts.json"),
    Path("artifacts/canonical_validation_v1/calibration.json"),
    Path("artifacts/canonical_validation_v1/redundancy.json"),
    Path("artifacts/canonical_validation_v1/stability.parquet"),
    Path("artifacts/canonical_validation_v1/report_manifest.json"),
)
_DATA_ARTIFACTS = (
    Path("canonical_validation_v1/phase6/predictions.parquet"),
    Path("canonical_validation_v1/phase6/manifest.json"),
    Path("canonical_validation_v1/independent_replication/predictions.parquet"),
    Path("canonical_validation_v1/independent_replication/manifest.json"),
)
_FIELDNAMES = (
    "logical_path",
    "category",
    "bytes",
    "sha256",
    "personal_paths_emitted",
    "secret_values_emitted",
)


def _sha256(path: Path) -> str:
    """Return SHA-256 for one required regular file."""

    if not path.is_file():
        raise RuntimeError("CANONICAL_EVIDENCE_INDEX_INPUT_UNAVAILABLE")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _relative_paths(paths: Sequence[Path], root: Path) -> tuple[Path, ...]:
    """Reject absolute or escaping paths before they can enter a manifest."""

    relative: list[Path] = []
    for path in paths:
        if path.is_absolute() or ".." in path.parts:
            raise RuntimeError("CANONICAL_EVIDENCE_INDEX_PATH_INVALID")
        resolved = (root / path).resolve()
        if not resolved.is_relative_to(root.resolve()):
            raise RuntimeError("CANONICAL_EVIDENCE_INDEX_PATH_INVALID")
        relative.append(path)
    return tuple(relative)


def build_evidence_records(
    *,
    repository_root: Path,
    data_root: Path,
    repository_artifacts: Sequence[Path] = _REPOSITORY_ARTIFACTS,
    data_artifacts: Sequence[Path] = _DATA_ARTIFACTS,
) -> list[dict[str, str | int | bool]]:
    """Hash canonical evidence while emitting only logical, portable locations.

    Parameters
    ----------
    repository_root
        Repository root containing compact sanitized artifacts.
    data_root
        External Samsung-backed root containing derived forecast Parquet and manifests.
    repository_artifacts
        Relative repository artifact paths to include.
    data_artifacts
        Relative data-root artifact paths to include.

    Returns
    -------
    list[dict[str, str | int | bool]]
        Deterministically ordered records with logical path, category, bytes, SHA-256 and explicit
        sanitization flags.

    Raises
    ------
    RuntimeError
        If a root/path is invalid or a required file is absent.

    Notes
    -----
    The index never emits absolute paths or provider/commercial contents. External data use the
    portable ``MDS650_DATA_ROOT/`` prefix instead of a workstation drive letter.

    Examples
    --------
    ``tests/contract/test_canonical_evidence_index.py`` verifies that data-root paths remain
    logical and do not expose a user profile path.
    """

    if not repository_root.is_dir() or not data_root.is_dir():
        raise RuntimeError("CANONICAL_EVIDENCE_INDEX_ROOT_INVALID")
    repository_paths = _relative_paths(repository_artifacts, repository_root)
    data_paths = _relative_paths(data_artifacts, data_root)
    records: list[dict[str, str | int | bool]] = []
    for relative in sorted(repository_paths, key=lambda item: item.as_posix()):
        path = repository_root / relative
        records.append(
            {
                "logical_path": relative.as_posix(),
                "category": "repository_artifact",
                "bytes": path.stat().st_size,
                "sha256": _sha256(path),
                "personal_paths_emitted": False,
                "secret_values_emitted": False,
            }
        )
    for relative in sorted(data_paths, key=lambda item: item.as_posix()):
        path = data_root / relative
        records.append(
            {
                "logical_path": f"MDS650_DATA_ROOT/{relative.as_posix()}",
                "category": "derived_forecast_data",
                "bytes": path.stat().st_size,
                "sha256": _sha256(path),
                "personal_paths_emitted": False,
                "secret_values_emitted": False,
            }
        )
    return records


def _write_csv_if_equal(path: Path, records: Sequence[dict[str, str | int | bool]]) -> str:
    """Persist a deterministic CSV index without overwriting different evidence."""

    import io

    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=_FIELDNAMES, lineterminator="\n")
    writer.writeheader()
    writer.writerows(records)
    data = stream.getvalue().encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != data:
            raise RuntimeError("CANONICAL_EVIDENCE_INDEX_OUTPUT_CONFLICT")
        return _sha256(path)
    temporary = path.with_name(path.name + f".tmp-{uuid.uuid4().hex}")
    temporary.write_bytes(data)
    temporary.rename(path)
    return _sha256(path)


def _parse_args() -> argparse.Namespace:
    """Parse offline evidence-index arguments."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--data-root",
        type=Path,
        default=Path(os.environ.get("MDS650_DATA_ROOT", r"D:\\MDS650")),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/canonical_validation_v1/evidence_index.csv"),
    )
    return parser.parse_args()


def main() -> None:
    """Create the portable evidence index and print its sanitized status."""

    args = _parse_args()
    records = build_evidence_records(repository_root=args.repository_root, data_root=args.data_root)
    digest = _write_csv_if_equal(args.output, records)
    print(
        json.dumps(
            {
                "status": "PASS_CANONICAL_EVIDENCE_INDEX",
                "records": len(records),
                "sha256": digest,
                "personal_paths_emitted": False,
                "secret_values_emitted": False,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
