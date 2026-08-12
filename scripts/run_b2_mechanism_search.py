"""Run the frozen, development-only B2 residual-mechanism search.

This script never opens the sealed independent outcome artifacts.  It uses the
80-session Phase 5 development panel to compare B0/B1/B2 models, fit residual
learners with cross-fitted B1 residuals, and register every primary, placebo and
lagged variant before any fresh blocks are acquired.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any, cast

import numpy as np
import polars as pl

from mds650.development_models import (
    B0_FEATURES,
    B1_FEATURES,
    candidate_parameter_grid,
    fit_development_candidate,
)
from mds650.development_models import (
    B2_FEATURES as FULL_B2_FEATURES,
)
from mds650.mechanism_search import (
    B2_FEATURES,
    MECHANISM_VARIANTS,
    add_predeclared_strata,
    combine_base_and_residual,
    fit_residual_learner,
    lag_b2_one_session,
    permute_residual_target,
)
from mds650.metrics import holm_adjust, paired_day_bootstrap, qlike_losses, regression_metrics
from mds650.study_design import canonical_sha256
from mds650.temporal_validation import (
    parse_fold_definitions,
    purge_and_embargo_training,
    split_expanding_fold,
    split_inner_validation,
)

ROOT = Path(__file__).resolve().parents[1]
PANEL_PATH = ROOT / "artifacts" / "phase5" / "common_development_80d.parquet"
PREREG_PATH = ROOT / "artifacts" / "methodology" / "b2_mechanism_search_preregistration.json"
PHASE5_PREREG_PATH = ROOT / "artifacts" / "phase5" / "preregistration.json"
OUT = ROOT / "artifacts" / "methodology"
FORECAST_PATH = OUT / "b2_mechanism_forecasts.parquet"
RESULT_PATH = OUT / "b2_mechanism_results.json"
LEDGER_PATH = OUT / "b2_mechanism_variant_ledger.json"
STABILITY_PATH = OUT / "b2_mechanism_stability.parquet"
CALIBRATION_PATH = OUT / "b2_mechanism_calibration.csv"
DRIFT_PATH = OUT / "b2_mechanism_drift.csv"
REDUNDANCY_PATH = OUT / "b2_mechanism_redundancy.csv"
INTERACTIONS_PATH = OUT / "b2_mechanism_interactions.csv"
MODEL_CARDS_PATH = ROOT / "docs" / "b2_mechanism_model_cards.md"
AUDIT_DOC_PATH = ROOT / "docs" / "b2_mechanism_audit_v1.md"
SEED = 650
PRIMARY_BOOTSTRAP = 10_000
SECONDARY_BOOTSTRAP = 2_000
FORECAST_FLOOR = 1e-12
MODEL_NAMES = ("gamma_glm", "har_rv", "ridge", "elastic_net", "lightgbm")
ASSETS = ("AAPL", "AMZN", "META", "MSFT", "NVDA", "TSLA")
INFO_SETS = {"B0": tuple(B0_FEATURES), "B1": tuple(B1_FEATURES), "B2": tuple(FULL_B2_FEATURES)}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON_OBJECT_REQUIRED:{path.name}")
    return value


def _select_parameters(
    training: pl.DataFrame,
    *,
    features: Sequence[str],
    model_name: str,
    purge_minutes: int,
) -> tuple[dict[str, float | int], list[dict[str, Any]]]:
    """Select one fixed candidate using only the latest training sessions."""
    fitting, validation = split_inner_validation(
        training,
        validation_sessions=10,
        purge_minutes=purge_minutes,
        embargo_minutes=purge_minutes,
    )
    records: list[dict[str, Any]] = []
    successful: list[tuple[float, str, dict[str, float | int]]] = []
    for parameters in candidate_parameter_grid(model_name):
        identity = {"model_name": model_name, "features": list(features), "parameters": parameters}
        record: dict[str, Any] = {
            **identity,
            "variant_id": canonical_sha256(identity)[:20],
            "selected": False,
            "n_fit": fitting.height,
            "n_validation": validation.height,
        }
        try:
            fitted = fit_development_candidate(
                fitting,
                feature_columns=features,
                model_name=model_name,
                parameters=parameters,
                seed=SEED,
            )
            score = regression_metrics(validation["rv30"].to_numpy(), fitted.predict(validation))[
                "qlike"
            ]
            record.update({"status": "RUN", "validation_qlike": score, "failure_reason": None})
            successful.append((score, json.dumps(parameters, sort_keys=True), parameters))
        except Exception as error:  # noqa: BLE001 - retain every failed grid variant
            record.update(
                {
                    "status": "FAILED_WITH_REASON",
                    "validation_qlike": None,
                    "failure_reason": f"{type(error).__name__}:{error}",
                }
            )
        records.append(record)
    if not successful:
        raise RuntimeError(f"MECHANISM_NO_SUCCESSFUL_VARIANT:{model_name}")
    selected = min(successful, key=lambda row: (row[0], row[1]))[2]
    selected_id = canonical_sha256(
        {"model_name": model_name, "features": list(features), "parameters": selected}
    )[:20]
    for record in records:
        record["selected"] = record["variant_id"] == selected_id
    return selected, records


def _cross_fitted_predictions(
    training: pl.DataFrame,
    *,
    features: Sequence[str],
    model_name: str,
    parameters: Mapping[str, float | int],
    purge_minutes: int,
) -> pl.DataFrame:
    """Generate expanding, purged predictions for residual-target construction."""
    sessions = sorted(str(value) for value in training["session_date"].unique().to_list())
    if len(sessions) <= 20:
        raise RuntimeError("MECHANISM_CROSSFIT_HISTORY_TOO_SHORT")
    eligible = sessions[20:]
    blocks = [
        list(block) for block in np.array_split(np.asarray(eligible, dtype=object), 3) if len(block)
    ]
    parts: list[pl.DataFrame] = []
    for block_sessions in blocks:
        first_session = str(block_sessions[0])
        block = training.filter(pl.col("session_date").is_in(block_sessions))
        prior = training.filter(pl.col("session_date") < first_session)
        if block.is_empty() or prior.is_empty():
            continue
        first_origin_raw = block["forecast_origin_utc"].min()
        if first_origin_raw is None:
            continue
        first_origin = cast(datetime, first_origin_raw)
        fit_frame = purge_and_embargo_training(
            prior,
            first_origin,
            target_horizon_minutes=30,
            purge_minutes=purge_minutes,
            embargo_minutes=purge_minutes,
        )
        fitted = fit_development_candidate(
            fit_frame,
            feature_columns=features,
            model_name=model_name,
            parameters=parameters,
            seed=SEED,
        )
        parts.append(
            block.select("origin_id").with_columns(
                pl.Series("b1_crossfit_prediction", fitted.predict(block))
            )
        )
    if not parts:
        raise RuntimeError("MECHANISM_CROSSFIT_PREDICTIONS_EMPTY")
    return pl.concat(parts, how="vertical").unique("origin_id")


def _forecast_rows(
    frame: pl.DataFrame,
    forecast: Sequence[float] | np.ndarray,
    *,
    fold: int,
    model_name: str,
    information_set: str,
    mechanism_id: str,
    b2_variant: str,
    variant_type: str,
) -> pl.DataFrame:
    target = np.asarray(frame["rv30"].to_numpy(), dtype=np.float64)
    prediction = np.asarray(forecast, dtype=np.float64)
    if prediction.shape != (frame.height,) or not np.isfinite(prediction).all():
        raise RuntimeError("MECHANISM_FORECAST_NONFINITE")
    errors = target - prediction
    return frame.select(
        "origin_id",
        "asset",
        "session_date",
        "b0_session_minute",
        "session_tercile",
        "volatility_regime",
        "rv30",
    ).with_columns(
        pl.lit(fold).alias("fold"),
        pl.lit(model_name).alias("model_name"),
        pl.lit(information_set).alias("information_set"),
        pl.lit(mechanism_id).alias("mechanism_id"),
        pl.lit(b2_variant).alias("b2_variant"),
        pl.lit(variant_type).alias("variant_type"),
        pl.Series("forecast", np.maximum(prediction, FORECAST_FLOOR)),
        pl.Series("qlike_loss", qlike_losses(target, prediction, floor=FORECAST_FLOOR)),
        pl.Series("absolute_error", np.abs(errors)),
        pl.Series("squared_error", np.square(errors)),
    )


def _residual_variant(
    training: pl.DataFrame,
    testing: pl.DataFrame,
    *,
    fold: int,
    model_name: str,
    base_parameters: Mapping[str, float | int],
    mechanism_id: str,
    purge_minutes: int,
    placebo: bool = False,
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Fit a base B1 model and a B2-only correction on cross-fitted residuals."""
    fitted = fit_development_candidate(
        training,
        feature_columns=B1_FEATURES,
        model_name=model_name,
        parameters=base_parameters,
        seed=SEED,
    )
    base_test = fitted.predict(testing)
    crossfit = _cross_fitted_predictions(
        training,
        features=B1_FEATURES,
        model_name=model_name,
        parameters=base_parameters,
        purge_minutes=purge_minutes,
    )
    residual_rows = training.join(crossfit, on="origin_id", how="inner", validate="1:1")
    residual_target = (
        residual_rows["rv30"].to_numpy() - residual_rows["b1_crossfit_prediction"].to_numpy()
    )
    if placebo:
        residual_target = permute_residual_target(residual_target, seed=SEED + fold)
    residual_frame = residual_rows.select(
        [*B2_FEATURES, "asset", "session_tercile", "volatility_regime"]
    )
    learner = fit_residual_learner(
        residual_frame,
        residual_target,
        mechanism_id=mechanism_id,
        seed=SEED,
    )
    correction = learner.predict_correction(
        testing.select([*B2_FEATURES, "asset", "session_tercile", "volatility_regime"])
    )
    corrected = combine_base_and_residual(base_test, correction)
    kind = "placebo" if placebo else "residual"
    baseline = _forecast_rows(
        testing,
        base_test,
        fold=fold,
        model_name=model_name,
        information_set="B1",
        mechanism_id="baseline",
        b2_variant="primary",
        variant_type="baseline",
    )
    expanded = _forecast_rows(
        testing,
        corrected,
        fold=fold,
        model_name=model_name,
        information_set="B2_residual",
        mechanism_id=mechanism_id,
        b2_variant="primary" if not placebo else "placebo_target_permuted",
        variant_type=kind,
    )
    return baseline, expanded


def _contrast(
    frame: pl.DataFrame,
    *,
    model_name: str,
    variant_type: str,
    mechanism_id: str,
    b2_variant: str,
    expanded_information_set: str = "B2_residual",
    repetitions: int = PRIMARY_BOOTSTRAP,
) -> dict[str, Any]:
    """Return one paired-day contrast for a B1/B2 variant."""
    keys = ["origin_id", "asset", "session_date", "fold"]
    left = frame.filter(
        (pl.col("model_name") == model_name)
        & (pl.col("information_set") == "B1")
        & (pl.col("b2_variant") == b2_variant)
    ).select(*keys, pl.col("qlike_loss").alias("baseline_loss"))
    right = frame.filter(
        (pl.col("model_name") == model_name)
        & (pl.col("information_set") == expanded_information_set)
        & (pl.col("mechanism_id") == mechanism_id)
        & (pl.col("b2_variant") == b2_variant)
        & (pl.col("variant_type") == variant_type)
    ).select(*keys, pl.col("qlike_loss").alias("expanded_loss"))
    paired = left.join(right, on=keys, how="inner", validate="1:1").with_columns(
        (pl.col("baseline_loss") - pl.col("expanded_loss")).alias("loss_difference")
    )
    if paired.height != left.height or paired.height != right.height:
        raise RuntimeError(f"MECHANISM_UNPAIRED_CONTRAST:{model_name}:{mechanism_id}:{b2_variant}")
    inference = paired_day_bootstrap(
        paired,
        repetitions=repetitions,
        seed=SEED,
    )
    return {
        "model_name": model_name,
        "mechanism_id": mechanism_id,
        "variant_type": variant_type,
        "b2_variant": b2_variant,
        "estimate": float(inference["estimate"]),
        "result_sign": (
            "POSITIVE"
            if float(inference["estimate"]) > 0
            else "NEGATIVE"
            if float(inference["estimate"]) < 0
            else "ZERO"
        ),
        "definition": "QLIKE(B1)-QLIKE(B2_VARIANT)",
        **inference,
    }


def _stability(
    frame: pl.DataFrame,
    *,
    model_name: str,
    mechanism_id: str,
    b2_variant: str,
    variant_type: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for dimension in ("asset", "session_tercile", "volatility_regime"):
        for value in sorted(str(item) for item in frame[dimension].unique().to_list()):
            subset = frame.filter(pl.col(dimension) == value)
            if subset.height < 2:
                continue
            try:
                result = _contrast(
                    subset,
                    model_name=model_name,
                    variant_type=variant_type,
                    mechanism_id=mechanism_id,
                    b2_variant=b2_variant,
                    repetitions=SECONDARY_BOOTSTRAP,
                )
            except (RuntimeError, ValueError):
                continue
            rows.append({"dimension": dimension, "value": value, **result})
    return rows


def _psi(training: np.ndarray, testing: np.ndarray, bins: int = 10) -> float:
    """Compute a finite train/test population-stability index."""
    edges = np.unique(np.quantile(training, np.linspace(0.0, 1.0, bins + 1)))
    if edges.size < 3:
        return 0.0
    edges[0], edges[-1] = -np.inf, np.inf
    train_counts = np.histogram(training, bins=edges)[0].astype(float)
    test_counts = np.histogram(testing, bins=edges)[0].astype(float)
    train_share = np.maximum(train_counts / max(train_counts.sum(), 1.0), 1e-8)
    test_share = np.maximum(test_counts / max(test_counts.sum(), 1.0), 1e-8)
    return float(np.sum((test_share - train_share) * np.log(test_share / train_share)))


def _calibration(forecasts: pl.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for keys, group in forecasts.group_by(
        "model_name", "information_set", "mechanism_id", "b2_variant", "variant_type"
    ):
        model, information, mechanism, b2_variant, kind = keys
        actual = group["rv30"].to_numpy()
        forecast = group["forecast"].to_numpy()
        rows.append(
            {
                "model_name": model,
                "information_set": information,
                "mechanism_id": mechanism,
                "b2_variant": b2_variant,
                "variant_type": kind,
                "observations": group.height,
                "actual_mean": float(np.mean(actual)),
                "forecast_mean": float(np.mean(forecast)),
                "forecast_to_actual_ratio": float(np.mean(forecast) / np.mean(actual)),
                "mean_signed_error": float(np.mean(actual - forecast)),
                **regression_metrics(actual, forecast),
            }
        )
    return rows


def _write_svg(results: Sequence[Mapping[str, Any]], path: Path) -> None:
    """Write a dependency-free horizontal bar figure for primary effects."""
    rows = [row for row in results if row.get("variant_type") == "residual"]
    rows = sorted(rows, key=lambda row: float(row["estimate"]), reverse=True)
    width, height = 1100, max(220, 30 * len(rows) + 80)
    if not rows:
        path.write_text(
            "<svg xmlns='http://www.w3.org/2000/svg' width='1100' height='220'></svg>\n",
            encoding="utf-8",
        )
        return
    max_abs = max(abs(float(row["estimate"])) for row in rows) or 1.0
    lines = [f"<svg xmlns='http://www.w3.org/2000/svg' width='{width}' height='{height}'>"]
    lines.append(
        "<rect width='100%' height='100%' fill='white'/><text x='20' y='24' "
        "font-size='16'>Development B2 residual QLIKE effects</text>"
    )
    center = 620
    for index, row in enumerate(rows):
        y = 50 + index * 30
        estimate = float(row["estimate"])
        length = estimate / max_abs * 300
        x = center if length >= 0 else center + length
        color = "#1b7f3a" if estimate >= 0 else "#b3261e"
        label = f"{row['model_name']} / {row['mechanism_id']}"
        lines.append(f"<text x='20' y='{y + 4}' font-size='11'>{label}</text>")
        lines.append(
            f"<rect x='{x:.2f}' y='{y - 9}' width='{abs(length):.2f}' height='16' fill='{color}'/>"
        )
        lines.append(f"<text x='940' y='{y + 4}' font-size='11'>{estimate:.6f}</text>")
    lines.append(
        f"<line x1='{center}' x2='{center}' y1='38' y2='{height - 12}' stroke='#333'/></svg>"
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_docs(result: Mapping[str, Any], *, diagnostics: Mapping[str, Any]) -> None:
    MODEL_CARDS_PATH.parent.mkdir(parents=True, exist_ok=True)
    diagnostics_path = diagnostics.get(
        "diagnostics_path", "artifacts/methodology/b2_mechanism_diagnostics.json"
    )
    MODEL_CARDS_PATH.write_text(
        "# B2 mechanism model cards\n\n"
        "All cards use the 80-session development panel only. No independent outcome "
        "was read for selection.\n\n"
        "## Gamma GLM (confirmatory)\n\n"
        "A positive-mean log-link GLM. Its coefficients are smooth and additive; it "
        "can miss thresholded interactions.\n\n"
        "## HAR-RV, Ridge and Elastic Net (linear challengers)\n\n"
        "These log-linear challengers expose whether the effect survives a simpler "
        "conditional mean specification.\n\n"
        "## LightGBM (robustness challenger)\n\n"
        "A shallow gamma tree ensemble that can model nonlinearities and interactions, "
        "but is more sensitive to drift and tuning.\n\n"
        "## Residual learner\n\n"
        "Each B2 variant is fit only to cross-fitted `RV30 - B1 forecast`; its output "
        "is an additive correction with a positive forecast floor.\n\n"
        f"Primary candidate count: {result.get('primary_variant_count', 0)} evaluated; "
        f"retained: {len(result.get('retained_candidates', []))}.\n",
        encoding="utf-8",
    )
    AUDIT_DOC_PATH.write_text(
        "# B2 mechanism audit v1\n\n"
        "Status: `PASS_DEVELOPMENT_MECHANISM_AUDIT`\n\n"
        "The search was frozen before fitting and used only the Phase 5 80-session "
        "development panel. The sealed independent samples were not read or used "
        "for selection. B2 was evaluated as a residual correction to B1, not as a "
        "trade-presence label.\n\n"
        f"Primary residual variants evaluated: {result.get('primary_variant_count', 0)}.\n\n"
        f"Variants retained by the frozen rule: {result.get('retained_candidates', [])}.\n\n"
        "Gamma–LightGBM divergence is diagnosed with calibration, residual dispersion, "
        "train/test PSI drift, feature redundancy and residual interactions; a positive "
        "Gamma result alone is not global confirmation.\n\n"
        f"Diagnostics artifact: `{diagnostics_path}`.\n",
        encoding="utf-8",
    )


def main() -> None:
    """Execute the full development mechanism audit and write immutable evidence."""
    prereg = _read_json(PREREG_PATH)
    if prereg.get("status") != "FROZEN_DEVELOPMENT_ONLY_BEFORE_MECHANISM_FIT":
        raise RuntimeError("MECHANISM_PREREGISTRATION_NOT_FROZEN")
    if prereg.get("oos_guard", {}).get("oos_read_count") != 0:
        raise RuntimeError("MECHANISM_OOS_READ_BEFORE_SELECTION")
    panel = (
        pl.read_parquet(PANEL_PATH)
        .filter(pl.col("asset").is_in(ASSETS) & pl.col("common_complete"))
        .sort("forecast_origin_utc")
    )
    required = {
        "origin_id",
        "session_date",
        "forecast_origin_utc",
        "rv30",
        *B0_FEATURES,
        *B1_FEATURES,
        *FULL_B2_FEATURES,
    }
    missing = required - set(panel.columns)
    if missing or panel.is_empty():
        raise RuntimeError(f"MECHANISM_PANEL_INVALID:{','.join(sorted(missing))}")
    phase5_prereg = _read_json(PHASE5_PREREG_PATH)
    folds = parse_fold_definitions(phase5_prereg["outer_folds"])
    all_parts: list[pl.DataFrame] = []
    ledger: list[dict[str, Any]] = []
    drift_rows: list[dict[str, Any]] = []
    parameter_ledger: list[dict[str, Any]] = []
    lagged_panel = lag_b2_one_session(panel)
    for fold in folds:
        training_raw, testing_raw = split_expanding_fold(
            panel,
            fold,
            purge_minutes=int(phase5_prereg["purge_embargo_minutes"]),
            embargo_minutes=int(phase5_prereg["purge_embargo_minutes"]),
        )
        cutpoints_values = training_raw.select(
            pl.col("b0_rv_30m_lag").quantile(1 / 3).alias("lower"),
            pl.col("b0_rv_30m_lag").quantile(2 / 3).alias("upper"),
        ).row(0)
        cutpoints = (float(cutpoints_values[0]), float(cutpoints_values[1]))
        training = add_predeclared_strata(training_raw, volatility_cutpoints=cutpoints)
        testing = add_predeclared_strata(testing_raw, volatility_cutpoints=cutpoints)
        lag_training_raw, lag_testing_raw = split_expanding_fold(
            lagged_panel,
            fold,
            purge_minutes=int(phase5_prereg["purge_embargo_minutes"]),
            embargo_minutes=int(phase5_prereg["purge_embargo_minutes"]),
        )
        lag_training = add_predeclared_strata(lag_training_raw, volatility_cutpoints=cutpoints)
        lag_testing = add_predeclared_strata(lag_testing_raw, volatility_cutpoints=cutpoints)
        for feature in B2_FEATURES:
            drift_rows.append(
                {
                    "fold": fold.fold,
                    "feature": feature,
                    "psi": _psi(
                        training[feature].to_numpy(),
                        testing[feature].to_numpy(),
                    ),
                }
            )
        for model_name in MODEL_NAMES:
            b1_parameters, b1_records = _select_parameters(
                training,
                features=INFO_SETS["B1"],
                model_name=model_name,
                purge_minutes=int(phase5_prereg["purge_embargo_minutes"]),
            )
            parameter_ledger.extend(
                [{**record, "fold": fold.fold, "information_set": "B1"} for record in b1_records]
            )
            for information_set in ("B0", "B2"):
                parameters, records = _select_parameters(
                    training,
                    features=INFO_SETS[information_set],
                    model_name=model_name,
                    purge_minutes=int(phase5_prereg["purge_embargo_minutes"]),
                )
                parameter_ledger.extend(
                    [
                        {**record, "fold": fold.fold, "information_set": information_set}
                        for record in records
                    ]
                )
                fitted = fit_development_candidate(
                    training,
                    feature_columns=INFO_SETS[information_set],
                    model_name=model_name,
                    parameters=parameters,
                    seed=SEED,
                )
                target_frame = testing
                all_parts.append(
                    _forecast_rows(
                        target_frame,
                        fitted.predict(target_frame),
                        fold=fold.fold,
                        model_name=model_name,
                        information_set=information_set,
                        mechanism_id="direct",
                        b2_variant="primary",
                        variant_type="direct",
                    )
                )
            for mechanism_id in MECHANISM_VARIANTS:
                baseline_frame, expanded_frame = _residual_variant(
                    training,
                    testing,
                    fold=fold.fold,
                    model_name=model_name,
                    base_parameters=b1_parameters,
                    mechanism_id=mechanism_id,
                    purge_minutes=int(phase5_prereg["purge_embargo_minutes"]),
                )
                if mechanism_id == MECHANISM_VARIANTS[0]:
                    all_parts.append(baseline_frame)
                all_parts.append(expanded_frame)
                placebo_baseline_frame, placebo_frame = _residual_variant(
                    training,
                    testing,
                    fold=fold.fold,
                    model_name=model_name,
                    base_parameters=b1_parameters,
                    mechanism_id=mechanism_id,
                    purge_minutes=int(phase5_prereg["purge_embargo_minutes"]),
                    placebo=True,
                )
                if mechanism_id == MECHANISM_VARIANTS[0]:
                    all_parts.append(
                        placebo_baseline_frame.with_columns(
                            pl.lit("placebo_target_permuted").alias("b2_variant")
                        )
                    )
                all_parts.append(placebo_frame)
                lag_baseline_frame, lag_expanded_frame = _residual_variant(
                    lag_training,
                    lag_testing,
                    fold=fold.fold,
                    model_name=model_name,
                    base_parameters=b1_parameters,
                    mechanism_id=mechanism_id,
                    purge_minutes=int(phase5_prereg["purge_embargo_minutes"]),
                )
                if mechanism_id == MECHANISM_VARIANTS[0]:
                    all_parts.append(
                        lag_baseline_frame.with_columns(pl.lit("lag_1_session").alias("b2_variant"))
                    )
                all_parts.append(
                    lag_expanded_frame.with_columns(pl.lit("lag_1_session").alias("b2_variant"))
                )
                ledger.append(
                    {
                        "fold": fold.fold,
                        "model_name": model_name,
                        "mechanism_id": mechanism_id,
                        "primary": True,
                        "placebo": True,
                        "lag_sensitivity": True,
                        "status": "RUN",
                    }
                )
    forecasts = pl.concat(all_parts, how="vertical_relaxed").sort(
        ["model_name", "b2_variant", "information_set", "origin_id"]
    )
    if (
        forecasts.select(
            pl.struct(
                "origin_id",
                "model_name",
                "information_set",
                "mechanism_id",
                "b2_variant",
                "variant_type",
            ).n_unique()
        ).item()
        != forecasts.height
    ):
        raise RuntimeError("MECHANISM_FORECAST_DUPLICATE_KEY")
    OUT.mkdir(parents=True, exist_ok=True)
    forecasts.write_parquet(FORECAST_PATH, compression="zstd")

    primary_results: list[dict[str, Any]] = []
    placebo_results: list[dict[str, Any]] = []
    lag_results: list[dict[str, Any]] = []
    direct_results: list[dict[str, Any]] = []
    stability_rows: list[dict[str, Any]] = []
    for model_name in MODEL_NAMES:
        for mechanism_id in MECHANISM_VARIANTS:
            primary = _contrast(
                forecasts,
                model_name=model_name,
                variant_type="residual",
                mechanism_id=mechanism_id,
                b2_variant="primary",
            )
            placebo = _contrast(
                forecasts,
                model_name=model_name,
                variant_type="placebo",
                mechanism_id=mechanism_id,
                b2_variant="placebo_target_permuted",
            )
            lag = _contrast(
                forecasts,
                model_name=model_name,
                variant_type="residual",
                mechanism_id=mechanism_id,
                b2_variant="lag_1_session",
            )
            primary_results.append(primary)
            placebo_results.append(placebo)
            lag_results.append(lag)
            stability_rows.extend(
                _stability(
                    forecasts,
                    model_name=model_name,
                    mechanism_id=mechanism_id,
                    b2_variant="primary",
                    variant_type="residual",
                )
            )
        for baseline_set, expanded_set, label in (
            ("B0", "B1", "delta_b1"),
            ("B1", "B2", "delta_b2_direct"),
        ):
            left = forecasts.filter(
                (pl.col("model_name") == model_name)
                & (pl.col("information_set") == baseline_set)
                & (pl.col("b2_variant") == "primary")
            ).select(
                "origin_id",
                "asset",
                "session_date",
                "fold",
                pl.col("qlike_loss").alias("baseline_loss"),
            )
            right = forecasts.filter(
                (pl.col("model_name") == model_name)
                & (pl.col("information_set") == expanded_set)
                & (pl.col("b2_variant") == "primary")
            ).select(
                "origin_id",
                "asset",
                "session_date",
                "fold",
                pl.col("qlike_loss").alias("expanded_loss"),
            )
            paired = left.join(
                right,
                on=["origin_id", "asset", "session_date", "fold"],
                how="inner",
                validate="1:1",
            ).with_columns(
                (pl.col("baseline_loss") - pl.col("expanded_loss")).alias("loss_difference")
            )
            direct_results.append(
                {
                    "model_name": model_name,
                    "contrast": label,
                    **paired_day_bootstrap(paired, repetitions=PRIMARY_BOOTSTRAP, seed=SEED),
                }
            )

    all_p = {
        f"{row['model_name']}::{row['mechanism_id']}": float(row["p_value_two_sided"])
        for row in primary_results
    }
    adjusted = holm_adjust(all_p)
    for row in primary_results:
        row["p_value_holm"] = adjusted[f"{row['model_name']}::{row['mechanism_id']}"]
    for row in placebo_results:
        row["p_value_holm"] = None
    for row in lag_results:
        row["p_value_holm"] = None
    retained: list[str] = []
    candidate_records: list[dict[str, Any]] = []
    for row in primary_results:
        asset_rows = [
            item
            for item in stability_rows
            if item["model_name"] == row["model_name"]
            and item["mechanism_id"] == row["mechanism_id"]
            and item["dimension"] == "asset"
        ]
        placebo_record = next(
            item
            for item in placebo_results
            if item["model_name"] == row["model_name"]
            and item["mechanism_id"] == row["mechanism_id"]
        )
        lag_record = next(
            item
            for item in lag_results
            if item["model_name"] == row["model_name"]
            and item["mechanism_id"] == row["mechanism_id"]
        )
        passes = {
            "positive": float(row["estimate"]) > 0,
            "ci_low_above_zero": float(row["ci_low"]) > 0,
            "holm_p_below_0_05": float(row["p_value_holm"]) < 0.05,
            "at_least_mde": float(row["estimate"]) >= float(prereg["inference"]["mde"]),
            "four_of_six_assets_positive": sum(float(item["estimate"]) > 0 for item in asset_rows)
            >= 4,
            "at_most_one_asset_wholly_negative": sum(
                float(item["ci_high"]) < 0 for item in asset_rows
            )
            <= 1,
            "placebo_not_positive_significant": float(placebo_record["estimate"]) <= 0
            or float(placebo_record["ci_low"]) <= 0,
            "lag_not_wholly_negative": float(lag_record["ci_high"]) >= 0,
        }
        key = f"{row['model_name']}::{row['mechanism_id']}"
        candidate_records.append(
            {"candidate": key, "passes": passes, "retained": all(passes.values())}
        )
        if all(passes.values()):
            retained.append(key)

    calibration = _calibration(forecasts)
    pl.DataFrame(calibration).write_csv(CALIBRATION_PATH)
    pl.DataFrame(drift_rows).write_csv(DRIFT_PATH)
    b2_values = panel.select(B2_FEATURES).to_numpy().astype(np.float64, copy=False)
    b2_corr = np.corrcoef(b2_values, rowvar=False)
    redundancy_rows: list[dict[str, Any]] = [
        {
            "feature_a": left,
            "feature_b": right,
            "pearson_abs_corr": float(abs(b2_corr[index, index + offset])),
        }
        for index, left in enumerate(B2_FEATURES)
        for offset, right in enumerate(B2_FEATURES[index + 1 :], start=1)
    ]
    pl.DataFrame(redundancy_rows).write_csv(REDUNDANCY_PATH)
    interaction_rows: list[dict[str, Any]] = []
    primary_b1 = forecasts.filter(
        (pl.col("information_set") == "B1") & (pl.col("b2_variant") == "primary")
    )
    primary_b1 = primary_b1.join(
        panel.select(["origin_id", *B2_FEATURES]),
        on="origin_id",
        how="inner",
    )
    for model_name in MODEL_NAMES:
        subset = primary_b1.filter(pl.col("model_name") == model_name)
        residual = subset["rv30"].to_numpy() - subset["forecast"].to_numpy()
        for feature in B2_FEATURES:
            interaction_rows.append(
                {
                    "model_name": model_name,
                    "term": "global",
                    "feature": feature,
                    "correlation_with_b1_residual": float(
                        np.corrcoef(subset[feature].to_numpy(), residual)[0, 1]
                    ),
                }
            )
    pl.DataFrame(interaction_rows).write_csv(INTERACTIONS_PATH)
    diagnostics = {
        "diagnostics_path": "artifacts/methodology/b2_mechanism_diagnostics.json",
        "calibration_path": str(CALIBRATION_PATH.relative_to(ROOT)).replace("\\", "/"),
        "drift_path": str(DRIFT_PATH.relative_to(ROOT)).replace("\\", "/"),
        "redundancy_path": str(REDUNDANCY_PATH.relative_to(ROOT)).replace("\\", "/"),
        "interactions_path": str(INTERACTIONS_PATH.relative_to(ROOT)).replace("\\", "/"),
        "max_abs_b2_pair_correlation": max(
            (float(row["pearson_abs_corr"]) for row in redundancy_rows), default=0.0
        ),
        "max_psi": max((float(row["psi"]) for row in drift_rows), default=0.0),
    }
    diagnostics_path = OUT / "b2_mechanism_diagnostics.json"
    diagnostics_path.write_text(
        json.dumps(diagnostics, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    stability_frame = pl.DataFrame(stability_rows)
    stability_frame.write_parquet(STABILITY_PATH, compression="zstd")
    result: dict[str, Any] = {
        "schema_version": "b2-mechanism-results-1.0",
        "status": "PASS_DEVELOPMENT_MECHANISM_AUDIT",
        "selection_source": "PHASE5_DEVELOPMENT_ONLY",
        "independent_samples_read": False,
        "oos_read_count": 0,
        "development_origins": int(panel.height),
        "development_sessions": int(panel["session_date"].n_unique()),
        "models": list(MODEL_NAMES),
        "primary_variant_count": len(primary_results),
        "primary_results": primary_results,
        "placebo_results": placebo_results,
        "lag_sensitivity_results": lag_results,
        "direct_model_comparison": direct_results,
        "retained_candidates": retained,
        "candidate_records": candidate_records,
        "all_variants_recorded": True,
        "all_variants_retained": len(retained) == len(primary_results),
        "calibration": calibration,
        "diagnostics": diagnostics,
        "artifact_hashes": {
            "forecasts": _sha256(FORECAST_PATH),
            "stability": _sha256(STABILITY_PATH),
            "calibration": _sha256(CALIBRATION_PATH),
            "drift": _sha256(DRIFT_PATH),
            "redundancy": _sha256(REDUNDANCY_PATH),
            "interactions": _sha256(INTERACTIONS_PATH),
        },
    }
    result["manifest_sha256"] = canonical_sha256(result)
    RESULT_PATH.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    ledger_payload = {
        "schema_version": "b2-mechanism-variant-ledger-1.0",
        "all_variants_recorded": True,
        "all_variants_retained": len(retained) == len(primary_results),
        "oos_read_count": 0,
        "parameter_variants": parameter_ledger,
        "mechanism_variants": ledger,
        "primary_results_hash": _sha256(RESULT_PATH),
    }
    ledger_payload["manifest_sha256"] = canonical_sha256(ledger_payload)
    LEDGER_PATH.write_text(
        json.dumps(ledger_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    _write_svg(primary_results, OUT / "b2_mechanism_qlike_effects.svg")
    _write_docs(result, diagnostics=diagnostics)
    print(
        json.dumps(
            {
                "status": result["status"],
                "origins": panel.height,
                "primary_variants": len(primary_results),
                "retained": retained,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
