"""Shared one-minute bar loading for Research Program v2.

Two invariants this module exists to enforce, both of which a naive implementation
violates silently:

**The session length is not a constant.** XNYS closes early on roughly nine days a year
(the day after Thanksgiving, Christmas Eve, July 3rd and similar). A fixed 390-minute grid
either truncates a full session or invents 180 minutes of flat price on a half day. The
length comes from the exchange calendar, per session.

**A bar may never be filled from the future.** Prices carry *forward* into minutes with no
trade. Minutes before the first observation of a session have no past to carry, so they stay
missing and the caller drops the origins that would have depended on them. Back-filling them
from the first observed price would leak that price backwards in time.

Session minutes are measured from the session's own open in America/New_York, never from a
fixed UTC hour: the UTC open shifts by an hour across daylight saving.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Final

import numpy as np
import numpy.typing as npt
import polars as pl

type FloatArray = npt.NDArray[np.float64]
type BoolArray = npt.NDArray[np.bool_]

#: Length of a full XNYS session. Used only as the upper bound of the minute grid; the
#: authoritative per-session length comes from :func:`session_length_minutes`.
FULL_SESSION_MINUTES: Final = 390
MARKET_TZ: Final = "America/New_York"
SESSION_OPEN_MINUTE: Final = 9 * 60 + 30
CALENDAR: Final = "XNYS"

#: ``(name, partition role, path relative to the store root)``, oldest window first.
BAR_SOURCES: Final[tuple[tuple[str, str, str], ...]] = (
    ("gate7_c6", "D", "data/fmp/gate7/underlying_1min_c6.parquet"),
    ("gate8_c4c", "D", "data/fmp/gate8_c4c/underlying_1min_c4c.parquet"),
    ("phase6_180d", "D", "phase6/data/fmp/underlying_1min_180d.parquet"),
    ("gate3_dev80", "V", "data/fmp/gate3/underlying_1min_dev80.parquet"),
    # The 153 tape sessions (2024-08-02..2025-12-24) that had no bars. Already-observed
    # eras, so Discovery only: they buy precision on the estimate, never confirmation.
    ("ext3_missing", "D", "data/fmp/rp2_ext3/underlying_1min_ext3.parquet"),
    # SPY and QQQ across the validation sessions. Without these, B0 carried market-wide
    # state in discovery and none in validation, so every D-versus-V contrast compared two
    # different baselines (decision 75).
    ("validation_market", "V", "data/fmp/rp2_validation_market/market_1min_validation.parquet"),
)

_OPTIONAL_COLUMNS: Final = ("open", "high", "low", "volume")


@lru_cache(maxsize=1)
def _schedule() -> pl.DataFrame:
    """XNYS open/close per session, as New-York wall-clock minutes past midnight."""

    import exchange_calendars as xc  # type: ignore[import-untyped]

    calendar = xc.get_calendar(CALENDAR)
    schedule = calendar.schedule.copy()
    opens = schedule["open"].dt.tz_convert(MARKET_TZ)
    closes = schedule["close"].dt.tz_convert(MARKET_TZ)
    return pl.DataFrame(
        {
            "session_date": [value.date() for value in schedule.index],
            "open_minute": (opens.dt.hour * 60 + opens.dt.minute).to_numpy().astype(np.int64),
            "close_minute": (closes.dt.hour * 60 + closes.dt.minute).to_numpy().astype(np.int64),
        }
    )


@lru_cache(maxsize=4096)
def session_length_minutes(session: date) -> int:
    """Minutes in one XNYS session, honouring early closes.

    Returns 0 for a date the exchange did not trade, so a caller that hands over a holiday
    gets an explicit empty session rather than 390 minutes of fabricated flat price.
    """

    table = _schedule()
    row = table.filter(pl.col("session_date") == session)
    if row.height == 0:
        return 0
    return int(row["close_minute"][0] - row["open_minute"][0])


@lru_cache(maxsize=4096)
def session_open_minute(session: date) -> int:
    """Minutes past New-York midnight at which this session opened."""

    table = _schedule()
    row = table.filter(pl.col("session_date") == session)
    if row.height == 0:
        return SESSION_OPEN_MINUTE
    return int(row["open_minute"][0])


@lru_cache(maxsize=4096)
def session_close_minute(session: date) -> int:
    """Minutes past New-York midnight at which this session closed.

    Returns 0 for a date the exchange did not trade, so a caller can tell "closed early"
    from "did not trade at all" rather than being handed a plausible-looking 16:00.
    """

    table = _schedule()
    row = table.filter(pl.col("session_date") == session)
    if row.height == 0:
        return 0
    return int(row["close_minute"][0])


def is_early_close(session: date) -> bool:
    """True when the exchange closed before its usual time on this session."""

    length = session_length_minutes(session)
    return 0 < length < FULL_SESSION_MINUTES


def normalise_bars(frame: pl.DataFrame) -> pl.DataFrame:
    """Reduce either on-disk bar schema to a common session-minute layout."""

    timestamp = "bar_start_utc" if "bar_start_utc" in frame.columns else "bar_timestamp_raw_utc"
    selected = [
        pl.col("asset"),
        pl.col(timestamp).dt.convert_time_zone(MARKET_TZ).alias("bar_ny"),
        pl.col("close").cast(pl.Float64),
    ]
    selected.extend(
        pl.col(name).cast(pl.Float64) for name in _OPTIONAL_COLUMNS if name in frame.columns
    )
    out = frame.select(selected).with_columns(pl.col("bar_ny").dt.date().alias("session_date"))
    out = out.with_columns(
        (
            pl.col("bar_ny").dt.hour().cast(pl.Int64) * 60
            + pl.col("bar_ny").dt.minute().cast(pl.Int64)
        ).alias("wall_minute")
    )
    # The open is per session, so the offset is joined rather than assumed.
    schedule = _schedule().select("session_date", "open_minute")
    out = out.join(schedule, on="session_date", how="left")
    return out.with_columns(
        (pl.col("wall_minute") - pl.col("open_minute").fill_null(SESSION_OPEN_MINUTE)).alias(
            "minute"
        )
    ).filter(pl.col("minute") >= 0)


#: Two stores may hold the same close for the same minute and still differ in the last
#: decimal after a round trip through parquet. Anything above this is a real disagreement.
BAR_PRICE_TOLERANCE: Final = 1e-6


def deduplicate_bar_sources(bars: pl.DataFrame) -> pl.DataFrame:
    """Keep one source per session-asset, failing closed if the sources disagree.

    Separate acquisitions overlap: a backfill re-acquires sessions an earlier campaign
    already held. Left alone, the same origin then appears twice in every panel built from
    these bars, which double-weights that origin in every mean, bootstrap and regression
    downstream. The duplication was invisible until now only because the sessions it
    affected — early closes — were being discarded by a quality gate reading a fabricated
    grid.

    Choosing a source silently would be the wrong repair: it would hide the case where two
    stores report *different* prices for the same minute, which is a data-integrity failure
    and not a preference. So the overlap is verified first and only then collapsed, keeping
    the alphabetically first source so the choice is reproducible.
    """

    keys = ["asset", "session_date", "minute"]
    overlapping = (
        bars.group_by(keys)
        .agg(
            pl.col("close").min().alias("low"),
            pl.col("close").max().alias("high"),
            pl.len().alias("copies"),
        )
        .filter(pl.col("copies") > 1)
    )
    disagreeing = overlapping.filter((pl.col("high") - pl.col("low")).abs() > BAR_PRICE_TOLERANCE)
    if disagreeing.height:
        sample = disagreeing.head(3).select(["asset", "session_date", "minute"]).rows()
        raise ValueError(f"RP2_BAR_SOURCES_DISAGREE:{disagreeing.height}:{sample}")
    if not overlapping.height:
        return bars

    chosen = (
        bars.group_by(["asset", "session_date"])
        .agg(pl.col("source").min().alias("keep"))
        .rename({"keep": "source"})
    )
    return bars.join(chosen, on=["asset", "session_date", "source"], how="semi")


def load_bar_sources(
    data_root: Path, sources: tuple[tuple[str, str, str], ...] = BAR_SOURCES
) -> pl.DataFrame:
    """Concatenate every available bar store, tagging source name and partition role.

    Overlapping acquisitions are collapsed to one source per session-asset; see
    :func:`deduplicate_bar_sources` for why that check is not a silent preference.
    """

    frames: list[pl.DataFrame] = []
    for name, role, relative in sources:
        path = data_root / relative
        if not path.is_file():
            continue
        frame = normalise_bars(pl.read_parquet(path))
        frames.append(frame.with_columns(source=pl.lit(name), role=pl.lit(role)))
    if not frames:
        raise ValueError("RP2_BARS_NO_SOURCES")
    return deduplicate_bar_sources(pl.concat(frames, how="diagonal"))


@dataclass(frozen=True, slots=True)
class SessionGrid:
    """One session-asset reindexed onto its own minute grid.

    ``valid[i]`` is False wherever no observation at or before minute ``i`` exists, so a
    caller can drop those origins instead of consuming a price that was carried backwards.
    """

    close: FloatArray
    #: The session's first print in each minute. It is the one price a trade *inside* that
    #: minute can be marked at without reading its own future, which matters for the
    #: opening minute, where there is no completed bar to fall back to.
    open: FloatArray
    high: FloatArray
    low: FloatArray
    volume: FloatArray
    valid: BoolArray
    fill_share: float
    minutes: int


def _forward_fill(values: FloatArray) -> tuple[FloatArray, BoolArray]:
    """Carry the last observation forward. Never backwards.

    Returns ``(filled, valid)``; ``valid`` is False for every leading minute that has no
    prior observation to carry, which is exactly the region a back-fill would fabricate.
    """

    present = ~np.isnan(values)
    valid = np.logical_or.accumulate(present)
    if not present.any():
        return values, valid
    indices = np.where(present, np.arange(values.size), 0)
    np.maximum.accumulate(indices, out=indices)
    filled = values[indices]
    return np.where(valid, filled, np.nan), valid


def build_session_grid(group: pl.DataFrame, *, session: date | None = None) -> SessionGrid:
    """Reindex one session-asset onto its own minute grid.

    Prices carry forward into minutes with no trade; volume of an absent minute is zero.
    Minutes before the first observation are marked invalid rather than back-filled.
    """

    minutes = group["minute"].to_numpy().astype(np.int64)
    # No session given means the caller wants a bare full-length grid.  A *named* session
    # the exchange did not trade has zero minutes and stays that way: substituting the
    # full-session length here would rebuild the fabrication session_length_minutes exists
    # to prevent — 390 minutes of flat price on a day the market was closed, which is
    # indistinguishable downstream from a real quiet session.
    length = FULL_SESSION_MINUTES if session is None else session_length_minutes(session)
    if length <= 0:
        empty = np.empty(0, dtype=np.float64)
        return SessionGrid(
            close=empty,
            open=empty,
            high=empty,
            low=empty,
            volume=empty,
            valid=np.empty(0, dtype=bool),
            fill_share=1.0,
            minutes=0,
        )
    inside = (minutes >= 0) & (minutes < length)
    minutes = minutes[inside]

    grids: dict[str, FloatArray] = {}
    for name in ("close", "open", "high", "low", "volume"):
        grid = np.full(length, np.nan, dtype=np.float64)
        if name in group.columns:
            grid[minutes] = group[name].to_numpy().astype(np.float64)[inside]
        grids[name] = grid

    fill_share = float(np.isnan(grids["close"]).mean())
    close, valid = _forward_fill(grids["close"])
    opening = np.where(np.isnan(grids["open"]), close, grids["open"])
    high = np.where(np.isnan(grids["high"]), close, grids["high"])
    low = np.where(np.isnan(grids["low"]), close, grids["low"])
    volume = np.where(np.isnan(grids["volume"]), 0.0, grids["volume"])
    return SessionGrid(
        close=close,
        open=opening,
        high=high,
        low=low,
        volume=volume,
        valid=valid,
        fill_share=fill_share,
        minutes=length,
    )
