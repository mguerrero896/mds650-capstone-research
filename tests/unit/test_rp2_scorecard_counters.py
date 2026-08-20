"""The scorecard's counters have to be measured, not assumed to be zero.

`b2_pit_violation_count` and `b1_post_cutoff_observations` are zero by construction: the
selection is a `searchsorted` at the cutoff. That is exactly why they are worth counting.
A field reported as zero because nobody looked is indistinguishable from a field reported
as zero because somebody did, and only one of them would notice a regression.
"""

from __future__ import annotations

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
