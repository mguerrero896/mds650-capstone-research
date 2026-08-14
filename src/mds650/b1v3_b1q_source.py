"""Seal Massive B1Q inputs to exact raw contract-day payloads without outcomes."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import polars as pl

from mds650.b1v3_confirmation import (
    canonical_sha256,
    sha256_file,
    validate_confirmation_plan_schema,
)
from mds650.b1v3_confirmation_build import (
    B1V3_CANONICAL_ASSETS,
    FrozenBuildInputs,
)
from mds650.provider_timing_v21 import (
    _expected_massive_cache_key,
    _expected_massive_source_request_hash,
    _massive_pagination_verified,
    _massive_request_parameters_status,
)

_HASH_RE: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}$")
_FORBIDDEN_COLUMN_FRAGMENTS: Final[tuple[str, ...]] = (
    "rv30",
    "qlike",
    "prediction",
    "predicted",
    "outcome",
    "residual",
    "loss",
)
_FORBIDDEN_SERIALIZED_TOKENS: Final[tuple[bytes, ...]] = (
    b"c:\\users\\",
    b"c:/users/",
    b"d:\\mds650",
    b"api_key",
    b"apikey",
    b"authorization",
    b"bearer ",
)
_REQUIRED_ATTEMPT_COLUMNS: Final[frozenset[str]] = frozenset(
    {
        "origin_id",
        "asset",
        "session_date",
        "forecast_origin_utc",
        "forecast_origin_ns",
        "contract",
        "expiry",
        "strike",
        "option_type",
        "dte",
        "spot",
        "moneyness",
        "target_moneyness",
        "rate",
        "rate_source_date",
        "dividend_yield",
        "dividend_assumption",
        "source_request_hash",
        "iv_success",
        "iv",
        "failure_reason",
        "sip_timestamp",
        "bid",
        "ask",
        "quote_age_seconds",
        "relative_spread",
        "midpoint",
    }
)
_OPTIONAL_ATTEMPT_COLUMNS: Final[frozenset[str]] = frozenset(
    {
        "bucket",
        "reference_request_id",
        "instrument_type",
        "iterations",
        "lower_bound",
        "upper_bound",
        "quote_cutoff_seconds",
        "sequence_number",
        "session_tercile",
    }
)
_ATTEMPT_AUDIT_COLUMNS: Final[tuple[str, ...]] = (
    "origin_id",
    "asset",
    "session_date",
    "forecast_origin_ns",
    "contract",
    "expiry",
    "strike",
    "option_type",
    "dte",
    "spot",
    "source_request_hash",
    "rate_source_date",
    "sip_timestamp",
)


@dataclass(frozen=True, slots=True)
class B1QSourceArtifacts:
    """Immutable artifacts produced by one B1Q source-binding pass."""

    inventory_path: Path
    manifest_path: Path
    inventory_sha256: str
    manifest_file_sha256: str
    manifest_sha256: str


def _json_object(path: Path, *, code: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(code) from exc
    if not isinstance(value, dict):
        raise ValueError(code)
    return value


def _origin_identity_sha256(frame: pl.DataFrame) -> str:
    return canonical_sha256(
        {"origin_ids": [str(value) for value in frame["origin_id"].to_list()]}
    )


def _validate_base_and_origins(
    *,
    inputs: FrozenBuildInputs,
    base_manifest_path: Path,
    origins_path: Path,
) -> tuple[dict[str, Any], pl.DataFrame, str]:
    base = _json_object(base_manifest_path, code="B1V3_B1Q_SOURCE_BASE_MANIFEST_INVALID")
    base_hash = base.get("manifest_sha256")
    if not isinstance(base_hash, str) or base_hash != canonical_sha256(
        {key: value for key, value in base.items() if key != "manifest_sha256"}
    ):
        raise ValueError("B1V3_B1Q_SOURCE_BASE_MANIFEST_HASH_INVALID")
    outputs = base.get("outputs")
    binding = outputs.get("b1_origins") if isinstance(outputs, dict) else None
    if (
        base.get("status") != "PASS_TARGET_BLIND_BASE_PREDICTORS"
        or base.get("plan_sha256") != inputs.plan_sha256
        or base.get("target_blind") is not True
        or base.get("outcome_read_count") != 0
        or base.get("safe_to_read_outcomes") is not False
        or not isinstance(binding, dict)
        or not origins_path.is_file()
        or binding.get("sha256") != sha256_file(origins_path)
    ):
        raise ValueError("B1V3_B1Q_SOURCE_BASE_GATE_INVALID")
    origins = pl.read_parquet(origins_path)
    required = {
        "origin_id",
        "asset",
        "session_date",
        "forecast_origin_utc",
        "spot",
    }
    if not required.issubset(origins.columns):
        raise ValueError("B1V3_B1Q_SOURCE_ORIGIN_SCHEMA_INVALID")
    if any(
        token in column.lower()
        for token in _FORBIDDEN_COLUMN_FRAGMENTS
        for column in origins.columns
    ):
        raise ValueError("B1V3_B1Q_SOURCE_TARGET_COLUMN_FORBIDDEN")
    sessions = tuple(sorted(str(value) for value in origins["session_date"].unique()))
    assets = tuple(sorted(str(value) for value in origins["asset"].unique()))
    origin_identity = _origin_identity_sha256(origins)
    if (
        origins.is_empty()
        or origins["origin_id"].n_unique() != origins.height
        or sessions != inputs.all_sessions
        or assets != B1V3_CANONICAL_ASSETS
        or origins["spot"].null_count()
        or origins.filter(pl.col("spot") <= 0).height
        or base.get("origin_count") != origins.height
        or base.get("origin_identity_sha256") != origin_identity
    ):
        raise ValueError("B1V3_B1Q_SOURCE_ORIGIN_SCOPE_INVALID")
    return base, origins, origin_identity


def _validate_attempt_schema(path: Path) -> tuple[str, tuple[str, ...]]:
    if not path.is_file() or path.suffix.lower() != ".parquet":
        raise ValueError("B1V3_B1Q_SOURCE_ATTEMPTS_INVALID")
    schema = pl.scan_parquet(path).collect_schema()
    columns = tuple(schema.names())
    missing = sorted(_REQUIRED_ATTEMPT_COLUMNS - set(columns))
    if missing:
        raise ValueError(f"B1V3_B1Q_SOURCE_ATTEMPT_SCHEMA_INVALID:{','.join(missing)}")
    allowed = _REQUIRED_ATTEMPT_COLUMNS | _OPTIONAL_ATTEMPT_COLUMNS
    for column in columns:
        lowered = column.lower()
        if column != "target_moneyness" and (
            lowered.startswith("target")
            or any(token in lowered for token in _FORBIDDEN_COLUMN_FRAGMENTS)
        ):
            raise ValueError("B1V3_B1Q_SOURCE_TARGET_COLUMN_FORBIDDEN")
        if column not in allowed:
            raise ValueError(f"B1V3_B1Q_SOURCE_COLUMN_NOT_ALLOWLISTED:{column}")
    return sha256_file(path), columns


def _load_and_validate_attempts(
    path: Path,
    *,
    origins: pl.DataFrame,
) -> tuple[pl.DataFrame, int, int]:
    attempts = (
        pl.scan_parquet(path)
        .select(_ATTEMPT_AUDIT_COLUMNS)
        .collect(engine="streaming")
    )
    if attempts.is_empty():
        raise ValueError("B1V3_B1Q_SOURCE_ATTEMPTS_EMPTY")
    if attempts.select(pl.struct("origin_id", "contract").is_duplicated().any()).item():
        raise ValueError("B1V3_B1Q_SOURCE_ATTEMPT_DUPLICATE")
    expected_ids = set(str(value) for value in origins["origin_id"].to_list())
    observed_ids = set(str(value) for value in attempts["origin_id"].unique().to_list())
    if observed_ids != expected_ids:
        raise ValueError("B1V3_B1Q_SOURCE_ATTEMPT_ORIGIN_SCOPE_INVALID")
    if tuple(sorted(str(value) for value in attempts["asset"].unique())) != tuple(
        sorted(str(value) for value in origins["asset"].unique())
    ):
        raise ValueError("B1V3_B1Q_SOURCE_ATTEMPT_ASSET_SCOPE_INVALID")
    expected = origins.select(
        "origin_id",
        pl.col("asset").alias("expected_asset"),
        pl.col("session_date").alias("expected_session_date"),
        pl.col("forecast_origin_utc").dt.timestamp("ns").alias("expected_origin_ns"),
        pl.col("spot").alias("expected_spot"),
    )
    joined = attempts.join(expected, on="origin_id", how="left", validate="m:1")
    inconsistent = joined.filter(
        pl.col("expected_asset").is_null()
        | (pl.col("asset") != pl.col("expected_asset"))
        | (pl.col("session_date") != pl.col("expected_session_date"))
        | (pl.col("forecast_origin_ns") != pl.col("expected_origin_ns"))
        | ((pl.col("spot") - pl.col("expected_spot")).abs() > 1e-10)
    ).height
    if inconsistent:
        raise ValueError("B1V3_B1Q_SOURCE_ATTEMPT_ORIGIN_METADATA_INVALID")
    future = attempts.filter(
        pl.col("sip_timestamp").is_not_null()
        & (pl.col("sip_timestamp") > pl.col("forecast_origin_ns"))
    ).height
    if future:
        raise ValueError("B1V3_B1Q_SOURCE_FUTURE_QUOTE")
    parsed_rate_date = pl.col("rate_source_date").str.to_date(strict=False)
    parsed_session = pl.col("session_date").str.to_date(strict=False)
    invalid_rate = attempts.filter(
        parsed_rate_date.is_null() | parsed_session.is_null() | (parsed_rate_date >= parsed_session)
    ).height
    if invalid_rate:
        raise ValueError("B1V3_B1Q_SOURCE_RATE_NOT_PRE_ORIGIN")
    invalid_hash = attempts.filter(
        pl.col("source_request_hash").is_null()
        | ~pl.col("source_request_hash").str.contains(r"^[0-9a-f]{64}$")
    ).height
    if invalid_hash:
        raise ValueError("B1V3_B1Q_SOURCE_REQUEST_HASH_INVALID")
    hash_conflicts = (
        attempts.group_by("asset", "session_date", "contract")
        .agg(pl.col("source_request_hash").n_unique().alias("hash_count"))
        .filter(pl.col("hash_count") != 1)
        .height
    )
    if hash_conflicts:
        raise ValueError("B1V3_B1Q_SOURCE_REQUEST_HASH_AMBIGUOUS")
    reverse_conflicts = (
        attempts.group_by("source_request_hash")
        .agg(
            pl.struct("asset", "session_date", "contract")
            .n_unique()
            .alias("identity_count")
        )
        .filter(pl.col("identity_count") != 1)
        .height
    )
    if reverse_conflicts:
        raise ValueError("B1V3_B1Q_SOURCE_REQUEST_HASH_REUSED")
    identities = attempts.select(
        "asset",
        "session_date",
        "contract",
        "expiry",
        "strike",
        "option_type",
        "dte",
        "source_request_hash",
    ).unique(maintain_order=False)
    duplicate_identity = identities.select(
        pl.struct("asset", "session_date", "contract").is_duplicated().any()
    ).item()
    if duplicate_identity:
        raise ValueError("B1V3_B1Q_SOURCE_CONTRACT_IDENTITY_AMBIGUOUS")
    return identities.sort("asset", "session_date", "contract"), attempts.height, future


def _load_contract_grid(
    path: Path,
    *,
    origins: pl.DataFrame,
    identities: pl.DataFrame,
) -> tuple[str, int, dict[tuple[str, str, str], Mapping[str, Any]]]:
    document = _json_object(path, code="B1V3_B1Q_SOURCE_CONTRACT_GRID_INVALID")
    records = document.get("records")
    if document.get("schema_version") != "b1q-contract-grid-3.0" or not isinstance(
        records, list
    ):
        raise ValueError("B1V3_B1Q_SOURCE_CONTRACT_GRID_INVALID")
    spot_by_asset_day = {
        (str(row["asset"]), str(row["session_date"])): float(row["spot"])
        for row in origins.group_by("asset", "session_date")
        .agg(pl.col("spot").first())
        .iter_rows(named=True)
    }
    expected_asset_days = set(spot_by_asset_day)
    observed_asset_days: set[tuple[str, str]] = set()
    contracts: dict[tuple[str, str, str], Mapping[str, Any]] = {}
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("contracts"), list):
            raise ValueError("B1V3_B1Q_SOURCE_CONTRACT_GRID_RECORD_INVALID")
        asset = str(record.get("asset", ""))
        session_date = str(record.get("session_date", ""))
        asset_day = (asset, session_date)
        spot = record.get("spot")
        if (
            asset_day in observed_asset_days
            or asset_day not in expected_asset_days
            or isinstance(spot, bool)
            or not isinstance(spot, int | float)
            or not math.isclose(float(spot), spot_by_asset_day[asset_day], abs_tol=1e-10)
        ):
            raise ValueError("B1V3_B1Q_SOURCE_CONTRACT_GRID_SCOPE_INVALID")
        observed_asset_days.add(asset_day)
        if not record["contracts"]:
            raise ValueError("B1V3_B1Q_SOURCE_CONTRACT_GRID_EMPTY")
        for metadata in record["contracts"]:
            if not isinstance(metadata, dict):
                raise ValueError("B1V3_B1Q_SOURCE_CONTRACT_GRID_RECORD_INVALID")
            contract = metadata.get("contract")
            key = (asset, session_date, str(contract or ""))
            if (
                not isinstance(contract, str)
                or not contract.startswith("O:")
                or key in contracts
            ):
                raise ValueError("B1V3_B1Q_SOURCE_CONTRACT_GRID_DUPLICATE")
            contracts[key] = metadata
    if observed_asset_days != expected_asset_days:
        raise ValueError("B1V3_B1Q_SOURCE_CONTRACT_GRID_SCOPE_INVALID")
    observed_contracts = {
        (str(row["asset"]), str(row["session_date"]), str(row["contract"]))
        for row in identities.iter_rows(named=True)
    }
    if set(contracts) != observed_contracts:
        raise ValueError("B1V3_B1Q_SOURCE_CONTRACT_SCOPE_INVALID")
    for row in identities.iter_rows(named=True):
        key = (str(row["asset"]), str(row["session_date"]), str(row["contract"]))
        metadata = contracts[key]
        if (
            metadata.get("expiry") != row["expiry"]
            or metadata.get("option_type") != row["option_type"]
            or metadata.get("dte") != row["dte"]
            or not isinstance(metadata.get("strike"), int | float)
            or not math.isclose(float(metadata["strike"]), float(row["strike"]), abs_tol=1e-10)
        ):
            raise ValueError("B1V3_B1Q_SOURCE_CONTRACT_METADATA_MISMATCH")
    return sha256_file(path), len(records), contracts


def _cache_index(cache_root: Path) -> Mapping[str, Sequence[Path]]:
    if not cache_root.is_dir():
        raise ValueError("B1V3_B1Q_SOURCE_CACHE_ROOT_INVALID")
    index: dict[str, list[Path]] = defaultdict(list)
    for path in cache_root.glob("*.json"):
        parts = path.stem.rsplit("_", maxsplit=1)
        if len(parts) == 2:
            index[parts[0]].append(path)
    return {key: tuple(sorted(values)) for key, values in index.items()}


def _validate_cache_payload(
    *,
    path: Path,
    raw: bytes,
    asset: str,
    session_date: str,
    contract: str,
    metadata: Mapping[str, Any],
    source_request_hash: str,
) -> dict[str, Any]:
    if any(token in raw.lower() for token in _FORBIDDEN_SERIALIZED_TOKENS):
        raise ValueError("B1V3_B1Q_SOURCE_CACHE_SECRET_OR_PATH")
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("B1V3_B1Q_SOURCE_CACHE_INVALID") from exc
    if not isinstance(payload, dict):
        raise ValueError("B1V3_B1Q_SOURCE_CACHE_INVALID")
    nested = payload.get("contract")
    if (
        payload.get("asset") != asset
        or payload.get("day") != session_date
        or payload.get("route") != "B1Q"
        or payload.get("schema_version") != 4
        or payload.get("http_status") != 200
        or not isinstance(nested, dict)
        or nested.get("contract") != contract
        or payload.get("source_request_hash") != source_request_hash
    ):
        raise ValueError("B1V3_B1Q_SOURCE_CACHE_INVALID")
    expected_cache_key = _expected_massive_cache_key(
        asset=asset,
        session_date=session_date,
        contract=contract,
        contract_metadata=metadata,
    )
    expected_name = (
        f"{asset}_{session_date}_{contract.replace(':', '_')}_"
        f"{hashlib.sha256(expected_cache_key.encode()).hexdigest()[:16]}.json"
    )
    expected_quote_key = (
        f"provider=massive|contract={contract}|session_date={session_date}|"
        "route=B1Q|schema_version=4"
    )
    request_params = payload.get("request_params_sanitized")
    if (
        path.name != expected_name
        or payload.get("cache_key") != expected_cache_key
        or payload.get("quote_cache_key") != expected_quote_key
        or not isinstance(request_params, dict)
        or _expected_massive_source_request_hash(
            contract=contract, request_params=request_params
        )
        != source_request_hash
    ):
        raise ValueError("B1V3_B1Q_SOURCE_CACHE_INVALID")
    request_status, bounds = _massive_request_parameters_status(
        request_params=request_params,
        session_date=session_date,
    )
    rows = payload.get("results")
    request_id = payload.get("request_id")
    if (
        request_status == "INVALID"
        or not isinstance(payload.get("pages"), int)
        or int(payload["pages"]) <= 0
        or not isinstance(rows, list)
        or not _massive_pagination_verified(payload=payload, rows=rows)
        or not isinstance(request_id, str)
        or not request_id.strip()
    ):
        raise ValueError("B1V3_B1Q_SOURCE_CACHE_INVALID")
    seen: set[tuple[int, int]] = set()
    prior_sip: int | None = None
    timestamps: list[int] = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("B1V3_B1Q_SOURCE_CACHE_INVALID")
        sip = row.get("sip_timestamp")
        sequence = row.get("sequence_number")
        bid = row.get("bid_price")
        ask = row.get("ask_price")
        if (
            not isinstance(sip, int)
            or not isinstance(sequence, int)
            or isinstance(bid, bool)
            or isinstance(ask, bool)
            or not isinstance(bid, int | float)
            or not isinstance(ask, int | float)
            or not math.isfinite(float(bid))
            or not math.isfinite(float(ask))
            or sip < int(bounds["open_ns"])
            or sip > int(request_params["timestamp.lte"])
        ):
            raise ValueError("B1V3_B1Q_SOURCE_CACHE_INVALID")
        key = (sip, sequence)
        # The provider request is sorted by timestamp only. Sequence numbers are
        # deterministic tie-breakers for local as-of selection, but their raw
        # order is not contractually monotone within one SIP timestamp.
        if key in seen or (prior_sip is not None and sip < prior_sip):
            raise ValueError("B1V3_B1Q_SOURCE_CACHE_INVALID")
        seen.add(key)
        prior_sip = sip
        timestamps.append(sip)
    return {
        "asset": asset,
        "session_date": session_date,
        "contract": contract,
        "source_request_hash": source_request_hash,
        "cache_filename": path.name,
        "cache_file_sha256": hashlib.sha256(raw).hexdigest(),
        "cache_bytes": len(raw),
        "request_id": request_id,
        "request_scope_status": request_status,
        "pages": int(payload["pages"]),
        "pagination_status": str(payload.get("pagination_complete")),
        "quote_row_count": len(rows),
        "first_sip_timestamp_ns": min(timestamps) if timestamps else None,
        "last_sip_timestamp_ns": max(timestamps) if timestamps else None,
    }


def _build_inventory(
    *,
    cache_root: Path,
    identities: pl.DataFrame,
    contracts: Mapping[tuple[str, str, str], Mapping[str, Any]],
) -> pl.DataFrame:
    index = _cache_index(cache_root)
    rows: list[dict[str, Any]] = []
    file_hashes: set[str] = set()
    for row in identities.iter_rows(named=True):
        asset = str(row["asset"])
        session_date = str(row["session_date"])
        contract = str(row["contract"])
        source_request_hash = str(row["source_request_hash"])
        prefix = f"{asset}_{session_date}_{contract.replace(':', '_')}"
        candidates = index.get(prefix, ())
        if len(candidates) != 1:
            raise ValueError("B1V3_B1Q_SOURCE_CACHE_FILE_AMBIGUOUS")
        path = candidates[0]
        if path.is_symlink() or path.parent.resolve() != cache_root.resolve():
            raise ValueError("B1V3_B1Q_SOURCE_CACHE_PATH_INVALID")
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise ValueError("B1V3_B1Q_SOURCE_CACHE_INVALID") from exc
        inventory_row = _validate_cache_payload(
            path=path,
            raw=raw,
            asset=asset,
            session_date=session_date,
            contract=contract,
            metadata=contracts[(asset, session_date, contract)],
            source_request_hash=source_request_hash,
        )
        file_hash = str(inventory_row["cache_file_sha256"])
        if file_hash in file_hashes:
            raise ValueError("B1V3_B1Q_SOURCE_DUPLICATE_PAYLOAD_HASH")
        file_hashes.add(file_hash)
        rows.append(inventory_row)
    return pl.DataFrame(rows, infer_schema_length=None, strict=False).sort(
        "asset", "session_date", "contract"
    )


def _write_parquet_if_identical(frame: pl.DataFrame, destination: Path) -> str:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if not pl.read_parquet(destination).equals(frame, null_equal=True):
            raise ValueError(f"B1V3_B1Q_SOURCE_OUTPUT_CONFLICT:{destination.name}")
        return sha256_file(destination)
    descriptor, name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".part", dir=destination.parent
    )
    os.close(descriptor)
    temporary = Path(name)
    try:
        frame.write_parquet(temporary, compression="zstd", statistics=True)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return sha256_file(destination)


def _write_json_if_identical(destination: Path, document: Mapping[str, Any]) -> str:
    payload = (json.dumps(document, indent=2, sort_keys=True, ensure_ascii=True) + "\n").encode()
    if any(token in payload.lower() for token in _FORBIDDEN_SERIALIZED_TOKENS):
        raise ValueError("B1V3_B1Q_SOURCE_MANIFEST_HYGIENE_INVALID")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if destination.read_bytes() != payload:
            raise ValueError(f"B1V3_B1Q_SOURCE_OUTPUT_CONFLICT:{destination.name}")
    else:
        descriptor, name = tempfile.mkstemp(
            prefix=f".{destination.name}.", suffix=".part", dir=destination.parent
        )
        os.close(descriptor)
        temporary = Path(name)
        try:
            temporary.write_bytes(payload)
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
    return sha256_file(destination)


def seal_b1q_source(
    *,
    inputs: FrozenBuildInputs,
    base_manifest_path: Path,
    origins_path: Path,
    attempts_path: Path,
    contract_grid_path: Path,
    cache_root: Path,
    inventory_path: Path,
    manifest_path: Path,
    manifest_schema_path: Path,
) -> B1QSourceArtifacts:
    """Bind every B1Q attempt to one validated raw Massive contract-day cache.

    Parameters
    ----------
    inputs:
        Frozen provider-passed B1v3 60/30 plan.
    base_manifest_path, origins_path:
        Source-bound base manifest and target-free canonical origin table.
    attempts_path:
        Target-free per-origin IV-attempt table produced by Massive acquisition.
    contract_grid_path:
        Historical ``as_of`` contract grid resolved from the canonical spot.
    cache_root:
        Restricted directory containing immutable Massive v4 quote envelopes.
    inventory_path, manifest_path:
        New immutable outputs; conflicting bytes or rows fail closed.
    manifest_schema_path:
        Draft 2020-12 schema for the sanitized source manifest.

    Returns
    -------
    B1QSourceArtifacts
        Paths and hashes of the raw-payload inventory and source manifest.

    Raises
    ------
    ValueError
        If any scope, PIT, request, cache, hash, schema, hygiene, or idempotence
        invariant fails.

    Notes
    -----
    This function reads no RV30, QLIKE, predictions, models, or outcomes. It
    processes one raw cache file at a time to keep memory bounded by the largest
    compressed JSON envelope plus the compact 32k-row inventory.
    """
    base, origins, origin_identity = _validate_base_and_origins(
        inputs=inputs,
        base_manifest_path=base_manifest_path,
        origins_path=origins_path,
    )
    attempts_hash, attempt_columns = _validate_attempt_schema(attempts_path)
    identities, attempt_rows, future_rows = _load_and_validate_attempts(
        attempts_path,
        origins=origins,
    )
    contract_grid_hash, asset_day_count, contracts = _load_contract_grid(
        contract_grid_path,
        origins=origins,
        identities=identities,
    )
    inventory = _build_inventory(
        cache_root=cache_root,
        identities=identities,
        contracts=contracts,
    )
    if inventory.height != identities.height:
        raise ValueError("B1V3_B1Q_SOURCE_INVENTORY_SCOPE_INVALID")
    inventory_hash = _write_parquet_if_identical(inventory, inventory_path)
    base_hash = str(base["manifest_sha256"])
    document: dict[str, Any] = {
        "schema_version": "1.0",
        "status": "PASS_TARGET_BLIND_B1Q_SOURCE_BOUND",
        "plan_sha256": inputs.plan_sha256,
        "base_manifest_sha256": base_hash,
        "target_blind": True,
        "outcome_read_count": 0,
        "safe_to_read_outcomes": False,
        "scope": {
            "training_session_count": len(inputs.training_sessions),
            "confirmation_session_count": len(inputs.confirmation_sessions),
            "session_count": len(inputs.all_sessions),
            "asset_count": len(B1V3_CANONICAL_ASSETS),
            "assets": list(B1V3_CANONICAL_ASSETS),
            "origin_count": origins.height,
            "origin_identity_sha256": origin_identity,
        },
        "attempts": {
            "logical_path": (
                "MDS650_B1V3_DATA_ROOT/tmp/b1q_acquisition_v1/"
                "b1_iv_attempts_20d.parquet"
            ),
            "sha256": attempts_hash,
            "bytes": attempts_path.stat().st_size,
            "row_count": attempt_rows,
            "columns": list(attempt_columns),
            "unique_request_hash_count": identities.height,
        },
        "contract_grid": {
            "logical_path": (
                "MDS650_B1V3_DATA_ROOT/cache/massive/"
                "resolved_contracts_b1v3_canonical_spot_v1.json"
            ),
            "schema_version": "b1q-contract-grid-3.0",
            "sha256": contract_grid_hash,
            "asset_day_count": asset_day_count,
            "contract_day_count": len(contracts),
        },
        "raw_payload_binding": {
            "status": "PRESENT_AND_VALIDATED",
            "inventory_logical_path": (
                "MDS650_B1V3_DATA_ROOT/evidence/b1q_raw_payload_inventory.parquet"
            ),
            "inventory_sha256": inventory_hash,
            "contract_day_count": inventory.height,
            "cache_bytes": int(inventory["cache_bytes"].sum()),
            "quote_row_count": int(inventory["quote_row_count"].sum()),
            "cache_schema_version": 4,
            "route": "B1Q",
        },
        "pit_invariants": {
            "future_selected_quote_rows": future_rows,
            "rate_source_strictly_pre_session": True,
            "request_scope_validated": True,
            "pagination_validated": True,
            "duplicate_attempt_identities": 0,
            "duplicate_payload_hashes": 0,
        },
        "security": {
            "secret_values_emitted": False,
            "personal_paths_emitted": False,
        },
    }
    document["manifest_sha256"] = canonical_sha256(document)
    validate_confirmation_plan_schema(document, manifest_schema_path)
    manifest_file_hash = _write_json_if_identical(manifest_path, document)
    return B1QSourceArtifacts(
        inventory_path=inventory_path,
        manifest_path=manifest_path,
        inventory_sha256=inventory_hash,
        manifest_file_sha256=manifest_file_hash,
        manifest_sha256=str(document["manifest_sha256"]),
    )
