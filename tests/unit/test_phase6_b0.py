from __future__ import annotations

from datetime import UTC, datetime, timedelta

import polars as pl
import pytest

from mds650.phase6 import build_b0v2_features, build_phase6_origins

ORIGIN = datetime(2026, 1, 5, 15, 5, tzinfo=UTC)
SESSION_DATE = "2026-01-05"


def _bars(*, missing_timestamp: datetime | None = None) -> pl.DataFrame:
    rows: list[dict[str, object]] = []
    first = datetime(2026, 1, 5, 14, 30, tzinfo=UTC)
    for asset_index, asset in enumerate(("AAPL", "SPY", "QQQ"), start=1):
        for minute in range(65):
            timestamp = first + timedelta(minutes=minute)
            if asset == "AAPL" and timestamp == missing_timestamp:
                continue
            close = 100.0 + 10.0 * asset_index + 0.05 * minute
            rows.append(
                {
                    "asset": asset,
                    "session_date": SESSION_DATE,
                    "bar_timestamp_raw_utc": timestamp,
                    "available_at_utc": timestamp + timedelta(minutes=1),
                    "close": close,
                    "volume": 1_000.0 + minute,
                }
            )
    return pl.DataFrame(rows)


def _origins() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "origin_id": [f"AAPL:{ORIGIN.isoformat()}"],
            "asset": ["AAPL"],
            "session_date": [SESSION_DATE],
            "forecast_origin_utc": [ORIGIN],
        }
    )


def _origin_at(origin: datetime) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "origin_id": [f"AAPL:{origin.isoformat()}"],
            "asset": ["AAPL"],
            "session_date": [SESSION_DATE],
            "forecast_origin_utc": [origin],
        }
    )


def test_b0v2_uses_only_available_bars_and_exact_rv30_prices() -> None:
    result = build_b0v2_features(_bars(), _origins())
    row = result.row(0, named=True)

    assert row["drop_reason"] is None
    assert row["target_price_count"] == 31
    assert row["target_return_count"] == 30
    assert row["max_predictor_available_at_utc"] <= row["forecast_origin_utc"]
    assert row["b0v2_spy_return_5m"] is not None
    assert row["b0v2_qqq_rv_30m"] is not None
    assert row["rv30"] > 0


def test_b0v2_two_minute_delay_changes_predictors_not_rv30() -> None:
    primary = build_b0v2_features(_bars(), _origins()).row(0, named=True)
    delayed_bars = _bars().with_columns(
        (pl.col("bar_timestamp_raw_utc") + pl.duration(minutes=2)).alias("available_at_utc")
    )

    delayed = build_b0v2_features(delayed_bars, _origins(), delay_minutes=2).row(0, named=True)

    assert delayed["drop_reason"] is None
    assert delayed["rv30"] == primary["rv30"]
    assert delayed["anchor_timestamp_raw_utc"] == ORIGIN - timedelta(minutes=1)
    assert delayed["predictor_anchor_timestamp_raw_utc"] == ORIGIN - timedelta(minutes=2)
    assert delayed["max_predictor_available_at_utc"] <= ORIGIN


def test_b0v2_delay_never_changes_target_when_predictor_history_is_short() -> None:
    early_origin = datetime(2026, 1, 5, 15, 1, tzinfo=UTC)
    primary = build_b0v2_features(_bars(), _origin_at(early_origin)).row(0, named=True)
    delayed = build_b0v2_features(
        _bars().with_columns(
            (pl.col("bar_timestamp_raw_utc") + pl.duration(minutes=2)).alias("available_at_utc")
        ),
        _origin_at(early_origin),
        delay_minutes=2,
    ).row(0, named=True)

    assert primary["target_price_count"] == delayed["target_price_count"] == 31
    assert primary["target_return_count"] == delayed["target_return_count"] == 30
    assert primary["rv30"] == delayed["rv30"]
    assert delayed["drop_reason"] == "B0V2_UNDERLYING_HISTORY_MISSING"


def test_missing_future_close_rejects_origin_without_interpolation() -> None:
    missing = ORIGIN + timedelta(minutes=7)
    result = build_b0v2_features(_bars(missing_timestamp=missing), _origins())
    row = result.row(0, named=True)

    assert row["drop_reason"] == "RV30_CONSECUTIVE_CLOSE_MISSING"
    assert row["rv30"] is None
    assert row["target_price_count"] == 30
    assert row["target_return_count"] == 0


def test_future_predictor_availability_fails_closed() -> None:
    bars = _bars().with_columns(
        pl.when(
            (pl.col("asset") == "AAPL")
            & (pl.col("bar_timestamp_raw_utc") == ORIGIN - timedelta(minutes=1))
        )
        .then(pl.col("available_at_utc") + timedelta(seconds=1))
        .otherwise(pl.col("available_at_utc"))
        .alias("available_at_utc")
    )

    with pytest.raises(ValueError, match="B0V2_ORIGIN_CLOSE_NOT_AVAILABLE"):
        build_b0v2_features(bars, _origins())


def test_origins_include_last_valid_time_and_respect_early_close() -> None:
    normal = build_phase6_origins(["2026-01-05"], assets=["AAPL"])
    early = build_phase6_origins(["2025-11-28"], assets=["AAPL"])

    assert normal.height == 72
    assert normal["forecast_origin_ny"].max().strftime("%H:%M") == "15:30"
    assert early.height == 36
    assert early["forecast_origin_ny"].max().strftime("%H:%M") == "12:30"


def test_zero_dollar_volume_drops_origin_without_imputation() -> None:
    bars = _bars().with_columns(
        pl.when(
            (pl.col("asset") == "AAPL")
            & (pl.col("bar_timestamp_raw_utc") >= ORIGIN - timedelta(minutes=5))
            & (pl.col("bar_timestamp_raw_utc") < ORIGIN)
        )
        .then(0.0)
        .otherwise(pl.col("volume"))
        .alias("volume")
    )

    row = build_b0v2_features(bars, _origins()).row(0, named=True)

    assert row["drop_reason"] == "B0V2_DOLLAR_VOLUME_NOT_POSITIVE"
    assert row["b0v2_log_dollar_volume_5m"] is None
