"""Contract checks for the explicitly non-historical fixture preview."""

from __future__ import annotations

import json
from pathlib import Path

import polars as pl

ROOT = Path(__file__).parents[2]
PREVIEW = ROOT / "artifacts" / "pilot_preview" / "fixture_20260721"


def test_fixture_preview_is_not_authorized_or_historical() -> None:
    """The preview must never masquerade as provider backfill evidence."""
    manifest = json.loads((PREVIEW / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["mode"] == "fixture_preview"
    assert manifest["fixture_data_only"] is True
    assert manifest["synthetic_data_used"] is True
    assert manifest["historical_provider_backfill"] is False
    assert manifest["authorized_for_backfill"] is False
    assert manifest["b1_status"] == "BLOCKED"


def test_fixture_preview_has_eight_assets_and_exact_rv30_shape() -> None:
    """The preview preserves natural event labels and the 31-price RV30 contract."""
    manifest = json.loads((PREVIEW / "manifest.json").read_text(encoding="utf-8"))
    assert len(manifest["candidate_assets"]) == 8
    assert len(manifest["frozen_assets"]) == 6
    assert manifest["target_contract"] == {
        "anchor_plus_future_closes": 31,
        "formula_version": "rv30-v1",
        "future_log_returns": 30,
    }
    targets = pl.read_parquet(PREVIEW / "rv30_targets.parquet")
    traces = pl.read_parquet(PREVIEW / "row_trace.parquet")
    assert targets.height == manifest["row_counts"]["rv30_targets"]
    assert traces.height == targets.height
    assert targets["future_close_count"].unique().to_list() == [30]
    assert traces.select("option_state_count").to_series().unique().to_list() == [0, 1]
    assert traces.select("trade_count").to_series().unique().to_list() == [0, 1]
    assert traces.select("quote_count").to_series().unique().to_list() == [0, 1]
