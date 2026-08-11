"""Causal and key-integrity primitives for canonical RV30 validation."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import datetime

import numpy as np
import polars as pl

from mds650.development_models import fit_development_candidate
from mds650.metrics import qlike_losses
from mds650.phase6_evaluation import phase6_information_sets
from mds650.study_design import canonical_sha256
from mds650.temporal_validation import FoldDefinition, purge_and_embargo_training

CANONICAL_MODEL_ROLES = (
    "gamma_glm_confirmatory",
    "har_rv_fixed_extension",
    "ridge_fixed_extension",
    "elastic_net_fixed_extension",
    "lightgbm_robustness",
)
_MODEL_NAMES = {
    "gamma_glm_confirmatory": "gamma_glm",
    "har_rv_fixed_extension": "har_rv",
    "ridge_fixed_extension": "ridge",
    "elastic_net_fixed_extension": "elastic_net",
    "lightgbm_robustness": "lightgbm",
}


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


def canonical_model_parameters(
    role: str, *, phase6_frozen: Mapping[str, object]
) -> dict[str, float | int]:
    """Return the fixed parameter contract for one canonical model role.

    Parameters
    ----------
    role
        One member of :data:`CANONICAL_MODEL_ROLES`.
    phase6_frozen
        Mapping holding the exact selected Gamma/LightGBM parameter mapping when either
        historical role is fitted for a controlled fixture or reconstruction.

    Returns
    -------
    dict[str, float | int]
        Immutable-by-convention parameter mapping. HAR-RV has no hyperparameters, Ridge uses
        alpha 1.0, and Elastic Net uses alpha 0.01 with l1_ratio 0.5.

    Raises
    ------
    ValueError
        If the role is unknown or a historical role lacks an explicit frozen mapping.

    Notes
    -----
    This function performs no selection.  For historical Phase 6 and independent-replication
    evidence, the runner references existing Gamma/LightGBM predictions by hash rather than
    replacing them.

    Examples
    --------
    >>> canonical_model_parameters("ridge_fixed_extension", phase6_frozen={})
    {'alpha': 1.0}
    """

    if role == "har_rv_fixed_extension":
        return {}
    if role == "ridge_fixed_extension":
        return {"alpha": 1.0}
    if role == "elastic_net_fixed_extension":
        return {"alpha": 0.01, "l1_ratio": 0.5}
    if role not in {"gamma_glm_confirmatory", "lightgbm_robustness"}:
        raise ValueError("CANONICAL_MODEL_ROLE_INVALID")
    raw = phase6_frozen.get(role)
    if not isinstance(raw, Mapping):
        raise ValueError("CANONICAL_FROZEN_PARAMETER_MISSING")
    parameters: dict[str, float | int] = {}
    for name, value in raw.items():
        if isinstance(value, bool) or not isinstance(value, (float, int)):
            raise ValueError("CANONICAL_FROZEN_PARAMETER_INVALID")
        parameters[str(name)] = value
    if not parameters:
        raise ValueError("CANONICAL_FROZEN_PARAMETER_MISSING")
    return parameters


def forecast_canonical_fold(
    training: pl.DataFrame,
    testing: pl.DataFrame,
    *,
    role: str,
    information_set: str,
    phase6_frozen: Mapping[str, object],
    fold: int,
) -> pl.DataFrame:
    """Fit a fixed-role model on earlier rows and forecast one later fold.

    Parameters
    ----------
    training
        Causally retained rows that precede the evaluation fold.
    testing
        Later rows of one evaluation fold.  Their RV30 values are used only after fitting to
        calculate recorded losses.
    role
        One canonical model role.
    information_set
        Frozen B0v2, B1v2a or B2v2 feature-set name.
    phase6_frozen
        Explicit historical parameter mapping for Gamma/LightGBM roles.
    fold
        Stable positive fold identifier.

    Returns
    -------
    polars.DataFrame
        One forecast and loss row per testing origin with the fixed role and information set.

    Raises
    ------
    ValueError
        If timestamps, feature columns, role, information set, fold, targets or forecasts violate
        the fixed canonical contract.

    Notes
    -----
    The fixed-extension roles are descriptive post-read analyses when their testing outcomes had
    already been accessed.  This function never performs a grid search or training-time
    validation selection.

    Examples
    --------
    The contract is exercised with a synthetic chronological fold in
    ``tests/unit/test_canonical_model_contract.py``.
    """

    if role not in CANONICAL_MODEL_ROLES or fold < 1:
        raise ValueError("CANONICAL_MODEL_ROLE_INVALID")
    information_sets = phase6_information_sets()
    features = information_sets.get(information_set)
    if features is None:
        raise ValueError("CANONICAL_INFORMATION_SET_INVALID")
    required = {
        "origin_id",
        "asset",
        "session_date",
        "forecast_origin_utc",
        "session_tercile",
        "volatility_regime",
        "rv30",
        *features,
    }
    if (
        not required <= set(training.columns)
        or not required <= set(testing.columns)
        or training.is_empty()
        or testing.is_empty()
    ):
        raise ValueError("CANONICAL_MODEL_COLUMNS_INVALID")
    latest_training = training.get_column("forecast_origin_utc").max()
    earliest_testing = testing.get_column("forecast_origin_utc").min()
    if (
        not isinstance(latest_training, datetime)
        or not isinstance(earliest_testing, datetime)
        or latest_training >= earliest_testing
    ):
        raise ValueError("CANONICAL_FOLD_TEMPORAL_ORDER_INVALID")
    parameters = canonical_model_parameters(role, phase6_frozen=phase6_frozen)
    model_name = _MODEL_NAMES[role]
    fitted = fit_development_candidate(
        training,
        feature_columns=features,
        model_name=model_name,
        parameters=parameters,
        categorical_columns=("b0v2_asset_identity",),
    )
    forecasts = fitted.predict(testing)
    target = np.asarray(testing.get_column("rv30").to_numpy(), dtype=np.float64)
    if forecasts.shape != target.shape or not np.isfinite(forecasts).all() or (
        forecasts <= 0
    ).any():
        raise ValueError("CANONICAL_MODEL_FORECAST_INVALID")
    errors = target - forecasts
    return testing.select(
        "origin_id",
        "asset",
        "session_date",
        "forecast_origin_utc",
        "session_tercile",
        "volatility_regime",
        "rv30",
    ).with_columns(
        pl.lit(fold).alias("fold"),
        pl.lit(role).alias("model_role"),
        pl.lit(information_set).alias("information_set"),
        pl.Series("forecast", forecasts),
        pl.Series("qlike_loss", qlike_losses(target, forecasts)),
        pl.Series("absolute_error", np.abs(errors)),
        pl.Series("squared_error", np.square(errors)),
        pl.lit(json.dumps(parameters, sort_keys=True)).alias("selected_parameters"),
        pl.lit(canonical_sha256({"features": list(features)})).alias(
            "feature_schema_sha256"
        ),
    )
