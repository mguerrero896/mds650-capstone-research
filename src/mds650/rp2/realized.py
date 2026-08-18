"""Block 3 - Gate 2: realized measures at several horizons.

For a window of ``h`` one-minute log returns the block needs realized variance, bipower
variation, the jump and continuous components, realized quarticity and the two
semivariances.  Everything is computed from prefix sums so that all origins of a session
and all horizons are obtained in one pass over the minute grid.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Final

import numpy as np
import numpy.typing as npt

type FloatArray = npt.NDArray[np.float64]

#: ``pi / 2`` scaling of the bipower estimator, as written in the program specification.
BIPOWER_SCALE: Final = math.pi / 2.0
#: Horizons compared in discovery, in minutes.
HORIZONS: Final[tuple[int, ...]] = (5, 15, 30, 60, 120)


@dataclass(frozen=True, slots=True)
class RealizedMeasures:
    """Forward realized measures over one window."""

    rv: FloatArray
    bipower: FloatArray
    jump: FloatArray
    continuous: FloatArray
    quarticity: FloatArray
    semivariance_up: FloatArray
    semivariance_down: FloatArray

    def as_dict(self) -> dict[str, FloatArray]:
        return {
            "rv": self.rv,
            "bv": self.bipower,
            "jump": self.jump,
            "continuous": self.continuous,
            "rq": self.quarticity,
            "rs_up": self.semivariance_up,
            "rs_down": self.semivariance_down,
        }


def log_returns(closes: FloatArray) -> FloatArray:
    """One-minute log returns from a strictly positive close series."""

    if closes.ndim != 1 or closes.size < 2:
        raise ValueError("RP2_RETURNS_SERIES_TOO_SHORT")
    if not np.isfinite(closes).all() or (closes <= 0.0).any():
        raise ValueError("RP2_RETURNS_PRICE_INVALID")
    return np.diff(np.log(closes))


def _prefix(values: FloatArray) -> FloatArray:
    out = np.zeros(values.size + 1, dtype=np.float64)
    np.cumsum(values, out=out[1:])
    return out


def forward_measures(
    returns: FloatArray, origin_indices: npt.NDArray[np.int64], horizon: int
) -> RealizedMeasures:
    """Realized measures over ``returns[i : i + horizon]`` for each origin index ``i``.

    ``origin_indices`` are positions in the return series, i.e. the first *future*
    return of the window.  Windows that would run past the end of the series are not
    permitted; the caller filters them.
    """

    if horizon <= 1:
        raise ValueError("RP2_HORIZON_TOO_SHORT")
    if origin_indices.size and int(origin_indices.max()) + horizon > returns.size:
        raise ValueError("RP2_WINDOW_EXCEEDS_SERIES")
    if origin_indices.size and int(origin_indices.min()) < 0:
        raise ValueError("RP2_WINDOW_NEGATIVE_INDEX")

    squared = _prefix(returns**2)
    quartic = _prefix(returns**4)
    up = _prefix(np.where(returns > 0.0, returns**2, 0.0))
    down = _prefix(np.where(returns < 0.0, returns**2, 0.0))
    # |r_j| |r_{j-1}| lives at position j; position 0 has no predecessor.
    absolute = np.abs(returns)
    adjacent = np.zeros_like(returns)
    adjacent[1:] = absolute[1:] * absolute[:-1]
    bipower_prefix = _prefix(adjacent)

    start = origin_indices
    stop = origin_indices + horizon
    rv = squared[stop] - squared[start]
    # The first product of each window needs the return immediately before it, which is
    # outside the window; the estimator therefore uses the horizon-1 interior products.
    bipower = BIPOWER_SCALE * (bipower_prefix[stop] - bipower_prefix[start + 1])
    jump = np.maximum(rv - bipower, 0.0)
    quarticity = (horizon / 3.0) * (quartic[stop] - quartic[start])
    return RealizedMeasures(
        rv=rv,
        bipower=bipower,
        jump=jump,
        continuous=rv - jump,
        quarticity=quarticity,
        semivariance_up=up[stop] - up[start],
        semivariance_down=down[stop] - down[start],
    )


def backward_rv(
    returns: FloatArray, origin_indices: npt.NDArray[np.int64], horizon: int
) -> FloatArray:
    """Realized variance over the ``horizon`` returns ending at each origin."""

    if origin_indices.size and int(origin_indices.min()) - horizon < 0:
        raise ValueError("RP2_WINDOW_NEGATIVE_INDEX")
    squared = _prefix(returns**2)
    return squared[origin_indices] - squared[origin_indices - horizon]


def relative_measurement_noise(
    rv: FloatArray, quarticity: FloatArray, horizon: int, *, floor: float = 1e-16
) -> FloatArray:
    """Barndorff-Nielsen-Shephard relative standard error ``sqrt(2 RQ / h) / RV``.

    This is the estimator's own sampling noise as a fraction of its level: the shorter
    the horizon, the noisier the target regardless of any model.
    """

    if horizon <= 0:
        raise ValueError("RP2_HORIZON_TOO_SHORT")
    denominator = np.maximum(rv, floor)
    return np.sqrt(np.maximum(2.0 * quarticity / horizon, 0.0)) / denominator
