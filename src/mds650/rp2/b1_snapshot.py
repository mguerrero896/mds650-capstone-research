"""The contemporaneous option-state snapshot B1 is read from.

One place decides which tape rows are visible at a forecast origin and which observation
of each contract survives, so the point-in-time rule is stated once and tested once rather
than being re-derived inside the origin loop.

See `docs/rp2_v3/B1_CONTEMPORANEOUS_SPEC.md` for the frozen parameters.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

import numpy as np
import numpy.typing as npt

type FloatArray = npt.NDArray[np.float64]
type IntArray = npt.NDArray[np.int64]

MICROSECONDS: Final = 1_000_000
#: Provider availability lag established in Block 2: a row is visible this long after it
#: happened, so an origin may only read rows created at or before ``t - 120 s``.
CUTOFF_SECONDS: Final = 120
#: How stale a contract's last quote may be and still describe the state at the origin.
MAX_QUOTE_AGE_SECONDS: Final = 1_800
#: The relaxed bound used only for sensitivity, never for the primary panel.
SENSITIVITY_MAX_AGE_SECONDS: Final = 3_600


@dataclass(frozen=True, slots=True)
class SnapshotWindow:
    """The half-open interval of tape a single origin may read, in microseconds."""

    origin_us: int
    cutoff_us: int
    oldest_us: int

    @property
    def span_seconds(self) -> float:
        return (self.cutoff_us - self.oldest_us) / MICROSECONDS


@dataclass(frozen=True, slots=True)
class ContemporaneousSnapshot:
    """One observation per contract, the latest each had before the cutoff."""

    positions: IntArray
    quote_age_seconds: FloatArray
    window: SnapshotWindow

    @property
    def contracts(self) -> int:
        return int(self.positions.size)


def snapshot_window(
    origin_us: int,
    *,
    cutoff_seconds: int = CUTOFF_SECONDS,
    max_quote_age_seconds: int = MAX_QUOTE_AGE_SECONDS,
) -> SnapshotWindow:
    """The window ending at the availability cutoff, not one ending half an hour earlier.

    RP2-v2 ended this window 1 920 seconds before the origin so that B1 and B2 could not
    share a tape row. That made B1 the state of the option market half an hour ago, which
    is not what a contemporaneous snapshot means and not what the conditional contrast
    needs.
    """

    if cutoff_seconds < 0 or max_quote_age_seconds <= 0:
        raise ValueError("RP2_B1_WINDOW_INVALID")
    cutoff_us = origin_us - cutoff_seconds * MICROSECONDS
    return SnapshotWindow(
        origin_us=origin_us,
        cutoff_us=cutoff_us,
        oldest_us=cutoff_us - max_quote_age_seconds * MICROSECONDS,
    )


def latest_quote_per_contract(
    created: IntArray, keys: IntArray, window: SnapshotWindow
) -> ContemporaneousSnapshot:
    """Pick each contract's last observation inside the window.

    ``created`` must be sorted ascending; the tape is read in provider order and kept that
    way. Age is measured against the **forecast origin**, because the number a reader cares
    about is how stale the state is when the forecast is made — the availability cutoff is
    a floor on it, not the reference point.
    """

    if created.shape != keys.shape:
        raise ValueError("RP2_B1_SNAPSHOT_SHAPE_MISMATCH")
    if created.size and not bool(np.all(np.diff(created) >= 0)):
        raise ValueError("RP2_B1_SNAPSHOT_UNSORTED")

    high = int(np.searchsorted(created, window.cutoff_us, side="right"))
    low = int(np.searchsorted(created, window.oldest_us, side="left"))
    if high <= low:
        empty_int: IntArray = np.empty(0, dtype=np.int64)
        return ContemporaneousSnapshot(empty_int, np.empty(0, dtype=np.float64), window)

    # Scanning backwards makes the first occurrence of a key the latest observation of it.
    reversed_keys = keys[low:high][::-1]
    _, first = np.unique(reversed_keys, return_index=True)
    positions = np.sort(high - 1 - first).astype(np.int64)
    age = (window.origin_us - created[positions]) / MICROSECONDS
    return ContemporaneousSnapshot(positions, age.astype(np.float64), window)
