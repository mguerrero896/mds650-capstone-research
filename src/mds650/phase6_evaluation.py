"""Fail-closed contracts for the preregistered Phase 6 evaluation."""

from __future__ import annotations

import itertools
import json
import math
from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any

import numpy as np
import polars as pl

from mds650.metrics import (
    holm_adjust,
    paired_day_bootstrap,
    qlike_losses,
    regression_metrics,
)
from mds650.modeling import fit_positive_model
from mds650.phase6 import (
    B0V2_FEATURES,
    B1V2A_FEATURES,
    B2V2_FEATURES,
)
from mds650.study_design import canonical_sha256
from mds650.temporal_validation import (
    FoldDefinition,
    split_expanding_fold,
    split_inner_validation,
)

FORECAST_FLOOR = 1e-12


def replace_phase6_features(
    primary: pl.DataFrame,
    sensitivity: pl.DataFrame,
    *,
    columns: Sequence[str],
) -> pl.DataFrame:
    """Replace registered sensitivity columns without changing keys or RV30."""
    keys = ("origin_id", "asset", "session_date", "forecast_origin_utc")
    if any(name not in frame.columns for frame in (primary, sensitivity) for name in keys):
        raise ValueError("PHASE6_SENSITIVITY_KEY_MISMATCH")
    if any(name not in primary.columns or name not in sensitivity.columns for name in columns):
        raise ValueError("PHASE6_SENSITIVITY_COLUMNS_MISSING")
    if any(frame["origin_id"].n_unique() != frame.height for frame in (primary, sensitivity)):
        raise ValueError("PHASE6_SENSITIVITY_KEY_MISMATCH")
    primary_keys = primary.select(keys).sort("origin_id")
    sensitivity_keys = sensitivity.select(keys).sort("origin_id")
    if not primary_keys.equals(sensitivity_keys):
        raise ValueError("PHASE6_SENSITIVITY_KEY_MISMATCH")
    if "rv30" in sensitivity.columns and (
        "rv30" not in primary.columns
        or not primary.select("origin_id", "rv30")
        .sort("origin_id")
        .equals(sensitivity.select("origin_id", "rv30").sort("origin_id"))
    ):
        raise ValueError("PHASE6_SENSITIVITY_TARGET_DRIFT")
    replacements = sensitivity.select("origin_id", *columns).rename(
        {name: f"{name}__sensitivity" for name in columns}
    )
    joined = primary.join(replacements, on="origin_id", how="left", maintain_order="left")
    return joined.with_columns(pl.col(f"{name}__sensitivity").alias(name) for name in columns).drop(
        *(f"{name}__sensitivity" for name in columns)
    )


def estimate_training_mde(
    daily_effects: Sequence[float],
    *,
    draws: int,
    seed: int,
) -> float:
    """Estimate the Holm-two, 80%-power MDE from training days only.

    The empirical day bootstrap is centered under the null. The threshold uses
    a two-sided Bonferroni/Holm first-step alpha of 0.025; the returned shift is
    the amount that moves 80% of resampled means above that threshold.
    """
    values = np.asarray(daily_effects, dtype=np.float64)
    if (
        values.ndim != 1
        or values.size < 2
        or draws < 100
        or not np.isfinite(values).all()
        or float(values.std(ddof=1)) == 0.0
    ):
        raise ValueError("PHASE6_TRAINING_MDE_INPUT_INVALID")
    centered = values - values.mean()
    generator = np.random.default_rng(seed)
    samples = centered[generator.integers(0, values.size, size=(draws, values.size))].mean(axis=1)
    null_critical = float(np.quantile(samples, 0.9875))
    power_tail = float(np.quantile(samples, 0.20))
    mde = null_critical - power_tail
    if not np.isfinite(mde) or mde <= 0:
        raise ValueError("PHASE6_TRAINING_MDE_INPUT_INVALID")
    return mde


def authorize_phase6_oos(
    ledger: Mapping[str, Any],
    *,
    common_panel_sha256: str,
    preregistration_manifest_sha256: str,
    results_exist: bool,
) -> dict[str, Any]:
    """Consume the sole Phase 6 evaluation authorization fail-closed."""
    unsigned = {key: value for key, value in ledger.items() if key != "manifest_sha256"}
    if (
        ledger.get("manifest_sha256") != canonical_sha256(unsigned)
        or ledger.get("status") != "SEALED_BEFORE_OOS"
        or ledger.get("oos_read_count") != 0
        or ledger.get("evaluation_attempt_count") != 0
        or ledger.get("common_panel_sha256") != common_panel_sha256
        or ledger.get("preregistration_manifest_sha256") != preregistration_manifest_sha256
        or ledger.get("results_inspected") is not False
        or results_exist
    ):
        raise ValueError("PHASE6_OOS_ACCESS_DENIED")
    authorized = {
        **unsigned,
        "status": "OOS_EVALUATION_IN_PROGRESS",
        "oos_read_count": 1,
        "evaluation_attempt_count": 1,
    }
    authorized["manifest_sha256"] = canonical_sha256(authorized)
    return authorized


def _parameter_grid(preregistration: Mapping[str, Any], role: str) -> list[dict[str, float | int]]:
    models = preregistration["models"]
    if role == "gamma_glm_confirmatory":
        model = models["confirmatory"]
        return [
            {
                "alpha": float(alpha),
                "max_iter": int(model["max_iter"]),
                "tol": float(model["tolerance"]),
            }
            for alpha in model["alpha_grid"]
        ]
    if role == "lightgbm_robustness":
        grid = models["robustness"]["grid"]
        names = tuple(sorted(grid))
        return [
            dict(zip(names, values, strict=True))
            for values in itertools.product(*(grid[name] for name in names))
        ]
    raise ValueError(f"UNKNOWN_MODEL_ROLE:{role}")


def select_phase6_parameters(
    training: pl.DataFrame,
    *,
    fold: FoldDefinition,
    information_set: str,
    features: tuple[str, ...],
    role: str,
    preregistration: Mapping[str, Any],
) -> tuple[dict[str, float | int], list[dict[str, Any]]]:
    """Select one preregistered model variant on training history only."""
    guard = int(preregistration["models"]["purge_embargo_minutes"])
    seed = int(preregistration["inference"]["seed"])
    fitting, validation = split_inner_validation(
        training,
        validation_sessions=10,
        purge_minutes=guard,
        embargo_minutes=guard,
    )
    records: list[dict[str, Any]] = []
    successful: list[tuple[float, str, dict[str, float | int]]] = []
    for parameters in _parameter_grid(preregistration, role):
        identity = {
            "fold": fold.fold,
            "information_set": information_set,
            "model_role": role,
            "parameters": parameters,
        }
        variant_id = canonical_sha256(identity)[:20]
        record: dict[str, Any] = {
            **identity,
            "variant_id": variant_id,
            "n_fit": fitting.height,
            "n_validation": validation.height,
            "selected": False,
        }
        try:
            fitted = fit_positive_model(
                fitting,
                feature_columns=features,
                categorical_columns=("b0v2_asset_identity",),
                target_column="rv30",
                role=role,
                parameters=parameters,
                seed=seed,
                forecast_floor=FORECAST_FLOOR,
            )
            score = regression_metrics(
                validation["rv30"].to_numpy(),
                fitted.predict(validation),
                floor=FORECAST_FLOOR,
            )["qlike"]
            record.update({"status": "RUN", "validation_qlike": score, "failure_reason": None})
            successful.append((score, json.dumps(parameters, sort_keys=True), parameters))
        except (ValueError, RuntimeError, ArithmeticError, np.linalg.LinAlgError) as error:
            # Only expected numerical/fitting failures may exclude a variant.
            # A coding bug (TypeError, KeyError, ...) must propagate: silently
            # dropping variants would turn the bug into an unregistered,
            # data-dependent hyperparameter selection pressure.
            record.update(
                {
                    "status": "FAILED_WITH_REASON",
                    "validation_qlike": None,
                    "failure_reason": f"{type(error).__name__}:{error}",
                }
            )
        records.append(record)
    if not successful:
        raise ValueError(
            f"PHASE6_NO_SUCCESSFUL_TUNING_VARIANT:{fold.fold}:{information_set}:{role}"
        )
    selected = min(successful, key=lambda row: (row[0], row[1]))[2]
    selected_id = canonical_sha256(
        {
            "fold": fold.fold,
            "information_set": information_set,
            "model_role": role,
            "parameters": selected,
        }
    )[:20]
    for record in records:
        record["selected"] = record["variant_id"] == selected_id
    return selected, records


def forecast_phase6_fold(
    training: pl.DataFrame,
    testing: pl.DataFrame,
    *,
    fold: FoldDefinition,
    information_set: str,
    features: tuple[str, ...],
    role: str,
    parameters: Mapping[str, float | int],
    preregistration: Mapping[str, Any],
) -> pl.DataFrame:
    """Fit on one expanding training block and forecast its untouched fold."""
    seed = int(preregistration["inference"]["seed"])
    fitted = fit_positive_model(
        training,
        feature_columns=features,
        categorical_columns=("b0v2_asset_identity",),
        target_column="rv30",
        role=role,
        parameters=parameters,
        seed=seed,
        forecast_floor=FORECAST_FLOOR,
    )
    predictions = fitted.predict(testing)
    target = np.asarray(testing["rv30"].to_numpy(), dtype=np.float64)
    errors = target - predictions
    return testing.select(
        "origin_id",
        "asset",
        "session_date",
        "forecast_origin_utc",
        "session_tercile",
        "volatility_regime",
        "rv30",
    ).with_columns(
        pl.lit(fold.fold).alias("fold"),
        pl.lit(role).alias("model_role"),
        pl.lit(information_set).alias("information_set"),
        pl.Series("forecast", predictions),
        pl.Series("qlike_loss", qlike_losses(target, predictions)),
        pl.Series("absolute_error", np.abs(errors)),
        pl.Series("squared_error", np.square(errors)),
        pl.lit(json.dumps(dict(parameters), sort_keys=True)).alias("selected_parameters"),
        pl.lit(canonical_sha256({"features": list(features)})).alias("feature_schema_sha256"),
    )


def phase6_contrast(
    forecasts: pl.DataFrame,
    *,
    role: str,
    name: str,
    baseline: str,
    expanded: str,
    preregistration: Mapping[str, Any],
) -> dict[str, Any]:
    """Estimate one paired QLIKE improvement with whole-day uncertainty."""
    keys = ["origin_id", "asset", "session_date", "fold"]
    left = forecasts.filter(
        (pl.col("model_role") == role) & (pl.col("information_set") == baseline)
    ).select(*keys, pl.col("qlike_loss").alias("baseline_loss"))
    right = forecasts.filter(
        (pl.col("model_role") == role) & (pl.col("information_set") == expanded)
    ).select(*keys, pl.col("qlike_loss").alias("expanded_loss"))
    paired = left.join(right, on=keys, how="inner", validate="1:1").with_columns(
        (pl.col("baseline_loss") - pl.col("expanded_loss")).alias("loss_difference")
    )
    if paired.height != left.height or paired.height != right.height:
        raise ValueError(f"PHASE6_UNPAIRED_CONTRAST:{role}:{name}")
    inference = paired_day_bootstrap(
        paired,
        repetitions=int(preregistration["inference"]["bootstrap_repetitions"]),
        seed=int(preregistration["inference"]["seed"]),
    )
    estimate = float(inference["estimate"])
    return {
        "model_role": role,
        "contrast": name,
        "definition": f"QLIKE({baseline})-QLIKE({expanded})",
        "positive_direction": "EXPANDED_INFORMATION_SET_BETTER",
        "result_sign": ("POSITIVE" if estimate > 0 else "NEGATIVE" if estimate < 0 else "ZERO"),
        "baseline_mean_qlike": float(np.asarray(left["baseline_loss"].to_numpy()).mean()),
        "expanded_mean_qlike": float(np.asarray(right["expanded_loss"].to_numpy()).mean()),
        "p_value_raw": float(inference["p_value_two_sided"]),
        **inference,
    }


def evaluate_phase6(
    predictions: pl.DataFrame,
    method: Mapping[str, Any],
    *,
    timing_predictions: pl.DataFrame | None = None,
) -> dict[str, Any]:
    """Evaluate every frozen Phase 6 view without selecting favorable results."""
    contrasts = (
        ("delta_b1v2", "B0v2", "B1v2a"),
        ("delta_b2v2", "B1v2a", "B2v2"),
    )
    roles = ("gamma_glm_confirmatory", "lightgbm_robustness")
    preregistration = {
        "inference": method["inference"],
    }
    global_rows = {
        (role, name): phase6_contrast(
            predictions,
            role=role,
            name=name,
            baseline=baseline,
            expanded=expanded,
            preregistration=preregistration,
        )
        for role in roles
        for name, baseline, expanded in contrasts
    }
    gamma_holm = holm_adjust(
        {
            name: float(global_rows[("gamma_glm_confirmatory", name)]["p_value_raw"])
            for name, _, _ in contrasts
        }
    )
    for name, adjusted in gamma_holm.items():
        global_rows[("gamma_glm_confirmatory", name)]["p_value_holm"] = adjusted

    metrics = []
    for key, frame in predictions.group_by("model_role", "information_set"):
        role, information_set = key
        metrics.append(
            {
                "model_role": role,
                "information_set": information_set,
                "observations": frame.height,
                **regression_metrics(frame["rv30"].to_numpy(), frame["forecast"].to_numpy()),
            }
        )
    stability = []
    for role in roles:
        for name, baseline, expanded in contrasts:
            for dimension in ("asset", "session_tercile", "volatility_regime"):
                for value in sorted(predictions[dimension].unique().to_list()):
                    row = phase6_contrast(
                        predictions.filter(pl.col(dimension) == value),
                        role=role,
                        name=name,
                        baseline=baseline,
                        expanded=expanded,
                        preregistration=preregistration,
                    )
                    stability.append({**row, "dimension": dimension, "value": value})

    targeted = {}
    for label, expression in (
        ("META", pl.col("asset") == "META"),
        ("MSFT", pl.col("asset") == "MSFT"),
        ("last_session_tercile", pl.col("session_tercile") == "last"),
    ):
        targeted[label] = phase6_contrast(
            predictions.filter(expression),
            role="gamma_glm_confirmatory",
            name="delta_b2v2",
            baseline="B1v2a",
            expanded="B2v2",
            preregistration=preregistration,
        )
    targeted_holm = holm_adjust({name: float(row["p_value_raw"]) for name, row in targeted.items()})
    for name, adjusted in targeted_holm.items():
        targeted[name]["p_value_holm"] = adjusted

    timing = _phase6_timing_contrasts(
        predictions, timing_predictions, preregistration, contrasts, roles
    )
    confirmed = []
    for name, _, _ in contrasts:
        gamma = global_rows[("gamma_glm_confirmatory", name)]
        challenger = global_rows[("lightgbm_robustness", name)]
        assets = [
            row
            for row in stability
            if row["model_role"] == "gamma_glm_confirmatory"
            and row["contrast"] == name
            and row["dimension"] == "asset"
        ]
        relevant_timing = [row for row in timing if row["contrast"] == name]
        mde = float(method["training_mde"][name])
        if (
            float(gamma["estimate"]) > 0
            and float(gamma["ci_low"]) > 0
            and float(gamma["p_value_holm"]) < 0.05
            and float(gamma["estimate"]) >= mde
            and float(challenger["estimate"]) > 0
            and sum(float(row["estimate"]) > 0 for row in assets) >= 4
            and sum(float(row["ci_high"]) < 0 for row in assets) <= 1
            and relevant_timing
            and not any(float(row["ci_high"]) < 0 for row in relevant_timing)
        ):
            confirmed.append(name)
    targeted_confirmed = all(
        float(row["estimate"]) > 0
        and float(row["ci_low"]) > 0
        and float(row["p_value_holm"]) < 0.05
        for row in targeted.values()
    )
    if "delta_b2v2" in confirmed:
        decision = "GLOBAL_B2V2_EDGE_CONFIRMED"
    elif "delta_b1v2" in confirmed:
        decision = "GLOBAL_B1V2_EDGE_CONFIRMED"
    elif targeted_confirmed:
        decision = "TARGETED_B2V2_REPLICATION_CONFIRMED"
    else:
        decision = "GLOBAL_EDGE_NOT_CONFIRMED"
    return {
        "metrics": sorted(metrics, key=lambda row: (row["model_role"], row["information_set"])),
        "global": {
            role: {name: global_rows[(role, name)] for name, _, _ in contrasts} for role in roles
        },
        "global_holm": gamma_holm,
        "targeted_b2v2": targeted,
        "targeted_holm": targeted_holm,
        "stability": stability,
        "timing": timing,
        "confirmed_contrasts": confirmed,
        "decision": decision,
        "all_signs_retained": True,
    }


def _phase6_timing_contrasts(
    primary: pl.DataFrame,
    sensitivity: pl.DataFrame | None,
    preregistration: Mapping[str, Any],
    contrasts: Sequence[tuple[str, str, str]],
    roles: Sequence[str],
) -> list[dict[str, Any]]:
    if sensitivity is None or sensitivity.is_empty():
        return []
    expected_variants = {
        "FMP_DELAY_2_MINUTES",
        "window_15m_60s",
        "window_30m_60s",
        "latency_5m_120s",
        "latency_5m_300s",
    }
    if set(sensitivity["timing_variant"].unique()) != expected_variants:
        raise ValueError("PHASE6_TIMING_VARIANTS_INCOMPLETE")
    output = []
    for variant in sorted(sensitivity["timing_variant"].unique().to_list()):
        variant_rows = sensitivity.filter(pl.col("timing_variant") == variant)
        expected_sets = {"B0v2", "B1v2a", "B2v2"} if variant == "FMP_DELAY_2_MINUTES" else {"B2v2"}
        if set(variant_rows["information_set"].unique()) != expected_sets:
            raise ValueError(f"PHASE6_TIMING_INFORMATION_SETS_INVALID:{variant}")
        for role in roles:
            for name, baseline, expanded in contrasts:
                available = set(variant_rows["information_set"].unique())
                if expanded not in available:
                    continue
                combined = variant_rows
                if baseline not in available:
                    baseline_rows = primary.filter(
                        (pl.col("model_role") == role) & (pl.col("information_set") == baseline)
                    )
                    combined = pl.concat([combined, baseline_rows], how="diagonal_relaxed")
                row = phase6_contrast(
                    combined,
                    role=role,
                    name=name,
                    baseline=baseline,
                    expanded=expanded,
                    preregistration=preregistration,
                )
                output.append({**row, "timing_variant": variant})
    return output


def training_only_oof_forecasts(
    panel: pl.DataFrame,
    preregistration: Mapping[str, Any],
) -> tuple[pl.DataFrame, list[dict[str, Any]]]:
    """Create three training-only OOF blocks for the MDE freeze."""
    registered = preregistration["folds"][0]
    dates = [str(day) for day in registered["train_dates"]]
    if len(dates) != 60 or set(panel["session_date"].cast(pl.String)) != set(dates):
        raise ValueError("PHASE6_MDE_TRAINING_DATES_INVALID")
    guard = int(preregistration["models"]["purge_embargo_minutes"])
    information_sets = phase6_information_sets()
    forecast_parts: list[pl.DataFrame] = []
    ledger: list[dict[str, Any]] = []
    for index in range(3):
        fold = FoldDefinition(
            fold=101 + index,
            train_end=date.fromisoformat(dates[29 + 10 * index]),
            test_start=date.fromisoformat(dates[30 + 10 * index]),
            test_end=date.fromisoformat(dates[39 + 10 * index]),
        )
        training, testing = split_expanding_fold(
            panel,
            fold,
            purge_minutes=guard,
            embargo_minutes=guard,
        )
        testing, _ = add_training_volatility_regime(training, testing)
        for information_set, features in information_sets.items():
            selected, records = select_phase6_parameters(
                training,
                fold=fold,
                information_set=information_set,
                features=features,
                role="gamma_glm_confirmatory",
                preregistration=preregistration,
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
                    preregistration=preregistration,
                )
            )
    forecasts = pl.concat(forecast_parts).sort(["fold", "information_set", "origin_id"])
    expected_origins = forecasts["origin_id"].n_unique()
    if expected_origins == 0 or forecasts.height != expected_origins * 3:
        raise ValueError("PHASE6_MDE_FORECAST_PAIRING_FAILURE")
    return forecasts, ledger


def training_mde_from_forecasts(
    forecasts: pl.DataFrame,
    *,
    draws: int,
    seed: int,
) -> dict[str, float]:
    """Estimate both registered MDEs from paired training-only OOF losses."""
    output: dict[str, float] = {}
    for name, baseline, expanded in (
        ("delta_b1v2", "B0v2", "B1v2a"),
        ("delta_b2v2", "B1v2a", "B2v2"),
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
            raise ValueError(f"PHASE6_MDE_UNPAIRED:{name}")
        daily_groups = (
            paired.with_columns(
                (pl.col("baseline_loss") - pl.col("expanded_loss")).alias("loss_difference")
            )
            .select("session_date", "fold", "origin_id", "loss_difference")
            .sort("session_date", "fold", "origin_id")
            .partition_by("session_date", maintain_order=True)
        )
        output[name] = estimate_training_mde(
            [
                math.fsum(group["loss_difference"].to_list()) / group.height
                for group in daily_groups
            ],
            draws=draws,
            seed=seed,
        )
    return output


def phase6_information_sets() -> dict[str, tuple[str, ...]]:
    """Return the three frozen, strictly nested Phase 6 predictor sets.

    Returns
    -------
    dict[str, tuple[str, ...]]
        B0v2, B1v2a and B2v2 feature names in preregistered order.
    """
    b0 = B0V2_FEATURES
    b1 = (*b0, *B1V2A_FEATURES)
    return {"B0v2": b0, "B1v2a": b1, "B2v2": (*b1, *B2V2_FEATURES)}


def add_training_volatility_regime(
    training: pl.DataFrame, testing: pl.DataFrame
) -> tuple[pl.DataFrame, dict[str, float]]:
    """Classify testing rows using RV cutpoints estimated on training only."""
    column = "b0v2_underlying_rv_30m"
    if column not in training.columns or column not in testing.columns:
        raise ValueError("PHASE6_VOLATILITY_COLUMN_MISSING")
    values = np.asarray(training[column].to_numpy(), dtype=np.float64)
    if values.size == 0 or not np.isfinite(values).all():
        raise ValueError("PHASE6_VOLATILITY_TRAINING_INVALID")
    lower, upper = np.quantile(values, [1 / 3, 2 / 3])
    classified = testing.with_columns(
        pl.when(pl.col(column) <= float(lower))
        .then(pl.lit("low"))
        .when(pl.col(column) <= float(upper))
        .then(pl.lit("normal"))
        .otherwise(pl.lit("high"))
        .alias("volatility_regime")
    )
    return classified, {"lower": float(lower), "upper": float(upper)}


def phase6_fold_definitions(
    preregistration: Mapping[str, Any],
) -> tuple[FoldDefinition, ...]:
    """Parse and verify the five frozen expanding Phase 6 folds.

    Parameters
    ----------
    preregistration:
        Self-hashed Phase 6 preregistration mapping.

    Returns
    -------
    tuple[FoldDefinition, ...]
        Five chronological expanding folds.

    Raises
    ------
    ValueError
        If counts, chronology, expansion or test disjointness drift.
    """
    rows = preregistration.get("folds")
    if not isinstance(rows, list) or len(rows) != 5:
        raise ValueError("PHASE6_FOLD_CONTRACT_INVALID")
    parsed: list[FoldDefinition] = []
    prior_train: set[str] = set()
    prior_tests: set[str] = set()
    for expected_fold, row in enumerate(rows, start=1):
        if not isinstance(row, Mapping):
            raise ValueError("PHASE6_FOLD_CONTRACT_INVALID")
        train = [str(value) for value in row.get("train_dates", ())]
        test = [str(value) for value in row.get("test_dates", ())]
        if (
            int(row.get("fold", -1)) != expected_fold
            or len(train) != 60 + 20 * (expected_fold - 1)
            or len(test) != 20
            or train != sorted(set(train))
            or test != sorted(set(test))
            or set(train) & set(test)
            or set(test) & prior_tests
            or (expected_fold > 1 and set(train) != prior_train | prior_tests)
            or max(train) >= min(test)
        ):
            raise ValueError("PHASE6_FOLD_CONTRACT_INVALID")
        parsed.append(
            FoldDefinition(
                fold=expected_fold,
                train_end=date.fromisoformat(max(train)),
                test_start=date.fromisoformat(min(test)),
                test_end=date.fromisoformat(max(test)),
            )
        )
        prior_train = set(train)
        prior_tests |= set(test)
    return tuple(parsed)


def validate_phase6_evaluation_panel(
    panel: pl.DataFrame,
    preregistration: Mapping[str, Any],
) -> pl.DataFrame:
    """Validate the frozen common panel without calculating any outcome metric.

    Parameters
    ----------
    panel:
        Complete-case Phase 6 panel on identical B0v2/B1v2a/B2v2 origins.
    preregistration:
        Frozen preregistration with zero prior OOS reads.

    Returns
    -------
    polars.DataFrame
        The input rows in deterministic chronological order.

    Raises
    ------
    ValueError
        If the preregistration, row keys, sessions, assets or predictors drift.
    """
    unsigned = {key: value for key, value in preregistration.items() if key != "manifest_sha256"}
    information_sets = phase6_information_sets()
    required = {
        "origin_id",
        "asset",
        "session_date",
        "forecast_origin_utc",
        "rv30",
        "common_complete",
        *information_sets["B2v2"],
    }
    folds = phase6_fold_definitions(preregistration)
    del folds
    expected_dates = {
        str(day)
        for row in preregistration["folds"]
        for key in ("train_dates", "test_dates")
        for day in row[key]
    }
    expected_assets = set(preregistration.get("outcome_assets", ()))
    numeric = [name for name in information_sets["B2v2"] if name != "b0v2_asset_identity"]
    invalid = (
        preregistration.get("status") != "FROZEN_BEFORE_OOS"
        or preregistration.get("oos_read_count") != 0
        or preregistration.get("manifest_sha256") != canonical_sha256(unsigned)
        or not required <= set(panel.columns)
        or panel.is_empty()
        or panel["origin_id"].null_count() > 0
        or panel["origin_id"].n_unique() != panel.height
        or set(panel["session_date"].cast(pl.String).unique()) != expected_dates
        or set(panel["asset"].cast(pl.String).unique()) != expected_assets
        or panel.filter(~pl.col("common_complete")).height > 0
        or panel.filter(~pl.col("rv30").is_finite() | (pl.col("rv30") <= 0)).height > 0
        or panel.select(
            pl.any_horizontal(
                [~pl.col(name).cast(pl.Float64).is_finite() for name in numeric]
            ).any()
        ).item()
        or panel["b0v2_asset_identity"].null_count() > 0
    )
    if invalid:
        raise ValueError("PHASE6_EVALUATION_PANEL_INVALID")
    return panel.sort(["session_date", "forecast_origin_utc", "asset"])
