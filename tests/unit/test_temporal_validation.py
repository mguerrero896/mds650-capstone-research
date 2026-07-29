"""Temporal split contracts for the preregistered Phase 5 study."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import polars as pl

from mds650.temporal_validation import (
    FoldDefinition,
    purge_and_embargo_training,
    split_expanding_fold,
    split_inner_validation,
)


def _session_frame(days: list[date]) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "session_date": [day.isoformat() for day in days],
            "forecast_origin_utc": [
                datetime.combine(day, datetime.min.time(), UTC)
                + timedelta(hours=15)
                for day in days
            ],
            "value": list(range(len(days))),
        }
    )


def test_purge_and_embargo_removes_overlapping_rv30_labels() -> None:
    test_start = datetime(2026, 6, 1, 15, 0, tzinfo=UTC)
    training = pl.DataFrame(
        {
            "forecast_origin_utc": [
                test_start - timedelta(minutes=90),
                test_start - timedelta(minutes=60),
                test_start - timedelta(minutes=55),
            ]
        }
    )

    filtered = purge_and_embargo_training(
        training,
        test_start,
        target_horizon_minutes=30,
        embargo_minutes=30,
    )

    assert filtered["forecast_origin_utc"].to_list() == [
        test_start - timedelta(minutes=90),
        test_start - timedelta(minutes=60),
    ]


def test_expanding_fold_uses_only_declared_train_and_test_dates() -> None:
    days = [
        date(2026, 5, 18),
        date(2026, 5, 19),
        date(2026, 5, 20),
        date(2026, 5, 21),
    ]
    fold = FoldDefinition(
        fold=1,
        train_end=date(2026, 5, 19),
        test_start=date(2026, 5, 20),
        test_end=date(2026, 5, 21),
    )

    training, testing = split_expanding_fold(_session_frame(days), fold)

    assert training["session_date"].to_list() == ["2026-05-18", "2026-05-19"]
    assert testing["session_date"].to_list() == ["2026-05-20", "2026-05-21"]
    assert set(training["session_date"].to_list()).isdisjoint(
        testing["session_date"].to_list()
    )


def test_inner_validation_is_last_training_history_only() -> None:
    days = [date(2026, 5, day) for day in range(11, 19)]

    fitting, validation = split_inner_validation(
        _session_frame(days),
        validation_sessions=2,
    )

    assert fitting["session_date"].unique().sort().to_list() == [
        day.isoformat() for day in days[:-2]
    ]
    assert validation["session_date"].unique().sort().to_list() == [
        day.isoformat() for day in days[-2:]
    ]
    assert fitting["forecast_origin_utc"].max() < validation[
        "forecast_origin_utc"
    ].min()
