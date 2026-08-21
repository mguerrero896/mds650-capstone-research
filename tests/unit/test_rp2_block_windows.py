"""The B1 surface and the B2 flow windows, and what each of them is allowed to read.

Both blocks are cut from one option tape. RP2-v2 forced them apart in time so that no row
could feed both, which made B1 the state of the option market half an hour before the
origin. The contrast is conditional — E[Y | B0, B1, B2] against E[Y | B0, B1] — so overlap
is permitted and B1 is now contemporaneous. What both still owe is the availability rule:
neither may read a row the provider had not published by ``origin - 120 s``.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from types import ModuleType

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[2]


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BLOCK5 = _load("rp2_block5_surface_panel")
BLOCK6 = _load("rp2_block6_flow_panel")


def test_both_blocks_honour_the_same_availability_cutoff() -> None:
    """One provider lag, one cutoff. A block reading further forward is reading the future."""

    assert BLOCK5.CUTOFF_SECONDS == BLOCK6.CUTOFF_SECONDS == 120


def test_the_surface_window_ends_at_the_cutoff_not_before_the_flow_window() -> None:
    """The lagged snapshot end is gone: B1 reads up to the cutoff like B2 does."""

    origin = 0
    window = BLOCK5.snapshot_window(origin)
    assert window.cutoff_us == -BLOCK5.CUTOFF_SECONDS * 1_000_000
    longest_flow = max(seconds for _, seconds in BLOCK6.WINDOWS)
    flow_start = origin - BLOCK6.CUTOFF_SECONDS * 1_000_000 - longest_flow * 1_000_000
    # The two windows now overlap, deliberately, and B1 no longer ends where B2 begins.
    assert window.oldest_us <= flow_start
    assert window.cutoff_us > flow_start


def test_the_surface_window_never_reaches_past_the_cutoff() -> None:
    """Contemporaneous is not the same as instantaneous."""

    window = BLOCK5.snapshot_window(0)
    assert window.cutoff_us < 0, "an origin may not read its own instant"
    assert window.span_seconds == BLOCK5.MAX_QUOTE_AGE_SECONDS


def test_a_spread_leg_contributes_volume_but_no_direction() -> None:
    """The defect this pins: side tags on spread legs manufacture signed flow.

    ``multi_vol`` is a running per-contract total, so a print belongs to a multi-leg order
    exactly when that total rises. Two prints of the same contract, the second lifting the
    running multi-leg total by its whole size, must be scored as one directional trade and
    one neutral one.
    """

    keys = np.array([1, 1, 2], dtype=np.int64)
    multi_vol = np.array([0.0, 5.0, 0.0])
    size = np.array([3.0, 5.0, 2.0])
    multileg = BLOCK6._multileg_size(keys, multi_vol, size)
    assert multileg.tolist() == [0.0, 5.0, 0.0]


def test_the_first_print_of_a_contract_is_not_charged_its_whole_history() -> None:
    """A window starting mid-session sees a running total that already carries earlier legs."""

    keys = np.array([7, 7], dtype=np.int64)
    multi_vol = np.array([400.0, 402.0])
    size = np.array([1.0, 2.0])
    multileg = BLOCK6._multileg_size(keys, multi_vol, size)
    assert multileg[0] == 0.0
    assert multileg[1] == pytest.approx(2.0)


def test_multileg_size_never_exceeds_the_print_it_is_attributed_to() -> None:
    keys = np.array([3, 3], dtype=np.int64)
    multi_vol = np.array([0.0, 99.0])  # a jump larger than this print can explain
    size = np.array([1.0, 4.0])
    assert BLOCK6._multileg_size(keys, multi_vol, size)[1] == pytest.approx(4.0)


def test_a_falling_running_total_is_never_read_as_negative_multileg_volume() -> None:
    keys = np.array([3, 3], dtype=np.int64)
    multi_vol = np.array([10.0, 4.0])
    size = np.array([1.0, 4.0])
    assert BLOCK6._multileg_size(keys, multi_vol, size).min() >= 0.0


def test_both_panel_builders_refuse_an_origin_past_the_end_of_its_grid() -> None:
    """Early closes are back in the panel, so the minute grid is no longer always 390 long.

    Blocks 5 and 6 look the spot price up as `closes[minute]`. On a 210-minute session an
    origin at minute 300 would read `closes[300]` — out of bounds if the guard is missing,
    and worse if a future refactor pads the array, because it would silently return a
    price from a minute the market never traded.
    """

    for module in (BLOCK5, BLOCK6):
        source = (REPO / "scripts" / f"{module.__name__}.py").read_text(encoding="utf-8")
        assert "size == 0" in source, f"{module.__name__} accepts an empty grid"
        assert "origin_minutes < closes.size" in source, (
            f"{module.__name__} indexes the grid without bounding the origin"
        )


def test_every_tape_column_a_builder_reads_is_a_column_it_declares() -> None:
    """The defect this pins: `executed_at` was read but never declared, so Block 6 died.

    Both builders project exactly `TAPE_COLUMNS` when reading the tape, so a column used in
    the body but missing from the tuple is not a degraded feature — it is a
    `ColumnNotFoundError` on the first file. The dual-clock latency features shipped in that
    state and could never have run.
    """

    pattern = re.compile(r'tape\["([a-z_]+)"\]')
    for module in (BLOCK5, BLOCK6):
        source = (REPO / "scripts" / f"{module.__name__}.py").read_text(encoding="utf-8")
        used = set(pattern.findall(source))
        declared = set(module.TAPE_COLUMNS)
        assert used <= declared, (
            f"{module.__name__} reads tape columns it never declares: {sorted(used - declared)}"
        )


def test_the_counting_window_reports_its_tail_over_the_trades_it_averages() -> None:
    """One slice, two statistics.

    The thirty-minute windows open after the session does and overlap each other; the
    counting windows tile the session and their first bucket reaches back to the start of the
    tape. A mean read from one and a tail read from the other are two populations under names
    that invite comparison - and the published scorecard carried exactly that pair.
    """

    latency = np.array([0.5] * 19 + [60.0])

    mean, p95 = BLOCK6.counting_latency(latency, 0, latency.size)
    assert mean == pytest.approx(float(np.mean(latency)))
    assert p95 == pytest.approx(float(np.quantile(latency, 0.95)))

    # The slow trade is inside the window the mean covers, so it is inside the window the
    # tail covers. A tail taken from a window that excludes it describes a different day.
    without_the_tail = BLOCK6.counting_latency(latency, 0, 19)
    assert without_the_tail == (pytest.approx(0.5), pytest.approx(0.5))
    assert p95 > without_the_tail[1]

    assert BLOCK6.counting_latency(latency, 3, 3) == (0.0, 0.0)
