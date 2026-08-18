"""Shared bar loading: session-minute derivation, DST, and grid reindexing."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import polars as pl
import pytest

from mds650.rp2.bars import (
    SESSION_MINUTES,
    build_session_grid,
    load_bar_sources,
    normalise_bars,
)

NY = ZoneInfo("America/New_York")


def _frame(timestamps: list[datetime], column: str = "bar_start_utc", **extra: list[float]
           ) -> pl.DataFrame:
    data: dict[str, object] = {
        "asset": ["AAPL"] * len(timestamps),
        column: timestamps,
        "close": [100.0 + index for index in range(len(timestamps))],
    }
    data.update(extra)
    return pl.DataFrame(data).with_columns(
        pl.col(column).dt.replace_time_zone("UTC")
    )


def test_session_minutes_are_measured_from_the_new_york_open_in_summer() -> None:
    # 13:30 UTC is 09:30 in New York during daylight saving.
    frame = _frame([datetime(2026, 6, 15, 13, 30), datetime(2026, 6, 15, 13, 45)])
    out = normalise_bars(frame)
    assert out["minute"].to_list() == [0, 15]
    assert out["session_date"].to_list() == [
        datetime(2026, 6, 15).date(),
        datetime(2026, 6, 15).date(),
    ]


def test_session_minutes_survive_the_winter_offset() -> None:
    # The same 09:30 New York open is 14:30 UTC under EST. A fixed-UTC grid would
    # place this at minute 60 and silently truncate the session.
    frame = _frame([datetime(2026, 1, 15, 14, 30), datetime(2026, 1, 15, 20, 59)])
    out = normalise_bars(frame)
    assert out["minute"].to_list() == [0, SESSION_MINUTES - 1]


def test_bars_outside_the_regular_session_are_dropped() -> None:
    frame = _frame(
        [
            datetime(2026, 6, 15, 12, 0),   # pre-market
            datetime(2026, 6, 15, 13, 30),  # open
            datetime(2026, 6, 15, 20, 30),  # after close
        ]
    )
    assert normalise_bars(frame)["minute"].to_list() == [0]


def test_the_alternate_timestamp_column_is_accepted() -> None:
    frame = _frame([datetime(2026, 6, 15, 13, 30)], column="bar_timestamp_raw_utc")
    assert normalise_bars(frame)["minute"].to_list() == [0]


def test_optional_columns_are_carried_when_present_and_absent_when_not() -> None:
    timestamps = [datetime(2026, 6, 15, 13, 30)]
    rich = normalise_bars(_frame(timestamps, high=[101.0], low=[99.0], volume=[500.0]))
    assert {"high", "low", "volume"} <= set(rich.columns)
    lean = normalise_bars(_frame(timestamps))
    assert not {"high", "low", "volume"} & set(lean.columns)


def _write_source(root: Path, relative: str, timestamps: list[datetime]) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    _frame(timestamps).write_parquet(path)


def test_load_bar_sources_tags_role_and_source_and_skips_absent_files(tmp_path: Path) -> None:
    sources = (
        ("present", "D", "a/bars.parquet"),
        ("missing", "V", "b/bars.parquet"),
    )
    _write_source(tmp_path, "a/bars.parquet", [datetime(2026, 6, 15, 13, 30)])
    out = load_bar_sources(tmp_path, sources)
    assert out["source"].unique().to_list() == ["present"]
    assert out["role"].unique().to_list() == ["D"]


def test_load_bar_sources_refuses_an_empty_selection(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="RP2_BARS_NO_SOURCES"):
        load_bar_sources(tmp_path, (("absent", "D", "nowhere.parquet"),))


def _group(minutes: list[int], closes: list[float], **extra: list[float]) -> pl.DataFrame:
    data: dict[str, object] = {"minute": minutes, "close": closes}
    data.update(extra)
    return pl.DataFrame(data)


def test_session_grid_forward_fills_prices_and_zero_fills_volume() -> None:
    grid = build_session_grid(
        _group([0, 3], [100.0, 103.0], high=[101.0, 104.0], low=[99.0, 102.0],
               volume=[10.0, 30.0])
    )
    # Minutes 1 and 2 were absent: price carries forward, volume is zero.
    assert grid.close[0:4].tolist() == [100.0, 100.0, 100.0, 103.0]
    assert grid.volume[0:4].tolist() == [10.0, 0.0, 0.0, 30.0]
    # The tail after the last observed minute also carries forward.
    assert grid.close[-1] == pytest.approx(103.0)
    assert grid.fill_share == pytest.approx((SESSION_MINUTES - 2) / SESSION_MINUTES)


def test_session_grid_backfills_a_late_open() -> None:
    grid = build_session_grid(_group([5], [100.0]))
    # Nothing before minute 5 was observed; the first known price is carried back.
    assert grid.close[0] == pytest.approx(100.0)
    assert np.isfinite(grid.close).all()


def test_session_grid_substitutes_close_for_missing_high_and_low() -> None:
    grid = build_session_grid(_group([0, 1], [100.0, 101.0]))
    assert grid.high[0:2].tolist() == [100.0, 101.0]
    assert grid.low[0:2].tolist() == [100.0, 101.0]
    assert grid.volume.sum() == 0.0
