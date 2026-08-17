"""Contract tests for HAR/HARQ feature construction and estimation."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import numpy as np
import polars as pl
import pytest

from mds650 import har


def _synthetic_bars(sessions: int = 8, minutes: int = 390) -> pl.DataFrame:
    rng = np.random.default_rng(21)
    rows = []
    for session in range(sessions):
        day = date(2026, 3, 2) + timedelta(days=session * (3 if session % 5 == 4 else 1))
        if day.weekday() >= 5:
            day += timedelta(days=7 - day.weekday())
        open_utc = datetime(day.year, day.month, day.day, 14, 30, tzinfo=UTC)
        price = 100.0
        for minute in range(minutes):
            price *= float(np.exp(rng.normal(0.0, 0.0008)))
            rows.append(("AAPL", open_utc + timedelta(minutes=minute), price))
    return pl.DataFrame(
        rows, schema=["asset", "bar_start_utc", "close"], orient="row"
    ).with_columns(pl.col("bar_start_utc").dt.replace_time_zone("UTC"))


def _origins(bars: pl.DataFrame) -> pl.DataFrame:
    sessions = sorted(
        bars.with_columns(pl.col("bar_start_utc").dt.date().alias("d"))["d"].unique().to_list()
    )
    rows = []
    for session in sessions:
        for minute in (60, 120, 180):
            origin = datetime(
                session.year, session.month, session.day, 14, 30, tzinfo=UTC
            ) + timedelta(minutes=minute)
            rows.append((f"{session}-{minute}", "AAPL", session, origin))
    return pl.DataFrame(
        rows,
        schema=["origin_id", "asset", "session_date", "forecast_origin_utc"],
        orient="row",
    ).with_columns(pl.col("forecast_origin_utc").dt.replace_time_zone("UTC"))


def test_features_have_expected_shape_and_positivity() -> None:
    bars = _synthetic_bars()
    origins = _origins(bars)
    features = har.build_har_features(bars, origins)
    assert features.height > 0
    assert set(har.HAR_COLUMNS).issubset(features.columns)
    assert har.HARQ_COLUMN in features.columns
    assert (features["rv_30m"].to_numpy() > 0).all()
    assert (features["rq_30m"].to_numpy() > 0).all()
    first_sessions = sorted(origins["session_date"].unique().to_list())[:5]
    assert not set(features["session_date"].unique().to_list()) & set(first_sessions)


def test_rv_window_uses_only_past_bars() -> None:
    bars = _synthetic_bars()
    origins = _origins(bars)
    features = har.build_har_features(bars, origins)
    row = features.sort("forecast_origin_utc").row(0, named=True)
    session_bars = bars.with_columns(
        pl.col("bar_start_utc").dt.date().alias("d")
    ).filter(pl.col("d") == row["session_date"])
    returns = (
        session_bars.sort("bar_start_utc")
        .with_columns(pl.col("close").log().diff().alias("r"))
        .drop_nulls("r")
        .filter(pl.col("bar_start_utc") < row["forecast_origin_utc"])
        .filter(
            pl.col("bar_start_utc")
            >= row["forecast_origin_utc"] - timedelta(minutes=30)
        )
    )
    manual = float((returns["r"].to_numpy() ** 2).sum())
    assert row["rv_30m"] == pytest.approx(manual, rel=1e-9)


def test_fit_and_predict_recover_signal() -> None:
    rng = np.random.default_rng(22)
    design = np.column_stack(
        [np.ones(500), rng.normal(0.0, 1.0, 500), rng.normal(0.0, 1.0, 500)]
    )
    truth = np.asarray([-10.0, 0.8, -0.3])
    log_target = design @ truth + rng.normal(0.0, 0.1, 500)
    fit = har.fit_log_ols(design, log_target)
    coefficients = np.asarray(fit["coefficients"])
    assert coefficients == pytest.approx(truth, abs=0.05)
    level = har.predict_level(design, coefficients, float(fit["sigma2"]))
    assert (level > 0).all()


def test_fit_contracts() -> None:
    with pytest.raises(ValueError, match="HAR_DESIGN_SHAPE_INVALID"):
        har.fit_log_ols(np.ones(5), np.ones(5))
    with pytest.raises(ValueError, match="HAR_DESIGN_UNDERDETERMINED"):
        har.fit_log_ols(np.ones((4, 3)), np.ones(4))
    degenerate = np.column_stack([np.ones(50), np.ones(50)])
    with pytest.raises(ValueError, match="HAR_DESIGN_RANK_DEFICIENT"):
        har.fit_log_ols(degenerate, np.ones(50))
    with pytest.raises(ValueError, match="HAR_SIGMA2_INVALID"):
        har.predict_level(np.ones((2, 1)), np.ones(1), -1.0)
