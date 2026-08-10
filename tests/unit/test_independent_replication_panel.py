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
