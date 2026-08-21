"""The scorecard's counters have to be measured, not assumed to be zero.

`b2_pit_violation_count` and `b1_post_cutoff_observations` are zero by construction: the
selection is a `searchsorted` at the cutoff. That is exactly why they are worth counting.
A field reported as zero because nobody looked is indistinguishable from a field reported
as zero because somebody did, and only one of them would notice a regression.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from mds650.rp2.b1_snapshot import latest_quote_per_contract, snapshot_window


def test_the_snapshot_counts_the_duplicates_it_collapsed() -> None:
    origin = 1_000_000_000_000
    window = snapshot_window(origin, cutoff_seconds=0, max_quote_age_seconds=600)
    # Three contracts, six observations: two of them quoted twice inside the window.
    created = np.array(
        [origin - 500_000_000, origin - 400_000_000, origin - 300_000_000, origin - 200_000_000],
        dtype=np.int64,
    )
    keys = np.array([1, 1, 2, 2], dtype=np.int64)
    snapshot = latest_quote_per_contract(created, keys, window)

    assert snapshot.contracts == 2
    assert snapshot.duplicates_dropped == 2
    assert snapshot.post_cutoff_selected == 0


def test_the_snapshot_counts_nothing_it_selected_after_the_cutoff() -> None:
    """The count is over the rows actually chosen, so it can only be zero if they are."""

    origin = 2_000_000_000_000
    window = snapshot_window(origin, cutoff_seconds=120, max_quote_age_seconds=1800)
    created = np.array(
        [
            window.cutoff_us - 10_000_000,
            window.cutoff_us - 1,
            window.cutoff_us + 1,  # published after the cutoff: must not be selected
            origin,
        ],
        dtype=np.int64,
    )
    keys = np.array([1, 2, 3, 4], dtype=np.int64)
    snapshot = latest_quote_per_contract(created, keys, window)

    assert snapshot.contracts == 2, "only the two observations at or before the cutoff"
    assert snapshot.post_cutoff_selected == 0
    assert snapshot.duplicates_dropped == 0
    assert float(np.max(created[snapshot.positions])) <= float(window.cutoff_us)


def test_an_empty_window_still_reports_its_counters() -> None:
    origin = 3_000_000_000_000
    window = snapshot_window(origin, cutoff_seconds=120, max_quote_age_seconds=60)
    created = np.array([origin - 10**12], dtype=np.int64)
    snapshot = latest_quote_per_contract(created, np.array([1], dtype=np.int64), window)

    assert snapshot.contracts == 0
    assert snapshot.duplicates_dropped == 0
    assert snapshot.post_cutoff_selected == 0


def test_the_scorecard_refuses_a_field_it_could_not_measure() -> None:
    from mds650.rp2.scorecard import assert_scorecard_complete, required_fields

    groups = required_fields()
    scorecard: dict[str, object] = {
        group: dict.fromkeys(fields, 1.0) for group, fields in groups.items() if group != "forecast"
    }
    # The three counters whose only admissible value is zero.
    scorecard["data"] = {**scorecard["data"], "duplicate_keys": 0}  # type: ignore[dict-item]
    scorecard["b1"] = {
        **scorecard["b1"],
        "b1_post_cutoff_observations": 0,
        "b1_duplicate_contracts_per_snapshot": 0,
        "b1_rows_dropped_for_rate_or_dividend": 0,
    }  # type: ignore[dict-item]
    scorecard["b2"] = {**scorecard["b2"], "b2_pit_violation_count": 0}  # type: ignore[dict-item]
    from mds650.rp2.ladder import PRIMARY_MODELS

    scorecard["forecast"] = {
        family: {
            role: {
                field: 1.0
                for field in groups["forecast"]
                if field not in ("calibration_slope", "calibration_intercept")
            }
            for role in ("D", "V")
        }
        for family in PRIMARY_MODELS
    }
    scorecard["forecast_calibration"] = {
        "calibration_slope": 1.0,
        "calibration_intercept": 0.0,
        "by_role_and_family": {
            role: {family: {"slope": 1.0, "intercept": 0.0} for family in PRIMARY_MODELS}
            for role in ("D", "V")
        },
    }
    assert_scorecard_complete(scorecard)

    scorecard["b2"] = {**scorecard["b2"], "b2_pit_violation_count": None}  # type: ignore[dict-item]
    with pytest.raises(ValueError, match="b2.b2_pit_violation_count:unmeasured"):
        assert_scorecard_complete(scorecard)


def test_a_container_that_measured_nothing_is_not_a_measurement() -> None:
    """`provider_failures` is a pair and `sessions_by_role` is a mapping.

    A shallower check would accept `(None, None)` and `{}` as measured values, because
    both are present and neither is itself null. That is the shape a run takes when a
    producer wrote no artifact at all.
    """

    from mds650.rp2.scorecard import assert_scorecard_complete, required_fields

    groups = required_fields()
    scorecard: dict[str, object] = {
        group: dict.fromkeys(fields, 1.0) for group, fields in groups.items() if group != "forecast"
    }
    # The three counters whose only admissible value is zero.
    scorecard["data"] = {**scorecard["data"], "duplicate_keys": 0}  # type: ignore[dict-item]
    scorecard["b1"] = {
        **scorecard["b1"],
        "b1_post_cutoff_observations": 0,
        "b1_duplicate_contracts_per_snapshot": 0,
        "b1_rows_dropped_for_rate_or_dividend": 0,
    }  # type: ignore[dict-item]
    scorecard["b2"] = {**scorecard["b2"], "b2_pit_violation_count": 0}  # type: ignore[dict-item]
    from mds650.rp2.ladder import PRIMARY_MODELS

    scorecard["forecast"] = {
        family: {
            role: {
                field: 1.0
                for field in groups["forecast"]
                if field not in ("calibration_slope", "calibration_intercept")
            }
            for role in ("D", "V")
        }
        for family in PRIMARY_MODELS
    }
    scorecard["forecast_calibration"] = {
        "calibration_slope": 1.0,
        "calibration_intercept": 0.0,
        "by_role_and_family": {
            role: {family: {"slope": 1.0, "intercept": 0.0} for family in PRIMARY_MODELS}
            for role in ("D", "V")
        },
    }

    for value in ((None, None), {}, {"D": None}, []):
        scorecard["data"] = {**scorecard["data"], "provider_failures": value}  # type: ignore[dict-item]
        with pytest.raises(ValueError, match="data.provider_failures:unmeasured"):
            assert_scorecard_complete(scorecard)

    scorecard["data"] = {**scorecard["data"], "provider_failures": (0, 0)}  # type: ignore[dict-item]
    assert_scorecard_complete(scorecard)


def test_calibration_is_reported_for_every_primary_family_and_role() -> None:
    """One family's calibration on one role is not the run's calibration.

    The scorecard reported the D-role `lightgbm_qlike` slope and intercept and nothing
    else, so a reader could not see that a smooth family was well calibrated where the
    booster was not, or that V differed from D — which is the comparison the number exists
    to support.
    """

    from mds650.rp2.ladder import PRIMARY_MODELS
    from mds650.rp2.scorecard import calibration_table

    ladder = {
        role: {
            "models": {
                family: {
                    "calibration": {
                        f"{family}|B0": {"slope": 1.0, "intercept": 0.0},
                        f"{family}|B0+B1+B2": {"slope": 1.1, "intercept": -0.2},
                    }
                }
                for family in PRIMARY_MODELS
            }
        }
        for role in ("D", "V")
    }
    table = calibration_table(ladder, ("D", "V"))
    for role in ("D", "V"):
        for family in PRIMARY_MODELS:
            entry = table[role][family]
            assert entry["slope"] == 1.1, (role, family)
            assert entry["intercept"] == -0.2, (role, family)

    # A family the run did not fit is absent, not silently reported as zero.
    partial = {"D": {"models": {"gamma_glm": ladder["D"]["models"]["gamma_glm"]}}}
    assert set(calibration_table(partial, ("D",))["D"]) == {"gamma_glm"}


def test_the_snapshot_separates_collapsed_observations_from_remaining_duplicates() -> None:
    """Two different questions that were answered with one number.

    `duplicates_dropped` counts the superseded quotes the collapse removed, which is
    ordinary and large. `duplicate_contracts_remaining` counts contracts appearing twice in
    the selected snapshot, which is zero by construction. Reporting the first under the
    second's name makes an ordinary snapshot look like a broken one.
    """

    origin = 4_000_000_000_000
    window = snapshot_window(origin, cutoff_seconds=0, max_quote_age_seconds=600)
    created = np.array([origin - 400_000_000, origin - 300_000_000, origin - 200_000_000], np.int64)
    keys = np.array([7, 7, 9], dtype=np.int64)
    snapshot = latest_quote_per_contract(created, keys, window)

    assert snapshot.contracts == 2
    assert snapshot.duplicates_dropped == 1
    assert snapshot.duplicate_contracts_remaining == 0


def test_block_three_and_block_four_read_one_list_of_bar_stores() -> None:
    """The target artifact described 316 sessions while the study ran on 469.

    Block 3 kept its own four-source copy while Block 4 used the shared six, so the
    published target panel was silently narrower than the panel every result was fitted on
    — including the 153-session backfill.
    """

    import importlib.util
    import sys
    from pathlib import Path

    from mds650.rp2.bars import BAR_SOURCES

    repo = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location(
        "rp2_block3_target_panel", repo / "scripts" / "rp2_block3_target_panel.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["rp2_block3_target_panel"] = module
    spec.loader.exec_module(module)

    assert module.BAR_SOURCES is BAR_SOURCES
    # Both roles must be represented, and every store must name a distinct path. The count
    # itself is not the invariant: it went from six to five when `gate7_c6` and
    # `gate8_c4c`, which carried no high, low or volume, were replaced by the re-acquired
    # `ohlcv_repair` covering the same 360 asset-sessions with the same closes.
    assert {role for _, role, _ in BAR_SOURCES} == {"D", "V"}
    assert len({path for _, _, path in BAR_SOURCES}) == len(BAR_SOURCES)
    assert len({name for name, _, _ in BAR_SOURCES}) == len(BAR_SOURCES)


def test_the_latency_tail_is_a_quantile_of_trades_not_of_windows() -> None:
    """Quantiles do not merge by averaging, whatever windows they came from.

    Taking the median across counting windows of each window's own 95th percentile lets a
    window holding one trade weigh as much as a window holding ninety-nine, and the result is
    not the 95th percentile of any population. The producer emits a fixed-bin histogram of
    the latencies it saw, the histograms add, and the quantile is read off the total.
    """

    from mds650.rp2.scorecard import DURATION_BIN_EDGES, duration_quantile

    # One window of ninety-nine fast trades and one window of a single slow trade. A median
    # of per-window tails calls this slow; the population's 95th percentile is fast.
    fast = np.zeros(len(DURATION_BIN_EDGES) + 1, dtype=np.int64)
    fast[np.searchsorted(DURATION_BIN_EDGES, 0.5, side="right")] = 99
    slow = np.zeros_like(fast)
    slow[np.searchsorted(DURATION_BIN_EDGES, 600.0, side="right")] = 1

    assert duration_quantile(fast + slow, 0.95) == pytest.approx(0.5, rel=0.5)
    # And the tail does find the slow trades once there are enough of them to be the tail.
    many_slow = np.zeros_like(fast)
    many_slow[np.searchsorted(DURATION_BIN_EDGES, 600.0, side="right")] = 20
    assert duration_quantile(fast + many_slow, 0.95) > 100.0
    assert duration_quantile(np.zeros_like(fast), 0.95) == 0.0


def test_a_tail_of_zero_beside_counted_trades_is_a_missing_measurement() -> None:
    """Zero is a legitimate latency and a legitimate way for a histogram to be absent.

    A panel written by a producer that does not emit latency bins yields an empty histogram,
    and `duration_quantile` reports 0.0 for it — a finite float that `assert_scorecard_complete`
    accepts. That is exactly how a run built by the previous Block 6 would have published an
    unmeasured tail as a measured one, so the pairing is checked instead: trades were counted
    and no latency was binned.
    """

    from mds650.rp2.scorecard import assert_scorecard_invariants

    measured = {
        "data": {"duplicate_keys": 0},
        "b1": {"b1_post_cutoff_observations": 0, "b1_duplicate_contracts_per_snapshot": 0},
        "b2": {
            "b2_pit_violation_count": 0,
            "b2_counted_trades": 580_000_000,
            "b2_p95_provider_latency_s": 4.5,
            "b2_mean_provider_latency_s": 1.2,
        },
    }
    assert_scorecard_invariants(measured)

    unmeasured = {**measured, "b2": {**measured["b2"], "b2_p95_provider_latency_s": 0.0}}
    with pytest.raises(ValueError, match="RP2_SCORECARD_LATENCY_TAIL_UNMEASURED"):
        assert_scorecard_invariants(unmeasured)


def test_a_panel_without_the_latency_bins_is_refused_rather_than_read_as_zero(
    tmp_path: Path,
) -> None:
    """An absent bin column and an empty bin are the same number and different facts."""

    import polars as pl

    from mds650.rp2.scorecard import DURATION_BIN_EDGES, duration_histogram

    panel = tmp_path / "b2.parquet"
    complete = {
        f"b2_latency_bin_{index}": [0.0] for index in range(len(DURATION_BIN_EDGES) + 1)
    }
    pl.DataFrame(complete).write_parquet(panel)
    assert duration_histogram(panel, "b2_latency_bin_").sum() == 0

    truncated = {k: v for k, v in complete.items() if k != "b2_latency_bin_7"}
    pl.DataFrame(truncated).write_parquet(panel)
    with pytest.raises(ValueError, match="RP2_SCORECARD_LATENCY_BINS_INCOMPLETE"):
        duration_histogram(panel, "b2_latency_bin_")

    pl.DataFrame({"b2_counting_trades": [1.0]}).write_parquet(panel)
    with pytest.raises(ValueError, match="RP2_SCORECARD_LATENCY_BINS_INCOMPLETE"):
        duration_histogram(panel, "b2_latency_bin_")
