"""A trade may not be marked at a price from its own future.

`rp2_ext2_tape_tensors.py` marked every trade's spot at `closes[minute_of_trade]` — the
close of the minute the trade happened in. A trade at 10:15:03 was therefore priced at
10:16:00, forty-three seconds after it printed, and its Greeks, its log-moneyness and the
bucket it lands in were all computed from that. The producer built the full `SessionGrid`
and then kept only `grid.close`, discarding the one field that exists for this case:

    The session's first print in each minute, NaN where the store did not supply one. It
    is the one price a trade *inside* that minute can be marked at without reading its own
    future ... It is never filled from the close: that would be the look-ahead it prevents.
        -- mds650.rp2.bars.SessionGrid

So the mark is the open of the trade's own minute where the store has one, and otherwise
the close of the previous minute, which is the last price that had certainly completed. A
trade in the opening minute of a session whose open is missing has no admissible mark and
is left unmarked rather than given a plausible one — the level-4 producer already fails
closed on a non-finite tensor cell.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "rp2_ext2_tape_tensors.py"


@pytest.fixture(scope="module")
def module():
    spec = importlib.util.spec_from_file_location("rp2_ext2_under_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    loaded = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = loaded
    spec.loader.exec_module(loaded)
    return loaded


def test_a_trade_is_marked_at_its_own_minutes_open(module) -> None:
    opens = np.array([100.0, 101.0, 102.0, 103.0])
    closes = np.array([100.5, 101.5, 102.5, 103.5])

    marks = module.trade_marks(np.array([0, 1, 2, 3]), opens, closes)

    assert marks.tolist() == [100.0, 101.0, 102.0, 103.0], (
        "a trade must be priced at the first print of its own minute, not at the last one"
    )


def test_a_missing_open_falls_back_to_the_previous_close(module) -> None:
    """The last price that had certainly completed, never this minute's own close."""
    opens = np.array([100.0, np.nan, 102.0])
    closes = np.array([100.5, 101.5, 102.5])

    marks = module.trade_marks(np.array([0, 1, 2]), opens, closes)

    assert marks[1] == pytest.approx(100.5), (
        f"minute 1 was marked at {marks[1]}; its own close 101.5 is in the trade's future"
    )


def test_the_opening_minute_without_an_open_has_no_admissible_mark(module) -> None:
    """There is no earlier price, so the honest answer is that there is none."""
    opens = np.array([np.nan, 101.0])
    closes = np.array([100.5, 101.5])

    marks = module.trade_marks(np.array([0, 1]), opens, closes)

    assert np.isnan(marks[0]), f"the opening minute was marked at {marks[0]} out of nothing"
    assert marks[1] == pytest.approx(101.0)


def test_no_mark_is_ever_the_close_of_the_trades_own_minute(module) -> None:
    """The property the defect violated, over a grid with gaps in both fields."""
    generator = np.random.default_rng(650)
    opens = generator.uniform(90.0, 110.0, 200)
    closes = generator.uniform(90.0, 110.0, 200)
    opens[generator.random(200) < 0.3] = np.nan
    minutes = np.arange(200)

    marks = module.trade_marks(minutes, opens, closes)

    same_minute_close = np.isclose(marks, closes, equal_nan=False)
    assert not same_minute_close.any(), (
        f"{int(same_minute_close.sum())} trades were marked at their own minute's close"
    )
