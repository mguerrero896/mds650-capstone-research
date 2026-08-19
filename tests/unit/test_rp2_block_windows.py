"""The B1 surface and the B2 flow windows must not share a single observation.

Both blocks are cut from one option tape. The programme's central question - does trade
flow add information beyond the surface? - is only answerable if the two feature sets are
built from different rows. Before this, B1 read [origin-1920s, origin-120s] and B2's 30-minute
window read exactly the same interval, so "B2 beyond B1" was partly B2 beyond itself.
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


def test_the_surface_window_ends_before_the_longest_flow_window_begins() -> None:
    longest_flow = max(seconds for _, seconds in BLOCK6.WINDOWS)
    assert longest_flow <= BLOCK5.FLOW_WINDOW_SECONDS, (
        "B1 is sizing its gap against a stale idea of how far back B2 reaches"
    )
    assert BLOCK6.CUTOFF_SECONDS + longest_flow <= BLOCK5.SNAPSHOT_END_SECONDS


def test_the_two_windows_are_disjoint_on_a_concrete_origin() -> None:
    origin = 0
    flow_window = max(seconds for _, seconds in BLOCK6.WINDOWS)
    flow = (origin - BLOCK6.CUTOFF_SECONDS - flow_window, origin - BLOCK6.CUTOFF_SECONDS)
    surface_end = origin - BLOCK5.SNAPSHOT_END_SECONDS
    surface = (surface_end - BLOCK5.LOOKBACK_SECONDS, surface_end)
    assert surface[1] <= flow[0], f"overlap: surface {surface} vs flow {flow}"


def test_the_guard_refuses_a_window_that_would_overlap() -> None:
    with pytest.raises(ValueError, match="RP2_B1_WINDOW_OVERLAPS_FLOW"):
        BLOCK5.assert_disjoint_from_flow_window(
            snapshot_end_seconds=120, flow_window_seconds=1800, cutoff_seconds=120
        )


def test_the_guard_accepts_the_shipped_constants() -> None:
    BLOCK5.assert_disjoint_from_flow_window()


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
        assert "closes.size == 0" in source, f"{module.__name__} accepts an empty grid"
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
