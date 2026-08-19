"""The contemporaneous snapshot: which rows an origin may read, and which one wins."""

from __future__ import annotations

import numpy as np
import pytest

from mds650.rp2.b1_snapshot import (
    CUTOFF_SECONDS,
    MAX_QUOTE_AGE_SECONDS,
    MICROSECONDS,
    latest_quote_per_contract,
    snapshot_window,
)

ORIGIN = 1_800_000_000 * MICROSECONDS


def _at(seconds_before_origin: float) -> int:
    return int(ORIGIN - seconds_before_origin * MICROSECONDS)


def test_b1_uses_a_quote_three_minutes_before_origin() -> None:
    """The whole point of the gate: a quote from three minutes ago is contemporaneous.

    Under the RP2-v2 window a row had to be at least 1 920 seconds old to be visible, so a
    three-minute-old quote — the freshest thing the tape had — was thrown away.
    """

    created = np.array([_at(180.0)], dtype=np.int64)
    keys = np.array([1], dtype=np.int64)
    snapshot = latest_quote_per_contract(created, keys, snapshot_window(ORIGIN))
    assert snapshot.contracts == 1
    assert snapshot.quote_age_seconds[0] == pytest.approx(180.0)


def test_b1_rejects_any_quote_after_the_cutoff() -> None:
    """A row the provider had not published yet is not evidence."""

    window = snapshot_window(ORIGIN)
    created = np.array(
        [_at(CUTOFF_SECONDS + 1.0), _at(CUTOFF_SECONDS), _at(CUTOFF_SECONDS - 1.0), _at(0.0)],
        dtype=np.int64,
    )
    keys = np.array([1, 2, 3, 4], dtype=np.int64)
    snapshot = latest_quote_per_contract(created, keys, window)
    assert snapshot.positions.tolist() == [0, 1]
    assert snapshot.quote_age_seconds.min() >= CUTOFF_SECONDS


def test_b1_keeps_only_the_latest_quote_per_contract() -> None:
    created = np.array([_at(1500.0), _at(900.0), _at(300.0), _at(200.0)], dtype=np.int64)
    keys = np.array([7, 7, 7, 9], dtype=np.int64)
    snapshot = latest_quote_per_contract(created, keys, snapshot_window(ORIGIN))
    assert snapshot.contracts == 2
    assert snapshot.positions.tolist() == [2, 3]
    assert sorted(snapshot.quote_age_seconds.tolist()) == [200.0, 300.0]


def test_b1_quote_age_is_measured_against_forecast_origin() -> None:
    """Against `t`, not against `t - 120 s`: the cutoff is a floor on the age, not zero."""

    created = np.array([_at(600.0)], dtype=np.int64)
    snapshot = latest_quote_per_contract(
        created, np.array([1], dtype=np.int64), snapshot_window(ORIGIN)
    )
    assert snapshot.quote_age_seconds[0] == pytest.approx(600.0)
    assert snapshot.quote_age_seconds[0] != pytest.approx(600.0 - CUTOFF_SECONDS)


def test_b1_at_1000_does_not_require_premarket_state() -> None:
    """A 10:00 origin reads 09:32 to 09:58, all of it inside the session."""

    window = snapshot_window(ORIGIN)
    assert window.span_seconds == pytest.approx(MAX_QUOTE_AGE_SECONDS)
    assert (ORIGIN - window.oldest_us) / MICROSECONDS == pytest.approx(
        MAX_QUOTE_AGE_SECONDS + CUTOFF_SECONDS
    )
    # 30 minutes into the session there is a full window of same-session tape available.
    assert MAX_QUOTE_AGE_SECONDS + CUTOFF_SECONDS <= 30 * 60 + CUTOFF_SECONDS


def test_an_empty_window_is_empty_rather_than_wrong() -> None:
    created = np.array([_at(4000.0), _at(3900.0)], dtype=np.int64)
    snapshot = latest_quote_per_contract(
        created, np.array([1, 2], dtype=np.int64), snapshot_window(ORIGIN)
    )
    assert snapshot.contracts == 0
    assert snapshot.quote_age_seconds.size == 0


def test_the_snapshot_refuses_an_unsorted_tape() -> None:
    created = np.array([_at(300.0), _at(900.0)], dtype=np.int64)
    with pytest.raises(ValueError, match="RP2_B1_SNAPSHOT_UNSORTED"):
        latest_quote_per_contract(
            created, np.array([1, 2], dtype=np.int64), snapshot_window(ORIGIN)
        )
