"""Shared one-minute bar loading for Research Program v2.

Session minutes are measured from the 09:30 America/New_York open, never from a fixed UTC
hour: the UTC open shifts by an hour across daylight saving, and a fixed-hour grid silently
truncates every winter session.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final

import numpy as np
import numpy.typing as npt
import polars as pl

type FloatArray = npt.NDArray[np.float64]

SESSION_MINUTES: Final = 390
MARKET_TZ: Final = "America/New_York"
SESSION_OPEN_MINUTE: Final = 9 * 60 + 30

#: ``(name, partition role, path relative to the store root)``, oldest window first.
BAR_SOURCES: Final[tuple[tuple[str, str, str], ...]] = (
    ("gate7_c6", "D", "data/fmp/gate7/underlying_1min_c6.parquet"),
    ("gate8_c4c", "D", "data/fmp/gate8_c4c/underlying_1min_c4c.parquet"),
    ("phase6_180d", "D", "phase6/data/fmp/underlying_1min_180d.parquet"),
    ("gate3_dev80", "V", "data/fmp/gate3/underlying_1min_dev80.parquet"),
)

_OPTIONAL_COLUMNS: Final = ("high", "low", "volume")


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
    return out.with_columns(
        (
            pl.col("bar_ny").dt.hour().cast(pl.Int64) * 60
            + pl.col("bar_ny").dt.minute().cast(pl.Int64)
            - SESSION_OPEN_MINUTE
        ).alias("minute")
    ).filter(pl.col("minute").is_between(0, SESSION_MINUTES - 1))


def load_bar_sources(
    data_root: Path, sources: tuple[tuple[str, str, str], ...] = BAR_SOURCES
) -> pl.DataFrame:
    """Concatenate every available bar store, tagging source name and partition role."""

    frames: list[pl.DataFrame] = []
    for name, role, relative in sources:
        path = data_root / relative
        if not path.is_file():
            continue
        frame = normalise_bars(pl.read_parquet(path))
        frames.append(frame.with_columns(source=pl.lit(name), role=pl.lit(role)))
    if not frames:
        raise ValueError("RP2_BARS_NO_SOURCES")
    return pl.concat(frames, how="diagonal")


@dataclass(frozen=True, slots=True)
class SessionGrid:
    """One session-asset reindexed onto the full minute grid."""

    close: FloatArray
    high: FloatArray
    low: FloatArray
    volume: FloatArray
    fill_share: float


def _forward_fill(values: FloatArray) -> FloatArray:
    present = ~np.isnan(values)
    if not present.any():
        return values
    first = int(np.argmax(present))
    filled = values.copy()
    filled[:first] = filled[first]
    indices = np.where(present, np.arange(values.size), 0)
    np.maximum.accumulate(indices, out=indices)
    return filled[indices]


def build_session_grid(group: pl.DataFrame) -> SessionGrid:
    """Reindex one session-asset onto 390 minutes, forward-filling absent minutes.

    Volume of an absent minute is zero (no trade), while prices carry forward.
    """

    minutes = group["minute"].to_numpy().astype(np.int64)
    grids: dict[str, FloatArray] = {}
    for name in ("close", "high", "low", "volume"):
        grid = np.full(SESSION_MINUTES, np.nan, dtype=np.float64)
        if name in group.columns:
            grid[minutes] = group[name].to_numpy().astype(np.float64)
        grids[name] = grid
    fill_share = float(np.isnan(grids["close"]).mean())
    close = _forward_fill(grids["close"])
    high = np.where(np.isnan(grids["high"]), close, grids["high"])
    low = np.where(np.isnan(grids["low"]), close, grids["low"])
    volume = np.where(np.isnan(grids["volume"]), 0.0, grids["volume"])
    return SessionGrid(close=close, high=high, low=low, volume=volume, fill_share=fill_share)
