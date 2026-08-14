"""One-read B1v3 confirmation forecasting and registered inference.

The functions in this module consume an already authorized outcome-bound panel.
They never tune on confirmation data.  All parameters, MDEs and regime cutpoints
come from the immutable 60-session development method freeze.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from typing import Any, Final

import polars as pl

from mds650.b1v3_evaluation import (
    b1v3_information_sets,
    b1v3_phase6_adapter_contract,
    registered_b1v3_contrasts,
)
from mds650.metrics import holm_adjust, regression_metrics
from mds650.phase6_evaluation import forecast_phase6_fold, phase6_contrast
from mds650.study_design import canonical_sha256
from mds650.temporal_validation import FoldDefinition, purge_and_embargo_training

_MODEL_ROLES: Final[tuple[str, ...]] = (
    "gamma_glm_confirmatory",
    "lightgbm_robustness",
)
_OUTCOME_ASSETS: Final[tuple[str, ...]] = (
    "AAPL",
    "AMZN",
    "META",
    "MSFT",
    "NVDA",
    "TSLA",
)
_TIMING_VARIANTS: Final[tuple[str, ...]] = (
    "FMP_DELAY_2_MINUTES",
    "MASSIVE_CUTOFF_60_SECONDS",
    "MASSIVE_CUTOFF_300_SECONDS",
    "UW_CREATED_AT_120_SECONDS",
    "UW_CREATED_AT_300_SECONDS",
)


def _self_hash_valid(document: Mapping[str, Any]) -> bool:
    stored = document.get("manifest_sha256")
    unsigned = {key: value for key, value in document.items() if key != "manifest_sha256"}
    return isinstance(stored, str) and stored == canonical_sha256(unsigned)


def _validate_method_freeze(
    method_freeze: Mapping[str, Any], preregistration: Mapping[str, Any]
) -> None:
    if (
        not _self_hash_valid(method_freeze)
        or method_freeze.get("status")
        != "FROZEN_AFTER_TRAINING_BEFORE_CONFIRMATION"
        or method_freeze.get("safe_to_read_confirmation") is not False
        or method_freeze.get("training_read_count") != 1
        or method_freeze.get("confirmation_read_count") != 0
        or method_freeze.get("preregistration_manifest_sha256")
        != preregistration.get("manifest_sha256")
        or set(method_freeze.get("selected_parameters", {})) != set(_MODEL_ROLES)
        or set(method_freeze.get("training_mde", {}))
        != {"delta_b1v3", "delta_b2"}
    ):
        raise ValueError("B1V3_METHOD_FREEZE_INVALID")


def _date_set(preregistration: Mapping[str, Any], key: str, expected: int) -> set[str]:
    value = preregistration.get(key)
    if not isinstance(value, list) or len(value) != expected:
        raise ValueError("B1V3_EVALUATION_DATE_SCOPE_INVALID")
    dates = {str(day) for day in value}
    if len(dates) != expected:
        raise ValueError("B1V3_EVALUATION_DATE_SCOPE_INVALID")
    return dates


def _apply_frozen_regimes(
    frame: pl.DataFrame, cutpoints: Mapping[str, Any]
) -> pl.DataFrame:
    if set(cutpoints) != {"lower", "upper"}:
        raise ValueError("B1V3_VOLATILITY_REGIME_FREEZE_INVALID")
    lower = float(cutpoints["lower"])
    upper = float(cutpoints["upper"])
    if not math.isfinite(lower) or not math.isfinite(upper) or lower >= upper:
        raise ValueError("B1V3_VOLATILITY_REGIME_FREEZE_INVALID")
    return frame.with_columns(
        pl.when(pl.col("b0v2_underlying_rv_30m") <= lower)
        .then(pl.lit("low"))
        .when(pl.col("b0v2_underlying_rv_30m") <= upper)
        .then(pl.lit("normal"))
        .otherwise(pl.lit("high"))
        .alias("volatility_regime")
    )


def forecast_b1v3_confirmation(
    panel: pl.DataFrame,
    *,
    preregistration: Mapping[str, Any],
    method_freeze: Mapping[str, Any],
) -> pl.DataFrame:
    """Fit on development and forecast confirmation with frozen parameters.

    Parameters
    ----------
    panel:
        Complete identical-sample development and authorized confirmation rows.
    preregistration, method_freeze:
        Immutable zero-confirmation-read contracts.

    Returns
    -------
    polars.DataFrame
        Six paired forecasts per confirmation origin: two roles by three sets.

    Raises
    ------
    ValueError
        If dates, roles, features, targets, parameters, or temporal guards drift.

    Notes
    -----
    Hyperparameter selection is deliberately absent.  The 30-minute purge and
    embargo are applied before the first confirmation origin even when the
    calendar gap is already wider.
    """
    adapter = b1v3_phase6_adapter_contract(preregistration)
    _validate_method_freeze(method_freeze, preregistration)
    features = b1v3_information_sets()["B2"]
    required = {
        "origin_id",
        "asset",
        "session_date",
        "forecast_origin_utc",
        "session_tercile",
        "role",
        "rv30",
        *features,
    }
    if not required <= set(panel.columns) or panel.is_empty():
        raise ValueError("B1V3_EVALUATION_PANEL_SCHEMA_INVALID")
    training_dates = _date_set(preregistration, "training_sessions", 60)
    confirmation_dates = _date_set(preregistration, "confirmation_sessions", 30)
    training = panel.filter(pl.col("role") == "development")
    confirmation = panel.filter(pl.col("role") == "confirmation")
    if (
        training.is_empty()
        or confirmation.is_empty()
        or set(training["session_date"].cast(pl.String).unique()) != training_dates
        or set(confirmation["session_date"].cast(pl.String).unique())
        != confirmation_dates
        or set(training["asset"].cast(pl.String).unique()) != set(_OUTCOME_ASSETS)
        or set(confirmation["asset"].cast(pl.String).unique()) != set(_OUTCOME_ASSETS)
        or panel["origin_id"].n_unique() != panel.height
        or panel.filter(~pl.col("rv30").is_finite() | (pl.col("rv30") <= 0)).height
    ):
        raise ValueError("B1V3_EVALUATION_PANEL_SCOPE_INVALID")
    first_origin = confirmation["forecast_origin_utc"].min()
    if not isinstance(first_origin, datetime):
        raise ValueError("B1V3_CONFIRMATION_ORIGIN_INVALID")
    guard = int(adapter["models"]["purge_embargo_minutes"])
    training = purge_and_embargo_training(
        training,
        first_origin,
        purge_minutes=guard,
        embargo_minutes=guard,
    )
    if training.is_empty():
        raise ValueError("B1V3_CONFIRMATION_PURGED_TRAINING_EMPTY")
    confirmation = _apply_frozen_regimes(
        confirmation,
        method_freeze["volatility_regime_cutpoints"],
    )
    fold = FoldDefinition(
        fold=1000,
        train_end=date.fromisoformat(max(training_dates)),
        test_start=date.fromisoformat(min(confirmation_dates)),
        test_end=date.fromisoformat(max(confirmation_dates)),
    )
    selected = method_freeze["selected_parameters"]
    parts: list[pl.DataFrame] = []
    for role in _MODEL_ROLES:
        role_parameters = selected.get(role)
        if not isinstance(role_parameters, Mapping):
            raise ValueError("B1V3_FROZEN_PARAMETERS_INVALID")
        for information_set, feature_names in b1v3_information_sets().items():
            parameters = role_parameters.get(information_set)
            if not isinstance(parameters, Mapping) or not parameters:
                raise ValueError("B1V3_FROZEN_PARAMETERS_INVALID")
            parts.append(
                forecast_phase6_fold(
                    training,
                    confirmation,
                    fold=fold,
                    information_set=information_set,
                    features=feature_names,
                    role=role,
                    parameters=parameters,
                    preregistration=adapter,
                )
            )
    forecasts = pl.concat(parts).sort(["model_role", "information_set", "origin_id"])
    origin_count = confirmation["origin_id"].n_unique()
    if origin_count == 0 or forecasts.height != origin_count * len(_MODEL_ROLES) * 3:
        raise ValueError("B1V3_CONFIRMATION_FORECAST_PAIRING_FAILURE")
    return forecasts


def _validate_prediction_cube(
    predictions: pl.DataFrame,
    *,
    preregistration: Mapping[str, Any],
) -> None:
    required = {
        "origin_id",
        "asset",
        "session_date",
        "forecast_origin_utc",
        "session_tercile",
        "volatility_regime",
        "fold",
        "model_role",
        "information_set",
        "rv30",
        "forecast",
        "qlike_loss",
        "absolute_error",
        "squared_error",
    }
    confirmation_dates = _date_set(preregistration, "confirmation_sessions", 30)
    duplicate_count = predictions.select(
        "origin_id", "model_role", "information_set"
    ).unique().height
    origin_count = predictions["origin_id"].n_unique() if not predictions.is_empty() else 0
    if (
        not required <= set(predictions.columns)
        or predictions.is_empty()
        or set(predictions["model_role"].unique()) != set(_MODEL_ROLES)
        or set(predictions["information_set"].unique()) != {"B0", "B1v3a", "B2"}
        or set(predictions["session_date"].cast(pl.String).unique())
        != confirmation_dates
        or set(predictions["asset"].cast(pl.String).unique()) != set(_OUTCOME_ASSETS)
        or predictions.height != origin_count * len(_MODEL_ROLES) * 3
        or duplicate_count != predictions.height
        or predictions.filter(
            ~pl.col("rv30").is_finite()
            | (pl.col("rv30") <= 0)
            | ~pl.col("forecast").is_finite()
            | (pl.col("forecast") <= 0)
            | ~pl.col("qlike_loss").is_finite()
        ).height
    ):
        raise ValueError("B1V3_CONFIRMATION_PREDICTION_CUBE_INVALID")


def _contrast_rows(
    predictions: pl.DataFrame,
    preregistration: Mapping[str, Any],
) -> dict[tuple[str, str], dict[str, Any]]:
    adapter = b1v3_phase6_adapter_contract(preregistration)
    return {
        (role, name): phase6_contrast(
            predictions,
            role=role,
            name=name,
            baseline=baseline,
            expanded=expanded,
            preregistration=adapter,
        )
        for role in _MODEL_ROLES
        for name, baseline, expanded in registered_b1v3_contrasts()
    }


def _stability_rows(
    predictions: pl.DataFrame,
    preregistration: Mapping[str, Any],
) -> list[dict[str, Any]]:
    adapter = b1v3_phase6_adapter_contract(preregistration)
    rows: list[dict[str, Any]] = []
    for role in _MODEL_ROLES:
        for name, baseline, expanded in registered_b1v3_contrasts():
            for dimension in ("asset", "session_tercile", "volatility_regime"):
                for value in sorted(predictions[dimension].unique().to_list()):
                    subset = predictions.filter(pl.col(dimension) == value)
                    if subset["session_date"].n_unique() < 2:
                        rows.append(
                            {
                                "model_role": role,
                                "contrast": name,
                                "dimension": dimension,
                                "value": value,
                                "status": "INSUFFICIENT_DAY_CLUSTERS",
                            }
                        )
                        continue
                    row = phase6_contrast(
                        subset,
                        role=role,
                        name=name,
                        baseline=baseline,
                        expanded=expanded,
                        preregistration=adapter,
                    )
                    rows.append(
                        {**row, "dimension": dimension, "value": value, "status": "ESTIMATED"}
                    )
    return rows


def _timing_rows(
    timing_predictions: pl.DataFrame | None,
    preregistration: Mapping[str, Any],
) -> list[dict[str, Any]]:
    if timing_predictions is None or timing_predictions.is_empty():
        raise ValueError("B1V3_TIMING_VARIANTS_INCOMPLETE")
    if "timing_variant" not in timing_predictions.columns or set(
        timing_predictions["timing_variant"].unique()
    ) != set(_TIMING_VARIANTS):
        raise ValueError("B1V3_TIMING_VARIANTS_INCOMPLETE")
    rows: list[dict[str, Any]] = []
    for variant in _TIMING_VARIANTS:
        subset = timing_predictions.filter(pl.col("timing_variant") == variant).drop(
            "timing_variant"
        )
        _validate_prediction_cube(subset, preregistration=preregistration)
        for (role, _name), row in _contrast_rows(subset, preregistration).items():
            rows.append({**row, "model_role": role, "timing_variant": variant})
    return rows


def _claim(
    *,
    name: str,
    global_rows: Mapping[tuple[str, str], Mapping[str, Any]],
    holm: Mapping[str, float],
    stability: Sequence[Mapping[str, Any]],
    timing: Sequence[Mapping[str, Any]],
    mde: float,
) -> dict[str, Any]:
    gamma = global_rows[("gamma_glm_confirmatory", name)]
    challenger = global_rows[("lightgbm_robustness", name)]
    assets = [
        row
        for row in stability
        if row.get("model_role") == "gamma_glm_confirmatory"
        and row.get("contrast") == name
        and row.get("dimension") == "asset"
        and row.get("status") == "ESTIMATED"
    ]
    expected_variants = (
        _TIMING_VARIANTS[:3] if name == "delta_b1v3" else _TIMING_VARIANTS
    )
    timing_rows = [
        row
        for row in timing
        if row.get("model_role") == "gamma_glm_confirmatory"
        and row.get("contrast") == name
        and row.get("timing_variant") in expected_variants
    ]
    conditions = {
        "gamma_estimate_positive": float(gamma["estimate"]) > 0,
        "gamma_interval_above_zero": float(gamma["ci_low"]) > 0,
        "holm_adjusted_p_below_0_05": float(holm[name]) < 0.05,
        "effect_meets_training_mde": float(gamma["estimate"]) >= mde,
        "lightgbm_sign_positive": float(challenger["estimate"]) > 0,
        "at_least_four_assets_positive": sum(
            float(row["estimate"]) > 0 for row in assets
        )
        >= 4,
        "no_more_than_one_asset_interval_below_zero": sum(
            float(row["ci_high"]) < 0 for row in assets
        )
        <= 1,
        "all_registered_timing_views_present": {
            str(row["timing_variant"]) for row in timing_rows
        }
        == set(expected_variants),
        "no_timing_interval_wholly_below_zero": not any(
            float(row["ci_high"]) < 0 for row in timing_rows
        ),
    }
    failed = [condition for condition, passed in conditions.items() if not passed]
    if not failed:
        status = "GLOBAL_EDGE_CONFIRMED"
    elif float(gamma["estimate"]) > 0:
        status = "POSITIVE_BUT_NOT_GLOBALLY_CONFIRMED"
    else:
        status = "GLOBAL_EDGE_NOT_CONFIRMED"
    return {
        "status": status,
        "mde": mde,
        "conditions": conditions,
        "failed_conditions": failed,
    }


def evaluate_b1v3_confirmation(
    predictions: pl.DataFrame,
    *,
    method_freeze: Mapping[str, Any],
    preregistration: Mapping[str, Any],
    timing_predictions: pl.DataFrame | None,
) -> dict[str, Any]:
    """Evaluate all preregistered B1v3 views without outcome-driven selection.

    Returns
    -------
    dict[str, Any]
        Global metrics, paired-day inference, Holm adjustment, stability,
        timing sensitivities, condition-level claims and overall decision.

    Raises
    ------
    ValueError
        If the method freeze, prediction cube, timing cube or pairing drifts.
    """
    b1v3_phase6_adapter_contract(preregistration)
    _validate_method_freeze(method_freeze, preregistration)
    _validate_prediction_cube(predictions, preregistration=preregistration)
    global_rows = _contrast_rows(predictions, preregistration)
    holm = holm_adjust(
        {
            name: float(global_rows[("gamma_glm_confirmatory", name)]["p_value_raw"])
            for name, _, _ in registered_b1v3_contrasts()
        }
    )
    for name, adjusted in holm.items():
        global_rows[("gamma_glm_confirmatory", name)]["p_value_holm"] = adjusted
    metrics = [
        {
            "model_role": str(key[0]),
            "information_set": str(key[1]),
            "observations": frame.height,
            **regression_metrics(frame["rv30"].to_numpy(), frame["forecast"].to_numpy()),
        }
        for key, frame in predictions.group_by("model_role", "information_set")
    ]
    stability = _stability_rows(predictions, preregistration)
    timing = _timing_rows(timing_predictions, preregistration)
    mde = method_freeze["training_mde"]
    claims = {
        name: _claim(
            name=name,
            global_rows=global_rows,
            holm=holm,
            stability=stability,
            timing=timing,
            mde=float(mde[name]),
        )
        for name, _, _ in registered_b1v3_contrasts()
    }
    confirmed = {
        name for name, claim in claims.items() if claim["status"] == "GLOBAL_EDGE_CONFIRMED"
    }
    if confirmed == {"delta_b1v3", "delta_b2"}:
        decision = "GLOBAL_B1V3_AND_B2_EDGE_CONFIRMED"
    elif confirmed == {"delta_b1v3"}:
        decision = "GLOBAL_B1V3_EDGE_CONFIRMED"
    elif confirmed == {"delta_b2"}:
        decision = "GLOBAL_B2_EDGE_CONFIRMED"
    elif any(claim["status"] == "POSITIVE_BUT_NOT_GLOBALLY_CONFIRMED" for claim in claims.values()):
        decision = "POSITIVE_BUT_NOT_GLOBALLY_CONFIRMED"
    else:
        decision = "GLOBAL_EDGE_NOT_CONFIRMED"
    return {
        "metrics": sorted(metrics, key=lambda row: (row["model_role"], row["information_set"])),
        "global": {
            role: {
                name: global_rows[(role, name)]
                for name, _, _ in registered_b1v3_contrasts()
            }
            for role in _MODEL_ROLES
        },
        "global_holm": holm,
        "stability": stability,
        "timing": timing,
        "claims": claims,
        "decision": decision,
        "all_signs_retained": True,
    }
