from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import run_canonical_validation as runner  # noqa: E402


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_runner_reuses_hash_verified_output(tmp_path: Path) -> None:
    block_output = tmp_path / "phase6"
    block_output.mkdir()
    predictions = block_output / "predictions.parquet"
    predictions.write_bytes(b"canonical-predictions")
    (block_output / "manifest.json").write_text(
        json.dumps(
            {
                "status": "PASS_CANONICAL_VALIDATION",
                "output_hashes": {"predictions.parquet": _sha256(predictions)},
            }
        ),
        encoding="utf-8",
    )

    result = runner.reuse_hash_verified_block(block_output)

    assert result == {
        "status": "REUSED_HASH_VERIFIED",
        "predictions_sha256": _sha256(predictions),
    }


def test_runner_refuses_corrupt_existing_output(tmp_path: Path) -> None:
    block_output = tmp_path / "phase6"
    block_output.mkdir()
    (block_output / "predictions.parquet").write_bytes(b"changed")
    (block_output / "manifest.json").write_text(
        json.dumps(
            {
                "status": "PASS_CANONICAL_VALIDATION",
                "output_hashes": {"predictions.parquet": "0" * 64},
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="CANONICAL_OUTPUT_HASH_MISMATCH"):
        runner.reuse_hash_verified_block(block_output)


def test_runner_rejects_evidence_root_equal_to_output_root(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="CANONICAL_EVIDENCE_ROOT_INVALID"):
        runner.validate_roots(
            evidence_root=tmp_path,
            data_root=tmp_path / "data",
            output_root=tmp_path,
        )
