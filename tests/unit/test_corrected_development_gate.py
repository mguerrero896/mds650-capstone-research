"""TDD checks for the target-free corrected-development release gate."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import polars as pl
import pytest

from mds650.corrected_development_release import (
    FROZEN_B2_FEATURES,
    prepare_corrected_development_panel,
)
from mds650.study_design import build_study_sessions


def test_gate_keeps_exact_development_sessions_and_explicit_b2_exclusions() -> None:
    """The target-free release retains all 80 development origins and no holdout row."""
    development, holdout = _study_sessions()

    prepared = prepare_corrected_development_panel(
        panel=_panel(development, excluded_index=3),
        development_sessions=development,
        holdout_sessions=holdout,
    )

    assert prepared.panel.height == 80
    assert prepared.panel.get_column("session_date").unique().sort().to_list() == development
    assert not set(prepared.panel.get_column("session_date").to_list()) & set(holdout)
    assert prepared.common.height == 79
    assert prepared.b2_excluded_origin_count == 1
    excluded = prepared.panel.filter(~pl.col("b2v2_availability_eligible"))
    assert all(excluded.get_column(name).null_count() == 1 for name in FROZEN_B2_FEATURES)


def test_gate_rejects_development_holdout_overlap_before_processing_rows() -> None:
    """A caller cannot smuggle a prospective date into the development identity."""
    development, holdout = _study_sessions()

    with pytest.raises(ValueError, match="CORRECTED_DEVELOPMENT_HOLDOUT_OVERLAP"):
        prepare_corrected_development_panel(
            panel=_panel(development),
            development_sessions=[*development[:-1], holdout[0]],
            holdout_sessions=holdout,
        )


def test_gate_rejects_duplicate_origin_and_future_predictor() -> None:
    """The target-free release fails before any target binding for two leakage hazards."""
    development, holdout = _study_sessions()
    panel = _panel(development)

    with pytest.raises(ValueError, match="CORRECTED_DEVELOPMENT_DUPLICATE_ORIGIN"):
        prepare_corrected_development_panel(
            panel=pl.concat([panel, panel.head(1)]),
            development_sessions=development,
            holdout_sessions=holdout,
        )

    future = panel.with_columns(
        (pl.col("b0v2_max_predictor_available_at_utc") + pl.duration(seconds=2)).alias(
            "b0v2_max_predictor_available_at_utc"
        )
    )
    with pytest.raises(ValueError, match="CORRECTED_DEVELOPMENT_FUTURE_PREDICTOR"):
        prepare_corrected_development_panel(
            panel=future,
            development_sessions=development,
            holdout_sessions=holdout,
        )


def test_gate_rejects_target_column_and_zero_coded_delayed_b2_row() -> None:
    """Neither an outcome payload nor delayed-source zero coding may enter this release."""
    development, holdout = _study_sessions()
    panel = _panel(development, excluded_index=0)

    with pytest.raises(ValueError, match="CORRECTED_DEVELOPMENT_FORBIDDEN_COLUMN"):
        prepare_corrected_development_panel(
            panel=panel.with_columns(pl.lit(0.01).alias("rv30")),
            development_sessions=development,
            holdout_sessions=holdout,
        )

    invalid = panel.with_columns(pl.lit(0.0).alias(FROZEN_B2_FEATURES[0]))
    with pytest.raises(ValueError, match="CORRECTED_DEVELOPMENT_B2_EXCLUDED_FEATURE_NOT_NULL"):
        prepare_corrected_development_panel(
            panel=invalid,
            development_sessions=development,
            holdout_sessions=holdout,
        )


def _study_sessions() -> tuple[list[str], list[str]]:
    sessions = build_study_sessions(
        "XNYS",
        development_end=datetime(2026, 7, 17, tzinfo=UTC).date(),
        development_count=80,
        holdout_count=10,
    )
    return sessions["development"], sessions["holdout"]


def _panel(development: list[str], excluded_index: int | None = None) -> pl.DataFrame:
    rows: list[dict[str, object]] = []
    for index, session_date in enumerate(development):
        origin = datetime.fromisoformat(f"{session_date}T14:00:00+00:00")
        eligible = index != excluded_index
        row: dict[str, object] = {
            "origin_id": f"AAPL|{session_date}|{index:03d}",
            "asset": "AAPL",
            "session_date": session_date,
            "forecast_origin_utc": origin,
            "forecast_origin_ns": int(origin.timestamp() * 1_000_000_000),
            "b0v2_max_predictor_available_at_utc": origin - timedelta(seconds=1),
            "max_sip_timestamp_ns": int(
                (origin - timedelta(seconds=1)).timestamp() * 1_000_000_000
            ),
            "b2v2_cutoff_utc": origin - timedelta(seconds=60),
            "b2v2_max_created_at_utc": origin - timedelta(seconds=61) if eligible else None,
            "b2v2_availability_eligible": eligible,
            "b2v2_availability_status": (
                "PIT_USABLE_ELIGIBLE_ACTIVITY"
                if eligible
                else "PIT_EXCLUDED_DELAYED_RAW_WINDOW_TRADES"
            ),
            "b2v2_predictor_missing_reason": (
                None if eligible else "B2V2_DELAYED_OR_UNAVAILABLE_ACTIVITY"
            ),
            "b2v2_predictor_complete": eligible,
            "common_predictor_complete": eligible,
        }
        for feature in FROZEN_B2_FEATURES:
            row[feature] = 1.0 if eligible else None
        rows.append(row)
    return pl.DataFrame(rows, strict=False)
