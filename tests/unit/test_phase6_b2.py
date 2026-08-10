from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import polars as pl
import pytest

from mds650.phase6 import (
    B2V2_FEATURES,
    aggregate_b2_activity,
    b2_activity_checkpoint_valid,
    build_b2v2_features,
    build_b2v2_from_activity,
    robust_prior_deviation,
)


def _frames(days: int = 22) -> tuple[pl.DataFrame, pl.DataFrame]:
    origins: list[dict[str, object]] = []
    activity: list[dict[str, object]] = []
    start = date(2025, 7, 7)
    for index in range(days):
        day = start + timedelta(days=index)
        origin = datetime(day.year, day.month, day.day, 14, 0, tzinfo=UTC)
        origin_id = f"AAPL:{origin.isoformat()}"
        count = float(index + 1)
        origins.append(
            {
                "origin_id": origin_id,
                "asset": "AAPL",
                "session_date": day.isoformat(),
                "forecast_origin_utc": origin,
            }
        )
        activity.append(
            {
                "origin_id": origin_id,
                "asset": "AAPL",
                "session_date": day.isoformat(),
                "forecast_origin_utc": origin,
                "option_trade_count_5m": count,
                "unique_contract_count_5m": max(1.0, count / 2.0),
                "total_premium_5m": count * 100.0,
                "max_trade_premium_5m": count * 25.0,
                "call_premium_5m": count * 60.0,
                "put_premium_5m": count * 40.0,
                "ask_side_premium_share": 0.6,
                "bid_side_premium_share": 0.3,
                "repeated_contract_premium": count * 20.0,
                "strike_concentration": min(0.9, 0.2 + index / 100.0),
                "expiry_concentration": min(0.9, 0.3 + index / 100.0),
            }
        )
    return pl.DataFrame(activity), pl.DataFrame(origins)


def test_b2v2_has_exactly_nine_registered_features() -> None:
    activity, origins = _frames()

    result = build_b2v2_from_activity(activity, origins)

    assert len(B2V2_FEATURES) == 9
    assert set(result.columns) & set(B2V2_FEATURES) == set(B2V2_FEATURES)


def test_b2v2_never_uses_current_or_future_session_history() -> None:
    activity, origins = _frames()
    baseline = build_b2v2_from_activity(activity, origins)
    future_origin = origins.row(-1, named=True)["origin_id"]
    shocked = activity.with_columns(
        pl.when(pl.col("origin_id") == future_origin)
        .then(1_000_000.0)
        .otherwise(pl.col("option_trade_count_5m"))
        .alias("option_trade_count_5m")
    )

    changed = build_b2v2_from_activity(shocked, origins)

    assert baseline.filter(pl.col("origin_id") != future_origin).select(
        B2V2_FEATURES
    ).equals(changed.filter(pl.col("origin_id") != future_origin).select(B2V2_FEATURES))


def test_b2v2_builder_rejects_target_columns() -> None:
    activity, origins = _frames()

    with pytest.raises(ValueError, match="B2V2_TARGET_COLUMN_FORBIDDEN"):
        build_b2v2_from_activity(
            activity.with_columns(pl.lit(1.0).alias("rv30")), origins
        )


def test_b2v2_requires_twenty_prior_sessions() -> None:
    activity, origins = _frames()

    result = build_b2v2_from_activity(activity, origins).sort("session_date")

    assert result.head(20)["b2v2_complete"].sum() == 0
    assert result.tail(2)["b2v2_complete"].all()


def test_robust_prior_deviation_uses_mad_before_fallbacks() -> None:
    score, label = robust_prior_deviation([1.0, 2.0, 3.0], 4.0)

    assert score == pytest.approx((4.0 - 2.0) / 1.4826)
    assert label == "MAD_1_4826"


def test_b2v2_raw_builder_excludes_trade_created_after_cutoff() -> None:
    _, origins = _frames()
    trades = []
    for row in origins.iter_rows(named=True):
        origin = row["forecast_origin_utc"]
        trades.append(
            {
                "underlying_symbol": row["asset"],
                "session_date": row["session_date"],
                "executed_at": origin - timedelta(minutes=2),
                "created_at": origin - timedelta(seconds=90),
                "option_chain_id": f"O:{row['origin_id']}",
                "premium": 100.0,
                "option_type": "call",
                "tags": "ask_side",
                "strike": 100.0,
                "expiry": date.fromisoformat(row["session_date"]) + timedelta(days=30),
            }
        )
    baseline = build_b2v2_features(pl.DataFrame(trades), origins)
    last = origins.row(-1, named=True)
    future = {
        **trades[-1],
        "option_chain_id": "O:FUTURE",
        "premium": 1_000_000_000.0,
        "created_at": last["forecast_origin_utc"] + timedelta(seconds=1),
    }

    changed = build_b2v2_features(pl.DataFrame([*trades, future]), origins)

    assert baseline.select(B2V2_FEATURES).equals(changed.select(B2V2_FEATURES))


def test_b2v2_carries_per_origin_cutoff_evidence() -> None:
    _, origins = _frames(days=1)
    origin = origins.row(0, named=True)["forecast_origin_utc"]
    created_at = origin - timedelta(seconds=90)
    trades = pl.DataFrame(
        [
            {
                "underlying_symbol": "AAPL",
                "session_date": "2025-07-07",
                "executed_at": origin - timedelta(minutes=2),
                "created_at": created_at,
                "option_chain_id": "O:AAPL",
                "premium": 100.0,
                "option_type": "call",
                "tags": "ask_side",
                "strike": 100.0,
                "expiry": date(2025, 8, 15),
            }
        ]
    )

    result = build_b2v2_features(trades, origins)

    assert result["b2v2_cutoff_utc"].to_list() == [origin - timedelta(seconds=60)]
    assert result["b2v2_max_created_at_utc"].to_list() == [created_at]


def test_b2v2_fifteen_minute_window_maps_trade_to_three_origins() -> None:
    base = datetime(2025, 7, 7, 14, 0, tzinfo=UTC)
    origins = pl.DataFrame(
        [
            {
                "origin_id": f"AAPL:{index}",
                "asset": "AAPL",
                "session_date": "2025-07-07",
                "forecast_origin_utc": base + timedelta(minutes=5 * index),
            }
            for index in range(3)
        ]
    )
    trade = pl.DataFrame(
        [
            {
                "underlying_symbol": "AAPL",
                "session_date": "2025-07-07",
                "executed_at": base - timedelta(minutes=2),
                "created_at": base - timedelta(seconds=90),
                "option_chain_id": "O:AAPL",
                "premium": 100.0,
                "option_type": "call",
                "tags": "ask_side",
                "strike": 100.0,
                "expiry": date(2025, 8, 15),
            }
        ]
    )

    activity = aggregate_b2_activity(trade, origins, window_minutes=15)

    assert activity["option_trade_count_5m"].to_list() == [1.0, 1.0, 1.0]


def test_b2_checkpoint_requires_cutoff_evidence(tmp_path) -> None:
    activity, _ = _frames(days=1)
    stale = tmp_path / "stale.parquet"
    activity.write_parquet(stale)

    assert not b2_activity_checkpoint_valid(stale, expected_rows=1)

    valid = tmp_path / "valid.parquet"
    activity.with_columns(
        pl.lit(datetime(2025, 7, 7, 13, 59, tzinfo=UTC)).alias(
            "b2v2_cutoff_utc"
        ),
        pl.lit(datetime(2025, 7, 7, 13, 58, 30, tzinfo=UTC)).alias(
            "b2v2_max_created_at_utc"
        ),
    ).write_parquet(valid)

    assert b2_activity_checkpoint_valid(valid, expected_rows=1)

    future = tmp_path / "future.parquet"
    activity.with_columns(
        pl.lit(datetime(2025, 7, 7, 13, 59, tzinfo=UTC)).alias(
            "b2v2_cutoff_utc"
        ),
        pl.lit(datetime(2025, 7, 7, 13, 59, 1, tzinfo=UTC)).alias(
            "b2v2_max_created_at_utc"
        ),
    ).write_parquet(future)

    assert not b2_activity_checkpoint_valid(future, expected_rows=1)
