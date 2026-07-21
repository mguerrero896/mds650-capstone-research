"""Immutable raw-response storage and provenance references."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb
import polars as pl


@dataclass(frozen=True, slots=True)
class RawPayloadReference:
    """Hash-addressed reference to a raw provider response stored outside Git."""

    source_response_id: str
    provider: str
    raw_sha256: str
    payload_path: Path


def hash_payload(payload: bytes) -> str:
    """Return the lowercase SHA-256 digest of immutable raw bytes.

    Parameters
    ----------
    payload:
        Exact bytes returned by a provider, before parsing or normalization.

    Returns
    -------
    str
        64-character lowercase hexadecimal SHA-256 digest.

    Examples
    --------
    ``hash_payload(b"ok")`` returns a deterministic digest suitable for a manifest.
    """
    return hashlib.sha256(payload).hexdigest()


def write_immutable_raw(
    payload: bytes,
    *,
    root: Path,
    provider: str,
    source_response_id: str,
) -> RawPayloadReference:
    """Persist a raw response once and return its provenance reference.

    Parameters
    ----------
    payload:
        Exact raw response bytes.
    root:
        Local restricted raw-data directory, never a Git-tracked output path.
    provider, source_response_id:
        Safe path components identifying the source response.

    Returns
    -------
    RawPayloadReference
        Provider, source identifier, digest, and persisted path.

    Raises
    ------
    ValueError
        If a response identifier would escape ``root`` or an existing response
        contains different bytes.
    OSError
        If the filesystem cannot create or write the bounded raw-data path.
    """
    _validate_component(provider, "PROVIDER_PATH_INVALID")
    _validate_component(source_response_id, "SOURCE_RESPONSE_PATH_INVALID")
    destination = root / provider / source_response_id / "payload.bin"
    digest = hash_payload(payload)
    if destination.exists():
        if destination.read_bytes() != payload:
            raise ValueError("RAW_PAYLOAD_IMMUTABILITY_VIOLATION")
        return RawPayloadReference(source_response_id, provider, digest, destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(payload)
    return RawPayloadReference(source_response_id, provider, digest, destination)


def _validate_component(value: str, error_code: str) -> None:
    if not value or value in {".", ".."} or any(part in {".", ".."} for part in Path(value).parts):
        raise ValueError(error_code)


def write_parquet_rows(rows: Sequence[Mapping[str, object]], path: Path) -> Path:
    """Write normalized rows to a bounded Parquet table.

    Parameters
    ----------
    rows:
        JSON-like normalized records. Empty output is rejected to avoid an
        untyped artifact that could be mistaken for a valid pilot table.
    path:
        Destination path under the caller-controlled normalized-data directory.

    Returns
    -------
    Path
        The written Parquet path.

    Raises
    ------
    ValueError
        If ``rows`` is empty.
    OSError
        If the destination cannot be created.
    """
    if not rows:
        raise ValueError("PARQUET_ROWS_EMPTY")
    path.parent.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(list(rows), strict=False).write_parquet(path)
    return path


def query_parquet(path: Path, sql: str) -> list[tuple[Any, ...]]:
    """Run a read-oriented DuckDB query against one Parquet file.

    Parameters
    ----------
    path:
        Existing Parquet file.
    sql:
        DuckDB SQL using ``?`` for the file path, e.g.
        ``SELECT * FROM read_parquet(?)``.

    Returns
    -------
    list[tuple[Any, ...]]
        Deterministic query rows in DuckDB order.
    """
    with duckdb.connect(database=":memory:") as connection:
        return [tuple(row) for row in connection.execute(sql, [str(path)]).fetchall()]
