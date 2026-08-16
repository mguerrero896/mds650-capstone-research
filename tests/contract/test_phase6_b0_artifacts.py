"""Evidence contracts for the Phase 6 FMP acquisition and B0v2 features."""

from __future__ import annotations

import json
import os
from pathlib import Path

import polars as pl
import pytest
from tests.evidence import require_evidence_root

from mds650.phase5_storage import sha256_file
from mds650.phase6 import B0V2_FEATURES, MARKET_CONTROLS, OUTCOME_ASSETS

pytestmark = pytest.mark.evidence


def _phase6() -> Path:
    """Return the mounted evidence package for the Phase 6 base artifacts."""
    root = require_evidence_root(
        "artifacts/phase6/fmp_manifest.json",
        "artifacts/phase6/origins.parquet",
        "artifacts/phase6/b0v2.parquet",
    )
    return root / "artifacts" / "phase6"


def _bars_path() -> Path:
    """Return the bulk 180-session bar store without spilling onto C:."""
    data_root = Path(os.environ.get("MDS650_DATA_ROOT", "D:/MDS650"))
    path = data_root / "phase6" / "data" / "fmp" / "underlying_1min_180d.parquet"
    if not path.is_file():
        pytest.fail("MDS650_PHASE6_UNDERLYING_BARS_MISSING")
    return path


def test_phase6_fmp_manifest_is_complete_sanitized_and_hash_valid() -> None:
    path = _phase6() / "fmp_manifest.json"
    text = path.read_text(encoding="utf-8")
    manifest = json.loads(text)
    records = manifest["records"]

    assert manifest["status"] == "PASS"
    assert manifest["completed_record_count"] == 1_440
    assert manifest["authorized_record_count"] == 1_440
    assert len(records) == 1_440
    assert len({(row["asset"], row["session_date"]) for row in records}) == 1_440
    assert all(row["http_status"] == 200 and row["rows_exact"] > 0 for row in records)
    assert all(row["reused_existing"] is True for row in records)
    assert manifest["secret_values_emitted"] is False
    assert manifest["personal_paths_emitted"] is False
    assert "C:\\Users\\" not in text
    assert sha256_file(_bars_path()) == manifest["bars_sha256"]


def test_phase6_b0_artifacts_preserve_pit_and_rv30_contract() -> None:
    phase6 = _phase6()
    bars = pl.read_parquet(_bars_path())
    origins = pl.read_parquet(phase6 / "origins.parquet")
    b0 = pl.read_parquet(phase6 / "b0v2.parquet")

    assert bars.select(pl.struct("asset", "bar_timestamp_raw_utc").n_unique()).item() == bars.height
    assert bars["asset"].n_unique() == len((*OUTCOME_ASSETS, *MARKET_CONTROLS))
    assert bars["session_date"].n_unique() == 180
    assert bars.filter(
        pl.col("available_at_utc")
        != pl.col("bar_timestamp_raw_utc") + pl.duration(minutes=1)
    ).is_empty()
    assert origins.height == 77_328
    assert origins["origin_id"].n_unique() == origins.height
    assert b0.height == origins.height
    assert b0["origin_id"].n_unique() == b0.height
    assert set(B0V2_FEATURES).issubset(b0.columns)
    assert b0.filter(
        pl.col("max_predictor_available_at_utc").is_not_null()
        & (pl.col("max_predictor_available_at_utc") > pl.col("forecast_origin_utc"))
    ).is_empty()

    valid = b0.filter(pl.col("rv30").is_not_null())
    invalid = b0.filter(pl.col("rv30").is_null())
    assert valid.height > 0
    assert (valid["target_price_count"] == 31).all()
    assert (valid["target_return_count"] == 30).all()
    assert invalid["drop_reason"].is_in(
        ["RV30_ORIGIN_CLOSE_MISSING", "RV30_CONSECUTIVE_CLOSE_MISSING"]
    ).all()
    assert valid.filter(
        pl.col("drop_reason").str.starts_with("RV30_")
    ).is_empty()
