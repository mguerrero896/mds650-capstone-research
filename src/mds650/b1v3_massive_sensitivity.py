"""Materialize Massive shifted-cutoff B1v3 attempts from local raw caches.

The implementation reuses the independently audited v2.1 cache-envelope,
pagination, quote ordering and IV inversion primitives.  It performs no network
request and reads no RV30, prediction, loss, QLIKE or result field.
"""

from __future__ import annotations

import math
import os
import tempfile
from collections import defaultdict
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

import mds650.provider_timing_v21 as timing
from mds650.b1v3_confirmation import sha256_file

_CUTOFFS: Final[frozenset[int]] = frozenset({0, 60, 300})
_UPDATED_TYPES: Final[Mapping[str, pa.DataType]] = {
    "sip_timestamp": pa.int64(),
    "sequence_number": pa.int64(),
    "bid": pa.float64(),
    "ask": pa.float64(),
    "midpoint": pa.float64(),
    "relative_spread": pa.float64(),
    "quote_age_seconds": pa.float64(),
    "iv_success": pa.bool_(),
    "iv": pa.float64(),
    "failure_reason": pa.string(),
    "quote_cutoff_seconds": pa.int64(),
}
_REQUIRED_IDENTITY_COLUMNS: Final[frozenset[str]] = frozenset(
    {
        "asset",
        "session_date",
        "contract",
        "source_request_hash",
        "forecast_origin_ns",
        "spot",
        "strike",
        "dte",
        "rate",
        "dividend_yield",
        "option_type",
    }
)
_FORBIDDEN_INPUT_TOKENS: Final[tuple[str, ...]] = (
    "rv30",
    "qlike",
    "prediction",
    "predicted",
    "outcome",
    "residual",
    "loss",
    "model_result",
)


def reselected_attempt_row(
    row: Mapping[str, Any],
    *,
    quote: tuple[int, int, float, float] | None,
    cutoff_seconds: int,
) -> dict[str, Any]:
    """Replace one attempt's quote and IV at an exact shifted cutoff.

    Parameters
    ----------
    row:
        Target-free origin/contract attempt containing spot, strike, DTE, rate,
        dividend and option type.
    quote:
        Last validated ``(sip_timestamp, sequence_number, bid, ask)`` at or
        before the shifted cutoff, or ``None`` when no quote exists.
    cutoff_seconds:
        Registered source-time shift: 0, 60 or 300 seconds.

    Returns
    -------
    dict[str, Any]
        Original attempt metadata with quote, spread, IV and cutoff identity
        recomputed.  No earlier valid quote replaces an invalid last quote.

    Raises
    ------
    ValueError
        If the cutoff is unregistered, the origin is invalid or a future quote
        is supplied.
    """
    if cutoff_seconds not in _CUTOFFS:
        raise ValueError("B1V3_SENSITIVITY_CUTOFF_INVALID")
    origin_ns = row.get("forecast_origin_ns")
    if not isinstance(origin_ns, int) or origin_ns <= 0:
        raise ValueError("B1V3_SENSITIVITY_ORIGIN_INVALID")
    cutoff_ns = origin_ns - cutoff_seconds * timing.NANOSECONDS_PER_SECOND
    output = dict(row)
    output["quote_cutoff_seconds"] = cutoff_seconds
    if quote is None:
        output.update(
            {
                "sip_timestamp": None,
                "sequence_number": None,
                "bid": None,
                "ask": None,
                "midpoint": None,
                "relative_spread": None,
                "quote_age_seconds": None,
                "iv_success": False,
                "iv": None,
                "failure_reason": "NO_QUOTE_AT_OR_BEFORE_CUTOFF",
            }
        )
        return output
    sip_timestamp, sequence_number, bid, ask = quote
    if sip_timestamp > cutoff_ns:
        raise ValueError("B1V3_SENSITIVITY_FUTURE_QUOTE")
    midpoint = (bid + ask) / 2.0 if math.isfinite(bid) and math.isfinite(ask) else None
    relative_spread = (
        (ask - bid) / midpoint
        if midpoint is not None and math.isfinite(midpoint) and midpoint != 0.0
        else None
    )
    iv_result = timing._iv_from_reselected_quote(row=row, quote=quote)
    if not isinstance(iv_result, Mapping):
        iv_result = {"success": False, "failure_reason": "IV_RESULT_INVALID"}
    success = iv_result.get("success") is True
    output.update(
        {
            "sip_timestamp": sip_timestamp,
            "sequence_number": sequence_number,
            "bid": bid,
            "ask": ask,
            "midpoint": midpoint,
            "relative_spread": relative_spread,
            "quote_age_seconds": (cutoff_ns - sip_timestamp)
            / timing.NANOSECONDS_PER_SECOND,
            "iv_success": success,
            "iv": float(iv_result["iv"]) if success else None,
            "failure_reason": None if success else str(iv_result.get("failure_reason")),
        }
    )
    return output


def _output_schema(source: pa.Schema) -> pa.Schema:
    fields = [
        pa.field(field.name, _UPDATED_TYPES.get(field.name, field.type), nullable=True)
        for field in source
    ]
    existing = {field.name for field in fields}
    fields.extend(
        pa.field(name, data_type, nullable=True)
        for name, data_type in _UPDATED_TYPES.items()
        if name not in existing
    )
    return pa.schema(fields)


def write_massive_reselected_attempts(
    *,
    attempts_path: Path,
    cache_root: Path,
    output_path: Path,
    cutoff_seconds: int,
    batch_size: int = 65_536,
) -> dict[str, Any]:
    """Stream one shifted-cutoff attempt table from validated local caches.

    Parameters
    ----------
    attempts_path:
        Primary target-free attempt Parquet used only for contract/exogenous
        inputs and raw-cache identities.
    cache_root:
        Existing Massive v4 contract-day JSON cache.
    output_path:
        New immutable Parquet destination.
    cutoff_seconds:
        Registered 60- or 300-second sensitivity shift (zero is also accepted
        for deterministic parity audits).
    batch_size:
        Maximum Arrow input batch size; asset-day memory remains bounded.

    Returns
    -------
    dict[str, Any]
        Sanitized counts and source/output hashes.

    Raises
    ------
    FileNotFoundError
        If the source table or cache root is absent.
    ValueError
        If schemas, target-blindness, cache identity, pagination, ordering,
        contiguity, output conflict or row preservation fails.
    """
    if cutoff_seconds not in _CUTOFFS:
        raise ValueError("B1V3_SENSITIVITY_CUTOFF_INVALID")
    if batch_size <= 0:
        raise ValueError("B1V3_SENSITIVITY_BATCH_SIZE_INVALID")
    if not attempts_path.is_file():
        raise FileNotFoundError("B1V3_SENSITIVITY_ATTEMPTS_MISSING")
    if not cache_root.is_dir():
        raise FileNotFoundError("B1V3_SENSITIVITY_CACHE_ROOT_MISSING")
    if output_path.exists():
        raise ValueError(f"B1V3_SENSITIVITY_OUTPUT_CONFLICT:{output_path.name}")
    reader = pq.ParquetFile(attempts_path)
    names = reader.schema_arrow.names
    if set(names) < _REQUIRED_IDENTITY_COLUMNS:
        raise ValueError("B1V3_SENSITIVITY_ATTEMPT_SCHEMA_INVALID")
    for name in names:
        lower = name.lower()
        if name != "target_moneyness" and any(
            token in lower for token in _FORBIDDEN_INPUT_TOKENS
        ):
            raise ValueError(f"B1V3_SENSITIVITY_FORBIDDEN_COLUMN:{name}")
    cache_index = timing._massive_cache_index(cache_root)
    output_schema = _output_schema(reader.schema_arrow)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{output_path.name}.", suffix=".part", dir=output_path.parent
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    writer: pq.ParquetWriter | None = None
    counters = {
        "asset_day_count": 0,
        "contract_day_count": 0,
        "cache_decode_count": 0,
        "attempt_count": 0,
        "selected_quote_count": 0,
        "no_quote_count": 0,
        "iv_success_count": 0,
        "max_asset_day_rows": 0,
    }

    def write_asset_day(asset: str, session_date: str, rows: list[dict[str, Any]]) -> None:
        nonlocal writer
        counters["asset_day_count"] += 1
        counters["max_asset_day_rows"] = max(counters["max_asset_day_rows"], len(rows))
        grouped: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(
            lambda: defaultdict(list)
        )
        for row in rows:
            grouped[str(row["contract"])][str(row["source_request_hash"])].append(row)
        output_rows: list[dict[str, Any]] = []
        for contract in sorted(grouped):
            by_hash = grouped[contract]
            counters["contract_day_count"] += 1
            if len(by_hash) != 1:
                raise ValueError("B1V3_SENSITIVITY_ATTEMPT_SOURCE_HASH_AMBIGUOUS")
            source_hash, contract_rows = next(iter(by_hash.items()))
            counters["cache_decode_count"] += 1
            cache_state, quotes = timing._load_and_validate_massive_cache(
                cache_index=cache_index,
                cache_root=cache_root,
                asset=asset,
                session_date=session_date,
                contract=contract,
                source_request_hash=source_hash,
            )
            if cache_state not in timing.VALID_MASSIVE_CACHE_STATES:
                raise ValueError(f"B1V3_SENSITIVITY_CACHE_INVALID:{cache_state}")
            for row in contract_rows:
                cutoff_ns = int(row["forecast_origin_ns"]) - (
                    cutoff_seconds * timing.NANOSECONDS_PER_SECOND
                )
                selected = timing._select_prepared_quote(quotes, cutoff_ns)
                transformed = reselected_attempt_row(
                    row,
                    quote=selected,
                    cutoff_seconds=cutoff_seconds,
                )
                counters["attempt_count"] += 1
                if selected is None:
                    counters["no_quote_count"] += 1
                else:
                    counters["selected_quote_count"] += 1
                if transformed["iv_success"] is True:
                    counters["iv_success_count"] += 1
                output_rows.append(transformed)
        table = pa.Table.from_pylist(output_rows, schema=output_schema)
        if writer is None:
            writer = pq.ParquetWriter(
                temporary,
                output_schema,
                compression="zstd",
                write_statistics=True,
            )
        writer.write_table(table)

    closed_asset_days: set[tuple[str, str]] = set()
    current_asset_day: tuple[str, str] | None = None
    current_rows: list[dict[str, Any]] = []
    try:
        for batch in reader.iter_batches(batch_size=batch_size, columns=names):
            for row in pa.Table.from_batches([batch]).to_pylist():
                asset_day = (str(row["asset"]), str(row["session_date"]))
                if current_asset_day is None:
                    current_asset_day = asset_day
                elif asset_day != current_asset_day:
                    write_asset_day(current_asset_day[0], current_asset_day[1], current_rows)
                    closed_asset_days.add(current_asset_day)
                    if asset_day in closed_asset_days:
                        raise ValueError(
                            "B1V3_SENSITIVITY_ATTEMPT_ASSET_DAY_NONCONTIGUOUS"
                        )
                    current_asset_day = asset_day
                    current_rows = []
                current_rows.append(row)
        if current_asset_day is not None:
            write_asset_day(current_asset_day[0], current_asset_day[1], current_rows)
        if writer is None:
            raise ValueError("B1V3_SENSITIVITY_EMPTY_INPUT")
        writer.close()
        writer = None
        if counters["attempt_count"] != reader.metadata.num_rows:
            raise ValueError("B1V3_SENSITIVITY_ROW_PRESERVATION_FAILURE")
        os.replace(temporary, output_path)
    finally:
        if writer is not None:
            writer.close()
        temporary.unlink(missing_ok=True)
    return {
        "status": "PASS_TARGET_BLIND_MASSIVE_RESELECTION",
        "cutoff_seconds": cutoff_seconds,
        "input_sha256": sha256_file(attempts_path),
        "output_sha256": sha256_file(output_path),
        **counters,
    }
