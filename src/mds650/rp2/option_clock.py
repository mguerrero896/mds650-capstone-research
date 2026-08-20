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
        """Provider latency: availability minus execution."""

        return np.asarray((self.created_us - self.executed_us) / MICROSECONDS, dtype=np.float64)

    @property
    def late_arrivals(self) -> BoolArray:
        return self.latency_seconds > LATE_ARRIVAL_SECONDS

    def visible_upto(self, cutoff_us: int) -> int:
        """Index one past the last row the provider had published by ``cutoff_us``.

        ``created_us`` must be sorted ascending; the tape is read in provider order.
        """

        return int(np.searchsorted(self.created_us, cutoff_us, side="right"))

    def economic_seconds(self) -> FloatArray:
        """Seconds since the session's first execution, on the exchange clock."""

        if self.executed_us.size == 0:
            return np.empty(0, dtype=np.float64)
        return np.asarray(
            (self.executed_us - self.executed_us[0]) / MICROSECONDS, dtype=np.float64
        )


def expiry_close_timestamps(expiry_dates: npt.NDArray[np.datetime64], market_tz: str) -> IntArray:
    """UTC microsecond stamp of the 16:00 close on each contract's expiry date.

    Built once per session: the exact-tenor arithmetic then costs one subtraction per trade
    instead of a timezone conversion.
    """

    zone = ZoneInfo(market_tz)
    unique, inverse = np.unique(expiry_dates, return_inverse=True)
    stamps = np.array(
        [
            int(
                np.datetime64(
                    datetime.combine(day.astype("datetime64[D]").astype(date), EXPIRY_CLOSE)
                    .replace(tzinfo=zone)
                    .astimezone(UTC)
                    .replace(tzinfo=None),
                    "us",
                ).astype(np.int64)
            )
            for day in unique
        ],
        dtype=np.int64,
    )
    return stamps[inverse]


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
