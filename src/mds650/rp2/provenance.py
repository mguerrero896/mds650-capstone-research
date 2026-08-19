"""Provenance for Research Program v2 artifacts.

A canonical-JSON hash of a result document proves the *document* was not edited. It says
nothing about the file the numbers came from: two runs over different data can produce the
same document if the numbers round the same way, and a silently mutated input leaves no
trace at all.

This module records what a reader needs to reproduce or refute a number: the byte SHA-256
of every input file, its schema, its row count, the time span it covers, and which provider
it came from. Content mutation changes the byte hash even when the row count and schema are
untouched, which is exactly the failure a shape-only check misses.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import polars as pl

CHUNK_BYTES: Final = 1 << 20
#: Providers whose data may appear in an input. Anything else must be declared explicitly
#: rather than silently recorded as unknown.
KNOWN_PROVIDERS: Final[frozenset[str]] = frozenset(
    {"fmp", "massive", "unusual_whales", "derived", "synthetic"}
)


def sha256_file(path: Path, *, chunk_bytes: int = CHUNK_BYTES) -> str:
    """Byte SHA-256 of a file, streamed so a multi-gigabyte input is not loaded."""

    if chunk_bytes <= 0:
        raise ValueError("RP2_PROVENANCE_CHUNK_INVALID")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_bytes):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True, slots=True)
class InputRecord:
    """One input file, described well enough to detect any change to it."""

    path: str
    provider: str
    sha256: str
    bytes: int
    rows: int | None
    columns: tuple[str, ...] | None
    schema_sha256: str | None
    time_column: str | None
    time_min: str | None
    time_max: str | None


def _schema_digest(columns: Iterable[tuple[str, str]]) -> str:
    payload = json.dumps(sorted(columns), separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def describe_input(path: Path, *, provider: str, time_column: str | None = None) -> InputRecord:
    """Byte hash plus schema, row count and time span for one input file.

    Parquet inputs are inspected for schema and span; any other file is recorded by byte
    hash and size alone, which is still enough to detect mutation.
    """

    if provider not in KNOWN_PROVIDERS:
        raise ValueError(f"RP2_PROVENANCE_UNKNOWN_PROVIDER:{provider}")
    if not path.is_file():
        raise FileNotFoundError(f"RP2_PROVENANCE_INPUT_MISSING:{path}")

    rows: int | None = None
    columns: tuple[str, ...] | None = None
    schema_digest: str | None = None
    time_min: str | None = None
    time_max: str | None = None
    if path.suffix == ".parquet":
        # Scanned, not loaded: a panel is tens of megabytes and only its schema, its height
        # and one column's extremes are needed to describe it.
        scan = pl.scan_parquet(path)
        schema = scan.collect_schema()
        columns = tuple(schema.names())
        schema_digest = _schema_digest((name, str(dtype)) for name, dtype in schema.items())
        rows = int(scan.select(pl.len()).collect().item())
        if time_column and time_column in columns:
            extremes = scan.select(
                pl.col(time_column).min().alias("low"), pl.col(time_column).max().alias("high")
            ).collect()
            low, high = extremes["low"][0], extremes["high"][0]
            if low is not None and high is not None:
                time_min, time_max = str(low), str(high)
    return InputRecord(
        path=path.as_posix(),
        provider=provider,
        sha256=sha256_file(path),
        bytes=path.stat().st_size,
        rows=rows,
        columns=columns,
        schema_sha256=schema_digest,
        time_column=time_column,
        time_min=time_min,
        time_max=time_max,
    )


def provenance_block(
    inputs: Mapping[str, InputRecord], *, run_id: str, code_commit: str | None = None
) -> dict[str, object]:
    """The block every RP2-v2 artifact embeds under ``provenance``."""

    records = {name: asdict(record) for name, record in sorted(inputs.items())}
    payload = json.dumps(records, sort_keys=True, separators=(",", ":"))
    return {
        "run_id": run_id,
        "code_commit": code_commit,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "inputs": records,
        "inputs_sha256": hashlib.sha256(payload.encode("utf-8")).hexdigest(),
    }


def verify_inputs(inputs: Mapping[str, InputRecord]) -> list[str]:
    """Re-hash every recorded input and return the names that no longer match.

    An empty list means every input is byte-identical to what was recorded. A non-empty
    list is a hard failure for the caller, not a warning.
    """

    drifted: list[str] = []
    for name, record in inputs.items():
        path = Path(record.path)
        if not path.is_file() or sha256_file(path) != record.sha256:
            drifted.append(name)
    return drifted
