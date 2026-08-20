"""Invariants a rebuild has to hold, not merely report.

A counter that is measured and never checked is a counter that will be nonzero one day
with nobody the wiser. A count that accumulates from the start of the session is not a
count of anything once it is summed. And a manifest that names a commit whose code was not
what ran attributes results to something that did not produce them.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[2]


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_a_zero_dte_trade_is_counted_once_per_session_not_once_per_origin() -> None:
    """Summing a running total over origins multiplies every trade by what came after it.

    Origins are five minutes apart and the flow windows are anchored at the availability
    cutoff, so the five-minute windows tile the session: counting inside that window and
    summing over origins counts each trade at most once. Counting everything visible since
    the open and summing counts the first trade of the day about seventy times.
    """

    block6 = _load("rp2_block6_flow_panel")
    # Three origins, one 0DTE trade inside the first window and one inside the third.
    visible = np.array([1, 1, 2], dtype=np.int64)
    window_start = np.array([0, 1, 1], dtype=np.int64)
    is_zero_dte = np.array([True, True], dtype=bool)

    per_origin = [
        block6.window_count(is_zero_dte, int(window_start[i]), int(visible[i])) for i in range(3)
    ]
    assert sum(per_origin) == 2, f"each trade once, got {per_origin}"


def test_the_scorecard_refuses_a_run_whose_point_in_time_invariants_broke() -> None:
    """`b2_pit_violation_count` is zero by construction. Measuring it is not enough."""

    from mds650.rp2.scorecard import assert_scorecard_complete, required_fields

    groups = required_fields()
    scorecard: dict[str, object] = {
        group: dict.fromkeys(fields, 1.0) for group, fields in groups.items() if group != "forecast"
    }
    scorecard["data"] = {**scorecard["data"], "duplicate_keys": 0}  # type: ignore[dict-item]
    scorecard["b1"] = {**scorecard["b1"], "b1_post_cutoff_observations": 0}  # type: ignore[dict-item]
    scorecard["b2"] = {**scorecard["b2"], "b2_pit_violation_count": 0}  # type: ignore[dict-item]
    scorecard["forecast"] = {
        "gamma_glm": {
            "D": {
                field: 1.0
                for field in groups["forecast"]
                if field not in ("calibration_slope", "calibration_intercept")
            }
        }
    }
    scorecard["forecast_calibration"] = {"calibration_slope": 1.0, "calibration_intercept": 0.0}
    assert_scorecard_complete(scorecard)

    for group, field in (
        ("b2", "b2_pit_violation_count"),
        ("b1", "b1_post_cutoff_observations"),
        ("data", "duplicate_keys"),
    ):
        broken = {**scorecard, group: {**scorecard[group], field: 3}}  # type: ignore[dict-item]
        with pytest.raises(ValueError, match=f"RP2_SCORECARD_INVARIANT_BREACH:{group}.{field}=3"):
            assert_scorecard_complete(broken)


def test_a_dirty_worktree_is_refused_before_a_commit_is_recorded() -> None:
    """`rev-parse HEAD` names the last commit; the subprocesses run the working tree.

    With uncommitted changes those are different things, and the manifest would attribute
    the artifacts to code that did not produce them.
    """

    runner = _load("run_rp2_v3_pipeline")
    with pytest.raises(SystemExit, match="RP2_RUN_WORKTREE_DIRTY"):
        runner.assert_worktree_clean(status=" M scripts/rp2_block8_ladder.py\n")
    runner.assert_worktree_clean(status="")
    # An untracked scratch file is not the code that ran.
    runner.assert_worktree_clean(status="?? notes.txt\n")


def test_every_session_asset_the_baseline_emits_has_a_tape_to_read() -> None:
    """Block 5 skips a session-asset with no tape, and the mask then drops those rows.

    Proving the inventory's paths exist says nothing about whether the inventory covers
    the panel. The run has to compare the two.
    """

    runner = _load("run_rp2_v3_pipeline")
    covered = {("AAPL", "2024-08-02"), ("MSFT", "2024-08-02")}
    runner.assert_tape_covers_panel(covered, covered, wildcard_sessions=frozenset())
    with pytest.raises(SystemExit, match="RP2_RUN_TAPE_COVERAGE_GAP:1:MSFT@2024-08-02"):
        runner.assert_tape_covers_panel(
            {("AAPL", "2024-08-02")}, covered, wildcard_sessions=frozenset()
        )


def test_a_session_level_tape_covers_every_asset_in_that_session() -> None:
    """Five V sessions are inventoried once, as `__ALL__`, and both producers use it.

    Treating that entry as an asset named `__ALL__` would report every concrete asset on
    those sessions as an uncovered gap and abort a rebuild that had nothing wrong with it.
    """

    runner = _load("run_rp2_v3_pipeline")
    panel = {("AAPL", "2026-07-13"), ("NVDA", "2026-07-13"), ("TSLA", "2026-07-17")}
    runner.assert_tape_covers_panel(
        set(), panel, wildcard_sessions=frozenset({"2026-07-13", "2026-07-17"})
    )
    with pytest.raises(SystemExit, match="RP2_RUN_TAPE_COVERAGE_GAP:1:TSLA@2026-07-17"):
        runner.assert_tape_covers_panel(
            set(), panel, wildcard_sessions=frozenset({"2026-07-13"})
        )


def test_the_frozen_inventory_covers_the_frozen_partition() -> None:
    """The real inventory against the real partition, not a fixture.

    Five V sessions carry only a session-level entry; the check has to accept them.
    """

    runner = _load("run_rp2_v3_pipeline")
    keys, wildcards = runner.tape_coverage(runner.TAPE_INVENTORY)
    assert wildcards == {"2026-07-13", "2026-07-14", "2026-07-15", "2026-07-16", "2026-07-17"}
    assert ("AAPL", "2024-08-02") in keys


def test_the_sealed_cohort_guard_has_no_opt_out() -> None:
    """A rule with a flag that switches it off is a default, not a rule."""

    source = (REPO / "scripts" / "run_rp2_v3_pipeline.py").read_text(encoding="utf-8")
    assert "--allow-sealed-cohorts" not in source
    assert "forbid_sealed_cohorts" not in source


def test_the_scorecard_does_not_change_between_identical_runs(tmp_path: Path) -> None:
    """The scorecard is an artifact of the run, so its digest is part of the run's identity.

    Embedding byte-level artifact digests puts the producers' timestamps into it, and
    printing the runtime into the Markdown puts the clock there too — so an otherwise
    identical retry would disagree with itself and be refused as a conflicting run.
    """

    from mds650.rp2.run_manifest import stable_content_digest
    from mds650.rp2.scorecard import render_scorecard

    def scorecard(runtime: float, digest: str) -> dict[str, object]:
        return {
            "run_id": "r",
            "code_commit": "c" * 40,
            "data": {"b0_rows": 1},
            "b1": {"b1_core_coverage": 1.0},
            "b2": {"b2_zero_dte_count": 2},
            "engineering": {
                "runtime_seconds": runtime,
                "peak_memory_bytes": int(runtime),
                "artifact_sha256": {"ladder.json": digest},
                "code_commit": "c" * 40,
            },
            "forecast": {
                "gamma_glm": {
                    "D": {
                        "qlike_b0": 0.1,
                        "delta_b1": 0.01,
                        "delta_b2_given_b1": 0.0,
                        "mde": {"delta_b1": 0.002},
                    }
                }
            },
            "forecast_calibration": {"calibration_slope": 1.0, "calibration_intercept": 0.0},
        }

    first = tmp_path / "a.md"
    second = tmp_path / "b.md"
    first.write_text(render_scorecard(scorecard(91.0, "a" * 64)), encoding="utf-8")
    second.write_text(render_scorecard(scorecard(4242.0, "a" * 64)), encoding="utf-8")
    assert stable_content_digest(first) == stable_content_digest(second), (
        "the rendered scorecard must not carry the run's runtime"
    )


def test_the_two_producers_are_held_to_the_same_evaluation_mask(tmp_path: Path) -> None:
    """The ladder and the inference must score the same rows, and the run must check it.

    Step 7's own digest is over the pre-split common mask in panel order, which is a
    different object from the held-out mask the producers hash. Recording it as though it
    were the same mask would put two unrelated numbers under one name; the check that
    matters is whether the two producers agree with each other.
    """

    runner = _load("run_rp2_v3_pipeline")
    import json as _json

    run = tmp_path / "run"
    (run / "rp2_block8_ladder").mkdir(parents=True)
    (run / "rp2_block10_inference").mkdir(parents=True)

    def write(ladder_digest: str, inference_digest: str) -> None:
        (run / "rp2_block8_ladder" / "ladder.json").write_text(
            _json.dumps({"D": {"evaluation_mask_sha256": ladder_digest}}), encoding="utf-8"
        )
        (run / "rp2_block10_inference" / "inference.json").write_text(
            _json.dumps({"D": {"evaluation_mask_sha256": inference_digest}}), encoding="utf-8"
        )

    write("a" * 64, "a" * 64)
    assert runner.assert_producers_share_the_mask(run, ("D",)) == {"D": "a" * 64}

    write("a" * 64, "b" * 64)
    with pytest.raises(SystemExit, match="RP2_RUN_MASK_DISAGREEMENT:D"):
        runner.assert_producers_share_the_mask(run, ("D",))
