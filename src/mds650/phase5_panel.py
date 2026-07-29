"""Fail-closed construction of the common Phase 5 development panel."""

from __future__ import annotations

from collections.abc import Iterable

import polars as pl

from mds650.study_design import B2_FEATURE_NAMES

_B0_PREDICTORS = (
    "b0_spot",
    "b0_rv_5m_lag",
    "b0_rv_30m_lag",
    "b0_return_5m_lag",
    "b0_volume_5m_lag",
    "b0_session_minute",
)


def _require_columns(frame: pl.DataFrame, name: str, columns: Iterable[str]) -> None:
    missing = sorted(set(columns) - set(frame.columns))
    if missing:
        raise ValueError(f"PANEL_REQUIRED_COLUMNS_MISSING:{name}:{','.join(missing)}")


def _reject_duplicate_origins(frame: pl.DataFrame) -> None:
    if frame["origin_id"].null_count() or frame["origin_id"].n_unique() != frame.height:
        raise ValueError("DUPLICATE_FORECAST_ORIGIN")


def _join_new_columns(left: pl.DataFrame, right: pl.DataFrame) -> pl.DataFrame:
    additions = ["origin_id", *[column for column in right.columns if column not in left.columns]]
    return left.join(right.select(additions), on="origin_id", how="left")


def build_common_panel(
    origins: pl.DataFrame,
    b0: pl.DataFrame,
    b1: pl.DataFrame,
    b2: pl.DataFrame,
    *,
    excluded_dates: frozenset[str],
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Join B0/B1a/B2 on identical valid RV30 forecast origins.

    Parameters
    ----------
    origins, b0, b1, b2:
        One-row-per-origin target and predictor tables.
    excluded_dates:
        Session dates reserved from development, including the holdout.

    Returns
    -------
    tuple[polars.DataFrame, polars.DataFrame]
        All development origins with gate flags, then the common complete-case
        panel used by every nested information set.

    Raises
    ------
    ValueError
        If keys repeat, required columns are absent, excluded dates leak into
        development, or a predictor timestamp occurs after its allowed cutoff.
    """
    required = {
        "origins": (
            "origin_id",
            "session_date",
            "forecast_origin_utc",
            "rv30",
            "target_price_count",
            "target_future_close_count",
            "target_validity",
        ),
        "b0": ("origin_id", "b0_available_at_utc", *_B0_PREDICTORS),
        "b1": (
            "origin_id",
            "b1q_atm_iv",
            "b1a_complete",
            "b1q_pit_evidence_valid",
            "b1q_quote_not_after_origin",
        ),
        "b2": (
            "origin_id",
            "b2_window_end",
            "b2_max_operational_time",
            *B2_FEATURE_NAMES,
        ),
    }
    frames = {"origins": origins, "b0": b0, "b1": b1, "b2": b2}
    for name, frame in frames.items():
        _require_columns(frame, name, required[name])
        _reject_duplicate_origins(frame)

    if excluded_dates and origins.filter(
        pl.col("session_date").cast(pl.String).is_in(excluded_dates)
    ).height:
        raise ValueError("HOLDOUT_DATE_IN_DEVELOPMENT_PANEL")

    panel = origins
    for frame in (b0, b1, b2):
        panel = _join_new_columns(panel, frame)
    if panel.height != origins.height:
        raise ValueError("PANEL_JOIN_MULTIPLIED_ORIGINS")

    if panel.filter(
        pl.col("b0_available_at_utc").is_not_null()
        & (pl.col("b0_available_at_utc") > pl.col("forecast_origin_utc"))
    ).height:
        raise ValueError("B0_PREDICTOR_AFTER_FORECAST_ORIGIN")
    if panel.filter(
        pl.col("b2_window_end").is_not_null()
        & (pl.col("b2_window_end") > pl.col("forecast_origin_utc"))
    ).height:
        raise ValueError("B2_WINDOW_END_AFTER_FORECAST_ORIGIN")
    if panel.filter(
        pl.col("b2_max_operational_time").is_not_null()
        & (pl.col("b2_max_operational_time") > pl.col("b2_window_end"))
    ).height:
        raise ValueError("B2_PREDICTOR_AFTER_WINDOW_END")

    target_complete = (
        (pl.col("target_validity") == "valid")
        & (pl.col("target_price_count") == 31)
        & (pl.col("target_future_close_count") == 30)
        & pl.col("rv30").cast(pl.Float64).is_finite()
        & (pl.col("rv30") > 0)
    )
    b0_complete = target_complete & pl.all_horizontal(
        [
            pl.col(column).cast(pl.Float64).is_finite().fill_null(False)
            for column in _B0_PREDICTORS
        ]
        + [
            pl.col("b0_available_at_utc").is_not_null(),
            pl.col("b0_available_at_utc") <= pl.col("forecast_origin_utc"),
        ]
    )
    b1a_common_complete = b0_complete & pl.all_horizontal(
        [
            pl.col("b1a_complete").fill_null(False),
            (
                pl.col("b1q_atm_iv").cast(pl.Float64).is_finite()
                & (pl.col("b1q_atm_iv") > 0)
            ).fill_null(False),
            pl.col("b1q_pit_evidence_valid").fill_null(False),
            pl.col("b1q_quote_not_after_origin").fill_null(False),
        ]
    )
    b2_complete = b1a_common_complete & pl.all_horizontal(
        [
            pl.col(name).cast(pl.Float64).is_finite().fill_null(False)
            for name in B2_FEATURE_NAMES
        ]
        + [
            pl.col("b2_window_end").is_not_null(),
            (
                pl.col("b2_max_operational_time").is_null()
                | (
                    pl.col("b2_max_operational_time")
                    <= pl.col("b2_window_end")
                )
            ),
        ]
    )
    panel = panel.with_columns(
        target_complete.fill_null(False).alias("target_complete"),
        b0_complete.fill_null(False).alias("b0_complete"),
        b1a_common_complete.fill_null(False).alias("b1a_common_complete"),
        b2_complete.fill_null(False).alias("common_complete"),
    )
    return panel, panel.filter(pl.col("common_complete"))
