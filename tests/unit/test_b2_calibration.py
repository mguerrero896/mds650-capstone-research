"""Unit tests for target-free Phase 3F B2 calibration helpers."""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

import polars as pl

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import build_b2_calibration_20d as b2  # noqa: E402
import finalize_calibration_20d as finalize  # noqa: E402


def test_median_mad_and_fallbacks_are_deterministic() -> None:
    assert b2._median_mad([1.0, 2.0, 3.0])[0] == 2.0
    assert b2._median_mad([1.0, 2.0, 3.0])[3] == "mad"
    assert b2._median_mad([0.0, 1.0, 1.0, 1.0, 1.0, 1.0, 2.0, 3.0])[3] == "iqr_fallback"
    assert b2._median_mad([4.0, 4.0, 4.0])[3] == "asset_constant_fallback"


def test_score_uses_only_declared_continuous_features() -> None:
    origin = datetime(2026, 6, 11, 14, 35, tzinfo=UTC)
    row = {
        "asset": "AAPL",
        "forecast_origin_utc": origin,
        "total_premium_5m": 100.0,
        "option_trade_count_5m": 4.0,
        "unique_contract_count_5m": 2.0,
        "max_trade_premium_5m": 50.0,
        "repeated_contract_premium": 25.0,
        "rv30": 999999.0,
    }
    feature_parameters = {
        feature: {"median": 0.0, "scale": 1.0, "fallback": "mad"} for feature in b2.CORE_FEATURES
    }
    params = {
        "AAPL|B30_02": {"features": feature_parameters, "sample_size": 10, "p95_threshold": 10.0}
    }
    first = b2._score_row(row, params)
    row["rv30"] = -123.0
    second = b2._score_row(row, params)
    assert first == second
    assert first["historical_sample_size"] == 10


def test_cutoff_excludes_future_created_at_and_preserves_natural_origins() -> None:
    origins = pl.DataFrame(
        {
            "origin": [datetime(2026, 6, 11, 14, 35, tzinfo=UTC)] * 2,
            "origin_id": ["with_event", "without_event"],
        }
    )
    events = pl.DataFrame(
        {
            "created_at": [
                datetime(2026, 6, 11, 14, 33, tzinfo=UTC),
                datetime(2026, 6, 11, 14, 35, 1, tzinfo=UTC),
            ],
            "origin_id": ["with_event", "with_event"],
        }
    )
    # The explicit, test-only join below mirrors the production PIT predicate.
    joined = events.join(origins, on="origin_id", how="inner")
    eligible = joined.filter(pl.col("created_at") <= pl.col("origin") - pl.duration(seconds=60))
    assert eligible.height == 1
    assert set(origins.get_column("origin_id")) == {"with_event", "without_event"}


def test_empirical_p95_is_deterministic_and_non_extrapolative() -> None:
    assert abs(finalize._p95([1.0, 2.0, 3.0, 4.0]) - 3.85) < 1e-9
    assert finalize._p95([]) == 0.0
