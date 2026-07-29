"""Unit contracts for the local-only Phase 4B helpers."""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import polars as pl
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from phase4b_common import (  # noqa: E402
    build_checkpoint,
    canonicalize_b2_frame,
    event_is_eligible,
    holdout_read_guard,
    strict_window_origin,
    validate_checkpoint,
    window_bounds,
)


def test_fixed_window_is_five_minutes_and_boundary_safe() -> None:
    origin = datetime(2026, 7, 13, 13, 35, tzinfo=UTC)
    start, end = window_bounds(origin, 60)
    assert end == datetime(2026, 7, 13, 13, 34, tzinfo=UTC)
    assert end - start == timedelta(minutes=5)
    assert event_is_eligible(start, start, origin, 60)
    assert not event_is_eligible(end, end, origin, 60)
    assert event_is_eligible(end - timedelta(microseconds=1), end, origin, 60)


def test_strict_window_origin_assigns_each_boundary_once() -> None:
    origin = datetime(2026, 7, 13, 13, 35, tzinfo=UTC)
    assert strict_window_origin(origin - timedelta(minutes=6), 60) == origin
    assert strict_window_origin(origin - timedelta(minutes=1), 60) == origin + timedelta(minutes=5)


def test_b2_aliases_are_canonicalized_and_duplicate_aliases_fail() -> None:
    frame = pl.DataFrame(
        {
            "implied_volatility_median": [0.2],
            "median_implied_volatility": [0.2],
            "implied_volatility_change_within_bin": [0.1],
        }
    )
    result = canonicalize_b2_frame(frame)
    assert set(result.columns) == {"implied_volatility_median", "within_bin_iv_change"}
    with pytest.raises(ValueError, match="B2_ALIAS_CONFLICT"):
        canonicalize_b2_frame(
            frame.with_columns(pl.lit(0.3).alias("median_implied_volatility"))
        )


def test_checkpoint_hashes_and_corruption_fail_closed() -> None:
    payload = build_checkpoint(
        session="2026-07-13",
        session_list=["2026-07-13"],
        config={"window_seconds": [60, 120, 300]},
        input_hashes={"events": "a" * 64},
        schema_hash="b" * 64,
        request_hashes=[],
        output_hash="c" * 64,
        origin_ids=["AAPL|2026-07-13|2026-07-13T13:35:00+00:00"],
    )
    assert validate_checkpoint(payload)
    corrupted = {**payload, "output_sha256": "d" * 64}
    with pytest.raises(ValueError, match="CHECKPOINT_CORRUPTED"):
        validate_checkpoint(corrupted)


def test_holdout_guard_denies_unreleased_data() -> None:
    manifest = {"status": "SEALED_NOT_ACQUIRED", "session_dates": ["2026-07-20"]}
    assert holdout_read_guard(manifest, requested_dates=[])
    with pytest.raises(PermissionError, match="PROSPECTIVE_HOLDOUT_READ_BLOCKED"):
        holdout_read_guard(manifest, requested_dates=["2026-07-20"])
