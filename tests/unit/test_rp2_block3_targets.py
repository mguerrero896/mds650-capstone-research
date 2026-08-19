"""Block 3 builds the targets. A leak here reaches every score in the programme.

The block carried a private copy of the grid builder with `grid[:first] = grid[first]` in
it — the first observed price written backwards over every earlier minute. Fixing that in
`mds650.rp2.bars` left this copy untouched, so the targets every later block is scored
against were still computed from prices that did not exist yet. These pin the shared
builder being used, not merely present.
"""

from __future__ import annotations

import importlib.util
from datetime import date
from pathlib import Path
from types import ModuleType

import numpy as np
import polars as pl

REPO = Path(__file__).resolve().parents[2]


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "rp2_block3_target_panel", REPO / "scripts" / "rp2_block3_target_panel.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BLOCK3 = _load()


def test_the_block_no_longer_carries_its_own_grid_builder() -> None:
    source = (REPO / "scripts" / "rp2_block3_target_panel.py").read_text(encoding="utf-8")
    assert "def _session_closes(" not in source
    assert "build_session_grid" in source


def test_origins_are_sized_from_the_session_rather_than_a_constant() -> None:
    """A 210-minute early close cannot hold this block's longest horizon at all.

    The longest target reaches 120 minutes forward and the first origin sits 120 minutes
    in, so a session needs more than 240 minutes to carry a single origin. The honest
    answer for an early close is none — not an origin whose forward window runs past the
    close into a grid that holds nothing.
    """

    assert BLOCK3.MAX_HORIZON == 120
    assert BLOCK3.session_origins(390).size > 0
    assert BLOCK3.session_origins(210).size == 0
    assert BLOCK3.session_origins(2 * BLOCK3.MAX_HORIZON).size == 0
    assert BLOCK3.session_origins(2 * BLOCK3.MAX_HORIZON + BLOCK3.ORIGIN_STEP).size == 1


def _bars(session: date, *, minutes: int, first_observed: int = 0) -> pl.DataFrame:
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
        }
    )


def test_targets_never_consume_a_price_from_before_the_first_observation() -> None:
    """A late open must remove origins, not manufacture a flat opening stretch.

    Under the old builder the first observed price was written backwards, so returns over
    the unobserved minutes were exactly zero — a run of fabricated calm that pushed every
    realized-variance target near that region downward.
    """

    bars = _bars(date(2025, 6, 20), minutes=390, first_observed=10)
    panel, counters = BLOCK3.build_panel(bars, max_fill_share=0.5)
    assert panel.height > 0
    assert int(panel["origin_minute"].min()) >= 10 + BLOCK3.MAX_HORIZON
    assert counters["sessions_dropped_fill"] == 0


def test_an_early_close_is_dropped_rather_than_indexed_past_its_close() -> None:
    """Mixed input: the full session contributes, the early close contributes nothing."""

    bars = pl.concat(
        [_bars(date(2025, 6, 20), minutes=390), _bars(date(2025, 11, 28), minutes=210)]
    )
    panel, counters = BLOCK3.build_panel(bars, max_fill_share=0.5)
    assert panel["session_date"].unique().to_list() == ["2025-06-20"]
    assert counters["sessions_dropped_short"] == 1


def test_a_holiday_yields_no_targets_rather_than_a_fabricated_session() -> None:
    """The grid must not substitute 390 minutes for a day the exchange did not open.

    `session_length_minutes` returned 0 for a holiday, but `build_session_grid` then
    replaced that 0 with the full-session length — rebuilding the exact fabrication the
    zero was there to prevent, and producing a full day of targets for a closed market.
    """

    bars = pl.concat(
        [_bars(date(2025, 6, 20), minutes=390), _bars(date(2025, 12, 25), minutes=390)]
    )
    panel, counters = BLOCK3.build_panel(bars, max_fill_share=0.5)
    assert panel["session_date"].unique().to_list() == ["2025-06-20"]
    assert counters["sessions_dropped_short"] == 1
