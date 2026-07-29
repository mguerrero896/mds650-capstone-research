"""Contracts for the local-only Phase 5 timing-sensitivity sidecar."""

from __future__ import annotations

import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import polars as pl
import pytest

from mds650.stability import b2_sensitivity_column
from mds650.study_design import B2_FEATURE_NAMES

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import build_phase5_stability_inputs as builder  # noqa: E402


def _event(
    event_id: str,
    executed_at: datetime,
    *,
    created_at: datetime | None = None,
    premium: float = 100.0,
) -> dict[str, object]:
    return {
        "id": event_id,
        "underlying_symbol": "AAPL",
        "option_chain_id": f"O:AAPL{event_id}",
        "executed_at": executed_at,
        "created_at": created_at or executed_at,
        "nbbo_bid": 0.9,
        "nbbo_ask": 1.1,
        "price": 1.0,
        "size": 1.0,
        "premium": premium,
        "expiry": date(2026, 8, 21),
        "strike": 200.0,
        "option_type": "call",
        "tags": "ask_side",
        "implied_volatility": 0.2,
    }


def test_stability_sidecar_enforces_each_operational_cutoff(tmp_path: Path) -> None:
    day = "2026-07-13"
    origin = datetime(2026, 7, 13, 14, 35, tzinfo=UTC)
    event_root = tmp_path / "events"
    partition = event_root / f"date={day}" / "asset=AAPL"
    partition.mkdir(parents=True)
    pl.DataFrame(
        [
            _event("early300", origin - timedelta(minutes=9)),
            _event("eligible120", origin - timedelta(minutes=3)),
            _event("future120", origin - timedelta(minutes=1)),
        ]
    ).write_parquet(partition / "events.parquet")
    panel = pl.DataFrame(
        {
            "origin_id": [f"AAPL|{day}|09:35", f"AAPL|{day}|09:40"],
            "asset": ["AAPL", "AAPL"],
            "session_date": [day, day],
            "forecast_origin_utc": [origin, origin + timedelta(minutes=5)],
            "b0_spot": [200.0, 201.0],
            "b2_source_hash": ["a" * 64, "a" * 64],
            "rv30": [0.1, 0.2],
        }
    )

    sidecar, evidence = builder.build_stability_inputs(
        panel,
        event_root=event_root,
        selected_assets=("AAPL",),
    )
    repeated, repeated_evidence = builder.build_stability_inputs(
        panel,
        event_root=event_root,
        selected_assets=("AAPL",),
    )

    first = sidecar.sort("origin_id").row(0, named=True)
    assert sidecar.height == 2
    assert sidecar["origin_id"].n_unique() == 2
    assert "rv30" not in sidecar.columns
    assert first[b2_sensitivity_column(B2_FEATURE_NAMES[0], 120)] == pytest.approx(
        0.6931471805599453
    )
    assert first[b2_sensitivity_column(B2_FEATURE_NAMES[0], 300)] == pytest.approx(
        0.6931471805599453
    )
    assert first["b2_window_end__120s"] == origin - timedelta(seconds=120)
    assert first["b2_window_end__300s"] == origin - timedelta(seconds=300)
    assert first["b2_max_operational_time__120s"] <= first["b2_window_end__120s"]
    assert first["b2_max_operational_time__300s"] <= first["b2_window_end__300s"]
    assert evidence["origin_count"] == 2
    assert evidence["delays_seconds"] == [120, 300]
    assert evidence["source_file_count"] == 1
    assert sidecar.equals(repeated)
    assert evidence == repeated_evidence
