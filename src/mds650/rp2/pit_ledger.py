"""Block 2 — Gate 1: operational point-in-time truth for the option tape.

Receipt latency is measured on the frozen tape as

``l_i = provider_created_at(i) - exchange_executed_at(i)``

and, for the live receipt campaign, as ``local_received_at - provider_created_at``.
Latencies span many orders of magnitude, so the pooled distribution is accumulated in
log-spaced bins rather than by holding hundreds of millions of values in memory.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

import numpy as np
import numpy.typing as npt

#: Log-spaced bin edges covering 100 us .. 10^7 s at 200 bins per decade.
LATENCY_DECADE_MIN: Final = -4.0
LATENCY_DECADE_MAX: Final = 7.0
LATENCY_BINS_PER_DECADE: Final = 200
LATENCY_BIN_COUNT: Final = int((LATENCY_DECADE_MAX - LATENCY_DECADE_MIN) * LATENCY_BINS_PER_DECADE)

#: Latency above this is treated as a backfilled / late-arriving record, not a live one.
BACKFILL_THRESHOLD_SECONDS: Final = 60.0
#: Multiplicative safety margin applied on top of the empirical P95.
CUTOFF_SAFETY_MULTIPLIER: Final = 2.0
#: The cutoff never drops below this, whatever the measurement says.
CUTOFF_FLOOR_SECONDS: Final = 60.0


def latency_bin_edges() -> npt.NDArray[np.float64]:
    """Return the fixed log-spaced bin edges, in seconds."""

    return np.logspace(
        LATENCY_DECADE_MIN, LATENCY_DECADE_MAX, LATENCY_BIN_COUNT + 1, dtype=np.float64
    )


@dataclass(frozen=True, slots=True)
class LatencySample:
    """Aggregate of one tape partition: counts plus a pooled-latency histogram."""

    rows: int
    non_positive: int
    over_backfill_threshold: int
    duplicate_id_rows: int
    cross_session_rows: int
    minimum_seconds: float
    maximum_seconds: float
    total_seconds: float
    histogram: npt.NDArray[np.int64]

    def merged_with(self, other: LatencySample) -> LatencySample:
        return LatencySample(
            rows=self.rows + other.rows,
            non_positive=self.non_positive + other.non_positive,
            over_backfill_threshold=self.over_backfill_threshold + other.over_backfill_threshold,
            duplicate_id_rows=self.duplicate_id_rows + other.duplicate_id_rows,
            cross_session_rows=self.cross_session_rows + other.cross_session_rows,
            minimum_seconds=min(self.minimum_seconds, other.minimum_seconds),
            maximum_seconds=max(self.maximum_seconds, other.maximum_seconds),
            total_seconds=self.total_seconds + other.total_seconds,
            histogram=self.histogram + other.histogram,
        )


def empty_sample() -> LatencySample:
    """Neutral element for :meth:`LatencySample.merged_with`."""

    return LatencySample(
        rows=0,
        non_positive=0,
        over_backfill_threshold=0,
        duplicate_id_rows=0,
        cross_session_rows=0,
        minimum_seconds=math.inf,
        maximum_seconds=-math.inf,
        total_seconds=0.0,
        histogram=np.zeros(LATENCY_BIN_COUNT, dtype=np.int64),
    )


def summarise_latencies(
    latency_seconds: npt.NDArray[np.float64],
    *,
    duplicate_id_rows: int = 0,
    cross_session_rows: int = 0,
) -> LatencySample:
    """Bin one array of latencies and record its edge statistics."""

    finite = latency_seconds[np.isfinite(latency_seconds)]
    positive = finite[finite > 0.0]
    counts, _ = np.histogram(positive, bins=latency_bin_edges())
    return LatencySample(
        rows=int(finite.size),
        non_positive=int(finite.size - positive.size),
        over_backfill_threshold=int(np.count_nonzero(finite > BACKFILL_THRESHOLD_SECONDS)),
        duplicate_id_rows=duplicate_id_rows,
        cross_session_rows=cross_session_rows,
        minimum_seconds=float(finite.min()) if finite.size else math.inf,
        maximum_seconds=float(finite.max()) if finite.size else -math.inf,
        total_seconds=float(finite.sum()),
        histogram=counts.astype(np.int64),
    )


def pooled_quantile(histogram: npt.NDArray[np.int64], quantile: float) -> float:
    """Quantile of the pooled distribution, interpolated inside its bin.

    Accurate to the bin width (0.5 % of the value at 200 bins per decade).
    """

    if not 0.0 < quantile < 1.0:
        raise ValueError("RP2_PIT_QUANTILE_OUT_OF_RANGE")
    total = int(histogram.sum())
    if total == 0:
        return math.nan
    target = quantile * total
    cumulative = np.cumsum(histogram)
    index = int(np.searchsorted(cumulative, target, side="left"))
    index = min(index, LATENCY_BIN_COUNT - 1)
    edges = latency_bin_edges()
    below = float(cumulative[index - 1]) if index > 0 else 0.0
    within = float(histogram[index])
    if within <= 0.0:
        return float(edges[index + 1])
    fraction = (target - below) / within
    low, high = math.log10(edges[index]), math.log10(edges[index + 1])
    return float(10.0 ** (low + fraction * (high - low)))


def recommended_cutoff_seconds(
    p95_seconds: float,
    *,
    multiplier: float = CUTOFF_SAFETY_MULTIPLIER,
    floor: float = CUTOFF_FLOOR_SECONDS,
) -> float:
    """Empirical B2 cutoff: ``max(floor, multiplier * P95)``, rounded up to a second."""

    if not math.isfinite(p95_seconds) or p95_seconds < 0.0:
        raise ValueError("RP2_PIT_P95_INVALID")
    return float(max(floor, math.ceil(multiplier * p95_seconds)))


def stability_verdict(session_p95: Sequence[float], *, tolerance: float = 3.0) -> bool:
    """P95 is stable when no session exceeds ``tolerance`` times the median session P95."""

    finite = [value for value in session_p95 if math.isfinite(value) and value > 0.0]
    if not finite:
        return False
    median = float(np.median(finite))
    return max(finite) <= tolerance * median


@dataclass(frozen=True, slots=True)
class SessionAdmissibility:
    """Whether one session's measured latency is compatible with a given B2 cutoff."""

    session: str
    p95_seconds: float
    backfill_share: float
    admissible: bool
    reason: str


def session_admissibility(
    session_stats: dict[str, dict[str, object]],
    *,
    cutoff_seconds: float,
    max_backfill_share: float = 0.01,
) -> list[SessionAdmissibility]:
    """Classify every session against the empirical cutoff and a backfill ceiling.

    A session is inadmissible when its own P95 latency exceeds the cutoff (the cutoff
    would not actually have made its data available) or when too large a share of its
    rows arrived after the backfill threshold.
    """

    verdicts: list[SessionAdmissibility] = []
    for session in sorted(session_stats):
        stats = session_stats[session]
        quantiles = stats["quantiles_seconds"]
        if not isinstance(quantiles, dict):
            raise ValueError("RP2_PIT_SESSION_STATS_MALFORMED")
        p95 = float(quantiles["p95"])
        backfill = float(str(stats["backfill_share"]))
        reasons: list[str] = []
        if not math.isfinite(p95) or p95 > cutoff_seconds:
            reasons.append("P95_ABOVE_CUTOFF")
        if backfill > max_backfill_share:
            reasons.append("BACKFILL_SHARE_ABOVE_CEILING")
        verdicts.append(
            SessionAdmissibility(
                session=session,
                p95_seconds=p95,
                backfill_share=backfill,
                admissible=not reasons,
                reason="+".join(reasons) if reasons else "OK",
            )
        )
    return verdicts
