"""Training-only method freeze for the approved B1v3 confirmation.

This module is the only bridge between the target-blind common predictor panel
and development RV30 outcomes.  It never authorizes or reads confirmation
outcomes.  The final 30-session block remains inaccessible until the returned
method freeze and all quality gates are bound by the separate access ledger.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from datetime import date
from typing import Any, Final

import polars as pl

from mds650.b1v3_evaluation import (
    b1v3_information_sets,
    b1v3_phase6_adapter_contract,
)
from mds650.phase6_evaluation import (
    add_training_volatility_regime,
    estimate_training_mde,
    forecast_phase6_fold,
    select_phase6_parameters,
)
from mds650.study_design import canonical_sha256
from mds650.temporal_validation import FoldDefinition, split_expanding_fold

_SHA256_LENGTH: Final = 64
_OUTCOME_ASSETS: Final[tuple[str, ...]] = (
    "AAPL",
    "AMZN",
    "META",
    "MSFT",
    "NVDA",
    "TSLA",
)
_MODEL_ROLES: Final[tuple[str, ...]] = (
    "gamma_glm_confirmatory",
    "lightgbm_robustness",
)
_TRAINING_BLOCK_STARTS: Final[tuple[int, ...]] = (30, 40, 50)


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == _SHA256_LENGTH
        and all(character in "0123456789abcdef" for character in value)
    )


def _training_sessions(preregistration: Mapping[str, Any]) -> list[str]:
    b1v3_phase6_adapter_contract(preregistration)
    raw = preregistration.get("training_sessions")
    if not isinstance(raw, list) or len(raw) != 60:
        raise ValueError("B1V3_TRAINING_DATE_SCOPE_INVALID")
    sessions = [str(value) for value in raw]
    try:
        parsed = [date.fromisoformat(value) for value in sessions]
    except ValueError as exc:
        raise ValueError("B1V3_TRAINING_DATE_SCOPE_INVALID") from exc
    if parsed != sorted(set(parsed)):
        raise ValueError("B1V3_TRAINING_DATE_SCOPE_INVALID")
    return sessions


def b1v3_training_folds(
    preregistration: Mapping[str, Any],
) -> tuple[FoldDefinition, ...]:
    """Return the three frozen development-only OOF blocks.

    Parameters
    ----------
    preregistration:
        Valid, self-hashed B1v3 zero-outcome preregistration.

    Returns
    -------
    tuple[FoldDefinition, ...]
        Expanding 30/10, 40/10 and 50/10 session folds numbered 101--103.

    Raises
    ------
    ValueError
        If the preregistration or its exact 60-session array is invalid.

    Notes
    -----
    Each split is additionally purged and embargoed by the caller.  These
    blocks are development evidence only and cannot be relabelled as the
    independent confirmation sample.
    """
    sessions = _training_sessions(preregistration)
    return tuple(
        FoldDefinition(
            fold=101 + index,
            train_end=date.fromisoformat(sessions[start - 1]),
            test_start=date.fromisoformat(sessions[start]),
            test_end=date.fromisoformat(sessions[start + 9]),
        )
        for index, start in enumerate(_TRAINING_BLOCK_STARTS)
    )


def bind_b1v3_training_targets(
    common_predictors: pl.DataFrame,
    target_frame: pl.DataFrame,
    *,
    preregistration: Mapping[str, Any],
) -> pl.DataFrame:
    """Bind exact development RV30 to the source-bound predictor sample.

    Parameters
    ----------
    common_predictors:
        Predictor-only 60/30 common panel.  Confirmation rows may be present,
        but this function selects development rows before touching targets.
    target_frame:
        Development-only output from ``build_b0v2_features`` with
        ``include_target=True`` and the registered one-minute delay.
    preregistration:
        Frozen zero-outcome B1v3 preregistration.

    Returns
    -------
    polars.DataFrame
        Identical complete-case B0/B1v3a/B2 development rows with RV30.

    Raises
    ------
    ValueError
        If origin identities, dates, predictor values, timing, the 31-price /
        30-return contract, completeness, or positive finite RV30 drift.

    Notes
    -----
    No incomplete information-set row is imputed.  Predictor equality is
    checked against the independent target-builder output before RV30 is
    joined, preventing target construction from silently changing B0.
    """
    information_sets = b1v3_information_sets()
    b0_features = information_sets["B0"]
    all_features = information_sets["B2"]
    common_required = {
        "origin_id",
        "asset",
        "session_date",
        "forecast_origin_utc",
        "role",
        "session_tercile",
        "b0_information_set_complete",
        "b1v3a_information_set_complete",
        "b2_information_set_complete",
        *all_features,
    }
    target_required = {
        "origin_id",
        "asset",
        "session_date",
        "forecast_origin_utc",
        "role",
        "target_price_count",
        "target_return_count",
        "rv30",
        "drop_reason",
        "max_predictor_available_at_utc",
        *b0_features,
    }
    if not common_required <= set(common_predictors.columns):
        raise ValueError("B1V3_TRAINING_COMMON_SCHEMA_INVALID")
    if not target_required <= set(target_frame.columns):
        raise ValueError("B1V3_TRAINING_TARGET_SCHEMA_INVALID")
    sessions = _training_sessions(preregistration)
    development = common_predictors.filter(pl.col("role") == "development")
    if (
        development.is_empty()
        or development["origin_id"].n_unique() != development.height
        or set(development["session_date"].cast(pl.String).unique()) != set(sessions)
        or set(development["asset"].cast(pl.String).unique()) != set(_OUTCOME_ASSETS)
    ):
        raise ValueError("B1V3_TRAINING_COMMON_SCOPE_INVALID")
    if (
        target_frame.is_empty()
        or target_frame["origin_id"].n_unique() != target_frame.height
        or set(target_frame["role"].cast(pl.String).unique()) != {"development"}
        or set(target_frame["session_date"].cast(pl.String).unique()) != set(sessions)
        or set(target_frame["asset"].cast(pl.String).unique()) != set(_OUTCOME_ASSETS)
    ):
        raise ValueError("B1V3_TRAINING_TARGET_SCOPE_INVALID")
    key_columns = ("origin_id", "asset", "session_date", "forecast_origin_utc")
    expected_keys = development.select(key_columns).sort("origin_id")
    observed_keys = target_frame.select(key_columns).sort("origin_id")
    if not expected_keys.equals(observed_keys, null_equal=True):
        raise ValueError("B1V3_TRAINING_ORIGIN_IDENTITY_MISMATCH")
    expected_b0 = development.select("origin_id", *b0_features).sort("origin_id")
    observed_b0 = target_frame.select("origin_id", *b0_features).sort("origin_id")
    if not expected_b0.equals(observed_b0, null_equal=True):
        raise ValueError("B1V3_TRAINING_B0_DRIFT")
    if target_frame.filter(
        pl.col("max_predictor_available_at_utc").is_null()
        | (pl.col("max_predictor_available_at_utc") > pl.col("forecast_origin_utc"))
    ).height:
        raise ValueError("B1V3_TRAINING_PREDICTOR_FUTURE")
    if target_frame.filter(
        (pl.col("target_price_count") != 31)
        | (pl.col("target_return_count") != 30)
        | pl.col("drop_reason").is_not_null()
        | ~pl.col("rv30").is_finite()
        | (pl.col("rv30") <= 0)
    ).height:
        raise ValueError("B1V3_RV30_CONTRACT_INVALID")
    target_values = target_frame.select(
        "origin_id",
        "target_price_count",
        "target_return_count",
        "rv30",
        pl.col("drop_reason").alias("rv30_drop_reason"),
    )
    bound = development.join(
        target_values,
        on="origin_id",
        how="left",
        validate="1:1",
        maintain_order="left",
    )
    complete = bound.filter(
        pl.col("b0_information_set_complete")
        & pl.col("b1v3a_information_set_complete")
        & pl.col("b2_information_set_complete")
    )
    if (
        complete.is_empty()
        or set(complete["session_date"].cast(pl.String).unique()) != set(sessions)
        or set(complete["asset"].cast(pl.String).unique()) != set(_OUTCOME_ASSETS)
        or complete["rv30"].null_count() > 0
    ):
        raise ValueError("B1V3_TRAINING_COMPLETE_SAMPLE_INVALID")
    return complete.sort(["session_date", "forecast_origin_utc", "asset"])


def training_only_b1v3_oof_forecasts(
    panel: pl.DataFrame,
    preregistration: Mapping[str, Any],
) -> tuple[pl.DataFrame, list[dict[str, Any]]]:
    """Create three purged Gamma OOF blocks using development rows only.

    Returns
    -------
    tuple[polars.DataFrame, list[dict[str, Any]]]
        Paired forecasts for B0/B1v3a/B2 and the full tuning ledger.

    Raises
    ------
    ValueError
        If date scope, pairing, temporal splits, tuning, or fitting fails.
    """
    sessions = _training_sessions(preregistration)
    if set(panel["session_date"].cast(pl.String).unique()) != set(sessions):
        raise ValueError("B1V3_TRAINING_DATE_SCOPE_INVALID")
    adapter = b1v3_phase6_adapter_contract(preregistration)
    guard = int(adapter["models"]["purge_embargo_minutes"])
    forecast_parts: list[pl.DataFrame] = []
    ledger: list[dict[str, Any]] = []
    for fold in b1v3_training_folds(preregistration):
        training, testing = split_expanding_fold(
            panel,
            fold,
            purge_minutes=guard,
            embargo_minutes=guard,
        )
        testing, _ = add_training_volatility_regime(training, testing)
        for information_set, features in b1v3_information_sets().items():
            selected, records = select_phase6_parameters(
                training,
                fold=fold,
                information_set=information_set,
                features=features,
                role="gamma_glm_confirmatory",
                preregistration=adapter,
            )
            ledger.extend(records)
            forecast_parts.append(
                forecast_phase6_fold(
                    training,
                    testing,
                    fold=fold,
                    information_set=information_set,
                    features=features,
                    role="gamma_glm_confirmatory",
                    parameters=selected,
                    preregistration=adapter,
                )
            )
    forecasts = pl.concat(forecast_parts).sort(
        ["fold", "information_set", "origin_id"]
    )
    unique_origins = forecasts["origin_id"].n_unique()
    if unique_origins == 0 or forecasts.height != unique_origins * 3:
        raise ValueError("B1V3_TRAINING_OOF_PAIRING_FAILURE")
    return forecasts, ledger


def training_mde_from_b1v3_forecasts(
    forecasts: pl.DataFrame,
    *,
    draws: int,
    seed: int,
) -> dict[str, float]:
    """Estimate both registered MDEs from paired development-day losses.

    Parameters
    ----------
    forecasts:
        Training-only OOF losses for the three B1v3 information sets.
    draws, seed:
        Frozen empirical day-bootstrap size and deterministic seed.

    Returns
    -------
    dict[str, float]
        Positive MDEs for ``delta_b1v3`` and ``delta_b2``.

    Raises
    ------
    ValueError
        If rows are unpaired, duplicated, incomplete, or statistically invalid.
    """
    required = {"origin_id", "session_date", "fold", "information_set", "qlike_loss"}
    if not required <= set(forecasts.columns) or forecasts.is_empty():
        raise ValueError("B1V3_TRAINING_MDE_FORECAST_SCHEMA_INVALID")
    if set(forecasts["information_set"].unique()) != {"B0", "B1v3a", "B2"}:
        raise ValueError("B1V3_TRAINING_MDE_INFORMATION_SETS_INVALID")
    output: dict[str, float] = {}
    for name, baseline, expanded in (
        ("delta_b1v3", "B0", "B1v3a"),
        ("delta_b2", "B1v3a", "B2"),
    ):
        keys = ["origin_id", "session_date", "fold"]
        left = forecasts.filter(pl.col("information_set") == baseline).select(
            *keys, pl.col("qlike_loss").alias("baseline_loss")
        )
        right = forecasts.filter(pl.col("information_set") == expanded).select(
            *keys, pl.col("qlike_loss").alias("expanded_loss")
        )
        paired = left.join(right, on=keys, how="inner", validate="1:1")
        if paired.height != left.height or paired.height != right.height:
            raise ValueError(f"B1V3_TRAINING_MDE_UNPAIRED:{name}")
        groups = (
            paired.with_columns(
                (pl.col("baseline_loss") - pl.col("expanded_loss")).alias(
                    "loss_difference"
                )
            )
            .sort(["session_date", "fold", "origin_id"])
            .partition_by("session_date", maintain_order=True)
        )
        output[name] = estimate_training_mde(
            [
                math.fsum(group["loss_difference"].to_list()) / group.height
                for group in groups
            ],
            draws=draws,
            seed=seed,
        )
    return output


def select_b1v3_final_parameters(
    panel: pl.DataFrame,
    preregistration: Mapping[str, Any],
) -> tuple[dict[str, dict[str, dict[str, float | int]]], list[dict[str, Any]]]:
    """Select final Gamma and LightGBM variants on development history only.

    Returns
    -------
    tuple[dict[str, dict[str, dict[str, float | int]]], list[dict[str, Any]]]
        Selected parameters by role/information set and all attempted variants.

    Raises
    ------
    ValueError
        If training dates drift or no registered candidate succeeds.
    """
    sessions = _training_sessions(preregistration)
    if set(panel["session_date"].cast(pl.String).unique()) != set(sessions):
        raise ValueError("B1V3_TRAINING_DATE_SCOPE_INVALID")
    adapter = b1v3_phase6_adapter_contract(preregistration)
    fold = FoldDefinition(
        fold=900,
        train_end=date.fromisoformat(sessions[-1]),
        test_start=date.fromisoformat(str(preregistration["confirmation_sessions"][0])),
        test_end=date.fromisoformat(str(preregistration["confirmation_sessions"][-1])),
    )
    selected: dict[str, dict[str, dict[str, float | int]]] = {}
    ledger: list[dict[str, Any]] = []
    for role in _MODEL_ROLES:
        selected[role] = {}
        for information_set, features in b1v3_information_sets().items():
            parameters, records = select_phase6_parameters(
                panel,
                fold=fold,
                information_set=information_set,
                features=features,
                role=role,
                preregistration=adapter,
            )
            selected[role][information_set] = parameters
            ledger.extend(records)
    return selected, ledger


def training_volatility_regime_cutpoints(panel: pl.DataFrame) -> dict[str, float]:
    """Estimate the two volatility-regime cutpoints from development only."""
    _, cutpoints = add_training_volatility_regime(panel, panel)
    return cutpoints


def build_b1v3_method_freeze(
    preregistration: Mapping[str, Any],
    *,
    common_panel_sha256: str,
    training_panel_sha256: str,
    training_target_source_sha256: str,
    oof_forecasts_sha256: str,
    tuning_ledger_sha256: str,
    method_freeze_code_sha256: str,
    uv_lock_sha256: str,
    selected_parameters: Mapping[str, Mapping[str, Mapping[str, float | int]]],
    training_mde: Mapping[str, float],
    volatility_regime_cutpoints: Mapping[str, float],
    row_count: int,
) -> dict[str, Any]:
    """Seal all training-derived choices before confirmation access.

    Returns
    -------
    dict[str, Any]
        Deterministic self-hashed method freeze with confirmation reads at zero.

    Raises
    ------
    ValueError
        If source hashes, selected variants, MDEs, cutpoints, or scope drift.
    """
    _training_sessions(preregistration)
    hashes = (
        common_panel_sha256,
        training_panel_sha256,
        training_target_source_sha256,
        oof_forecasts_sha256,
        tuning_ledger_sha256,
        method_freeze_code_sha256,
        uv_lock_sha256,
    )
    if (
        preregistration.get("common_predictor_panel_sha256") != common_panel_sha256
        or not all(_is_sha256(value) for value in hashes)
        or row_count < 1
    ):
        raise ValueError("B1V3_METHOD_FREEZE_SOURCE_INVALID")
    expected_sets = set(b1v3_information_sets())
    if set(selected_parameters) != set(_MODEL_ROLES) or any(
        set(selected_parameters[role]) != expected_sets for role in _MODEL_ROLES
    ):
        raise ValueError("B1V3_METHOD_FREEZE_PARAMETERS_INVALID")
    if any(
        not isinstance(selected_parameters[role][information_set], Mapping)
        or not selected_parameters[role][information_set]
        for role in _MODEL_ROLES
        for information_set in expected_sets
    ):
        raise ValueError("B1V3_METHOD_FREEZE_PARAMETERS_INVALID")
    method = preregistration["method"]
    confirmatory = method["confirmatory"]
    robustness = method["robustness"]
    gamma_expected_keys = {"alpha", "max_iter", "tol"}
    lightgbm_expected_keys = {
        "learning_rate",
        "max_depth",
        "min_child_samples",
        "n_estimators",
        "num_leaves",
        "reg_lambda",
    }
    for information_set in expected_sets:
        gamma = selected_parameters["gamma_glm_confirmatory"][information_set]
        lightgbm = selected_parameters["lightgbm_robustness"][information_set]
        grid = robustness["grid"]
        if (
            set(gamma) != gamma_expected_keys
            or float(gamma["alpha"]) not in confirmatory["alpha_grid"]
            or int(gamma["max_iter"]) != int(confirmatory["max_iter"])
            or float(gamma["tol"]) != float(confirmatory["tolerance"])
            or set(lightgbm) != lightgbm_expected_keys
            or any(lightgbm[name] not in grid[name] for name in lightgbm_expected_keys)
        ):
            raise ValueError("B1V3_METHOD_FREEZE_PARAMETERS_INVALID")
    if set(training_mde) != {"delta_b1v3", "delta_b2"} or any(
        not math.isfinite(float(value)) or float(value) <= 0
        for value in training_mde.values()
    ):
        raise ValueError("B1V3_METHOD_FREEZE_MDE_INVALID")
    if set(volatility_regime_cutpoints) != {"lower", "upper"}:
        raise ValueError("B1V3_METHOD_FREEZE_REGIME_INVALID")
    lower = float(volatility_regime_cutpoints["lower"])
    upper = float(volatility_regime_cutpoints["upper"])
    if not math.isfinite(lower) or not math.isfinite(upper) or lower >= upper:
        raise ValueError("B1V3_METHOD_FREEZE_REGIME_INVALID")
    document: dict[str, Any] = {
        "schema_version": "1.0",
        "status": "FROZEN_AFTER_TRAINING_BEFORE_CONFIRMATION",
        "safe_to_read_confirmation": False,
        "outcome_read_count": 1,
        "training_read_count": 1,
        "confirmation_read_count": 0,
        "preregistration_manifest_sha256": str(preregistration["manifest_sha256"]),
        "common_panel_sha256": common_panel_sha256,
        "training_sessions": list(preregistration["training_sessions"]),
        "confirmation_sessions": list(preregistration["confirmation_sessions"]),
        "training_sample": {
            "row_count": row_count,
            "session_count": 60,
            "asset_count": len(_OUTCOME_ASSETS),
            "identical_information_set_sample": True,
            "target_price_count": 31,
            "target_return_count": 30,
        },
        "source_hashes": {
            "training_panel_sha256": training_panel_sha256,
            "training_target_source_sha256": training_target_source_sha256,
            "oof_forecasts_sha256": oof_forecasts_sha256,
            "tuning_ledger_sha256": tuning_ledger_sha256,
            "method_freeze_code_sha256": method_freeze_code_sha256,
            "uv_lock_sha256": uv_lock_sha256,
        },
        "oof_blocks": [101, 102, 103],
        "selected_parameters": {
            role: {
                information_set: dict(selected_parameters[role][information_set])
                for information_set in ("B0", "B1v3a", "B2")
            }
            for role in _MODEL_ROLES
        },
        "training_mde": {
            name: float(training_mde[name]) for name in ("delta_b1v3", "delta_b2")
        },
        "volatility_regime_cutpoints": {"lower": lower, "upper": upper},
        "confirmation_policy": "EXACTLY_ONE_ANALYTICAL_READ_AFTER_ACCESS_LEDGER",
        "retain_all_registered_signs": True,
    }
    document["manifest_sha256"] = canonical_sha256(document)
    return document
