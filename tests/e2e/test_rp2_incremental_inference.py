"""One contrast, end to end: the session is the unit and the record says so.

Every number the programme reports about an increment comes from this path. What is
checked here is not that the arithmetic runs but that the answer is invariant to things
that carry no information — how many origins a session happened to contain, what order the
assets arrived in — and that it moves when the sessions themselves change.
"""

from __future__ import annotations

import numpy as np
import pytest

from mds650.rp2.inference import (
    SESSION_BLOCK_LENGTH,
    session_contrast,
)

MASK = "b" * 64


def _losses(sessions_count: int = 60, per_session: int = 8, seed: int = 5) -> tuple:
    rng = np.random.default_rng(seed)
    sessions = np.repeat(np.arange(sessions_count, dtype=np.int64), per_session)
    base = rng.lognormal(-1.0, 0.5, sessions.size)
    expanded = base - 0.02 + rng.normal(0.0, 0.05, sessions.size)
    return base, expanded, sessions


def _contrast(base, expanded, sessions):
    return session_contrast(
        base,
        expanded,
        sessions,
        model_family="lightgbm_qlike",
        base_information_set="B0",
        expanded_information_set="B0+B1",
        common_mask_sha256=MASK,
    )


def test_replicating_rows_inside_one_day_does_not_change_the_estimate() -> None:
    """A session with twice the origins is still one session.

    A count-weighted mean would let a busy day speak twice; the contract says every
    trading session carries the same weight.
    """

    base, expanded, sessions = _losses()
    plain = _contrast(base, expanded, sessions)
    duplicated = sessions == 0
    doubled = _contrast(
        np.concatenate([base, base[duplicated]]),
        np.concatenate([expanded, expanded[duplicated]]),
        np.concatenate([sessions, sessions[duplicated]]),
    )
    assert doubled.estimate == pytest.approx(plain.estimate, abs=1e-12)
    assert doubled.sessions == plain.sessions


def test_reordering_assets_inside_a_day_does_not_change_inference() -> None:
    base, expanded, sessions = _losses()
    order = np.random.default_rng(3).permutation(sessions.size)
    shuffled = _contrast(base[order], expanded[order], sessions[order])
    plain = _contrast(base, expanded, sessions)
    assert shuffled.estimate == pytest.approx(plain.estimate, abs=1e-12)
    assert shuffled.p_value == pytest.approx(plain.p_value, abs=1e-12)
    assert shuffled.ci_low == pytest.approx(plain.ci_low, abs=1e-12)


def test_early_close_days_receive_the_same_day_weight() -> None:
    """A half day has fewer origins. It is not half a session."""

    rng = np.random.default_rng(11)
    sessions = np.concatenate(
        [np.repeat(np.arange(40, dtype=np.int64), 8), np.full(2, 40, dtype=np.int64)]
    )
    base = rng.lognormal(-1.0, 0.4, sessions.size)
    expanded = base.copy()
    expanded[sessions == 40] -= 5.0  # the short session strongly favours the expansion
    full_only = _contrast(base[sessions < 40], expanded[sessions < 40], sessions[sessions < 40])
    with_short = _contrast(base, expanded, sessions)
    # One extra session out of 41, weighted like any other: 5.0 / 41 of the mean.
    assert with_short.estimate - full_only.estimate * 40.0 / 41.0 == pytest.approx(
        5.0 / 41.0, abs=1e-9
    )
    assert with_short.sessions == 41


def test_the_record_carries_everything_the_plan_requires() -> None:
    base, expanded, sessions = _losses()
    record = _contrast(base, expanded, sessions).as_record()
    required = {
        "estimate",
        "ci_low",
        "ci_high",
        "p_value",
        "sessions",
        "block_length",
        "common_mask_sha256",
        "model_family",
        "base_information_set",
        "expanded_information_set",
        "mde",
        "equivalence_bound",
    }
    assert required <= set(record)
    assert record["block_length"] == SESSION_BLOCK_LENGTH
    assert record["common_mask_sha256"] == MASK
    assert record["mde"] > 0.0
    assert record["equivalence_bound"] > 0.0


def test_a_contrast_refuses_to_be_recorded_without_the_mask_it_was_measured_on() -> None:
    """A delta whose evaluation rows are unidentified cannot be checked by anyone."""

    base, expanded, sessions = _losses()
    with pytest.raises(ValueError, match="RP2_INFERENCE_MASK_DIGEST_INVALID"):
        session_contrast(
            base,
            expanded,
            sessions,
            model_family="ridge_log",
            base_information_set="B0",
            expanded_information_set="B0+B1",
            common_mask_sha256="",
        )


def test_a_null_is_reported_as_equivalent_only_when_the_interval_is_inside_the_bound() -> None:
    rng = np.random.default_rng(7)
    sessions = np.repeat(np.arange(80, dtype=np.int64), 6)
    base = rng.lognormal(-1.0, 0.3, sessions.size)
    null = _contrast(base, base + rng.normal(0.0, 1e-6, sessions.size), sessions)
    assert null.p_value > 0.05
    assert null.equivalent, "a tiny, tightly bounded difference is equivalence, not silence"

    wide = _contrast(base, base + rng.normal(0.0, 3.0, sessions.size), sessions)
    assert not wide.equivalent, "a wide interval is an inconclusive result, not a null"
