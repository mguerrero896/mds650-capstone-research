"""Causal and key-integrity primitives for canonical RV30 validation."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import datetime

import numpy as np
import polars as pl

from mds650.development_models import fit_development_candidate
from mds650.metrics import (
    holm_adjust,
    paired_day_bootstrap,
    qlike_losses,
    regression_metrics,
)
from mds650.phase6 import B2V2_FEATURES
from mds650.phase6_evaluation import phase6_information_sets
from mds650.study_design import canonical_sha256
from mds650.temporal_validation import FoldDefinition, purge_and_embargo_training

# NAMING NOTE (2026-08-18, reviewer correction): "har_rv_fixed_extension" is a
# fixed-extension LinearRegression on the log target over the frozen
# information-set columns - it is NOT the dedicated intraday HAR/HARQ of
# src/mds650/har.py (Gate 3+: intraday/daily/weekly components + realized
# quarticity). The registered name is kept verbatim for fidelity with the
# frozen canonical artifacts; see docs/model_naming_note_v1.md before citing.
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
_INFORMATION_SET_ORDER = ("B0v2", "B1v2a", "B2v2")
_CANONICAL_CONTRASTS = (
    ("delta_b1v2", "B0v2", "B1v2a"),
    ("delta_b2v2", "B1v2a", "B2v2"),
)
_REGISTERED_ROLES = {"gamma_glm_confirmatory", "lightgbm_robustness"}


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
        causal_pass = retained_gap is not None and retained_gap >= float(protected_minutes)
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
    # Volatility regimes are assigned from each fold's training distribution to
    # evaluation rows only.  They are a reporting stratum, not a training input;
    # requiring the label on the earlier panel would falsely reject a valid
    # target-blind training fold.
    training_required = required - {"volatility_regime"}
    if (
        not training_required <= set(training.columns)
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
    if (
        forecasts.shape != target.shape
        or not np.isfinite(forecasts).all()
        or (forecasts <= 0).any()
    ):
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
        pl.lit(canonical_sha256({"features": list(features)})).alias("feature_schema_sha256"),
    )


def _canonical_prediction_frame(predictions: pl.DataFrame) -> pl.DataFrame:
    """Validate prediction keys and recompute losses from RV30 and forecasts."""

    required = {
        "block",
        "fold",
        "model_role",
        "information_set",
        "origin_id",
        "asset",
        "session_date",
        "forecast_origin_utc",
        "session_tercile",
        "volatility_regime",
        "rv30",
        "forecast",
        "analysis_status",
    }
    if predictions.is_empty() or not required <= set(predictions.columns):
        raise ValueError("CANONICAL_PREDICTION_COLUMNS_INVALID")
    if not set(predictions.get_column("model_role").unique().to_list()) <= set(
        CANONICAL_MODEL_ROLES
    ):
        raise ValueError("CANONICAL_MODEL_ROLE_INVALID")
    if not set(predictions.get_column("information_set").unique().to_list()) <= set(
        _INFORMATION_SET_ORDER
    ):
        raise ValueError("CANONICAL_INFORMATION_SET_INVALID")
    key_columns = ("block", "fold", "model_role", "information_set", "origin_id")
    if (
        any(predictions.get_column(column).null_count() for column in key_columns)
        or predictions.select(pl.struct(*key_columns).n_unique()).item() != predictions.height
    ):
        raise ValueError("CANONICAL_PREDICTION_DUPLICATE_KEY")
    observed = np.asarray(predictions.get_column("rv30").to_numpy(), dtype=np.float64)
    forecasts = np.asarray(predictions.get_column("forecast").to_numpy(), dtype=np.float64)
    if (
        not np.isfinite(observed).all()
        or not np.isfinite(forecasts).all()
        or (observed <= 0).any()
        or (forecasts <= 0).any()
    ):
        raise ValueError("CANONICAL_PREDICTION_VALUES_INVALID")
    for (block, fold, role), frame in predictions.group_by(
        "block", "fold", "model_role", maintain_order=True
    ):
        information_frames = {
            information_set: frame.filter(pl.col("information_set") == information_set)
            for information_set in _INFORMATION_SET_ORDER
        }
        if any(item.is_empty() for item in information_frames.values()):
            raise ValueError(f"CANONICAL_INFORMATION_SET_MISSING:{block}:{fold}:{role}")
        assert_identical_origin_sets(information_frames)
    return predictions.with_columns(
        pl.Series("canonical_qlike_loss", qlike_losses(observed, forecasts))
    ).sort(list(key_columns))


def _analysis_status_for_role(role: str) -> str:
    """Return the evidence status allowed for a model role."""

    return "REGISTERED_OOS" if role in _REGISTERED_ROLES else "POST_READ_FIXED_EXTENSION"


def _finite_float(value: object, error_code: str) -> float:
    """Return one finite numeric value or raise its explicit contract code."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(error_code)
    result = float(value)
    if not np.isfinite(result):
        raise ValueError(error_code)
    return result


def _calibration_summary(frame: pl.DataFrame) -> dict[str, float | int | str | None]:
    """Calculate a descriptive calibration regression without selection."""

    actual = np.asarray(frame.get_column("rv30").to_numpy(), dtype=np.float64)
    forecast = np.asarray(frame.get_column("forecast").to_numpy(), dtype=np.float64)
    if np.unique(actual).size < 2 or np.unique(forecast).size < 2:
        return {
            "status": "NON_IDENTIFIABLE",
            "intercept": None,
            "slope": None,
            "r_squared": None,
            "observations": int(frame.height),
        }
    design = np.column_stack((np.ones(forecast.size), forecast))
    intercept, slope = np.linalg.lstsq(design, actual, rcond=None)[0]
    fitted = intercept + slope * forecast
    residual_sum = float(np.square(actual - fitted).sum())
    total_sum = float(np.square(actual - actual.mean()).sum())
    return {
        "status": "DESCRIPTIVE",
        "intercept": float(intercept),
        "slope": float(slope),
        "r_squared": 1.0 - residual_sum / total_sum if total_sum > 0 else None,
        "observations": int(frame.height),
    }


def _paired_loss_frame(
    predictions: pl.DataFrame,
    *,
    baseline: str,
    expanded: str,
) -> tuple[pl.DataFrame, int]:
    """Pair two nested information sets and fail on target or key drift."""

    key_columns = (
        "block",
        "fold",
        "model_role",
        "origin_id",
        "asset",
        "session_date",
        "forecast_origin_utc",
    )
    left = predictions.filter(pl.col("information_set") == baseline).select(
        *key_columns,
        pl.col("rv30").alias("baseline_rv30"),
        pl.col("canonical_qlike_loss").alias("baseline_loss"),
    )
    right = predictions.filter(pl.col("information_set") == expanded).select(
        *key_columns,
        pl.col("rv30").alias("expanded_rv30"),
        pl.col("canonical_qlike_loss").alias("expanded_loss"),
    )
    paired = left.join(right, on=key_columns, how="inner", validate="1:1")
    unpaired = left.height + right.height - 2 * paired.height
    if unpaired:
        raise ValueError("CANONICAL_CONTRAST_UNPAIRED")
    target_difference = paired.select(
        (pl.col("baseline_rv30") - pl.col("expanded_rv30")).abs().max()
    ).item()
    if target_difference is None or float(target_difference) != 0.0:
        raise ValueError("CANONICAL_CONTRAST_TARGET_DRIFT")
    return paired.with_columns(
        (pl.col("baseline_loss") - pl.col("expanded_loss")).alias("loss_difference")
    ), unpaired


def _contrast_summary(
    paired: pl.DataFrame,
    *,
    block: str,
    role: str,
    name: str,
    baseline: str,
    expanded: str,
    bootstrap_seed: int,
    draws: int,
    mde: float | None,
    dimension: str | None = None,
    value: str | None = None,
) -> dict[str, object]:
    """Summarize one paired contrast with a whole-day bootstrap."""

    days = paired.get_column("session_date").n_unique()
    result: dict[str, object] = {
        "block": block,
        "model_role": role,
        "registered_status": _analysis_status_for_role(role),
        "contrast": name,
        "definition": f"QLIKE({baseline})-QLIKE({expanded})",
        "positive_direction": "EXPANDED_INFORMATION_SET_BETTER",
        "baseline": baseline,
        "expanded": expanded,
        "paired_rows": paired.height,
        "clusters": days,
        "dimension": dimension,
        "value": value,
        "mde": mde,
    }
    if days < 2:
        return {
            **result,
            "status": "INSUFFICIENT_DAY_CLUSTERS",
            "estimate": None,
            "ci_low": None,
            "ci_high": None,
            "p_value_raw": None,
            "p_value_holm": None,
            "mde_pass": None,
        }
    inference = paired_day_bootstrap(
        paired.select("session_date", "loss_difference"),
        repetitions=draws,
        seed=bootstrap_seed,
    )
    estimate = float(inference["estimate"])
    mde_pass = None if mde is None else estimate >= mde
    return {
        **result,
        "status": "RUN",
        "estimate": estimate,
        "ci_low": float(inference["ci_low"]),
        "ci_high": float(inference["ci_high"]),
        "p_value_raw": float(inference["p_value_two_sided"]),
        "p_value_holm": None,
        "mde_pass": mde_pass,
        "bootstrap_repetitions": int(inference["repetitions"]),
        "bootstrap_seed": int(inference["seed"]),
        "result_sign": ("POSITIVE" if estimate > 0 else "NEGATIVE" if estimate < 0 else "ZERO"),
    }


def _add_holm_adjustment(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    """Apply the declared Holm family to one role/block's two contrasts."""

    p_values: dict[str, float] = {}
    for row in rows:
        if row.get("status") == "RUN":
            p_values[str(row["contrast"])] = _finite_float(
                row.get("p_value_raw"), "CANONICAL_P_VALUE_INVALID"
            )
    adjusted = holm_adjust(p_values) if p_values else {}
    return [{**row, "p_value_holm": adjusted.get(str(row["contrast"]))} for row in rows]


def _metrics_and_calibration(
    predictions: pl.DataFrame,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """Calculate non-selected descriptive metrics for each evaluated view."""

    metrics: list[dict[str, object]] = []
    calibration: list[dict[str, object]] = []
    for (block, role, information_set), frame in predictions.group_by(
        "block", "model_role", "information_set", maintain_order=True
    ):
        metric = regression_metrics(
            frame.get_column("rv30").to_numpy(), frame.get_column("forecast").to_numpy()
        )
        context = {
            "block": str(block),
            "model_role": str(role),
            "registered_status": _analysis_status_for_role(str(role)),
            "information_set": str(information_set),
            "observations": frame.height,
            "origins": frame.get_column("origin_id").n_unique(),
            "session_count": frame.get_column("session_date").n_unique(),
        }
        metrics.append({**context, **metric})
        calibration.append({**context, **_calibration_summary(frame)})
    return (
        sorted(metrics, key=_result_row_order),
        sorted(calibration, key=_result_row_order),
    )


def _result_row_order(row: Mapping[str, object]) -> tuple[str, str, str]:
    """Order model/information rows deterministically for persisted evidence."""

    return (
        str(row["block"]),
        str(row["model_role"]),
        str(row["information_set"]),
    )


def _metric_drift(metrics: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    """Compare descriptive metrics across evidence blocks without a causal claim."""

    by_key: dict[tuple[str, str], dict[str, Mapping[str, object]]] = {}
    for row in metrics:
        key = (str(row["model_role"]), str(row["information_set"]))
        by_key.setdefault(key, {})[str(row["block"])] = row
    drift: list[dict[str, object]] = []
    for (role, information_set), blocks in sorted(by_key.items()):
        if {"phase6", "independent_replication"} <= set(blocks):
            phase6 = blocks["phase6"]
            independent = blocks["independent_replication"]
            drift.append(
                {
                    "model_role": role,
                    "information_set": information_set,
                    "registered_status": _analysis_status_for_role(role),
                    "comparison": "independent_replication_minus_phase6",
                    "qlike_difference": _finite_float(
                        independent.get("qlike"), "CANONICAL_METRIC_INVALID"
                    )
                    - _finite_float(phase6.get("qlike"), "CANONICAL_METRIC_INVALID"),
                    "mae_difference": _finite_float(
                        independent.get("mae"), "CANONICAL_METRIC_INVALID"
                    )
                    - _finite_float(phase6.get("mae"), "CANONICAL_METRIC_INVALID"),
                    "rmse_difference": _finite_float(
                        independent.get("rmse"), "CANONICAL_METRIC_INVALID"
                    )
                    - _finite_float(phase6.get("rmse"), "CANONICAL_METRIC_INVALID"),
                    "status": "DESCRIPTIVE_BETWEEN_BLOCK",
                }
            )
    return drift


def evaluate_canonical_predictions(
    predictions: pl.DataFrame,
    *,
    bootstrap_seed: int,
    draws: int,
    mde_by_contrast: Mapping[str, float],
) -> dict[str, object]:
    """Evaluate fixed B0/B1/B2 forecasts on identical, paired RV30 origins.

    Parameters
    ----------
    predictions
        Hash-validated forecast rows from one or more blocks. Every model role and information
        set must use exactly the same origins within each block and fold.
    bootstrap_seed
        Deterministic whole-day bootstrap seed fixed before reporting.
    draws
        Positive number of whole-day bootstrap repetitions.
    mde_by_contrast
        Frozen, training-only minimum detectable effects keyed by ``delta_b1v2`` and
        ``delta_b2v2``.

    Returns
    -------
    dict[str, object]
        JSON-safe metrics, paired contrasts, descriptive stability/calibration/drift tables and
        a claim-eligibility label for each nested contrast.

    Raises
    ------
    ValueError
        If forecast keys, targets, information sets, pairings, values, bootstrap settings or MDE
        values violate the canonical contract.

    Notes
    -----
    QLIKE is recomputed from ``rv30`` and ``forecast``.  MAE, RMSE, calibration, drift and
    strata are descriptive; only registered Gamma/LightGBM contrasts can enter an eligibility
    decision. Fixed HAR/Ridge/Elastic-Net extensions remain visibly post-read.

    Examples
    --------
    Synthetic pairing and model-disagreement guards are tested in
    ``tests/contract/test_canonical_inference.py``.
    """

    if draws < 100 or bootstrap_seed < 0:
        raise ValueError("CANONICAL_BOOTSTRAP_SETTINGS_INVALID")
    if set(mde_by_contrast) != {name for name, _, _ in _CANONICAL_CONTRASTS} or any(
        not np.isfinite(value) or value <= 0 for value in mde_by_contrast.values()
    ):
        raise ValueError("CANONICAL_MDE_CONTRACT_INVALID")
    frame = _canonical_prediction_frame(predictions)
    metrics, calibration = _metrics_and_calibration(frame)
    contrasts: list[dict[str, object]] = []
    stability: list[dict[str, object]] = []
    unpaired_rows = 0
    for (block, role), model_frame in frame.group_by("block", "model_role", maintain_order=True):
        role_rows: list[dict[str, object]] = []
        for name, baseline, expanded in _CANONICAL_CONTRASTS:
            paired, unpaired = _paired_loss_frame(model_frame, baseline=baseline, expanded=expanded)
            unpaired_rows += unpaired
            role_rows.append(
                _contrast_summary(
                    paired,
                    block=str(block),
                    role=str(role),
                    name=name,
                    baseline=baseline,
                    expanded=expanded,
                    bootstrap_seed=bootstrap_seed,
                    draws=draws,
                    mde=float(mde_by_contrast[name]),
                )
            )
            for dimension in ("asset", "session_tercile", "volatility_regime"):
                for value in sorted(
                    model_frame.get_column(dimension).cast(pl.String).unique().to_list()
                ):
                    subset = model_frame.filter(pl.col(dimension).cast(pl.String) == value)
                    subset_paired, subset_unpaired = _paired_loss_frame(
                        subset, baseline=baseline, expanded=expanded
                    )
                    unpaired_rows += subset_unpaired
                    stability.append(
                        _contrast_summary(
                            subset_paired,
                            block=str(block),
                            role=str(role),
                            name=name,
                            baseline=baseline,
                            expanded=expanded,
                            bootstrap_seed=bootstrap_seed,
                            draws=draws,
                            mde=None,
                            dimension=dimension,
                            value=value,
                        )
                    )
        contrasts.extend(_add_holm_adjustment(role_rows))
    contrasts = sorted(
        contrasts,
        key=lambda row: (
            str(row["block"]),
            str(row["model_role"]),
            str(row["contrast"]),
        ),
    )
    stability = sorted(
        stability,
        key=lambda row: (
            str(row["block"]),
            str(row["model_role"]),
            str(row["contrast"]),
            str(row["dimension"]),
            str(row["value"]),
        ),
    )
    eligibility = {
        name: validate_claim_eligibility(
            {"contrasts": [row for row in contrasts if row["contrast"] == name]}
        )
        for name, _, _ in _CANONICAL_CONTRASTS
    }
    return {
        "schema_version": "1.0",
        "bootstrap": {
            "cluster": "XNYS_SESSION_DATE_WITH_ALL_ASSETS",
            "draws": draws,
            "seed": bootstrap_seed,
            "multiplicity": "Holm within block/model nested contrasts",
        },
        "metrics": metrics,
        "contrasts": contrasts,
        "stability": stability,
        "calibration": calibration,
        "drift": _metric_drift(metrics),
        "contrast_integrity": {
            "unpaired_rows": unpaired_rows,
            "status": "PASS" if unpaired_rows == 0 else "FAIL",
        },
        "claim_eligibility": eligibility,
        "all_signs_retained": True,
    }


def validate_claim_eligibility(results: Mapping[str, object]) -> str:
    """Classify the strongest defensible claim without selecting favorable models.

    Parameters
    ----------
    results
        Either canonical contrast rows under ``contrasts`` or a minimal mapping with
        ``gamma_b2``, ``lightgbm_b2`` and ``mde_pass`` for a contract-level sign check.

    Returns
    -------
    str
        ``GLOBAL_EDGE``, ``MODEL_FAMILY_DEPENDENT``, ``CONDITIONAL`` or ``NOT_SUPPORTED``.

    Raises
    ------
    ValueError
        If a canonical contrast mapping is malformed.

    Notes
    -----
    A global claim requires positive, Holm-supported, MDE-exceeding results from both registered
    model families in every evidence block. Post-read fixed extensions cannot upgrade the label.

    Examples
    --------
    >>> validate_claim_eligibility({"gamma_b2": 0.01, "lightgbm_b2": -0.01,
    ...                            "mde_pass": True})
    'MODEL_FAMILY_DEPENDENT'
    """

    if {"gamma_b2", "lightgbm_b2", "mde_pass"} <= set(results):
        gamma = results["gamma_b2"]
        challenger = results["lightgbm_b2"]
        if not isinstance(gamma, (int, float)) or not isinstance(challenger, (int, float)):
            raise ValueError("CANONICAL_CLAIM_INPUT_INVALID")
        if float(gamma) * float(challenger) < 0:
            return "MODEL_FAMILY_DEPENDENT"
        if float(gamma) > 0 and float(challenger) > 0:
            return "GLOBAL_EDGE" if results["mde_pass"] is True else "CONDITIONAL"
        return "NOT_SUPPORTED"
    rows = results.get("contrasts")
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        raise ValueError("CANONICAL_CLAIM_INPUT_INVALID")
    registered: list[Mapping[str, object]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            raise ValueError("CANONICAL_CLAIM_INPUT_INVALID")
        if row.get("registered_status") == "REGISTERED_OOS":
            registered.append(row)
    if not registered:
        return "NOT_SUPPORTED"
    by_block: dict[str, dict[str, Mapping[str, object]]] = {}
    for row in registered:
        role = str(row.get("model_role"))
        block = str(row.get("block"))
        if role not in _REGISTERED_ROLES:
            return "NOT_SUPPORTED"
        _finite_float(row.get("estimate"), "CANONICAL_CLAIM_INPUT_INVALID")
        by_block.setdefault(block, {})[role] = row
    if any(set(rows_by_role) != _REGISTERED_ROLES for rows_by_role in by_block.values()):
        return "NOT_SUPPORTED"
    for rows_by_role in by_block.values():
        signs = {
            _finite_float(row.get("estimate"), "CANONICAL_CLAIM_INPUT_INVALID") > 0
            for row in rows_by_role.values()
        }
        if len(signs) > 1:
            return "MODEL_FAMILY_DEPENDENT"
    all_positive = all(
        _finite_float(row.get("estimate"), "CANONICAL_CLAIM_INPUT_INVALID") > 0
        for row in registered
    )
    if not all_positive:
        return "NOT_SUPPORTED"
    all_strong = all(
        row.get("status") == "RUN"
        and _finite_float(row.get("ci_low"), "CANONICAL_CLAIM_INPUT_INVALID") > 0
        and _finite_float(row.get("p_value_holm"), "CANONICAL_CLAIM_INPUT_INVALID") < 0.05
        and row.get("mde_pass") is True
        for row in registered
    )
    return "GLOBAL_EDGE" if all_strong else "CONDITIONAL"


def summarize_b2_redundancy(panel: pl.DataFrame, *, block: str) -> list[dict[str, object]]:
    """Describe target-blind redundancy among the nine fixed B2 features.

    Parameters
    ----------
    panel
        Forecast-origin feature panel containing the preregistered B2 columns. ``rv30`` is not
        read by this function.
    block
        Stable evidence label attached to every result row.

    Returns
    -------
    list[dict[str, object]]
        One row per B2 feature with unique-value count, zero share and largest absolute pairwise
        correlation among the other B2 features.

    Raises
    ------
    ValueError
        If B2 columns are missing, null, non-finite or the panel is empty.

    Notes
    -----
    This is a feature-only diagnostic. It neither reads the RV30 outcome nor evaluates forecast
    performance, so it cannot select a B2 variant by outcome.

    Examples
    --------
    The function is called from ``scripts/report_canonical_validation.py`` only after the
    B2 feature schema is frozen.
    """

    features = tuple(B2V2_FEATURES)
    if panel.is_empty() or not set(features) <= set(panel.columns):
        raise ValueError("CANONICAL_B2_REDUNDANCY_COLUMNS_INVALID")
    values = np.asarray(panel.select(*features).to_numpy(), dtype=np.float64)
    if values.ndim != 2 or values.shape[0] == 0 or not np.isfinite(values).all():
        raise ValueError("CANONICAL_B2_REDUNDANCY_VALUES_INVALID")
    correlations = np.corrcoef(values, rowvar=False)
    rows: list[dict[str, object]] = []
    for index, feature in enumerate(features):
        candidates = [
            (abs(float(correlations[index, other])), features[other])
            for other in range(len(features))
            if other != index and np.isfinite(correlations[index, other])
        ]
        maximum, partner = max(candidates, default=(None, None))
        column = values[:, index]
        rows.append(
            {
                "block": block,
                "feature": feature,
                "observations": int(values.shape[0]),
                "unique_values": int(np.unique(column).size),
                "zero_share": float(np.mean(column == 0.0)),
                "max_abs_pairwise_correlation": maximum,
                "max_correlation_partner": partner,
                "status": "TARGET_BLIND_DESCRIPTIVE",
            }
        )
    return rows
