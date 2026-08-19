"""Block 4 must survive the sessions that are not 390 minutes long.

Both cases here abort the block outright against the previous code, on real dates inside
the study window. Neither is exotic: XNYS closes early roughly nine times a year, and a
missing opening bar is common enough that the fill-share threshold exists to tolerate it.
"""

from __future__ import annotations

import importlib.util
from datetime import date
from pathlib import Path
from types import ModuleType

import numpy as np
import polars as pl
import pytest

REPO = Path(__file__).resolve().parents[2]


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "rp2_block4_b0_panel", REPO / "scripts" / "rp2_block4_b0_panel.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BLOCK4 = _load()


def test_origins_are_sized_to_the_session_that_actually_happened() -> None:
    """The abort this pins: a 210-minute session indexed with full-session origins.

    `forward_measures` reaches 30 minutes past each origin, so an origin at minute 355 on
    a 210-minute session reads off the end of the grid and raises
    RP2_WINDOW_EXCEEDS_SERIES — the whole block dies on an early close.
    """

    full = BLOCK4.session_origins(390)
    early = BLOCK4.session_origins(210)
    assert full.max() == 355
    assert early.max() <= 210 - BLOCK4.TARGET_HORIZON
    assert early.size < full.size


def test_a_session_too_short_to_hold_one_origin_yields_none() -> None:
    assert BLOCK4.session_origins(BLOCK4.FIRST_ORIGIN + BLOCK4.TARGET_HORIZON).size == 0
    assert BLOCK4.session_origins(0).size == 0


def test_the_first_usable_minute_skips_an_unobserved_open() -> None:
    valid = np.array([False, False, True, True])
    assert BLOCK4.first_valid_minute(valid) == 2
    assert BLOCK4.first_valid_minute(np.array([True, True])) == 0
    # No observation anywhere: the caller must find no usable minute, not index minute 0.
    assert BLOCK4.first_valid_minute(np.array([False, False])) == 2


def _bars(session: date, *, minutes: int, first_observed: int = 0) -> pl.DataFrame:
    """One asset's session, optionally missing its first ``first_observed`` minutes.

    `session_date` is a real date, as `load_bar_sources` produces it — the exchange
    calendar is keyed on dates, so a string here silently means a different session.
    """

    index = np.arange(first_observed, minutes, dtype=np.int64)
    price = 100.0 + np.cumsum(np.full(index.size, 0.01))
    return pl.DataFrame(
        {
            "asset": ["AAPL"] * index.size,
            "session_date": [session] * index.size,
            "role": ["D"] * index.size,
            "source": ["test"] * index.size,
            "minute": index,
            "close": price,
            "high": price + 0.05,
            "low": price - 0.05,
            "volume": np.full(index.size, 1000.0),
        }
    )


def test_a_missing_opening_bar_drops_its_origins_rather_than_the_session() -> None:
    """The abort this pins: NaN at minute 0 reaching `log_returns`.

    The grid refuses to carry a price backwards, so an unobserved open is NaN. NaN fails
    the `close.min() <= 0` guard silently, and `log_returns` then raises
    RP2_RETURNS_PRICE_INVALID — a fatal error for a session the fill-share threshold was
    written to accept.
    """

    bars = _bars(date(2025, 6, 20), minutes=390, first_observed=3)
    panel, counters = BLOCK4.build_b0_panel(bars, max_fill_share=0.5)
    assert panel.height > 0
    assert counters["dropped_fill"] == 0
    # Every surviving origin leaves a full horizon after the first observed minute.
    assert int(panel["origin_minute"].min()) >= 3 + BLOCK4.TARGET_HORIZON


def test_minutes_to_close_is_measured_against_the_session_own_close() -> None:
    bars = _bars(date(2025, 6, 20), minutes=390)
    panel, _ = BLOCK4.build_b0_panel(bars, max_fill_share=0.5)
    row = panel.filter(pl.col("origin_minute") == 100)
    assert row.height == 1
    assert row["minutes_to_close"][0] == pytest.approx(390 - 100)


def test_the_market_control_frame_survives_a_short_session() -> None:
    bars = pl.concat(
        [
            _bars(date(2025, 11, 28), minutes=210).with_columns(asset=pl.lit("SPY")),
            _bars(date(2025, 11, 28), minutes=210).with_columns(asset=pl.lit("QQQ")),
        ]
    )
    controls = BLOCK4.build_market_controls(bars)
    assert controls.height > 0
    assert int(controls["origin_minute"].max()) <= 210 - BLOCK4.TARGET_HORIZON
