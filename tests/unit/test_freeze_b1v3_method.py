"""Artifact safety checks for the B1v3 method-freeze command."""

from __future__ import annotations

import sys
from pathlib import Path

import polars as pl
import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from freeze_b1v3_method import (  # noqa: E402
    _write_json_if_identical,
    _write_parquet_if_identical,
)


def test_method_freeze_writers_are_idempotent_and_fail_on_conflict(
    tmp_path: Path,
) -> None:
    json_path = tmp_path / "freeze.json"
    parquet_path = tmp_path / "training.parquet"
    frame = pl.DataFrame({"origin_id": ["a", "b"], "rv30": [0.1, 0.2]})

    first_json = _write_json_if_identical(json_path, {"status": "PASS"})
    first_parquet = _write_parquet_if_identical(parquet_path, frame)

    assert _write_json_if_identical(json_path, {"status": "PASS"}) == first_json
    assert _write_parquet_if_identical(parquet_path, frame) == first_parquet
    with pytest.raises(ValueError, match="B1V3_METHOD_OUTPUT_CONFLICT"):
        _write_json_if_identical(json_path, {"status": "FAIL"})
    with pytest.raises(ValueError, match="B1V3_METHOD_OUTPUT_CONFLICT"):
        _write_parquet_if_identical(
            parquet_path,
            pl.DataFrame({"origin_id": ["c"], "rv30": [0.3]}),
        )


def test_method_freeze_json_writer_rejects_paths_and_secrets(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="B1V3_METHOD_OUTPUT_HYGIENE_INVALID"):
        _write_json_if_identical(
            tmp_path / "unsafe.json",
            {"path": "D:/MDS650/private", "apiKey": "never"},
        )
