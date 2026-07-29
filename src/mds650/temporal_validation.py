"""Chronological, purged validation helpers for the RV30 study."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import polars as pl


@dataclass(frozen=True)
class FoldDefinition:
    """One preregistered expanding-window outer fold."""

    fold: int
    train_end: date
    test_start: date
    test_end: date


def parse_fold_definitions(
    rows: Sequence[Mapping[str, object]],
) -> tuple[FoldDefinition, ...]:
    """Parse preregistered fold dictionaries.

    Parameters
    ----------
    rows:
        Mappings with ``fold``, ``train_end``, ``test_start`` and ``test_end``.

    Returns
    -------
    tuple[FoldDefinition, ...]
        Validated folds in declared order.

    Raises
    ------
    ValueError
        If dates are missing, unordered or folds repeat.
    """
    parsed: list[FoldDefinition] = []
    for row in rows:
        try:
            fold = FoldDefinition(
                fold=int(str(row["fold"])),
                train_end=date.fromisoformat(str(row["train_end"])),
                test_start=date.fromisoformat(str(row["test_start"])),
                test_end=date.fromisoformat(str(row["test_end"])),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("INVALID_FOLD_DEFINITION") from exc
        if fold.train_end >= fold.test_start or fold.test_start > fold.test_end:
            raise ValueError("INVALID_FOLD_DATE_ORDER")
        parsed.append(fold)
    if len({fold.fold for fold in parsed}) != len(parsed):
        raise ValueError("DUPLICATE_FOLD_ID")
    return tuple(parsed)


def purge_and_embargo_training(
    frame: pl.DataFrame,
    test_start: datetime,
    *,
    origin_column: str = "forecast_origin_utc",
    target_horizon_minutes: int = 30,
    purge_minutes: int = 30,
    embargo_minutes: int = 30,
) -> pl.DataFrame:
    """Remove training origins whose labels approach a test boundary.

    The cutoff conservatively combines the larger of the target horizon and
    declared purge with the declared embargo.

    Parameters
    ----------
    frame:
        Candidate training rows.
    test_start:
        Earliest forecast origin in the evaluation block.
    origin_column:
        UTC forecast-origin column.
    target_horizon_minutes, purge_minutes, embargo_minutes:
        Non-negative temporal safeguards.

    Returns
    -------
    polars.DataFrame
        Rows whose origins end before the protected test boundary.

    Raises
    ------
    ValueError
        If the origin column or a valid safeguard is missing.
    """
    if origin_column not in frame.columns:
        raise ValueError(f"TEMPORAL_COLUMN_MISSING:{origin_column}")
    if min(target_horizon_minutes, purge_minutes, embargo_minutes) < 0:
        raise ValueError("NEGATIVE_TEMPORAL_GUARD")
    protected_minutes = max(target_horizon_minutes, purge_minutes) + embargo_minutes
    cutoff = test_start - timedelta(minutes=protected_minutes)
    return frame.filter(pl.col(origin_column) <= cutoff)


def split_expanding_fold(
    frame: pl.DataFrame,
    fold: FoldDefinition,
    *,
    session_column: str = "session_date",
    origin_column: str = "forecast_origin_utc",
    target_horizon_minutes: int = 30,
    purge_minutes: int = 30,
    embargo_minutes: int = 30,
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Create one expanding training/test split without temporal overlap.

    Parameters
    ----------
    frame:
        Development panel.
    fold:
        Preregistered fold boundary.
    session_column, origin_column:
        Session and UTC-origin columns.
    target_horizon_minutes, purge_minutes, embargo_minutes:
        Temporal safeguards.

    Returns
    -------
    tuple[polars.DataFrame, polars.DataFrame]
        Purged training rows and untouched chronological test rows.

    Raises
    ------
    ValueError
        If required columns are absent or either side is empty.
    """
    missing = {session_column, origin_column} - set(frame.columns)
    if missing:
        raise ValueError(f"TEMPORAL_COLUMNS_MISSING:{','.join(sorted(missing))}")
    day = pl.col(session_column).cast(pl.String)
    training = frame.filter(day <= pl.lit(fold.train_end.isoformat()))
    testing = frame.filter(
        day.is_between(
            pl.lit(fold.test_start.isoformat()),
            pl.lit(fold.test_end.isoformat()),
            closed="both",
        )
    )
    if training.is_empty() or testing.is_empty():
        raise ValueError(f"EMPTY_TEMPORAL_FOLD:{fold.fold}")
    first_test_origin = testing[origin_column].min()
    if not isinstance(first_test_origin, datetime):
        raise ValueError("INVALID_TEST_ORIGIN")
    training = purge_and_embargo_training(
        training,
        first_test_origin,
        origin_column=origin_column,
        target_horizon_minutes=target_horizon_minutes,
        purge_minutes=purge_minutes,
        embargo_minutes=embargo_minutes,
    )
    if training.is_empty():
        raise ValueError(f"EMPTY_PURGED_TRAINING_FOLD:{fold.fold}")
    return training.sort(origin_column), testing.sort(origin_column)


def split_inner_validation(
    frame: pl.DataFrame,
    *,
    validation_sessions: int = 10,
    session_column: str = "session_date",
    origin_column: str = "forecast_origin_utc",
    target_horizon_minutes: int = 30,
    purge_minutes: int = 30,
    embargo_minutes: int = 30,
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Reserve the last training sessions for deterministic inner selection.

    Parameters
    ----------
    frame:
        Outer-fold training history only.
    validation_sessions:
        Number of latest sessions used for inner validation.
    session_column, origin_column:
        Session and UTC-origin columns.
    target_horizon_minutes, purge_minutes, embargo_minutes:
        Temporal safeguards.

    Returns
    -------
    tuple[polars.DataFrame, polars.DataFrame]
        Earlier fitting rows and latest validation rows.

    Raises
    ------
    ValueError
        If there is insufficient training history.
    """
    missing = {session_column, origin_column} - set(frame.columns)
    if missing:
        raise ValueError(f"TEMPORAL_COLUMNS_MISSING:{','.join(sorted(missing))}")
    sessions = sorted(
        frame[session_column].cast(pl.String).unique().to_list()
    )
    if validation_sessions < 1 or len(sessions) <= validation_sessions:
        raise ValueError("INSUFFICIENT_INNER_VALIDATION_HISTORY")
    validation_days = sessions[-validation_sessions:]
    validation = frame.filter(
        pl.col(session_column).cast(pl.String).is_in(validation_days)
    )
    fitting = frame.filter(
        ~pl.col(session_column).cast(pl.String).is_in(validation_days)
    )
    first_validation_origin = validation[origin_column].min()
    if not isinstance(first_validation_origin, datetime):
        raise ValueError("INVALID_INNER_VALIDATION_ORIGIN")
    fitting = purge_and_embargo_training(
        fitting,
        first_validation_origin,
        origin_column=origin_column,
        target_horizon_minutes=target_horizon_minutes,
        purge_minutes=purge_minutes,
        embargo_minutes=embargo_minutes,
    )
    if fitting.is_empty():
        raise ValueError("EMPTY_INNER_FITTING_HISTORY")
    return fitting.sort(origin_column), validation.sort(origin_column)
