"""Causal and key-integrity primitives for canonical RV30 validation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime

import polars as pl

from mds650.temporal_validation import FoldDefinition, purge_and_embargo_training


def assert_identical_origin_sets(
    frames: Mapping[str, pl.DataFrame], *, key: str = "origin_id"
) -> list[str]:
    """Require identical, unique origin keys across information sets.

    Parameters
    ----------
    frames
        Named comparison frames. Every frame must contain exactly one row per origin key.
    key
        Key column used to pair information sets.

    Returns
    -------
    list[str]
        Deterministically sorted shared keys.

    Raises
    ------
    ValueError
        If no frames are supplied, a key is missing/null/duplicated, or a frame has a different
        key set.

    Notes
    -----
    The function does not join or impute rows. It only proves that a later paired comparison is
    based on precisely the same forecast origins.

    Examples
    --------
    >>> frames = {"B0v2": pl.DataFrame({"origin_id": ["a"]}),
    ...           "B1v2a": pl.DataFrame({"origin_id": ["a"]})}
    >>> assert_identical_origin_sets(frames)
    ['a']
    """

    if not frames:
        raise ValueError("CANONICAL_ORIGIN_SET_INVALID")
    sets: dict[str, set[str]] = {}
    for name, frame in sorted(frames.items()):
        if key not in frame.columns:
            raise ValueError("CANONICAL_ORIGIN_KEY_INVALID")
        values = frame.get_column(key).cast(pl.String)
        if values.null_count() > 0 or values.n_unique() != frame.height:
            raise ValueError("CANONICAL_ORIGIN_KEY_INVALID")
        sets[name] = set(values.to_list())
    baseline_name = min(sets)
    baseline = sets[baseline_name]
    if any(values != baseline for values in sets.values()):
        raise ValueError("CANONICAL_ORIGIN_SET_MISMATCH")
    return sorted(baseline)


def build_causal_audit(
    panel: pl.DataFrame,
    folds: Sequence[FoldDefinition],
    *,
    model_roles: Sequence[str],
    target_horizon_minutes: int,
    embargo_minutes: int,
    block: str,
) -> pl.DataFrame:
    """Build a train-before-test audit row for each fold and model role.

    Parameters
    ----------
    panel
        Forecast-origin panel containing ``origin_id``, ``session_date`` and
        ``forecast_origin_utc``. The timestamp must be an observed UTC datetime.
    folds
        Chronological fold definitions defining training end and evaluation date bounds.
    model_roles
        Fixed model roles subject to the same temporal split.
    target_horizon_minutes
        Maximum future target interval from a forecast origin.
    embargo_minutes
        Additional gap retained between final training and first evaluation origin.
    block
        Stable evidence block label, for example ``phase6``.

    Returns
    -------
    polars.DataFrame
        One deterministic audit row per fold and model role. ``causal_pass`` is true only when
        retained training origins end before the protected evaluation boundary.

    Raises
    ------
    ValueError
        If required columns, non-negative safeguards, folds, roles or temporal rows are absent.

    Notes
    -----
    The retained training subset is produced with the project-wide purge-and-embargo helper.
    Raw pre-purge counts are recorded as diagnostic evidence and never used for fitting.

    Examples
    --------
    >>> build_causal_audit(
    ...     pl.DataFrame(), (), model_roles=(), target_horizon_minutes=30,
    ...     embargo_minutes=30, block="x"
    ... )
    Traceback (most recent call last):
    ...
    ValueError: CANONICAL_CAUSAL_AUDIT_INPUT_INVALID
    """

    required = {"origin_id", "session_date", "forecast_origin_utc"}
    if (
        not required <= set(panel.columns)
        or panel.is_empty()
        or not folds
        or not model_roles
        or not block
        or min(target_horizon_minutes, embargo_minutes) < 0
    ):
        raise ValueError("CANONICAL_CAUSAL_AUDIT_INPUT_INVALID")
    origin = "forecast_origin_utc"
    if panel.get_column("origin_id").null_count() > 0 or (
        panel.get_column("origin_id").n_unique() != panel.height
    ):
        raise ValueError("CANONICAL_ORIGIN_KEY_INVALID")

    protected_minutes = target_horizon_minutes + embargo_minutes
    session = pl.col("session_date").cast(pl.String)
    rows: list[dict[str, object]] = []
    for fold in folds:
        raw_training = panel.filter(session <= fold.train_end.isoformat())
        testing = panel.filter(
            session.is_between(
                pl.lit(fold.test_start.isoformat()),
                pl.lit(fold.test_end.isoformat()),
                closed="both",
            )
        )
        if raw_training.is_empty() or testing.is_empty():
            raise ValueError("CANONICAL_CAUSAL_AUDIT_FOLD_EMPTY")
        first_test = testing.get_column(origin).min()
        raw_last_train = raw_training.get_column(origin).max()
        if not isinstance(first_test, datetime) or not isinstance(raw_last_train, datetime):
            raise ValueError("CANONICAL_CAUSAL_AUDIT_TIMESTAMP_INVALID")
        retained_training = purge_and_embargo_training(
            raw_training,
            first_test,
            origin_column=origin,
            target_horizon_minutes=target_horizon_minutes,
            purge_minutes=target_horizon_minutes,
            embargo_minutes=embargo_minutes,
        )
        retained_last_train = retained_training.get_column(origin).max()
        retained_gap = (
            (first_test - retained_last_train).total_seconds() / 60.0
            if isinstance(retained_last_train, datetime)
            else None
        )
        causal_pass = (
            retained_gap is not None and retained_gap >= float(protected_minutes)
        )
        for role in sorted(model_roles):
            rows.append(
                {
                    "block": block,
                    "fold": fold.fold,
                    "model_role": role,
                    "raw_training_rows": raw_training.height,
                    "retained_training_rows": retained_training.height,
                    "testing_rows": testing.height,
                    "raw_training_origin_max_utc": raw_last_train.isoformat(),
                    "training_origin_max_utc": (
                        retained_last_train.isoformat()
                        if isinstance(retained_last_train, datetime)
                        else None
                    ),
                    "testing_origin_min_utc": first_test.isoformat(),
                    "observed_gap_minutes": retained_gap,
                    "required_protected_minutes": protected_minutes,
                    "causal_pass": causal_pass,
                }
            )
    return pl.DataFrame(rows).sort(["block", "fold", "model_role"])


def assert_causal_audit(audit: pl.DataFrame) -> None:
    """Fail closed when a causal-audit row violates the temporal guard.

    Parameters
    ----------
    audit
        Audit output from :func:`build_causal_audit`.

    Returns
    -------
    None
        The function returns only when every row satisfies the stated protection interval.

    Raises
    ------
    ValueError
        If the audit schema is incomplete or a row is non-causal, null, or shorter than its
        required protection interval.

    Examples
    --------
    >>> assert_causal_audit(pl.DataFrame({
    ...     "block": ["example"], "fold": [1], "model_role": ["ridge"],
    ...     "causal_pass": [True], "observed_gap_minutes": [60.0],
    ...     "required_protected_minutes": [60],
    ... }))
    """

    required = {
        "block",
        "fold",
        "model_role",
        "causal_pass",
        "observed_gap_minutes",
        "required_protected_minutes",
    }
    if not required <= set(audit.columns) or audit.is_empty():
        raise ValueError("CANONICAL_CAUSAL_AUDIT_INVALID")
    invalid = audit.filter(
        ~pl.col("causal_pass").fill_null(False)
        | pl.col("observed_gap_minutes").is_null()
        | (
            pl.col("observed_gap_minutes").cast(pl.Float64)
            < pl.col("required_protected_minutes").cast(pl.Float64)
        )
    )
    if not invalid.is_empty():
        raise ValueError("CANONICAL_CAUSALITY_VIOLATION")
