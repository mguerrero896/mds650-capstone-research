"""Contract tests for the target-blind B1v3 Massive source sealer."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import polars as pl
import pytest

from mds650.b1v3_b1q_source import seal_b1q_source
from mds650.b1v3_confirmation import canonical_sha256, sha256_file
from mds650.b1v3_confirmation_build import (
    B1V3_CANONICAL_ASSETS,
    FrozenBuildInputs,
)

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = (
    ROOT
    / "specs"
    / "001-pit-options-rv30"
    / "contracts"
    / "b1v3-confirmation-b1q-source-v1.schema.json"
)


@dataclass(frozen=True, slots=True)
class Fixture:
    inputs: FrozenBuildInputs
    base_manifest_path: Path
    origins_path: Path
    attempts_path: Path
    contract_grid_path: Path
    cache_root: Path
    inventory_path: Path
    manifest_path: Path


def _source_request_hash(contract: str, params: dict[str, str]) -> str:
    material = (
        f"https://api.massive.com/v3/quotes/{contract}|"
        f"{json.dumps(params, sort_keys=True)}|route=B1Q|schema_version=4"
    )
    return hashlib.sha256(material.encode()).hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True), encoding="utf-8")


def _fixture(tmp_path: Path) -> Fixture:
    day = "2024-08-02"
    origin = datetime(2024, 8, 2, 13, 35, tzinfo=UTC)
    origin_ns = int(origin.timestamp() * 1_000_000_000)
    open_ns = int(datetime(2024, 8, 2, 13, 30, tzinfo=UTC).timestamp() * 1_000_000_000)
    close_ns = int(datetime(2024, 8, 2, 20, 0, tzinfo=UTC).timestamp() * 1_000_000_000)
    plan_hash = "a" * 64
    inputs = FrozenBuildInputs(
        plan_sha256=plan_hash,
        report_sha256="b" * 64,
        provider_candidate_plan_sha256="c" * 64,
        source_confirmation_plan_sha256="d" * 64,
        training_sessions=(day,),
        confirmation_sessions=(),
        fmp_records=(),
    )
    origins_rows: list[dict[str, object]] = []
    attempt_rows: list[dict[str, object]] = []
    contract_records: list[dict[str, object]] = []
    cache_root = tmp_path / "massive-cache"
    cache_root.mkdir(parents=True)
    for index, asset in enumerate(B1V3_CANONICAL_ASSETS, start=1):
        spot = 100.0 + index
        origin_id = f"{asset}|{day}|09:35"
        contract = f"O:{asset}240920C00100000"
        metadata = {
            "contract": contract,
            "expiry": "2024-09-20",
            "strike": 100.0,
            "option_type": "call",
            "dte": 49,
            "target_moneyness": 1.0,
            "bucket": "medium",
        }
        params = {
            "timestamp.gte": str(open_ns),
            "timestamp.lte": str(close_ns),
            "sort": "timestamp",
            "order": "asc",
            "limit": "50000",
        }
        source_hash = _source_request_hash(contract, params)
        cache_key = (
            f"provider=massive|asset={asset}|session_date={day}|expiry=2024-09-20|"
            f"strike=100.0|option_type=call|contract={contract}|route=B1Q|"
            "schema_version=4"
        )
        digest = hashlib.sha256(cache_key.encode()).hexdigest()[:16]
        cache_path = cache_root / f"{asset}_{day}_{contract.replace(':', '_')}_{digest}.json"
        sip_timestamp = origin_ns - 30_000_000_000
        _write_json(
            cache_path,
            {
                "schema_version": 4,
                "route": "B1Q",
                "asset": asset,
                "day": day,
                "contract": metadata,
                "cache_key": cache_key,
                "quote_cache_key": (
                    f"provider=massive|contract={contract}|session_date={day}|"
                    "route=B1Q|schema_version=4"
                ),
                "source_request_hash": source_hash,
                "request_params_sanitized": params,
                "request_id": f"request-{index}",
                "http_status": 200,
                "pages": 1,
                "pagination_complete": True,
                "provider_duplicate_rows_removed": 0,
                "results": [
                    {
                        "sip_timestamp": sip_timestamp,
                        "sequence_number": 1,
                        "bid_price": 1.0,
                        "ask_price": 1.2,
                    }
                ],
            },
        )
        origins_rows.append(
            {
                "origin_id": origin_id,
                "asset": asset,
                "session_date": day,
                "forecast_origin_utc": origin,
                "spot": spot,
                "session_segment": "first",
            }
        )
        attempt_rows.append(
            {
                **metadata,
                "asset": asset,
                "session_date": day,
                "origin_id": origin_id,
                "forecast_origin_utc": origin.isoformat(),
                "forecast_origin_ns": origin_ns,
                "spot": spot,
                "moneyness": 100.0 / spot,
                "rate": 0.05,
                "rate_source_date": "2024-08-01",
                "dividend_yield": 0.0,
                "dividend_assumption": "NO_PRE_ORIGIN_DIVIDEND_Q_ZERO",
                "source_request_hash": source_hash,
                "iv_success": True,
                "iv": 0.25,
                "failure_reason": None,
                "sip_timestamp": sip_timestamp,
                "bid": 1.0,
                "ask": 1.2,
                "quote_age_seconds": 30.0,
                "relative_spread": 2.0 / 11.0,
                "midpoint": 1.1,
            }
        )
        contract_records.append(
            {
                "asset": asset,
                "session_date": day,
                "spot": spot,
                "contracts": [metadata],
            }
        )
    origins_path = tmp_path / "b1_origins_target_blind.parquet"
    attempts_path = tmp_path / "b1_iv_attempts_20d.parquet"
    contract_grid_path = tmp_path / "resolved_contracts_b1v3_canonical_spot_v1.json"
    pl.DataFrame(origins_rows).write_parquet(origins_path)
    pl.DataFrame(attempt_rows, strict=False).write_parquet(attempts_path)
    _write_json(
        contract_grid_path,
        {"schema_version": "b1q-contract-grid-3.0", "records": contract_records},
    )
    base: dict[str, object] = {
        "schema_version": "1.0",
        "status": "PASS_TARGET_BLIND_BASE_PREDICTORS",
        "plan_sha256": plan_hash,
        "target_blind": True,
        "outcome_read_count": 0,
        "safe_to_read_outcomes": False,
        "origin_count": len(origins_rows),
        "origin_identity_sha256": canonical_sha256(
            {"origin_ids": [str(row["origin_id"]) for row in origins_rows]}
        ),
        "outputs": {
            "b1_origins": {
                "sha256": sha256_file(origins_path),
                "row_count": len(origins_rows),
            }
        },
    }
    base["manifest_sha256"] = canonical_sha256(base)
    base_path = tmp_path / "base_predictor_manifest.json"
    _write_json(base_path, base)
    return Fixture(
        inputs=inputs,
        base_manifest_path=base_path,
        origins_path=origins_path,
        attempts_path=attempts_path,
        contract_grid_path=contract_grid_path,
        cache_root=cache_root,
        inventory_path=tmp_path / "out" / "b1q_raw_payload_inventory.parquet",
        manifest_path=tmp_path / "out" / "b1q_source_manifest.json",
    )


def _seal(paths: Fixture) -> object:
    return seal_b1q_source(
        inputs=paths.inputs,
        base_manifest_path=paths.base_manifest_path,
        origins_path=paths.origins_path,
        attempts_path=paths.attempts_path,
        contract_grid_path=paths.contract_grid_path,
        cache_root=paths.cache_root,
        inventory_path=paths.inventory_path,
        manifest_path=paths.manifest_path,
        manifest_schema_path=SCHEMA,
    )


def test_sealer_binds_attempts_contract_grid_and_raw_caches(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    first = _seal(paths)
    second = _seal(paths)

    assert first == second
    inventory = pl.read_parquet(paths.inventory_path)
    manifest = json.loads(paths.manifest_path.read_text(encoding="utf-8"))
    assert inventory.height == len(B1V3_CANONICAL_ASSETS)
    assert inventory["cache_file_sha256"].n_unique() == inventory.height
    assert manifest["status"] == "PASS_TARGET_BLIND_B1Q_SOURCE_BOUND"
    assert manifest["raw_payload_binding"]["status"] == "PRESENT_AND_VALIDATED"
    assert manifest["pit_invariants"]["future_selected_quote_rows"] == 0
    assert manifest["outcome_read_count"] == 0
    assert manifest["safe_to_read_outcomes"] is False
    assert manifest["manifest_sha256"] == canonical_sha256(
        {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    )


def test_sealer_rejects_target_columns_and_future_quotes(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    attempts_path = paths.attempts_path
    attempts = pl.read_parquet(attempts_path)
    attempts.with_columns(pl.lit(0.1).alias("rv30")).write_parquet(attempts_path)
    with pytest.raises(ValueError, match="B1V3_B1Q_SOURCE_TARGET_COLUMN_FORBIDDEN"):
        _seal(paths)

    paths = _fixture(tmp_path / "future")
    attempts_path = paths.attempts_path
    attempts = pl.read_parquet(attempts_path).with_columns(
        (pl.col("forecast_origin_ns") + 1).alias("sip_timestamp")
    )
    attempts.write_parquet(attempts_path)
    with pytest.raises(ValueError, match="B1V3_B1Q_SOURCE_FUTURE_QUOTE"):
        _seal(paths)


def test_sealer_rejects_cache_tamper_and_conflicting_output(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    cache_path = next(paths.cache_root.glob("*.json"))
    cache = json.loads(cache_path.read_text(encoding="utf-8"))
    cache["source_request_hash"] = "f" * 64
    _write_json(cache_path, cache)
    with pytest.raises(ValueError, match="B1V3_B1Q_SOURCE_CACHE_INVALID"):
        _seal(paths)

    paths = _fixture(tmp_path / "conflict")
    _seal(paths)
    manifest_path = paths.manifest_path
    manifest_path.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="B1V3_B1Q_SOURCE_OUTPUT_CONFLICT"):
        _seal(paths)


def test_sealer_rejects_duplicate_attempt_identity(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    attempts_path = paths.attempts_path
    attempts = pl.read_parquet(attempts_path)
    pl.concat([attempts, attempts.head(1)]).write_parquet(attempts_path)
    with pytest.raises(ValueError, match="B1V3_B1Q_SOURCE_ATTEMPT_DUPLICATE"):
        _seal(paths)


@pytest.mark.parametrize(
    ("column", "value", "code"),
    [
        ("rate_source_date", "2024-08-02", "RATE_NOT_PRE_ORIGIN"),
        ("source_request_hash", "bad", "REQUEST_HASH_INVALID"),
        ("asset", "SPY", "ATTEMPT_ASSET_SCOPE_INVALID"),
    ],
)
def test_sealer_rejects_invalid_attempt_provenance(
    tmp_path: Path,
    column: str,
    value: object,
    code: str,
) -> None:
    paths = _fixture(tmp_path)
    attempts = pl.read_parquet(paths.attempts_path).with_columns(
        pl.lit(value).alias(column)
    )
    attempts.write_parquet(paths.attempts_path)

    with pytest.raises(ValueError, match=f"B1V3_B1Q_SOURCE_{code}"):
        _seal(paths)


def test_sealer_rejects_contract_grid_drift_and_unverified_pagination(
    tmp_path: Path,
) -> None:
    paths = _fixture(tmp_path)
    grid = json.loads(paths.contract_grid_path.read_text(encoding="utf-8"))
    grid["records"][0]["contracts"][0]["strike"] = 99.0
    _write_json(paths.contract_grid_path, grid)
    with pytest.raises(ValueError, match="B1V3_B1Q_SOURCE_CONTRACT_METADATA_MISMATCH"):
        _seal(paths)

    paths = _fixture(tmp_path / "pagination")
    cache_path = next(paths.cache_root.glob("*.json"))
    cache = json.loads(cache_path.read_text(encoding="utf-8"))
    cache["pagination_complete"] = False
    _write_json(cache_path, cache)
    with pytest.raises(ValueError, match="B1V3_B1Q_SOURCE_CACHE_INVALID"):
        _seal(paths)


def test_sealer_rejects_base_hash_and_cache_identity_ambiguity(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    base = json.loads(paths.base_manifest_path.read_text(encoding="utf-8"))
    base["origin_count"] = 999
    _write_json(paths.base_manifest_path, base)
    with pytest.raises(ValueError, match="B1V3_B1Q_SOURCE_BASE_MANIFEST_HASH_INVALID"):
        _seal(paths)

    paths = _fixture(tmp_path / "ambiguous")
    cache_path = next(paths.cache_root.glob("*.json"))
    duplicate = cache_path.with_name(f"{cache_path.stem.rsplit('_', 1)[0]}_ffffffffffffffff.json")
    duplicate.write_bytes(cache_path.read_bytes())
    with pytest.raises(ValueError, match="B1V3_B1Q_SOURCE_CACHE_FILE_AMBIGUOUS"):
        _seal(paths)


def test_sealer_rejects_inventory_conflict_and_missing_schema(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    _seal(paths)
    pl.DataFrame({"broken": [1]}).write_parquet(paths.inventory_path)
    with pytest.raises(ValueError, match="B1V3_B1Q_SOURCE_OUTPUT_CONFLICT"):
        _seal(paths)

    paths = _fixture(tmp_path / "schema")
    with pytest.raises(ValueError, match="B1V3_CONFIRMATION_SCHEMA_MISSING"):
        seal_b1q_source(
            inputs=paths.inputs,
            base_manifest_path=paths.base_manifest_path,
            origins_path=paths.origins_path,
            attempts_path=paths.attempts_path,
            contract_grid_path=paths.contract_grid_path,
            cache_root=paths.cache_root,
            inventory_path=paths.inventory_path,
            manifest_path=paths.manifest_path,
            manifest_schema_path=tmp_path / "missing.schema.json",
        )
