"""Provenance: content mutation must be detected, shape checks alone must not suffice."""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from mds650.rp2.provenance import (
    describe_input,
    provenance_block,
    sha256_file,
    verify_inputs,
)


def _write(path: Path, values: list[float]) -> None:
    pl.DataFrame(
        {
            "asset": ["AAPL"] * len(values),
            "session_date": ["2026-06-15"] * len(values),
            "close": values,
        }
    ).write_parquet(path)


def test_content_mutation_changes_the_hash_even_at_identical_shape(tmp_path: Path) -> None:
    """The failure a row-count or schema check cannot see.

    Same columns, same dtypes, same row count, one different value. A shape-only
    provenance record calls these two files identical.
    """

    first, second = tmp_path / "a.parquet", tmp_path / "b.parquet"
    _write(first, [100.0, 101.0, 102.0])
    _write(second, [100.0, 101.0, 102.5])

    a = describe_input(first, provider="fmp")
    b = describe_input(second, provider="fmp")
    assert a.rows == b.rows
    assert a.columns == b.columns
    assert a.schema_sha256 == b.schema_sha256
    assert a.sha256 != b.sha256


def test_schema_digest_moves_when_a_column_is_added(tmp_path: Path) -> None:
    path = tmp_path / "a.parquet"
    _write(path, [100.0])
    before = describe_input(path, provider="fmp")
    pl.DataFrame(
        {"asset": ["AAPL"], "session_date": ["2026-06-15"], "close": [100.0], "extra": [1.0]}
    ).write_parquet(path)
    after = describe_input(path, provider="fmp")
    assert before.schema_sha256 != after.schema_sha256
    assert after.columns is not None and "extra" in after.columns


def test_time_span_is_recorded_when_a_time_column_is_named(tmp_path: Path) -> None:
    path = tmp_path / "a.parquet"
    pl.DataFrame(
        {"session_date": ["2026-06-15", "2026-06-16", "2026-06-17"], "close": [1.0, 2.0, 3.0]}
    ).write_parquet(path)
    record = describe_input(path, provider="fmp", time_column="session_date")
    assert record.time_min == "2026-06-15"
    assert record.time_max == "2026-06-17"


def test_an_undeclared_provider_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "a.parquet"
    _write(path, [1.0])
    with pytest.raises(ValueError, match="RP2_PROVENANCE_UNKNOWN_PROVIDER"):
        describe_input(path, provider="mystery_vendor")


def test_a_missing_input_is_refused_rather_than_recorded_as_empty(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="RP2_PROVENANCE_INPUT_MISSING"):
        describe_input(tmp_path / "absent.parquet", provider="fmp")


def test_verify_detects_a_file_changed_after_it_was_recorded(tmp_path: Path) -> None:
    path = tmp_path / "a.parquet"
    _write(path, [100.0, 101.0])
    inputs = {"bars": describe_input(path, provider="fmp")}
    assert verify_inputs(inputs) == []

    _write(path, [100.0, 999.0])
    assert verify_inputs(inputs) == ["bars"]

    path.unlink()
    assert verify_inputs(inputs) == ["bars"]


def test_provenance_block_is_deterministic_and_input_sensitive(tmp_path: Path) -> None:
    path = tmp_path / "a.parquet"
    _write(path, [1.0])
    inputs = {"bars": describe_input(path, provider="fmp")}
    first = provenance_block(inputs, run_id="r1", code_commit="abc123")
    second = provenance_block(inputs, run_id="r1", code_commit="abc123")
    assert first["inputs_sha256"] == second["inputs_sha256"]
    assert first["run_id"] == "r1"

    _write(path, [2.0])
    changed = provenance_block(
        {"bars": describe_input(path, provider="fmp")}, run_id="r1", code_commit="abc123"
    )
    assert changed["inputs_sha256"] != first["inputs_sha256"]


def test_sha256_file_rejects_a_non_positive_chunk(tmp_path: Path) -> None:
    path = tmp_path / "a.parquet"
    _write(path, [1.0])
    with pytest.raises(ValueError, match="RP2_PROVENANCE_CHUNK_INVALID"):
        sha256_file(path, chunk_bytes=0)
