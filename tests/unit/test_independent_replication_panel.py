"""Offline contracts for the independent replication origin stage."""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import polars as pl

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import build_independent_replication_panel as panel  # noqa: E402


def test_replication_origins_are_frozen_and_outcome_free() -> None:
    window = json.loads(
        (ROOT / "artifacts/independent_replication/window_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    frame = panel._origins(window)
    assert frame.height == 38664
    assert frame["origin_id"].n_unique() == frame.height
    assert frame["asset"].n_unique() == 6
    assert frame["session_date"].n_unique() == 90
    assert set(frame["role"].unique().to_list()) == {"warmup", "target"}
    assert not {name.lower() for name in frame.columns} & {"rv30", "qlike", "target"}


def test_replication_origin_dates_match_frozen_allow_list() -> None:
    window = json.loads(
        (ROOT / "artifacts/independent_replication/window_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    frame = panel._origins(window)
    assert set(frame["session_date"].unique().to_list()) == set(window["all_dates"])
    assert min(date.fromisoformat(value) for value in window["all_dates"]) == date(
        2025, 2, 25
    )


def test_persisted_origins_match_builder() -> None:
    path = Path("D:/MDS650/independent_replication_30/derived/origins_90d.parquet")
    assert path.is_file()
    persisted = pl.read_parquet(path).select(
        "origin_id", "asset", "session_date", "forecast_origin_utc", "role"
    )
    window = json.loads(
        (ROOT / "artifacts/independent_replication/window_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    expected = panel._origins(window).select(
        "origin_id", "asset", "session_date", "forecast_origin_utc", "role"
    )
    assert persisted.equals(expected)


def test_fmp_manifest_filters_provider_over_return_and_keeps_b0_warmup_only() -> None:
    fmp = json.loads(
        (ROOT / "artifacts/independent_replication/fmp_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    b0 = json.loads(
        (ROOT / "artifacts/independent_replication/b0_training_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert fmp["status"] == "PASS_FMP_EXACT_SESSION"
    assert fmp["record_count"] == 720
    assert all(record["requested_date"] in record["returned_dates"] for record in fmp["records"])
    assert b0["status"] == "PASS_B0_WARMUP_ONLY"
    assert b0["target_outcome_read"] is False
    assert b0["target_dates_read"] == []
