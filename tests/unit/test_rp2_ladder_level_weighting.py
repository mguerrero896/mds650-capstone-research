"""A published loss level and the delta beside it have to be the same statistic.

The ladder's contrasts were moved to session weighting because origins five minutes apart
share overlapping thirty-minute targets, so a busy session outweighed a quiet one and an
early close counted for less than a full day. `_contrast`'s own docstring records that
change. The loss LEVELS published in the same record kept `np.mean` over every evaluated
test row.

The consequence is that a reader cannot rebuild the published delta from the published
levels. Measured on the RP2-v3 development panel, `qlike[B0] - qlike[B0+B1]` disagrees with
`delta_b1` by 2.2 % for `gamma_glm`, 2.0 % for `ridge_log` and 0.2 % for `lightgbm_qlike` —
small, and enough that the two numbers are not describing the same quantity.
"""

from __future__ import annotations

import numpy as np
import pytest

from mds650.rp2.ladder import session_weighted_level


def test_a_busy_session_does_not_outweigh_a_quiet_one() -> None:
    """Two sessions, one with nine origins and one with a single origin."""
    losses = np.array([1.0] * 9 + [11.0], dtype=np.float64)
    sessions = np.array([0] * 9 + [1], dtype=np.int64)

    by_origin = float(np.mean(losses))
    by_session = session_weighted_level(losses, sessions)

    assert by_origin == pytest.approx(2.0), "the origin-weighted mean follows the busy session"
    assert by_session == pytest.approx(6.0), "each session contributes once"


def test_the_level_difference_reproduces_the_session_delta() -> None:
    """The property the published record has to have: level(base) - level(expanded)."""
    sessions = np.array([0, 0, 0, 1], dtype=np.int64)
    base = np.array([1.0, 1.0, 1.0, 4.0], dtype=np.float64)
    expanded = np.array([0.5, 0.5, 0.5, 3.0], dtype=np.float64)

    # The session-level contrast is the mean over sessions of each session's mean
    # difference, which is exactly the difference of the two session-weighted levels.
    per_session_delta = np.array([np.mean(base[:3] - expanded[:3]), base[3] - expanded[3]])

    difference = session_weighted_level(base, sessions) - session_weighted_level(
        expanded, sessions
    )

    assert difference == pytest.approx(float(per_session_delta.mean()))
    assert difference != pytest.approx(float(np.mean(base) - np.mean(expanded)))


def test_non_finite_losses_are_dropped_rather_than_propagated() -> None:
    losses = np.array([1.0, np.nan, 3.0, 8.0], dtype=np.float64)
    sessions = np.array([0, 0, 0, 1], dtype=np.int64)

    assert session_weighted_level(losses, sessions) == pytest.approx(5.0)


def test_an_empty_evaluation_is_unmeasured_rather_than_zero() -> None:
    empty = np.empty(0, dtype=np.float64)
    assert np.isnan(session_weighted_level(empty, np.empty(0, dtype=np.int64)))
