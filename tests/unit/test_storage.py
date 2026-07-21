from __future__ import annotations

from pathlib import Path

import pytest

from mds650.storage import hash_payload, query_parquet, write_immutable_raw, write_parquet_rows


def test_hash_payload_is_deterministic() -> None:
    assert hash_payload(b'{"rows": []}') == hash_payload(b'{"rows": []}')
    assert len(hash_payload(b"payload")) == 64


def test_write_immutable_raw_keeps_hash_addressed_payload(tmp_path: Path) -> None:
    reference = write_immutable_raw(
        b'{"rows": []}',
        root=tmp_path,
        provider="fmp",
        source_response_id="resp-1",
    )

    assert reference.payload_path.exists()
    assert reference.raw_sha256 == hash_payload(b'{"rows": []}')
    assert reference.payload_path.read_bytes() == b'{"rows": []}'


def test_write_immutable_raw_rejects_changed_replay(tmp_path: Path) -> None:
    write_immutable_raw(b"first", root=tmp_path, provider="fmp", source_response_id="resp-1")

    with pytest.raises(ValueError, match="RAW_PAYLOAD_IMMUTABILITY_VIOLATION"):
        write_immutable_raw(b"second", root=tmp_path, provider="fmp", source_response_id="resp-1")


def test_normalized_rows_round_trip_through_parquet_and_duckdb(tmp_path: Path) -> None:
    path = tmp_path / "bars.parquet"

    write_parquet_rows([{"asset": "SPY", "close": 600.5}], path)

    assert query_parquet(path, "SELECT asset, close FROM read_parquet(?)") == [("SPY", 600.5)]
