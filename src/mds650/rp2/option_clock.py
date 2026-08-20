"""The two clocks an option trade carries, and what each of them is for.

``executed_at`` is when the trade happened at the exchange. ``created_at`` is when the
provider made it visible. They answer different questions and are not interchangeable:

* **availability** — which rows a forecast origin may read — is ``created_at``, because that
  is what a forecaster could actually have seen;
* **economics** — spot as-of, Greeks, time to expiry, interarrivals, intensity — is
  ``executed_at``, because that is when the market moved.

Measuring economics on the availability clock turns provider behaviour into market
behaviour: a provider flushing a backlog reads as a burst of trading, and a batched print is
priced against whatever the underlying happened to be doing when the batch was published.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from typing import Final
from zoneinfo import ZoneInfo

import numpy as np
import numpy.typing as npt

type FloatArray = npt.NDArray[np.float64]
type IntArray = npt.NDArray[np.int64]
type BoolArray = npt.NDArray[np.bool_]

MICROSECONDS: Final = 1_000_000
#: Julian year, so a tenor in years is the unit the Black-Scholes inputs assume.
SECONDS_PER_YEAR: Final = 365.25 * 24 * 3600
#: US option contracts expire at the close of the expiry session.
EXPIRY_CLOSE: Final = time(16, 0)
#: A print published later than this after its execution is a late arrival.
LATE_ARRIVAL_SECONDS: Final = 60.0


@dataclass(frozen=True, slots=True)
class OptionClocks:
    """Both timestamps of every tape row, in microseconds, plus the gap between them."""

    executed_us: IntArray
    created_us: IntArray

    def __post_init__(self) -> None:
        if self.executed_us.shape != self.created_us.shape:
            raise ValueError("RP2_CLOCK_SHAPE_MISMATCH")

    @property
    def latency_seconds(self) -> FloatArray:
        """Record-creation lag: the availability stamp minus the exchange stamp.

        Not a measurement of the provider's delivery pipe.
        ``docs/provider_timing_pit_contract_v22.md`` establishes ``created_at`` as an
        operational record-creation proxy rather than a proven publication or receipt time,
        so using it as an availability bound is conservative and reading it as provider
        behaviour is a claim this dataset cannot support.
        """

        return np.asarray((self.created_us - self.executed_us) / MICROSECONDS, dtype=np.float64)

    @property
    def late_arrivals(self) -> BoolArray:
        return self.latency_seconds > LATE_ARRIVAL_SECONDS

    @property
    def execution_order(self) -> IntArray:
        """Positions that put the tape in execution order, keeping ties as published."""

        return np.argsort(self.executed_us, kind="stable").astype(np.int64)

    @property
    def is_reordered(self) -> bool:
        """True when latency put a later trade on the tape before an earlier one.

        The tape arrives in publication order. Where that differs from execution order,
        anything computed by subtracting neighbours — an interarrival gap, an
        exponential-decay intensity — sees a negative step and the decay becomes growth.
        """

        return bool(self.executed_us.size and np.any(np.diff(self.executed_us) < 0))

    def visible_upto(self, cutoff_us: int) -> int:
        """Index one past the last row the provider had published by ``cutoff_us``.

        ``created_us`` must be sorted ascending; the tape is read in provider order.
        """

        return int(np.searchsorted(self.created_us, cutoff_us, side="right"))

    def economic_seconds(self) -> FloatArray:
        """Seconds since the session's earliest execution, on the exchange clock.

        Measured from the minimum rather than from the first row, because the first row is
        the first *published* one and latency does not always preserve the order. The result
        stays in publication order, so it lines up with the point-in-time window slicing,
        and is never negative.
        """

        if self.executed_us.size == 0:
            return np.empty(0, dtype=np.float64)
        return np.asarray(
            (self.executed_us - self.executed_us.min()) / MICROSECONDS, dtype=np.float64
        )


def expiry_close_timestamps(expiry_dates: npt.NDArray[np.datetime64], market_tz: str) -> IntArray:
    """UTC microsecond stamp of the close on each contract's expiry session.

    The close comes from the exchange calendar, not from a fixed 16:00. A half-session —
    2025-11-28 in the study window, among others — closes at 13:00, and a hard-coded 16:00
    would hand every same-day contract three hours it never had, straight into the 0DTE
    Greeks this gate exists to get right. A date the exchange did not trade falls back to
    the regular close, which is the listing convention for a contract whose expiry lands on
    a non-session date.

    Built once per session: the exact-tenor arithmetic then costs one subtraction per trade
    instead of a timezone conversion.
    """

    from mds650.rp2.bars import session_close_minute

    zone = ZoneInfo(market_tz)
    unique, inverse = np.unique(expiry_dates, return_inverse=True)
    stamps = np.array(
        [_close_stamp(day.astype("datetime64[D]").astype(date), zone, session_close_minute)
         for day in unique],
        dtype=np.int64,
    )
    return stamps[inverse]


def _close_stamp(day: date, zone: ZoneInfo, close_minute: Callable[[date], int]) -> int:
    minutes = close_minute(day)
    closing = (
        time(minutes // 60, minutes % 60) if minutes > 0 else EXPIRY_CLOSE
    )
    return int(
        np.datetime64(
            datetime.combine(day, closing)
            .replace(tzinfo=zone)
            .astimezone(UTC)
            .replace(tzinfo=None),
            "us",
        ).astype(np.int64)
    )


def time_to_expiry_years(expiry_close_us: IntArray, executed_us: IntArray) -> FloatArray:
    """Exact time to expiry from each trade's own execution stamp.

    The producer floored this at one day, so every 0DTE contract — the ones whose whole
    behaviour is that they have hours left — was priced as if it had a full day. The floor
    is gone: an expired contract reads as a non-positive tenor and the caller decides what
    to do with it, rather than being silently rounded up into existence.
    """

    if expiry_close_us.shape != executed_us.shape:
        raise ValueError("RP2_CLOCK_SHAPE_MISMATCH")
    return np.asarray(
        (expiry_close_us - executed_us) / MICROSECONDS / SECONDS_PER_YEAR, dtype=np.float64
    )
