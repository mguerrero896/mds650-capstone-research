"""Bar loading: DST, true session lengths, and the ban on filling from the future."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import numpy as np
import polars as pl
import pytest

from mds650.rp2.bars import (
    FULL_SESSION_MINUTES,
    build_session_grid,
    is_early_close,
    load_bar_sources,
    normalise_bars,
    session_length_minutes,
    session_open_minute,
)


def _frame(
    timestamps: list[datetime], column: str = "bar_start_utc", **extra: list[float]
) -> pl.DataFrame:
    data: dict[str, object] = {
        "asset": ["AAPL"] * len(timestamps),
        column: timestamps,
        "close": [100.0 + index for index in range(len(timestamps))],
    }
    data.update(extra)
    return pl.DataFrame(data).with_columns(pl.col(column).dt.replace_time_zone("UTC"))


# --------------------------------------------------------------- calendar truth


def test_early_closes_are_shorter_than_a_full_session() -> None:
    # Day after Thanksgiving and Christmas Eve are 13:00 ET closes.
    assert session_length_minutes(date(2025, 11, 28)) == 210
    assert session_length_minutes(date(2025, 12, 24)) == 210
    assert is_early_close(date(2025, 11, 28))


def test_a_full_session_is_390_minutes_and_is_not_flagged_early() -> None:
    assert session_length_minutes(date(2026, 6, 15)) == FULL_SESSION_MINUTES
    assert not is_early_close(date(2026, 6, 15))


def test_a_holiday_has_no_session_rather_than_a_fabricated_one() -> None:
    assert session_length_minutes(date(2025, 12, 25)) == 0
    assert not is_early_close(date(2025, 12, 25))


def test_the_open_is_0930_new_york() -> None:
    assert session_open_minute(date(2026, 6, 15)) == 9 * 60 + 30


# ------------------------------------------------------------------ DST safety


def test_session_minutes_survive_both_sides_of_daylight_saving() -> None:
    # 13:30 UTC is 09:30 New York in summer; 14:30 UTC is 09:30 in winter. A fixed-UTC
    # grid places the winter open at minute 60 and truncates the session.
    summer = normalise_bars(_frame([datetime(2026, 6, 15, 13, 30)]))
    winter = normalise_bars(_frame([datetime(2026, 1, 15, 14, 30)]))
    assert summer["minute"].to_list() == [0]
    assert winter["minute"].to_list() == [0]


def test_premarket_bars_are_dropped() -> None:
    out = normalise_bars(_frame([datetime(2026, 6, 15, 12, 0), datetime(2026, 6, 15, 13, 30)]))
    assert out["minute"].to_list() == [0]


def test_the_alternate_timestamp_column_is_accepted() -> None:
    frame = _frame([datetime(2026, 6, 15, 13, 30)], column="bar_timestamp_raw_utc")
    assert normalise_bars(frame)["minute"].to_list() == [0]


def test_optional_columns_are_carried_when_present_and_absent_when_not() -> None:
    timestamps = [datetime(2026, 6, 15, 13, 30)]
    rich = normalise_bars(_frame(timestamps, high=[101.0], low=[99.0], volume=[500.0]))
    assert {"high", "low", "volume"} <= set(rich.columns)
    lean = normalise_bars(_frame(timestamps))
    assert not {"high", "low", "volume"} & set(lean.columns)


# ------------------------------------------------------- no fill from the future


def _group(minutes: list[int], closes: list[float], **extra: list[float]) -> pl.DataFrame:
    data: dict[str, object] = {"minute": minutes, "close": closes}
    data.update(extra)
    return pl.DataFrame(data)


def test_prices_carry_forward_into_minutes_with_no_trade() -> None:
    grid = build_session_grid(
        _group([0, 3], [100.0, 103.0], high=[101.0, 104.0], low=[99.0, 102.0], volume=[10.0, 30.0]),
        session=date(2026, 6, 15),
    )
    assert grid.close[0:4].tolist() == [100.0, 100.0, 100.0, 103.0]
    assert grid.volume[0:4].tolist() == [10.0, 0.0, 0.0, 30.0]
    assert grid.close[-1] == pytest.approx(103.0)


def test_a_late_open_is_marked_invalid_and_never_back_filled() -> None:
    """The defect this test exists for: filling minute 0 from the minute-5 price.

    That price did not exist at minute 0. Carrying it backwards leaks the future into
    every feature and every target computed at minutes 0 through 4.
    """

    grid = build_session_grid(_group([5, 6], [100.0, 101.0]), session=date(2026, 6, 15))
    assert not grid.valid[:5].any()
    assert np.isnan(grid.close[:5]).all()
    assert grid.valid[5:].all()
    assert grid.close[5] == pytest.approx(100.0)


def test_an_early_close_session_produces_a_short_grid() -> None:
    grid = build_session_grid(_group([0, 100], [100.0, 105.0]), session=date(2025, 11, 28))
    assert grid.minutes == 210
    assert grid.close.size == 210
    # A 390-minute grid would have invented 180 further minutes of flat price.
    assert grid.close[-1] == pytest.approx(105.0)


def test_bars_past_the_session_close_are_discarded() -> None:
    grid = build_session_grid(_group([0, 300], [100.0, 999.0]), session=date(2025, 11, 28))
    assert grid.minutes == 210
    # Minute 300 lies past a 13:00 close and must not appear anywhere in the grid.
    assert 999.0 not in grid.close.tolist()


def test_a_session_with_no_observations_is_entirely_invalid() -> None:
    grid = build_session_grid(_group([], []), session=date(2026, 6, 15))
    assert not grid.valid.any()
    assert grid.fill_share == pytest.approx(1.0)


def test_a_source_without_a_range_reports_it_as_unknown() -> None:
    """This assertion used to run the other way, and it pinned a defect as a feature.

    It required a source carrying only closes to have its high and low fabricated from the
    close and its volume set to zero. Two of the six bar stores carry exactly that schema,
    both in development, so parkinson_30, volume_30 and dollar_volume_30 came out exactly
    zero on 22,967 of 152,954 development origins and on none of the 31,678 validation
    ones. All three are `log` features: zero became log(1e-12) = -27.631, and being finite
    it recorded no missing indicator, so the fabrication could not be told from a
    measurement. The evidence is in the published ladder's own standardisation scales,
    where dollar_volume_30 is 20.762 in development against 0.692 in validation.

    A minute that had no bar keeps the old treatment - a flat range and no volume - because
    there the zero is the truth. See `tests/unit/test_rp2_bars_missing_columns.py`.
    """
    grid = build_session_grid(_group([0, 1], [100.0, 101.0]), session=date(2026, 6, 15))
    assert grid.close[0:2].tolist() == [100.0, 101.0]
    assert np.isnan(grid.high[0:2]).all()
    assert np.isnan(grid.low[0:2]).all()
    assert np.isnan(grid.volume[0:2]).all()
    # Minutes the source never reached still had no bar, so they stay repaired.
    assert grid.volume[2] == 0.0
    assert grid.high[2] == 101.0


# ------------------------------------------------------------------- source loading


def test_load_bar_sources_tags_role_and_source_and_skips_absent_files(tmp_path: Path) -> None:
    path = tmp_path / "a" / "bars.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    _frame([datetime(2026, 6, 15, 13, 30)]).write_parquet(path)
    out = load_bar_sources(
        tmp_path, (("present", "D", "a/bars.parquet"), ("missing", "V", "b/bars.parquet"))
    )
    assert out["source"].unique().to_list() == ["present"]
    assert out["role"].unique().to_list() == ["D"]


def test_load_bar_sources_refuses_an_empty_selection(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="RP2_BARS_NO_SOURCES"):
        load_bar_sources(tmp_path, (("absent", "D", "nowhere.parquet"),))


def test_overlapping_acquisitions_collapse_to_one_source_per_session() -> None:
    """The defect this pins: a re-acquired session appears twice in every panel built on it.

    Two campaigns overlapped on 24 early-close session-assets. Left alone the same origin
    is emitted twice, double-weighting it in every mean, bootstrap and regression
    downstream — and it stayed invisible only because a quality gate reading a fabricated
    390-minute grid was discarding exactly those sessions.
    """

    from mds650.rp2.bars import deduplicate_bar_sources

    shared = pl.DataFrame(
        {
            "asset": ["AAPL"] * 4,
            "session_date": [date(2024, 11, 29)] * 4,
            "minute": [0, 1, 0, 1],
            "close": [10.0, 11.0, 10.0, 11.0],
            "source": ["gate7_c6", "gate7_c6", "ext3_missing", "ext3_missing"],
        }
    )
    deduped = deduplicate_bar_sources(shared)
    assert deduped.height == 2
    assert deduped["source"].unique().to_list() == ["ext3_missing"]


def test_sources_that_disagree_on_a_price_fail_closed_instead_of_being_picked_between() -> None:
    """Choosing silently would hide a data-integrity failure behind a preference."""

    from mds650.rp2.bars import deduplicate_bar_sources

    conflicting = pl.DataFrame(
        {
            "asset": ["AAPL", "AAPL"],
            "session_date": [date(2024, 11, 29)] * 2,
            "minute": [0, 0],
            "close": [10.0, 10.5],
            "source": ["gate7_c6", "ext3_missing"],
        }
    )
    with pytest.raises(ValueError, match="RP2_BAR_SOURCES_DISAGREE"):
        deduplicate_bar_sources(conflicting)


def test_a_single_source_frame_is_returned_untouched() -> None:
    from mds650.rp2.bars import deduplicate_bar_sources

    single = pl.DataFrame(
        {
            "asset": ["AAPL", "AAPL"],
            "session_date": [date(2024, 11, 29)] * 2,
            "minute": [0, 1],
            "close": [10.0, 11.0],
            "source": ["gate7_c6", "gate7_c6"],
        }
    )
    assert deduplicate_bar_sources(single).height == 2
