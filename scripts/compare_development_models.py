"""Compare preregistered candidate models on the frozen Phase 5 development panel."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from mds650.development_models import (
    B2_FEATURES,
    INFORMATION_SETS,
    candidate_parameter_grid,
    fit_development_candidate,
)
from mds650.metrics import holm_adjust, paired_day_bootstrap, qlike_losses, regression_metrics
from mds650.phase6_evaluation import estimate_training_mde
from mds650.study_design import canonical_sha256
from mds650.temporal_validation import (
    parse_fold_definitions,
    split_expanding_fold,
    split_inner_validation,
)

ROOT = Path(__file__).resolve().parents[1]
PHASE5 = ROOT / "artifacts" / "phase5"
METHOD = ROOT / "artifacts" / "methodology"
PANEL_PATH = PHASE5 / "common_development_80d.parquet"
FROZEN_FORECAST_PATH = PHASE5 / "development_forecasts.parquet"
PREREG_PATH = PHASE5 / "preregistration.json"
FORECAST_PATH = METHOD / "development_model_comparison.parquet"
RESULT_PATH = METHOD / "development_model_comparison.json"
CONTRAST_PATH = METHOD / "development_contrasts_v2.json"
STABILITY_PATH = METHOD / "development_stability_v2.parquet"
VARIANT_LEDGER_PATH = METHOD / "development_model_variant_ledger.json"
SEED = 650
BOOTSTRAP_REPETITIONS = 10_000
# ponytail: one registered linear challenger is sufficient for this gate;
# Elastic Net remains implemented and ledger-ready without multiplying runtime.
MODEL_NAMES = ("persistence", "har_rv", "ridge", "gamma_glm", "lightgbm")
STABILITY_BOOTSTRAP_REPETITIONS = 2_000
ASSETS = ("AAPL", "AMZN", "META", "MSFT", "NVDA", "TSLA")


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON_OBJECT_REQUIRED:{path.name}")
    return payload


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _variant_id(payload: Mapping[str, Any]) -> str:
    return canonical_sha256(payload)[:20]


def _select_parameters(
    training: pl.DataFrame,
    *,
    information_set: str,
    model_name: str,
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
    for parameters in candidate_parameter_grid(model_name):
        identity = {
            "information_set": information_set,
            "model_name": model_name,
            "parameters": parameters,
        }
        record: dict[str, Any] = {
            **identity,
            "variant_id": _variant_id(identity),
            "selected": False,
            "n_fit": fitting.height,
            "n_validation": validation.height,
        }
        try:
            fitted = fit_development_candidate(
                fitting,
                feature_columns=INFORMATION_SETS[information_set],
                model_name=model_name,
                parameters=parameters,
                seed=SEED,
            )
            forecast = fitted.predict(validation)
            score = regression_metrics(validation["rv30"].to_numpy(), forecast)["qlike"]
            record.update({"status": "RUN", "validation_qlike": score, "failure_reason": None})
            successful.append((score, json.dumps(parameters, sort_keys=True), parameters))
        except Exception as error:  # noqa: BLE001 - retain every failed variant reason
            record.update(
                {
                    "status": "FAILED_WITH_REASON",
                    "validation_qlike": None,
                    "failure_reason": f"{type(error).__name__}:{error}",
                }
            )
        records.append(record)
    if not successful:
        raise RuntimeError(f"NO_SUCCESSFUL_DEVELOPMENT_VARIANT:{information_set}:{model_name}")
    selected = min(successful, key=lambda row: (row[0], row[1]))[2]
    selected_id = _variant_id(
        {
            "information_set": information_set,
            "model_name": model_name,
            "parameters": selected,
        }
    )
    for record in records:
        record["selected"] = record["variant_id"] == selected_id
    return selected, records


def _session_tercile() -> pl.Expr:
    minute = pl.col("b0_session_minute")
    return (
        pl.when(minute <= 130)
        .then(pl.lit("first"))
        .when(minute <= 260)
        .then(pl.lit("middle"))
        .otherwise(pl.lit("last"))
    )


def _with_regime(
    training: pl.DataFrame, testing: pl.DataFrame
) -> tuple[pl.DataFrame, dict[str, float]]:
    lower_raw = training["b0_rv_30m_lag"].quantile(1 / 3)
    upper_raw = training["b0_rv_30m_lag"].quantile(2 / 3)
    if not isinstance(lower_raw, (int, float)) or not isinstance(upper_raw, (int, float)):
        raise RuntimeError("DEVELOPMENT_VOLATILITY_CUTPOINTS_MISSING")
    lower = float(lower_raw)
    upper = float(upper_raw)
    if not np.isfinite([lower, upper]).all() or lower >= upper:
        raise RuntimeError("DEVELOPMENT_VOLATILITY_CUTPOINTS_INVALID")
    classified = testing.with_columns(
        pl.when(pl.col("b0_rv_30m_lag") <= lower)
        .then(pl.lit("low"))
        .when(pl.col("b0_rv_30m_lag") <= upper)
        .then(pl.lit("normal"))
        .otherwise(pl.lit("high"))
        .alias("volatility_regime")
    )
    return classified, {"lower": lower, "upper": upper}


def _forecast_block(
    training: pl.DataFrame,
    testing: pl.DataFrame,
    *,
    fold: int,
    information_set: str,
    model_name: str,
    parameters: Mapping[str, float | int],
) -> pl.DataFrame:
    fitted = fit_development_candidate(
        training,
        feature_columns=INFORMATION_SETS[information_set],
        model_name=model_name,
        parameters=parameters,
        seed=SEED,
    )
    forecast = fitted.predict(testing)
    target = np.asarray(testing["rv30"].to_numpy(), dtype=np.float64)
    errors = target - forecast
    return testing.select(
        "origin_id",
        "asset",
        "session_date",
        "forecast_origin_utc",
        "rv30",
        "b0_session_minute",
        "volatility_regime",
    ).with_columns(
        pl.lit(fold).alias("fold"),
        pl.lit(model_name).alias("model_name"),
        pl.lit(information_set).alias("information_set"),
        pl.Series("forecast", forecast),
        pl.Series("qlike_loss", qlike_losses(target, forecast)),
        pl.Series("absolute_error", np.abs(errors)),
        pl.Series("squared_error", np.square(errors)),
        pl.lit(json.dumps(dict(parameters), sort_keys=True)).alias("selected_parameters"),
        _session_tercile().alias("session_tercile"),
    )


def _required_mean(frame: pl.DataFrame, column: str) -> float:
    """Return a numeric mean and reject empty or malformed contrast columns."""
    value = frame[column].mean()
    if not isinstance(value, (int, float)):
        raise RuntimeError(f"DEVELOPMENT_CONTRAST_MEAN_MISSING:{column}")
    return float(value)


def _contrast(
    frame: pl.DataFrame,
    *,
    model_name: str,
    baseline: str,
    expanded: str,
    repetitions: int = BOOTSTRAP_REPETITIONS,
) -> dict[str, Any]:
    keys = ["origin_id", "asset", "session_date", "fold"]
    left = frame.filter(
        (pl.col("model_name") == model_name) & (pl.col("information_set") == baseline)
    ).select(*keys, pl.col("qlike_loss").alias("baseline_loss"))
    right = frame.filter(
        (pl.col("model_name") == model_name) & (pl.col("information_set") == expanded)
    ).select(*keys, pl.col("qlike_loss").alias("expanded_loss"))
    paired = left.join(right, on=keys, how="inner", validate="1:1").with_columns(
        (pl.col("baseline_loss") - pl.col("expanded_loss")).alias("loss_difference")
    )
    if paired.height != left.height or paired.height != right.height:
        raise RuntimeError(f"DEVELOPMENT_UNPAIRED_CONTRAST:{model_name}:{baseline}:{expanded}")
    inference = paired_day_bootstrap(paired, repetitions=repetitions, seed=SEED)
    estimate = float(inference["estimate"])
    return {
        "model_name": model_name,
        "contrast": f"delta_{baseline.lower()}_{expanded.lower()}",
        "definition": f"QLIKE({baseline})-QLIKE({expanded})",
        "positive_direction": "expanded_information_set_better",
        "result_sign": "POSITIVE" if estimate > 0 else "NEGATIVE" if estimate < 0 else "ZERO",
        "baseline_mean_qlike": _required_mean(paired, "baseline_loss"),
        "expanded_mean_qlike": _required_mean(paired, "expanded_loss"),
        **inference,
    }


def _stability(
    frame: pl.DataFrame, *, model_name: str, baseline: str, expanded: str
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for group_type, group_column in (
        ("asset", "asset"),
        ("session_tercile", "session_tercile"),
        ("volatility_regime", "volatility_regime"),
    ):
        for group in frame[group_column].unique().sort().to_list():
            subset = frame.filter(pl.col(group_column) == group)
            if subset.filter(pl.col("model_name") == model_name).is_empty():
                continue
            try:
                result = _contrast(
                    subset,
                    model_name=model_name,
                    baseline=baseline,
                    expanded=expanded,
                    repetitions=STABILITY_BOOTSTRAP_REPETITIONS,
                )
            except (RuntimeError, ValueError):
                continue
            rows.append({"group_type": group_type, "group": str(group), **result})
    return rows


def _daily_effects(
    frame: pl.DataFrame, *, model_name: str, baseline: str, expanded: str
) -> list[float]:
    keys = ["origin_id", "asset", "session_date", "fold"]
    left = frame.filter(
        (pl.col("model_name") == model_name) & (pl.col("information_set") == baseline)
    ).select(*keys, pl.col("qlike_loss").alias("left"))
    right = frame.filter(
        (pl.col("model_name") == model_name) & (pl.col("information_set") == expanded)
    ).select(*keys, pl.col("qlike_loss").alias("right"))
    paired = left.join(right, on=keys, how="inner").with_columns(
        (pl.col("left") - pl.col("right")).alias("effect")
    )
    return [
        float(row["effect"])
        for row in paired.group_by("session_date")
        .agg(pl.col("effect").mean())
        .sort("session_date")
        .iter_rows(named=True)
    ]


def main() -> None:
    preregistration = _read_json(PREREG_PATH)
    panel = (
        pl.read_parquet(PANEL_PATH)
        .filter(pl.col("asset").is_in(ASSETS) & pl.col("common_complete"))
        .sort("forecast_origin_utc")
    )
    required = {"rv30", "origin_id", "asset", "session_date", "forecast_origin_utc", *B2_FEATURES}
    missing = required - set(panel.columns)
    if missing or panel.is_empty():
        raise RuntimeError(f"DEVELOPMENT_PANEL_INVALID:{','.join(sorted(missing))}")
    numeric = [name for name in B2_FEATURES if name != "asset"]
    if (
        not np.isfinite(panel.select(numeric).to_numpy()).all()
        or not np.isfinite(panel["rv30"].to_numpy()).all()
    ):
        raise RuntimeError("DEVELOPMENT_PANEL_NONFINITE")
    folds = parse_fold_definitions(preregistration["outer_folds"])
    forecast_parts: list[pl.DataFrame] = []
    regime_parts: list[pl.DataFrame] = []
    variants: list[dict[str, Any]] = []
    regime_cutpoints: list[dict[str, Any]] = []
    for fold in folds:
        training, testing = split_expanding_fold(
            panel,
            fold,
            purge_minutes=int(preregistration["purge_embargo_minutes"]),
            embargo_minutes=int(preregistration["purge_embargo_minutes"]),
        )
        testing, cutpoints = _with_regime(training, testing)
        regime_cutpoints.append({"fold": fold.fold, **cutpoints})
        regime_parts.append(testing.select("origin_id", "b0_session_minute", "volatility_regime"))
        for information_set in INFORMATION_SETS:
            for model_name in ("persistence", "har_rv", "ridge"):
                selected, records = _select_parameters(
                    training,
                    information_set=information_set,
                    model_name=model_name,
                    preregistration=preregistration,
                )
                variants.extend([{**record, "fold": fold.fold} for record in records])
                forecast_parts.append(
                    _forecast_block(
                        training,
                        testing,
                        fold=fold.fold,
                        information_set=information_set,
                        model_name=model_name,
                        parameters=selected,
                    )
                )
    regime_map = pl.concat(regime_parts).unique("origin_id")
    frozen = (
        pl.read_parquet(FROZEN_FORECAST_PATH)
        .filter(pl.col("asset").is_in(ASSETS))
        .with_columns(
            pl.when(pl.col("model_role") == "gamma_glm_confirmatory")
            .then(pl.lit("gamma_glm"))
            .otherwise(pl.lit("lightgbm"))
            .alias("model_name")
        )
        .join(regime_map, on="origin_id", how="left", validate="m:1")
        .with_columns(_session_tercile().alias("session_tercile"))
        .select(
            "origin_id",
            "asset",
            "session_date",
            "forecast_origin_utc",
            "rv30",
            "b0_session_minute",
            "volatility_regime",
            "fold",
            "model_name",
            "information_set",
            "forecast",
            "qlike_loss",
            "absolute_error",
            "squared_error",
            "selected_parameters",
            "session_tercile",
        )
    )
    for fold in folds:
        for information_set in INFORMATION_SETS:
            for model_name in ("gamma_glm", "lightgbm"):
                variants.append(
                    {
                        "fold": fold.fold,
                        "information_set": information_set,
                        "model_name": model_name,
                        "variant_id": f"REUSED_PHASE5_{model_name}_{information_set}_{fold.fold}",
                        "status": "REUSED_FROZEN_PHASE5_DEVELOPMENT",
                        "selected": True,
                        "source_sha256": _sha256(FROZEN_FORECAST_PATH),
                    }
                )
    variants.append(
        {
            "fold": None,
            "information_set": None,
            "model_name": "elastic_net",
            "variant_id": "REGISTERED_NOT_RUN",
            "status": "REGISTERED_NOT_RUN_RUNTIME_BUDGET",
            "selected": False,
            "reason": (
                "Ridge is the preregistered linear challenger for this development "
                "gate; Elastic Net remains available for a separately registered extension."
            ),
        }
    )
    forecasts = pl.concat([pl.concat(forecast_parts), frozen]).sort(
        ["model_name", "information_set", "origin_id"]
    )
    if forecasts["origin_id"].n_unique() == 0:
        raise RuntimeError("DEVELOPMENT_FORECASTS_EMPTY")
    expected = forecasts["origin_id"].n_unique()
    if forecasts.height != expected * len(MODEL_NAMES) * len(INFORMATION_SETS):
        raise RuntimeError("DEVELOPMENT_FORECAST_PAIRING_FAILURE")
    METHOD.mkdir(parents=True, exist_ok=True)
    forecasts.write_parquet(FORECAST_PATH, compression="zstd")
    metrics: list[dict[str, Any]] = []
    for model_name in MODEL_NAMES:
        for information_set in INFORMATION_SETS:
            subset = forecasts.filter(
                (pl.col("model_name") == model_name)
                & (pl.col("information_set") == information_set)
            )
            metrics.append(
                {
                    "model_name": model_name,
                    "information_set": information_set,
                    "observations": subset.height,
                    **regression_metrics(subset["rv30"].to_numpy(), subset["forecast"].to_numpy()),
                }
            )
    contrasts: list[dict[str, Any]] = []
    stability: list[dict[str, Any]] = []
    for model_name in MODEL_NAMES:
        for baseline, expanded, label in (("B0", "B1a", "delta_b1"), ("B1a", "B2", "delta_b2")):
            result = _contrast(
                forecasts, model_name=model_name, baseline=baseline, expanded=expanded
            )
            result["contrast"] = label
            contrasts.append(result)
            stability.extend(
                _stability(forecasts, model_name=model_name, baseline=baseline, expanded=expanded)
            )
    daily_mde: dict[str, float] = {}
    for model_name in MODEL_NAMES:
        for baseline, expanded, label in (("B0", "B1a", "delta_b1"), ("B1a", "B2", "delta_b2")):
            effects = _daily_effects(
                forecasts, model_name=model_name, baseline=baseline, expanded=expanded
            )
            if len(effects) >= 2 and np.std(effects, ddof=1) > 0:
                daily_mde[f"{model_name}:{label}"] = round(
                    estimate_training_mde(effects, draws=BOOTSTRAP_REPETITIONS, seed=SEED),
                    12,
                )
    holm: dict[str, float] = {}
    for model_name in MODEL_NAMES:
        raw_p = {
            row["contrast"]: float(row["p_value_two_sided"])
            for row in contrasts
            if row["model_name"] == model_name
        }
        holm.update({f"{model_name}:{name}": value for name, value in holm_adjust(raw_p).items()})
    for row in contrasts:
        row["p_value_holm_within_model_family"] = holm[f"{row['model_name']}:{row['contrast']}"]
    retained: list[str] = []
    for model_name in MODEL_NAMES:
        b2 = next(
            row
            for row in contrasts
            if row["model_name"] == model_name and row["contrast"] == "delta_b2"
        )
        if (
            b2["estimate"] > 0
            and b2["ci_low"] > 0
            and b2["p_value_holm_within_model_family"] < 0.05
        ):
            retained.append(model_name)
    result = {
        "schema_version": "development-model-comparison-1.0",
        "status": "PASS_DEVELOPMENT_MODEL_COMPARISON",
        "oos_reads": 0,
        "panel": str(PANEL_PATH.relative_to(ROOT)).replace("\\", "/"),
        "panel_sha256": _sha256(PANEL_PATH),
        "assets": list(ASSETS),
        "information_sets": list(INFORMATION_SETS),
        "models": list(MODEL_NAMES),
        "evaluated_origins": expected,
        "forecast_rows": forecasts.height,
        "metrics": metrics,
        "contrasts": contrasts,
        "retained_b2_candidates_by_development_rule": retained,
        "planning_mde_from_development_outer_folds": daily_mde,
        "variant_ledger_sha256": None,
        "all_variants_retained": True,
        "seed": SEED,
    }
    variant_ledger = {
        "schema_version": "development-model-variant-ledger-1.0",
        "oos_reads": 0,
        "all_variants_retained": True,
        "variants": variants,
        "volatility_regime_cutpoints": regime_cutpoints,
    }
    variant_ledger["manifest_sha256"] = canonical_sha256(variant_ledger)
    VARIANT_LEDGER_PATH.write_text(
        json.dumps(variant_ledger, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    result["variant_ledger_sha256"] = _sha256(VARIANT_LEDGER_PATH)
    RESULT_PATH.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    CONTRAST_PATH.write_text(
        json.dumps(
            {
                "schema_version": "development-contrasts-v2",
                "all_variants_retained": True,
                "oos_reads": 0,
                "contrasts": contrasts,
                "holm": holm,
                "planning_mde": daily_mde,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    if stability:
        pl.DataFrame(stability).write_parquet(STABILITY_PATH, compression="zstd")
    print(
        json.dumps(
            {
                "status": result["status"],
                "origins": expected,
                "forecast_rows": forecasts.height,
                "retained": retained,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
