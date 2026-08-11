"""Contract tests for the hash-bound canonical reporting runner."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import polars as pl
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import report_canonical_validation as report  # noqa: E402


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_block(tmp_path: Path, *, expected_hash: str | None = None) -> tuple[Path, Path]:
    """Create one compact fake prediction block with a manifest and summary."""

    data_root = tmp_path / "data"
    output_root = tmp_path / "output"
    data_block = data_root / "canonical_validation_v1" / "phase6"
    summary_block = output_root / "phase6"
    data_block.mkdir(parents=True)
    summary_block.mkdir(parents=True)
    prediction_path = data_block / "predictions.parquet"
    pl.DataFrame({"origin_id": ["a"], "forecast": [0.01], "rv30": [0.02]}).write_parquet(
        prediction_path
    )
    digest = _sha256(prediction_path)
    (data_block / "manifest.json").write_text(
        json.dumps(
            {
                "status": "PASS_CANONICAL_VALIDATION",
                "output_hashes": {
                    "predictions.parquet": expected_hash if expected_hash is not None else digest
                },
            }
        ),
        encoding="utf-8",
    )
    (summary_block / "summary.json").write_text(
        json.dumps(
            {"status": "PASS_CANONICAL_VALIDATION", "prediction_sha256": digest}
        ),
        encoding="utf-8",
    )
    return data_root, output_root


def test_reporting_runner_reads_only_hash_verified_predictions(tmp_path: Path) -> None:
    """Report inputs must match both the data manifest and repository summary."""

    data_root, output_root = _write_block(tmp_path)

    result = report.load_hash_verified_predictions(
        data_root=data_root, output_root=output_root, block="phase6"
    )

    assert result.get_column("block").unique().to_list() == ["phase6"]


def test_reporting_runner_refuses_mismatched_prediction_hash(tmp_path: Path) -> None:
    """A stale or replaced forecast file cannot enter the report."""

    data_root, output_root = _write_block(tmp_path, expected_hash="0" * 64)

    with pytest.raises(RuntimeError, match="CANONICAL_REPORT_INPUT_HASH_MISMATCH"):
        report.load_hash_verified_predictions(
            data_root=data_root, output_root=output_root, block="phase6"
        )
