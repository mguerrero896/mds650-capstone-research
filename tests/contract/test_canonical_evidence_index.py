"""Contracts for the sanitized canonical evidence index."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import build_canonical_evidence_index as indexer  # noqa: E402


def test_index_uses_logical_data_root_without_personal_paths(tmp_path: Path) -> None:
    """External data evidence is hashable but emits no workstation path."""

    repository = tmp_path / "repository"
    data = tmp_path / "data"
    artifact = repository / "artifacts" / "canonical_validation_v1" / "metrics.json"
    prediction = data / "canonical_validation_v1" / "phase6" / "predictions.parquet"
    artifact.parent.mkdir(parents=True)
    prediction.parent.mkdir(parents=True)
    artifact.write_text("{}\n", encoding="utf-8")
    prediction.write_bytes(b"parquet-like")

    records = indexer.build_evidence_records(
        repository_root=repository,
        data_root=data,
        repository_artifacts=(artifact.relative_to(repository),),
        data_artifacts=(prediction.relative_to(data),),
    )

    assert [record["logical_path"] for record in records] == [
        "artifacts/canonical_validation_v1/metrics.json",
        "MDS650_DATA_ROOT/canonical_validation_v1/phase6/predictions.parquet",
    ]
    assert all("Users" not in str(record) for record in records)
    assert all(record["secret_values_emitted"] is False for record in records)
