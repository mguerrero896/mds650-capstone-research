"""Run the preregistered Phase 5 development-only RV30 evaluation."""

from __future__ import annotations

import hashlib
import itertools
import json
import math
from collections.abc import Mapping, Sequence
from importlib.metadata import version
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from mds650.holdout import FROZEN_PHASE5_SOURCE_PATHS
from mds650.metrics import (
    holm_adjust,
    paired_day_bootstrap,
    qlike_losses,
    regression_metrics,
)
from mds650.modeling import fit_positive_model
from mds650.stability import (
    B2_DELAYS_SECONDS,
    FMP_DELAYS_MINUTES,
    SESSION_TERCILE_BOUNDS,
    b2_sensitivity_column,
    development_volatility_cutpoints,
)
from mds650.study_design import (
    B2_FEATURE_NAMES,
    canonical_sha256,
    freeze_json,
    source_sha256,
)
from mds650.temporal_validation import (
    FoldDefinition,
    parse_fold_definitions,
    split_expanding_fold,
    split_inner_validation,
)

ROOT = Path(__file__).resolve().parents[1]
PHASE5 = ROOT / "artifacts" / "phase5"
PREREGISTRATION_PATH = PHASE5 / "preregistration.json"
PANEL_PATH = PHASE5 / "common_development_80d.parquet"
QUALITY_PATH = PHASE5 / "development_panel_quality.json"
SOURCE_MANIFEST_PATH = PHASE5 / "development_source_manifest_80d.json"
FORECASTS_PATH = PHASE5 / "development_forecasts.parquet"
RESULTS_PATH = PHASE5 / "development_results.json"
LEDGER_PATH = PHASE5 / "variant_ledger.json"
METHOD_FREEZE_PATH = PHASE5 / "method_freeze.json"
STABILITY_INPUT_PATH = Path(
    "D:/MDS650/data/phase5_stability/development_stability_inputs_80d.parquet"
)
STABILITY_INPUT_MANIFEST_PATH = PHASE5 / "development_stability_input_manifest.json"
STABILITY_VALIDATION_PATH = PHASE5 / "development_stability_validation.json"

B0_FEATURES = (
    "asset",
    "b0_spot",
    "b0_rv_5m_lag",
    "b0_rv_30m_lag",
    "b0_return_5m_lag",
    "b0_volume_5m_lag",
    "b0_session_minute",
)
INFORMATION_SETS = {
    "B0": B0_FEATURES,
    "B1a": (*B0_FEATURES, "b1q_atm_iv"),
    "B2": (*B0_FEATURES, "b1q_atm_iv", *B2_FEATURE_NAMES),
}
MODEL_ROLES = ("gamma_glm_confirmatory", "lightgbm_robustness")


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"PHASE5_JSON_OBJECT_REQUIRED:{path.name}")
    return payload


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parameter_grid(
    preregistration: Mapping[str, Any],
    role: str,
) -> list[dict[str, float | int]]:
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


def _variant_id(payload: Mapping[str, Any]) -> str:
    return canonical_sha256(payload)[:20]


def _select_parameters(
    training: pl.DataFrame,
    *,
    fold: FoldDefinition,
    information_set: str,
    features: Sequence[str],
    role: str,
    preregistration: Mapping[str, Any],
) -> tuple[dict[str, float | int], list[dict[str, Any]]]:
    fitting, validation = split_inner_validation(
        training,
        validation_sessions=10,
        purge_minutes=int(preregistration["purge_embargo_minutes"]),
        embargo_minutes=int(preregistration["purge_embargo_minutes"]),
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
        record: dict[str, Any] = {
            **identity,
            "variant_id": _variant_id(identity),
            "n_fit": fitting.height,
            "n_validation": validation.height,
            "selected": False,
        }
        try:
            fitted = fit_positive_model(
                fitting,
                feature_columns=features,
                categorical_columns=("asset",),
                target_column="rv30",
                role=role,
                parameters=parameters,
                seed=int(preregistration["seed"]),
                forecast_floor=float(preregistration["forecast_floor"]),
            )
            predictions = fitted.predict(validation)
            validation_qlike = regression_metrics(
                validation["rv30"].to_numpy(),
                predictions,
                floor=float(preregistration["forecast_floor"]),
            )["qlike"]
            record.update(
                {
                    "status": "RUN",
                    "validation_qlike": validation_qlike,
                    "failure_reason": None,
                }
            )
            successful.append(
                (
                    validation_qlike,
                    json.dumps(parameters, sort_keys=True),
                    parameters,
                )
            )
        except Exception as error:
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
            f"PHASE5_NO_SUCCESSFUL_TUNING_VARIANT:{fold.fold}:{information_set}:{role}"
        )
    selected = min(successful, key=lambda row: (row[0], row[1]))[2]
    selected_id = _variant_id(
        {
            "fold": fold.fold,
            "information_set": information_set,
            "model_role": role,
            "parameters": selected,
        }
    )
    for record in records:
        record["selected"] = record["variant_id"] == selected_id
    return selected, records


def _forecast_block(
    training: pl.DataFrame,
    testing: pl.DataFrame,
    *,
    fold: FoldDefinition,
    information_set: str,
    features: Sequence[str],
    role: str,
    parameters: Mapping[str, float | int],
    preregistration: Mapping[str, Any],
) -> pl.DataFrame:
    fitted = fit_positive_model(
        training,
        feature_columns=features,
        categorical_columns=("asset",),
        target_column="rv30",
        role=role,
        parameters=parameters,
        seed=int(preregistration["seed"]),
        forecast_floor=float(preregistration["forecast_floor"]),
    )
    predictions = fitted.predict(testing)
    target = np.asarray(testing["rv30"].to_numpy(), dtype=np.float64)
    errors = target - predictions
    return testing.select(
        "origin_id",
        "asset",
        "session_date",
        "forecast_origin_utc",
        "rv30",
    ).with_columns(
        pl.lit(fold.fold).alias("fold"),
        pl.lit(role).alias("model_role"),
        pl.lit(information_set).alias("information_set"),
        pl.Series("forecast", predictions),
        pl.Series(
            "qlike_loss",
            qlike_losses(
                target,
                predictions,
                floor=float(preregistration["forecast_floor"]),
            ),
        ),
        pl.Series("absolute_error", np.abs(errors)),
        pl.Series("squared_error", np.square(errors)),
        pl.lit(json.dumps(parameters, sort_keys=True)).alias("selected_parameters"),
        pl.lit(canonical_sha256({"features": list(features)})).alias("feature_schema_sha256"),
    )


def _metrics(forecasts: pl.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for role in MODEL_ROLES:
        for information_set in INFORMATION_SETS:
            subset = forecasts.filter(
                (pl.col("model_role") == role) & (pl.col("information_set") == information_set)
            )
            values = regression_metrics(
                subset["rv30"].to_numpy(),
                subset["forecast"].to_numpy(),
            )
            rows.append(
                {
                    "model_role": role,
                    "information_set": information_set,
                    "observations": subset.height,
                    **values,
                }
            )
    return rows


def _contrast(
    forecasts: pl.DataFrame,
    *,
    role: str,
    name: str,
    baseline: str,
    expanded: str,
    preregistration: Mapping[str, Any],
) -> dict[str, Any]:
    keys = ["origin_id", "asset", "session_date", "fold"]
    left = forecasts.filter(
        (pl.col("model_role") == role) & (pl.col("information_set") == baseline)
    ).select(
        *keys,
        pl.col("qlike_loss").alias("baseline_loss"),
    )
    right = forecasts.filter(
        (pl.col("model_role") == role) & (pl.col("information_set") == expanded)
    ).select(
        *keys,
        pl.col("qlike_loss").alias("expanded_loss"),
    )
    paired = left.join(right, on=keys, how="inner").with_columns(
        (pl.col("baseline_loss") - pl.col("expanded_loss")).alias("loss_difference")
    )
    if paired.height != left.height or paired.height != right.height:
        raise ValueError(f"PHASE5_UNPAIRED_CONTRAST:{role}:{name}")
    inference = paired_day_bootstrap(
        paired,
        repetitions=int(preregistration["inference"]["bootstrap_repetitions"]),
        seed=int(preregistration["seed"]),
    )
    estimate = float(inference["estimate"])
    return {
        "model_role": role,
        "contrast": name,
        "definition": f"QLIKE({baseline})-QLIKE({expanded})",
        "positive_direction": "expanded_information_set_better",
        "result_sign": ("POSITIVE" if estimate > 0 else "NEGATIVE" if estimate < 0 else "ZERO"),
        "baseline_mean_qlike": float(np.asarray(paired["baseline_loss"].to_numpy()).mean()),
        "expanded_mean_qlike": float(np.asarray(paired["expanded_loss"].to_numpy()).mean()),
        "p_value_raw": float(inference["p_value_two_sided"]),
        **inference,
    }


def _timing_variants() -> list[dict[str, Any]]:
    return [
        {
            "variant_id": "FMP_DELAY_1_MINUTE",
            "status": "RUN",
            "role": "PRIMARY",
        },
        {
            "variant_id": "FMP_DELAY_2_MINUTES",
            "status": "NOT_RUN_PREREGISTERED",
            "role": "T193_STABILITY",
        },
        {
            "variant_id": "B2_DELAY_60_SECONDS",
            "status": "RUN",
            "role": "PRIMARY",
        },
        {
            "variant_id": "B2_DELAY_120_SECONDS",
            "status": "NOT_RUN_PREREGISTERED",
            "role": "T193_STABILITY",
        },
        {
            "variant_id": "B2_DELAY_300_SECONDS",
            "status": "NOT_RUN_PREREGISTERED",
            "role": "T193_STABILITY",
        },
    ]


def _select_holdout_parameters(
    tuning_variants: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    candidates: dict[
        tuple[str, str, str],
        list[tuple[float, int]],
    ] = {}
    parameters_by_key: dict[
        tuple[str, str, str],
        Mapping[str, float | int],
    ] = {}
    for row in tuning_variants:
        if row["status"] != "RUN":
            continue
        parameters = row["parameters"]
        serialized = json.dumps(parameters, sort_keys=True)
        key = (
            str(row["information_set"]),
            str(row["model_role"]),
            serialized,
        )
        candidates.setdefault(key, []).append(
            (float(row["validation_qlike"]), int(row["n_validation"]))
        )
        parameters_by_key[key] = parameters

    ledger: list[dict[str, Any]] = []
    selected: list[dict[str, Any]] = []
    for information_set in INFORMATION_SETS:
        for role in MODEL_ROLES:
            eligible: list[tuple[float, str, tuple[str, str, str]]] = []
            for key, scores in candidates.items():
                if key[:2] != (information_set, role):
                    continue
                if len(scores) != 4:
                    raise ValueError(f"PHASE5_HOLDOUT_TUNING_FOLD_COUNT:{information_set}:{role}")
                total_rows = sum(count for _, count in scores)
                weighted_qlike = (
                    math.fsum(sorted(score * count for score, count in scores)) / total_rows
                )
                eligible.append((weighted_qlike, key[2], key))
            if not eligible:
                raise ValueError(f"PHASE5_HOLDOUT_TUNING_EMPTY:{information_set}:{role}")
            winning_key = min(eligible, key=lambda row: (row[0], row[1]))[2]
            for weighted_qlike, _, key in sorted(
                eligible,
                key=lambda row: row[1],
            ):
                entry = {
                    "variant_id": _variant_id(
                        {
                            "information_set": information_set,
                            "model_role": role,
                            "parameters": parameters_by_key[key],
                            "purpose": "FINAL_HOLDOUT_METHOD",
                        }
                    ),
                    "information_set": information_set,
                    "model_role": role,
                    "parameters": parameters_by_key[key],
                    "development_inner_fold_count": 4,
                    "weighted_validation_qlike": weighted_qlike,
                    "selected": key == winning_key,
                    "status": "RUN",
                }
                ledger.append(entry)
                if key == winning_key:
                    selected.append(
                        {
                            "information_set": information_set,
                            "model_role": role,
                            "parameters": parameters_by_key[key],
                            "selection_basis": (
                                "WEIGHTED_MEAN_OF_FOUR_DEVELOPMENT_INNER_VALIDATION_QLIKE_VALUES"
                            ),
                        }
                    )
    if len(selected) != len(INFORMATION_SETS) * len(MODEL_ROLES):
        raise ValueError("PHASE5_HOLDOUT_METHOD_SELECTION_INCOMPLETE")
    return selected, ledger


def _validate_inputs(
    panel: pl.DataFrame,
    preregistration: Mapping[str, Any],
    quality: Mapping[str, Any],
) -> pl.DataFrame:
    unsigned = {key: value for key, value in preregistration.items() if key != "manifest_sha256"}
    if (
        preregistration.get("status") != "FROZEN_BEFORE_MODEL_OR_QLIKE"
        or preregistration.get("manifest_sha256") != canonical_sha256(unsigned)
        or preregistration.get("holdout_reads") != 0
    ):
        raise ValueError("PHASE5_PREREGISTRATION_INVALID")
    selected_assets = quality.get("selected_assets")
    if (
        quality.get("status") != "PASS"
        or not isinstance(selected_assets, list)
        or not 4 <= len(selected_assets) <= 6
        or quality.get("selection_uses_predictive_outcomes") is not False
    ):
        raise ValueError("PHASE5_ASSET_QUALITY_FREEZE_INVALID")
    development = panel.filter(pl.col("asset").is_in(selected_assets))
    holdout = set(preregistration["holdout_sessions"])
    if (
        development.height == 0
        or development["origin_id"].n_unique() != development.height
        or set(development["session_date"]) & holdout
        or development.filter(~pl.col("common_complete")).height
        or development.select(
            pl.any_horizontal(
                [
                    ~pl.col(column).cast(pl.Float64).is_finite()
                    for column in INFORMATION_SETS["B2"][1:]
                ]
            ).any()
        ).item()
    ):
        raise ValueError("PHASE5_DEVELOPMENT_INPUT_INVALID")
    return development


def _validate_stability_inputs(
    development: pl.DataFrame,
    quality: Mapping[str, Any],
) -> dict[str, Any]:
    manifest = _read_json(STABILITY_INPUT_MANIFEST_PATH)
    validation = _read_json(STABILITY_VALIDATION_PATH)
    unsigned = {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    validation_unsigned = {
        key: value for key, value in validation.items() if key != "manifest_sha256"
    }
    required_columns = {
        "origin_id",
        *(
            b2_sensitivity_column(feature, delay)
            for delay in (120, 300)
            for feature in B2_FEATURE_NAMES
        ),
    }
    schema = set(pl.read_parquet_schema(STABILITY_INPUT_PATH))
    sidecar_ids = pl.read_parquet(STABILITY_INPUT_PATH, columns=["origin_id"])
    if (
        manifest.get("status") != "PASS_TARGET_BLIND_STABILITY_INPUTS"
        or manifest.get("manifest_sha256") != canonical_sha256(unsigned)
        or manifest.get("origin_count") != development.height
        or manifest.get("selected_assets") != sorted(quality["selected_assets"])
        or manifest.get("delays_seconds") != [120, 300]
        or manifest.get("target_columns_read") != []
        or manifest.get("provider_requests") != 0
        or manifest.get("output", {}).get("sha256") != _sha256_file(STABILITY_INPUT_PATH)
        or validation.get("status") != "PASS"
        or validation.get("manifest_sha256") != canonical_sha256(validation_unsigned)
        or validation.get("holdout_reads") != 0
        or validation.get("provider_requests") != 0
        or validation.get("hashes", {}).get(
            "development_stability_inputs_80d.parquet"
        )
        != _sha256_file(STABILITY_INPUT_PATH)
        or any(
            row.get("maximum_absolute_feature_difference") != 0.0
            for row in validation.get("retained_phase4b_crosscheck", ())
        )
        or not required_columns <= schema
        or any(
            token in column.lower()
            for column in schema
            for token in ("rv30", "qlike", "forecast", "loss")
        )
        or sidecar_ids.height != development.height
        or sidecar_ids["origin_id"].n_unique() != sidecar_ids.height
        or set(sidecar_ids["origin_id"]) != set(development["origin_id"])
    ):
        raise ValueError("PHASE5_STABILITY_INPUTS_INVALID")
    return manifest


def main() -> None:
    """Fit development folds, retain all outcomes and freeze the method."""
    preregistration = _read_json(PREREGISTRATION_PATH)
    quality = _read_json(QUALITY_PATH)
    panel = _validate_inputs(
        pl.read_parquet(PANEL_PATH),
        preregistration,
        quality,
    )
    _validate_stability_inputs(panel, quality)
    folds = parse_fold_definitions(preregistration["outer_folds"])
    forecast_parts: list[pl.DataFrame] = []
    tuning_variants: list[dict[str, Any]] = []
    selections: list[dict[str, Any]] = []

    for fold in folds:
        training, testing = split_expanding_fold(
            panel,
            fold,
            purge_minutes=int(preregistration["purge_embargo_minutes"]),
            embargo_minutes=int(preregistration["purge_embargo_minutes"]),
        )
        for information_set, features in INFORMATION_SETS.items():
            for role in MODEL_ROLES:
                selected, records = _select_parameters(
                    training,
                    fold=fold,
                    information_set=information_set,
                    features=features,
                    role=role,
                    preregistration=preregistration,
                )
                tuning_variants.extend(records)
                selections.append(
                    {
                        "fold": fold.fold,
                        "information_set": information_set,
                        "model_role": role,
                        "parameters": selected,
                    }
                )
                forecast_parts.append(
                    _forecast_block(
                        training,
                        testing,
                        fold=fold,
                        information_set=information_set,
                        features=features,
                        role=role,
                        parameters=selected,
                        preregistration=preregistration,
                    )
                )
                print(
                    f"fold={fold.fold} set={information_set} role={role} PASS",
                    flush=True,
                )

    forecasts = pl.concat(forecast_parts).sort(
        ["fold", "model_role", "information_set", "origin_id"]
    )
    if forecasts.group_by(["origin_id", "model_role"]).agg(
        pl.col("information_set").n_unique().alias("sets")
    ).filter(pl.col("sets") != 3).height or set(forecasts["session_date"]) & set(
        preregistration["holdout_sessions"]
    ):
        raise ValueError("PHASE5_FORECAST_PAIRING_OR_HOLDOUT_FAILURE")
    forecasts.write_parquet(FORECASTS_PATH, compression="zstd")

    metric_rows = _metrics(forecasts)
    holdout_parameters, holdout_parameter_ledger = _select_holdout_parameters(tuning_variants)
    contrasts = [
        _contrast(
            forecasts,
            role=role,
            name=name,
            baseline=baseline,
            expanded=expanded,
            preregistration=preregistration,
        )
        for role in MODEL_ROLES
        for name, baseline, expanded in (
            ("delta_b1", "B0", "B1a"),
            ("delta_b2", "B1a", "B2"),
        )
    ]
    gamma_p_values = {
        row["contrast"]: row["p_value_raw"]
        for row in contrasts
        if row["model_role"] == "gamma_glm_confirmatory"
    }
    adjusted = holm_adjust(gamma_p_values)
    for row in contrasts:
        row["p_value_holm"] = (
            adjusted[row["contrast"]] if row["model_role"] == "gamma_glm_confirmatory" else None
        )

    results: dict[str, Any] = {
        "schema_version": "phase5-development-results-1.0",
        "status": "PASS_DEVELOPMENT_ONLY",
        "holdout_reads": 0,
        "evaluated_origin_count": forecasts["origin_id"].n_unique(),
        "forecast_row_count": forecasts.height,
        "selected_assets": quality["selected_assets"],
        "outer_fold_count": len(folds),
        "information_sets": list(INFORMATION_SETS),
        "model_roles": list(MODEL_ROLES),
        "bootstrap_repetitions": preregistration["inference"]["bootstrap_repetitions"],
        "metrics": metric_rows,
        "contrasts": contrasts,
        "selected_hyperparameters": selections,
        "holdout_hyperparameters": holdout_parameters,
        "forecast_sha256": _sha256_file(FORECASTS_PATH),
        "preregistration_manifest_sha256": preregistration["manifest_sha256"],
        "outcome_reporting": preregistration["outcome_reporting"],
    }
    results["manifest_sha256"] = canonical_sha256(results)
    _write_json(RESULTS_PATH, results)

    ledger: dict[str, Any] = {
        "schema_version": "phase5-variant-ledger-1.0",
        "holdout_reads": 0,
        "outcome_reporting": preregistration["outcome_reporting"],
        "tuning_variants": tuning_variants,
        "holdout_method_candidates": holdout_parameter_ledger,
        "holdout_method_selection": holdout_parameters,
        "development_variants": metric_rows,
        "contrast_results": contrasts,
        "timing_variants": _timing_variants(),
    }
    ledger["manifest_sha256"] = canonical_sha256(ledger)
    _write_json(LEDGER_PATH, ledger)

    volatility_lower, volatility_upper = development_volatility_cutpoints(panel)
    source_files = tuple(ROOT / path for path in FROZEN_PHASE5_SOURCE_PATHS)
    method_freeze: dict[str, Any] = {
        "schema_version": "phase5-method-freeze-1.0",
        "status": "FROZEN_AFTER_DEVELOPMENT_BEFORE_HOLDOUT",
        "holdout_reads": 0,
        "selected_assets": quality["selected_assets"],
        "information_sets": {name: list(features) for name, features in INFORMATION_SETS.items()},
        "folds": preregistration["outer_folds"],
        "selected_hyperparameters": selections,
        "holdout_hyperparameters": holdout_parameters,
        "seed": preregistration["seed"],
        "forecast_floor": preregistration["forecast_floor"],
        "timing": preregistration["timing"],
        "stability_definition": {
            "session_tercile_upper_bounds": list(SESSION_TERCILE_BOUNDS),
            "volatility_regime": {
                "source": "b0_rv_30m_lag",
                "quantiles": [1 / 3, 2 / 3],
                "interpolation": "linear",
                "lower_cutpoint": volatility_lower,
                "upper_cutpoint": volatility_upper,
                "fit_scope": "SELECTED_ASSET_DEVELOPMENT_PANEL_ONLY",
            },
            "fmp_delay_minutes": list(FMP_DELAYS_MINUTES),
            "b2_delay_seconds": list(B2_DELAYS_SECONDS),
            "sensitivity_hyperparameters": "FROZEN_PRIMARY_WITHOUT_RETUNING",
            "confirmatory_role": "gamma_glm_confirmatory",
            "confirmatory_family_expanded": False,
            "operationalization_timing": "AFTER_DEVELOPMENT_BEFORE_HOLDOUT",
            "preregistration_scope": (
                "STABILITY_DIMENSIONS_PREDECLARED;"
                "MATERIAL_REVERSAL_THRESHOLD_PRE_HOLDOUT_CLARIFICATION"
            ),
            "systematic_reversal_rule": {
                "minimum_sessions_per_stratum": 2,
                "material_negative_definition": "BOOTSTRAP_CI_HIGH_STRICTLY_BELOW_ZERO",
                "minimum_material_negative_strata": 2,
                "minimum_negative_origin_share": 0.5,
                "timing_variant_rule": "ANY_NONPRIMARY_VARIANT_WITH_CI_HIGH_STRICTLY_BELOW_ZERO",
            },
        },
        "inference": preregistration["inference"],
        "outcome_reporting": preregistration["outcome_reporting"],
        "package_versions": {
            package: version(package)
            for package in (
                "lightgbm",
                "numpy",
                "polars",
                "scikit-learn",
            )
        },
        "source_code_hashes": {
            str(path.relative_to(ROOT)).replace("\\", "/"): source_sha256(path)
            for path in source_files
        },
        "contract_hashes": {
            "specs/001-pit-options-rv30/contracts/phase5-stability-results.schema.json": (
                _sha256_file(
                    ROOT / "specs/001-pit-options-rv30/contracts/"
                    "phase5-stability-results.schema.json"
                )
            )
        },
        "input_hashes": {
            "common_development_80d.parquet": _sha256_file(PANEL_PATH),
            "development_stability_inputs_80d.parquet": _sha256_file(STABILITY_INPUT_PATH),
            "development_stability_input_manifest.json": _sha256_file(
                STABILITY_INPUT_MANIFEST_PATH
            ),
            "development_stability_validation.json": _sha256_file(
                STABILITY_VALIDATION_PATH
            ),
            "development_panel_quality.json": _sha256_file(QUALITY_PATH),
            "development_source_manifest_80d.json": _sha256_file(SOURCE_MANIFEST_PATH),
            "preregistration.json": _sha256_file(PREREGISTRATION_PATH),
            "uv.lock": _sha256_file(ROOT / "uv.lock"),
        },
        "output_hashes": {
            "development_forecasts.parquet": _sha256_file(FORECASTS_PATH),
            "development_results.json": _sha256_file(RESULTS_PATH),
            "variant_ledger.json": _sha256_file(LEDGER_PATH),
        },
    }
    method_freeze["manifest_sha256"] = canonical_sha256(method_freeze)
    freeze_json(METHOD_FREEZE_PATH, method_freeze)
    print(
        json.dumps(
            {
                "status": results["status"],
                "evaluated_origins": results["evaluated_origin_count"],
                "forecast_rows": results["forecast_row_count"],
                "holdout_reads": 0,
                "results_manifest_sha256": results["manifest_sha256"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
