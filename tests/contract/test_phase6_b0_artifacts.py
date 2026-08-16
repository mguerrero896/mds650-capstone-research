from __future__ import annotations

import json
from pathlib import Path

import polars as pl

from mds650.phase5_storage import sha256_file
from mds650.phase6 import B0V2_FEATURES, MARKET_CONTROLS, OUTCOME_ASSETS

ROOT = Path(__file__).resolve().parents[2]
PHASE6 = ROOT / "artifacts" / "phase6"
SSD = Path("D:/MDS650/phase6")


def test_phase6_fmp_manifest_is_complete_sanitized_and_hash_valid() -> None:
    path = PHASE6 / "fmp_manifest.json"
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
    bars_path = SSD / "data" / "fmp" / "underlying_1min_180d.parquet"
    assert sha256_file(bars_path) == manifest["bars_sha256"]


def test_phase6_b0_artifacts_preserve_pit_and_rv30_contract() -> None:
    bars = pl.read_parquet(SSD / "data" / "fmp" / "underlying_1min_180d.parquet")
    origins = pl.read_parquet(PHASE6 / "origins.parquet")
    b0 = pl.read_parquet(PHASE6 / "b0v2.parquet")

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
