"""Source-binding tests for target-blind independent-replication B1Q caches."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import polars as pl

from mds650 import b1v3_b1q_source as source_core
from mds650.b1_replication_b1q_source import seal_replication_b1q_source
from mds650.b1v3_confirmation import canonical_sha256, sha256_file

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import build_b1v3_target_blind as b1_builder  # noqa: E402


def _fixture(tmp_path: Path) -> dict[str, Path]:
    assets = ("AAPL", "AMZN", "META", "MSFT", "NVDA", "TSLA")
    sessions = [
        (datetime(2024, 12, 10, tzinfo=UTC) + timedelta(days=index)).date().isoformat()
        for index in range(30)
    ]
    preregistration: dict[str, Any] = {
        "status": "FROZEN_BEFORE_PROVIDER_PAYLOAD",
        "target_blind": True,
        "replication_target_reads": 0,
        "safe_to_access_replication_targets": "NO",
        "result_sign_selection": "PROHIBITED",
        "replication_sessions": sessions,
    }
    preregistration["manifest_sha256"] = canonical_sha256(preregistration)
    preregistration_path = tmp_path / "preregistration.json"
    preregistration_path.write_text(json.dumps(preregistration), encoding="utf-8")

    rows = [
        {
            "origin_id": f"{asset}:{session}:001",
            "asset": asset,
            "session_date": session,
            "forecast_origin_utc": datetime(2024, 12, 10, 15, tzinfo=UTC),
            "spot": 100.0,
        }
        for session in sessions
        for asset in assets
    ]
    origins = pl.DataFrame(rows)
    origins_path = tmp_path / "origins.parquet"
    origins.write_parquet(origins_path)
    base: dict[str, Any] = {
        "status": "PASS_TARGET_BLIND_BASE_PREDICTORS",
        "target_blind": True,
        "outcome_read_count": 0,
        "safe_to_read_outcomes": False,
        "preregistration_sha256": preregistration["manifest_sha256"],
        "origin_count": origins.height,
        "origin_identity_sha256": source_core._origin_identity_sha256(origins),
        "outputs": {"b1_origins": {"sha256": sha256_file(origins_path)}},
    }
    base["manifest_sha256"] = canonical_sha256(base)
    base_path = tmp_path / "base.json"
    base_path.write_text(json.dumps(base), encoding="utf-8")
    attempts = tmp_path / "attempts.parquet"
    attempts.write_bytes(b"target-free-attempt-fixture")
    contract_grid = tmp_path / "contracts.json"
    contract_grid.write_text("{}", encoding="utf-8")
    cache_root = tmp_path / "cache"
    cache_root.mkdir()
    return {
        "preregistration": preregistration_path,
        "base": base_path,
        "origins": origins_path,
        "attempts": attempts,
        "contract_grid": contract_grid,
        "cache_root": cache_root,
        "inventory": tmp_path / "inventory.parquet",
        "manifest": tmp_path / "manifest.json",
        "schema": ROOT
        / "specs/001-pit-options-rv30/contracts/"
        "b1-independent-replication-b1q-source-v1.schema.json",
    }


def _patch_source_core(monkeypatch: Any, *, future_rows: int = 0) -> None:
    identities = pl.DataFrame(
        {
            "asset": ["AAPL"],
            "session_date": ["2024-12-10"],
            "contract": ["O:AAPL241220C00100000"],
            "source_request_hash": ["a" * 64],
        }
    )
    monkeypatch.setattr(
        source_core,
        "_validate_attempt_schema",
        lambda path: (
            sha256_file(path),
            tuple(f"column_{index}" for index in range(28)),
        ),
    )
    monkeypatch.setattr(
        source_core,
        "_load_and_validate_attempts",
        lambda _path, *, origins: (identities, 10, future_rows),
    )
    monkeypatch.setattr(
        source_core,
        "_load_contract_grid",
        lambda _path, *, origins, identities: (
            "c" * 64,
            180,
            {("AAPL", "2024-12-10", "O:AAPL241220C00100000"): {}},
        ),
    )
    inventory = pl.DataFrame(
        {
            "cache_bytes": [100],
            "quote_row_count": [5],
        }
    )
    monkeypatch.setattr(
        source_core,
        "_build_inventory",
        lambda *, cache_root, identities, contracts: inventory,
    )


def test_source_seal_is_accepted_by_b1v3_builder(
    tmp_path: Path, monkeypatch: Any
) -> None:
    paths = _fixture(tmp_path)
    _patch_source_core(monkeypatch)
    document = seal_replication_b1q_source(
        preregistration_path=paths["preregistration"],
        base_manifest_path=paths["base"],
        origins_path=paths["origins"],
        attempts_path=paths["attempts"],
        contract_grid_path=paths["contract_grid"],
        cache_root=paths["cache_root"],
        inventory_path=paths["inventory"],
        manifest_path=paths["manifest"],
        schema_path=paths["schema"],
    )

    binding = b1_builder._load_source_binding(
        input_sha256=sha256_file(paths["attempts"]),
        manifest_path=paths["manifest"],
        schema_path=paths["schema"],
        inventory_path=paths["inventory"],
    )
    assert document["status"] == "PASS_TARGET_BLIND_B1Q_SOURCE_BOUND"
    assert document["outcome_read_count"] == 0
    assert binding is not None


def test_source_seal_fails_when_a_future_quote_was_selected(
    tmp_path: Path, monkeypatch: Any
) -> None:
    paths = _fixture(tmp_path)
    _patch_source_core(monkeypatch, future_rows=1)
    try:
        seal_replication_b1q_source(
            preregistration_path=paths["preregistration"],
            base_manifest_path=paths["base"],
            origins_path=paths["origins"],
            attempts_path=paths["attempts"],
            contract_grid_path=paths["contract_grid"],
            cache_root=paths["cache_root"],
            inventory_path=paths["inventory"],
            manifest_path=paths["manifest"],
            schema_path=paths["schema"],
        )
    except ValueError as exc:
        assert str(exc) == "B1V3_CONFIRMATION_SCHEMA_VALIDATION_FAILED"
    else:
        raise AssertionError("future quote selection was accepted")
