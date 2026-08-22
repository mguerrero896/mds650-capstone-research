"""A store that never carried a column must not be handed fabricated values.

`load_bar_sources` concatenates six stores with `how="diagonal"`, so every store ends up
with the full schema and the two that hold only (asset, bar_start_utc, close) contribute
nulls for open, high, low and volume. `build_session_grid` then repaired every NaN
unconditionally: high and low from the close, volume from zero. That is right for a minute
in which nothing traded and wrong for a minute that traded and whose range was never
recorded.

Measured consequence on the published panel: parkinson_30, volume_30 and dollar_volume_30
are exactly 0.0 on 22,967 of 152,954 development origins and on 0 of 31,678 validation
origins. All three are declared `log` features, so zero maps to log(1e-12) = -27.631, and
because that is finite the missing-value machinery never fires and the fabrication is
indistinguishable from a measurement. The standardisation scales recorded in the published
ladder show it directly: dollar_volume_30 is 20.762 in development against 0.692 in
validation, while every honest feature differs between roles by less than a factor of two.

The discriminator is the close. A minute with no close had no bar, so a flat range and a
zero volume are the truth. A minute with a close but no high has a range that was never
recorded, and NaN is the only honest value.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import polars as pl

from mds650.rp2.bars import build_session_grid


def _group(minutes: list[int], **columns: list[float | None]) -> pl.DataFrame:
    return pl.DataFrame({"minute": minutes, **columns})


def test_a_store_without_high_low_volume_yields_unknown_not_zero() -> None:
    """Every minute has a bar; the source simply never carried the other columns."""
    group = _group(
        [0, 1, 2],
        close=[100.0, 101.0, 102.0],
        high=[None, None, None],
        low=[None, None, None],
        volume=[None, None, None],
    )

    grid = build_session_grid(group)

    assert np.isfinite(grid.close[:3]).all(), "the closes are present and must survive"
    assert np.isnan(grid.high[:3]).all(), (
        f"high came back as {grid.high[:3]}, so a range that was never recorded was "
        "fabricated from the close"
    )
    assert np.isnan(grid.low[:3]).all()
    assert np.isnan(grid.volume[:3]).all(), (
        f"volume came back as {grid.volume[:3]}; zero is a measurement, not an absence"
    )


def test_a_minute_with_no_bar_still_gets_a_flat_range_and_no_volume() -> None:
    """A gap is not the same as a missing column: nothing traded, so the truth is zero."""
    group = _group(
        [0, 2],
        close=[100.0, 102.0],
        high=[100.5, 102.5],
        low=[99.5, 101.5],
        volume=[1_000.0, 2_000.0],
    )

    grid = build_session_grid(group)

    # Minute 1 has no bar. The price carries forward, the range is flat, nothing traded.
    assert grid.close[1] == 100.0
    assert grid.high[1] == 100.0
    assert grid.low[1] == 100.0
    assert grid.volume[1] == 0.0
    # The minutes that do have bars keep their own values.
    assert grid.high[0] == 100.5
    assert grid.volume[2] == 2_000.0


def test_a_partial_store_is_repaired_only_where_the_bar_is_absent() -> None:
    """One source with the columns, one without, inside a single session."""
    group = _group(
        [0, 1, 3],
        close=[100.0, 101.0, 103.0],
        high=[100.5, None, 103.5],
        low=[99.5, None, 102.5],
        volume=[1_000.0, None, 3_000.0],
    )

    grid = build_session_grid(group)

    assert grid.high[0] == 100.5 and grid.volume[0] == 1_000.0
    assert np.isnan(grid.high[1]), "minute 1 traded; its range was never recorded"
    assert np.isnan(grid.volume[1])
    assert grid.high[2] == 101.0, "minute 2 had no bar at all, so its range is flat"
    assert grid.volume[2] == 0.0
    assert grid.high[3] == 103.5 and grid.volume[3] == 3_000.0


def test_a_volume_of_zero_on_a_minute_whose_price_moved_is_unknown() -> None:
    """A price cannot move without trades, so a zero there is an absence, not a count.

    The first repair keyed on a missing close and fixed the case where a STORE never
    carried the column. It left the case where the store carried the column and wrote
    exactly 0.0 for a minute that plainly traded. Measured across the six bar stores, 2,355
    of the 2,357 zero-volume minutes have `high > low`: AAPL on 2026-02-02 alone has 133
    consecutive such minutes, one of them opening 264.66, ranging 264.508 to 264.69 and
    closing 264.68 on a recorded volume of zero.

    volume_30 and dollar_volume_30 are `log` features, so a zero becomes -27.631 - finite,
    so no missing indicator fires and the fold-local imputation never runs, which is the
    same mechanism that made the baseline dishonest in the first place. It reached 2,958 of
    152,954 development origins and 0 of 31,678 validation ones, the same asymmetry the
    first repair was diagnosing.
    """
    group = _group(
        [0, 1, 2],
        close=[100.0, 101.0, 102.0],
        high=[100.5, 101.5, 102.0],
        low=[99.5, 100.5, 102.0],
        volume=[1_000.0, 0.0, 0.0],
    )

    grid = build_session_grid(group)

    assert grid.volume[0] == 1_000.0
    assert np.isnan(grid.volume[1]), (
        f"minute 1 ranged 100.5 to 101.5 on a recorded volume of {grid.volume[1]}; a price "
        "that moved had trades, so the zero is an absence rather than a count"
    )
    # Minute 2 did not move at all, so nothing contradicts a genuine zero.
    assert grid.volume[2] == 0.0


def test_a_flat_minute_with_no_volume_keeps_its_zero() -> None:
    """Two of the 2,357 are flat. A quiet minute really can trade nothing."""
    group = _group([0], close=[100.0], high=[100.0], low=[100.0], volume=[0.0])

    grid = build_session_grid(group)

    assert grid.volume[0] == 0.0


def test_the_volume_overlay_fills_only_the_contradicted_minutes(tmp_path) -> None:
    """A volume recovered from the second provider replaces a zero, never a measurement.

    2,343 minutes across the bar stores carry `volume == 0.0` with `high > low`. The
    second provider reports real volume on them - 53,676 shares across 809 trades on the
    AAPL minute the first records as empty - and 899 of them were recovered, taking the
    development test-fold coverage of `volume_30` from 0.8433 to 0.9205 against a 0.90
    floor. The overlay must touch those minutes and nothing else: a minute that genuinely
    reported zero on a flat price keeps its zero, and a minute with a real volume keeps
    the one its own store recorded even if the overlay disagrees.
    """
    import polars as pl

    from mds650.rp2.bars import VOLUME_REPAIR, apply_volume_repair

    stamp = datetime(2026, 6, 15, 13, 30, tzinfo=UTC)
    bars = pl.DataFrame(
        {
            "asset": ["AAPL"] * 3,
            "bar_ny": [
                (stamp + timedelta(minutes=index)).astimezone(ZoneInfo("America/New_York"))
                for index in range(3)
            ],
            "close": [100.0, 101.0, 102.0],
            "high": [100.5, 101.5, 102.0],
            "low": [99.5, 100.5, 102.0],
            "volume": [5_000.0, 0.0, 0.0],
        }
    )
    overlay = pl.DataFrame(
        {
            "asset": ["AAPL"] * 3,
            "bar_start_utc": [stamp + timedelta(minutes=index) for index in range(3)],
            "volume": [999_999.0, 42_000.0, 777_777.0],
        }
    )
    path = tmp_path / VOLUME_REPAIR
    path.parent.mkdir(parents=True, exist_ok=True)
    overlay.write_parquet(path)

    out = apply_volume_repair(bars, tmp_path).sort("bar_ny")

    assert out["volume"].to_list() == [5_000.0, 42_000.0, 0.0], (
        "the overlay must fill only the minute whose own bar contradicts its zero: minute 0 "
        "recorded a real volume and minute 2 was flat, so neither is a contradiction"
    )


def test_bars_load_unchanged_when_no_overlay_exists(tmp_path) -> None:
    """The repair is an input, not a requirement: without it the bars pass through."""
    import polars as pl

    from mds650.rp2.bars import apply_volume_repair

    bars = pl.DataFrame(
        {
            "asset": ["AAPL"],
            "bar_ny": [datetime(2026, 6, 15, 9, 30, tzinfo=ZoneInfo("America/New_York"))],
            "close": [100.0],
            "high": [100.5],
            "low": [99.5],
            "volume": [0.0],
        }
    )

    assert apply_volume_repair(bars, tmp_path).equals(bars)
