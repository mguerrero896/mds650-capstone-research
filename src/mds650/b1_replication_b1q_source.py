"""Source-bind independent-replication B1Q attempts to Massive raw caches."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

import polars as pl

from mds650 import b1v3_b1q_source as source_core
from mds650.b1v3_confirmation import (
    canonical_sha256,
    sha256_file,
    validate_confirmation_plan_schema,
)

_ASSETS: Final[tuple[str, ...]] = (
    "AAPL",
    "AMZN",
    "META",
    "MSFT",
    "NVDA",
    "TSLA",
)


def _json_object(path: Path, *, code: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(code) from exc
    if not isinstance(value, dict):
        raise ValueError(code)
    return value


def _self_hash_valid(document: Mapping[str, Any]) -> bool:
    stored = document.get("manifest_sha256")
    unsigned = {key: value for key, value in document.items() if key != "manifest_sha256"}
    return isinstance(stored, str) and stored == canonical_sha256(unsigned)


def _validate_origins(
    *,
    preregistration: Mapping[str, Any],
    base: Mapping[str, Any],
    origins_path: Path,
) -> tuple[pl.DataFrame, str]:
    outputs = base.get("outputs")
    binding = outputs.get("b1_origins") if isinstance(outputs, Mapping) else None
    if (
        not _self_hash_valid(base)
        or base.get("status") != "PASS_TARGET_BLIND_BASE_PREDICTORS"
        or base.get("target_blind") is not True
        or base.get("outcome_read_count") != 0
        or base.get("safe_to_read_outcomes") is not False
        or base.get("preregistration_sha256")
        != preregistration.get("manifest_sha256")
        or not isinstance(binding, Mapping)
        or not origins_path.is_file()
        or binding.get("sha256") != sha256_file(origins_path)
    ):
        raise ValueError("B1_REPLICATION_B1Q_BASE_BINDING_INVALID")
    origins = pl.read_parquet(origins_path)
    required = {
        "origin_id",
        "asset",
        "session_date",
        "forecast_origin_utc",
        "spot",
    }
    if not required <= set(origins.columns) or any(
        token in column.lower()
        for token in source_core._FORBIDDEN_COLUMN_FRAGMENTS
        for column in origins.columns
    ):
        raise ValueError("B1_REPLICATION_B1Q_ORIGIN_SCHEMA_INVALID")
    identity = source_core._origin_identity_sha256(origins)
    sessions = tuple(sorted(str(value) for value in origins["session_date"].unique()))
    assets = tuple(sorted(str(value) for value in origins["asset"].unique()))
    if (
        origins.is_empty()
        or origins["origin_id"].n_unique() != origins.height
        or sessions != tuple(preregistration["replication_sessions"])
        or assets != _ASSETS
        or origins["spot"].null_count()
        or origins.filter(pl.col("spot") <= 0).height
        or base.get("origin_count") != origins.height
        or base.get("origin_identity_sha256") != identity
    ):
        raise ValueError("B1_REPLICATION_B1Q_ORIGIN_SCOPE_INVALID")
    return origins, identity


def seal_replication_b1q_source(
    *,
    preregistration_path: Path,
    base_manifest_path: Path,
    origins_path: Path,
    attempts_path: Path,
    contract_grid_path: Path,
    cache_root: Path,
    inventory_path: Path,
    manifest_path: Path,
    schema_path: Path,
) -> dict[str, Any]:
    """Validate and seal every target-free B1Q contract-day payload."""
    preregistration = _json_object(
        preregistration_path, code="B1_REPLICATION_B1Q_PREREGISTRATION_INVALID"
    )
    base = _json_object(base_manifest_path, code="B1_REPLICATION_B1Q_BASE_INVALID")
    if (
        not _self_hash_valid(preregistration)
        or preregistration.get("status") != "FROZEN_BEFORE_PROVIDER_PAYLOAD"
        or preregistration.get("target_blind") is not True
        or preregistration.get("replication_target_reads") != 0
        or preregistration.get("safe_to_access_replication_targets") != "NO"
        or preregistration.get("result_sign_selection") != "PROHIBITED"
    ):
        raise ValueError("B1_REPLICATION_B1Q_PREREGISTRATION_INVALID")
    origins, origin_identity = _validate_origins(
        preregistration=preregistration,
        base=base,
        origins_path=origins_path,
    )
    attempts_hash, attempt_columns = source_core._validate_attempt_schema(attempts_path)
    identities, attempt_rows, future_rows = source_core._load_and_validate_attempts(
        attempts_path,
        origins=origins,
    )
    contract_grid_hash, asset_day_count, contracts = source_core._load_contract_grid(
        contract_grid_path,
        origins=origins,
        identities=identities,
    )
    inventory = source_core._build_inventory(
        cache_root=cache_root,
        identities=identities,
        contracts=contracts,
    )
    if inventory.height != identities.height:
        raise ValueError("B1_REPLICATION_B1Q_INVENTORY_SCOPE_INVALID")
    inventory_hash = source_core._write_parquet_if_identical(inventory, inventory_path)
    document: dict[str, Any] = {
        "schema_version": "b1-independent-replication-b1q-source-1.0",
        "status": "PASS_TARGET_BLIND_B1Q_SOURCE_BOUND",
        "preregistration_manifest_sha256": preregistration["manifest_sha256"],
        "base_manifest_sha256": base["manifest_sha256"],
        "target_blind": True,
        "outcome_read_count": 0,
        "safe_to_read_outcomes": False,
        "scope": {
            "replication_session_count": 30,
            "asset_count": 6,
            "assets": list(_ASSETS),
            "origin_count": origins.height,
            "origin_identity_sha256": origin_identity,
        },
        "attempts": {
            "logical_path": (
                "MDS650_B1_REPLICATION_DATA_ROOT/tmp/b1q_acquisition_v1/"
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
                "MDS650_B1_REPLICATION_DATA_ROOT/cache/massive/"
                "resolved_contracts_b1_independent_replication_v1.json"
            ),
            "schema_version": "b1q-contract-grid-3.0",
            "sha256": contract_grid_hash,
            "asset_day_count": asset_day_count,
            "contract_day_count": len(contracts),
        },
        "raw_payload_binding": {
            "status": "PRESENT_AND_VALIDATED",
            "inventory_logical_path": (
                "MDS650_B1_REPLICATION_DATA_ROOT/evidence/"
                "b1q_raw_payload_inventory.parquet"
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
    validate_confirmation_plan_schema(document, schema_path)
    source_core._write_json_if_identical(manifest_path, document)
    return document
