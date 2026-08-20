"""The two clocks: which one answers availability, and which one answers economics."""

from __future__ import annotations

import numpy as np
import pytest

from mds650.rp2.option_clock import (
    LATE_ARRIVAL_SECONDS,
    MICROSECONDS,
    SECONDS_PER_YEAR,
    OptionClocks,
    expiry_close_timestamps,
    time_to_expiry_years,
)

BASE = 1_800_000_000 * MICROSECONDS


def test_trade_is_unavailable_before_created_at() -> None:
    """Execution does not make a row readable; publication does."""

    clocks = OptionClocks(
        executed_us=np.array([BASE, BASE + 1 * MICROSECONDS], dtype=np.int64),
        created_us=np.array(
            [BASE + 90 * MICROSECONDS, BASE + 300 * MICROSECONDS], dtype=np.int64
        ),
    )
    # A cutoff after the first execution but before its publication sees nothing.
    assert clocks.visible_upto(BASE + 10 * MICROSECONDS) == 0
    assert clocks.visible_upto(BASE + 90 * MICROSECONDS) == 1
    assert clocks.visible_upto(BASE + 400 * MICROSECONDS) == 2


def test_provider_batching_does_not_create_economic_intensity() -> None:
    """Three trades a minute apart, published together, are not a burst."""

    executed = np.array([BASE, BASE + 60 * MICROSECONDS, BASE + 120 * MICROSECONDS], np.int64)
    published_together = np.full(3, BASE + 300 * MICROSECONDS, dtype=np.int64)
    clocks = OptionClocks(executed_us=executed, created_us=published_together)

    assert clocks.economic_seconds().tolist() == [0.0, 60.0, 120.0]
    # On the availability clock all three land on one instant: a burst that never happened.
    availability = (published_together - published_together[0]) / MICROSECONDS
    assert availability.tolist() == [0.0, 0.0, 0.0]


def test_latency_and_late_arrivals_come_from_the_gap() -> None:
    clocks = OptionClocks(
        executed_us=np.array([BASE, BASE], dtype=np.int64),
        created_us=np.array(
            [BASE + 30 * MICROSECONDS, BASE + 90 * MICROSECONDS], dtype=np.int64
        ),
    )
    assert clocks.latency_seconds.tolist() == [30.0, 90.0]
    assert clocks.late_arrivals.tolist() == [False, True]
    assert LATE_ARRIVAL_SECONDS == 60.0


def test_zero_dte_uses_fractional_time_until_expiry() -> None:
    """A contract expiring at this afternoon's close has hours left, not a floored day."""

    expiry = np.array(["2026-06-15", "2026-06-15"], dtype="datetime64[D]")
    closes = expiry_close_timestamps(expiry, "America/New_York")
    # 09:30 and one second before the close, on the expiry day itself.
    executed = np.array(
        [closes[0] - int(6.5 * 3600 * MICROSECONDS), closes[1] - MICROSECONDS], np.int64
    )
    years = time_to_expiry_years(closes, executed)

    assert years[0] * SECONDS_PER_YEAR == pytest.approx(6.5 * 3600)
    assert years[1] * SECONDS_PER_YEAR == pytest.approx(1.0)
    # The producer's one-day floor would have called both of these a full day.
    assert years.max() < 1.0 / 365.25
    assert (years > 0.0).all()


def test_an_expired_contract_reads_as_non_positive_rather_than_one_day() -> None:
    expiry = np.array(["2026-06-15"], dtype="datetime64[D]")
    closes = expiry_close_timestamps(expiry, "America/New_York")
    years = time_to_expiry_years(closes, closes + 3600 * MICROSECONDS)
    assert years[0] < 0.0


def test_the_clocks_refuse_mismatched_shapes() -> None:
    with pytest.raises(ValueError, match="RP2_CLOCK_SHAPE_MISMATCH"):
        OptionClocks(
            executed_us=np.array([1, 2], dtype=np.int64),
            created_us=np.array([1], dtype=np.int64),
        )
    with pytest.raises(ValueError, match="RP2_CLOCK_SHAPE_MISMATCH"):
        time_to_expiry_years(np.array([1], dtype=np.int64), np.array([1, 2], dtype=np.int64))


def test_latency_can_reorder_prints_and_the_economics_must_notice() -> None:
    """The tape arrives in publication order, which is not always execution order.

    A later trade published sooner puts a negative gap into every interarrival statistic
    computed by subtracting neighbours, and makes an exponential-decay intensity amplify
    instead of decay.
    """

    executed = np.array([BASE + 60 * MICROSECONDS, BASE], dtype=np.int64)
    created = np.array([BASE + 61 * MICROSECONDS, BASE + 62 * MICROSECONDS], dtype=np.int64)
    clocks = OptionClocks(executed_us=executed, created_us=created)

    assert clocks.is_reordered, "publication order differs from execution order here"
    assert clocks.execution_order.tolist() == [1, 0]
    # Seconds are measured from the earliest execution, so they are never negative even
    # though the array is in publication order.
    assert clocks.economic_seconds().tolist() == [60.0, 0.0]
    assert clocks.economic_seconds().min() == 0.0


def test_a_tape_in_execution_order_is_not_reordered() -> None:
    clocks = OptionClocks(
        executed_us=np.array([BASE, BASE + 60 * MICROSECONDS], dtype=np.int64),
        created_us=np.array(
            [BASE + MICROSECONDS, BASE + 61 * MICROSECONDS], dtype=np.int64
        ),
    )
    assert not clocks.is_reordered
    assert clocks.execution_order.tolist() == [0, 1]


def test_the_expiry_close_follows_the_exchange_calendar() -> None:
    """An early close is three hours the 0DTE tenor does not have."""

    from mds650.rp2.option_clock import expiry_close_timestamps

    normal = np.array(["2025-11-26"], dtype="datetime64[D]")
    early = np.array(["2025-11-28"], dtype="datetime64[D]")
    normal_close = expiry_close_timestamps(normal, "America/New_York")[0]
    early_close = expiry_close_timestamps(early, "America/New_York")[0]

    def minute_of_day(stamp: int) -> int:
        return int(stamp // MICROSECONDS // 60) % (24 * 60)

    assert minute_of_day(early_close) < minute_of_day(normal_close), (
        "2025-11-28 is an early close; a fixed 16:00 adds hours the contract never had"
    )
