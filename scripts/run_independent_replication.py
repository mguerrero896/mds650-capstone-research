"""Run the frozen 60-session training / 30-session RV30 replication.

The target stage is deliberately separate from target-free panel construction:
it records one guarded outcome read, then the evaluation stage fits the frozen
Gamma and LightGBM roles without tuning on the target block.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from mds650.metrics import qlike_losses
from mds650.modeling import fit_positive_model
from mds650.phase6 import (
    B0V2_FEATURES,
    B1V2A_FEATURES,
    B2V2_FEATURES,
    build_b0v2_features,
    build_b2v2_from_activity,
    build_phase6_common_panel,
)
from mds650.phase6_evaluation import evaluate_phase6, phase6_contrast
from mds650.study_design import canonical_sha256

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "artifacts" / "independent_replication"
DATA_ROOT = Path("D:/MDS650/independent_replication_30")
DERIVED = DATA_ROOT / "derived"
WINDOW = ARTIFACT / "window_manifest.json"
METHOD = ARTIFACT / "method_freeze.json"
PARAMETERS = ARTIFACT / "parameter_freeze.json"
ACQUISITION = ARTIFACT / "acquisition_manifest.json"
FMP_MANIFEST = ARTIFACT / "fmp_manifest.json"
B1_MANIFEST = ARTIFACT / "b1_manifest.json"
B2_MANIFEST = ARTIFACT / "b2_manifest.json"
ORIGINS = DERIVED / "origins_90d.parquet"
BARS = DERIVED / "underlying_1min_90d.parquet"
B0_WARMUP = DERIVED / "b0_warmup_60d.parquet"
B0_TARGET = DERIVED / "b0_target_30d.parquet"
B1 = DERIVED / "b1" / "b1v2a_90d.parquet"
B2 = DERIVED / "b2_primary_90d.parquet"
TARGET_ACCESS = ARTIFACT / "target_access_ledger.json"
PANEL = DERIVED / "common_panel_90d.parquet"
COMPLETE_PANEL = DERIVED / "common_complete_90d.parquet"
PREDICTIONS = DERIVED / "independent_predictions.parquet"
TIMING_PREDICTIONS = DERIVED / "independent_timing_predictions.parquet"
RESULTS = ARTIFACT / "independent_results.json"
PANEL_MANIFEST = ARTIFACT / "independent_panel_manifest.json"
SEED = 650
FORECAST_FLOOR = 1e-12
KEYS = ("origin_id", "asset", "session_date", "forecast_origin_utc")
ROLES = ("gamma_glm_confirmatory", "lightgbm_robustness")
SETS = ("B0v2", "B1v2a", "B2v2")


def _sha(path: Path) -> str:
    """Return a SHA-256 digest for one local file."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json(path: Path) -> dict[str, Any]:
    """Read one JSON object and reject malformed artifacts."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"JSON_OBJECT_REQUIRED:{path.name}")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    """Write a self-hashed JSON manifest atomically."""
    unsigned = {key: value for key, value in payload.items() if key != "manifest_sha256"}
    output = {**unsigned, "manifest_sha256": canonical_sha256(unsigned)}
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_text(
        json.dumps(output, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _assert_hashed(payload: dict[str, Any], name: str) -> None:
    """Fail closed if a repository manifest was changed without its hash."""
    unsigned = {key: value for key, value in payload.items() if key != "manifest_sha256"}
    if payload.get("manifest_sha256") != canonical_sha256(unsigned):
        raise RuntimeError(f"MANIFEST_HASH_INVALID:{name}")


def _assert_target_free(path: Path, status: str) -> dict[str, Any]:
    """Validate one target-free manifest and reject target columns/flags."""
    payload = _json(path)
    _assert_hashed(payload, path.name)
    if payload.get("status") != status or payload.get("target_outcome_read") is not False:
        raise RuntimeError(f"TARGET_FREE_MANIFEST_INVALID:{path.name}")
    if payload.get("secret_values_emitted") or payload.get("personal_paths_emitted"):
        raise RuntimeError(f"UNSANITIZED_MANIFEST:{path.name}")
    return payload


def _window() -> dict[str, Any]:
    """Load and validate the exact 60/30 session allow-list."""
    window = _json(WINDOW)
    _assert_hashed(window, WINDOW.name)
    if window.get("status") != "READY_FOR_BOUNDED_BODY_ACQUISITION":
        raise RuntimeError("REPLICATION_WINDOW_NOT_READY")
    if len(window.get("all_dates", [])) != 90 or len(window.get("warmup_dates", [])) != 60:
        raise RuntimeError("REPLICATION_WINDOW_COUNT_INVALID")
    if len(window.get("target_dates", [])) != 30:
        raise RuntimeError("REPLICATION_TARGET_COUNT_INVALID")
    return window


def _validate_acquisition(window: dict[str, Any]) -> dict[str, Any]:
    """Require all dates or an explicitly hashed provider-incident exception."""
    manifest = _json(ACQUISITION)
    _assert_hashed(manifest, ACQUISITION.name)
    records_value = manifest.get("records")
    records: list[dict[str, Any]] = (
        [row for row in records_value if isinstance(row, dict)]
        if isinstance(records_value, list)
        else []
    )
    dates = [str(row.get("session_date")) for row in records]
    excluded = sorted(str(item) for item in manifest.get("excluded_provider_sessions", []))
    expected_dates = {str(day) for day in window["all_dates"]}
    missing = sorted(expected_dates - set(dates))
    if (
        manifest.get("status") not in {"PASS", "PASS_WITH_PROVIDER_INCIDENT"}
        or manifest.get("completed_count") != len(records)
        or dates != sorted(set(dates))
        or any(day not in expected_dates for day in dates)
        or (manifest.get("status") == "PASS" and (missing or len(records) != 90))
        or (manifest.get("status") == "PASS_WITH_PROVIDER_INCIDENT" and missing != excluded)
        or (manifest.get("status") == "PASS_WITH_PROVIDER_INCIDENT" and not excluded)
    ):
        raise RuntimeError("UW_FULL_TAPE_ACQUISITION_INCOMPLETE")
    for day in excluded:
        incident = ARTIFACT / "acquisition_incidents" / f"{day}_crc_failure.json"
        payload = _json(incident)
        if (
            payload.get("status") != "BLOCKED_PROVIDER_ARCHIVE_CORRUPT"
            or payload.get("provider_artifact_stable_across_retries") is not True
        ):
            raise RuntimeError(f"UW_PROVIDER_INCIDENT_INVALID:{day}")
    for row in records:
        if (
            row.get("status") != "PASS"
            or row.get("http_status") != 200
            or row.get("duplicate_event_ids") != 0
            or row.get("secret_values_emitted")
            or row.get("personal_paths_emitted")
        ):
            raise RuntimeError(f"UW_ACQUISITION_RECORD_INVALID:{row.get('session_date')}")
    return manifest


def _validate_pre_target() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Validate every gate that must precede the sole target read."""
    window = _window()
    _validate_acquisition(window)
    _assert_target_free(FMP_MANIFEST, "PASS_FMP_EXACT_SESSION")
    _assert_target_free(B1_MANIFEST, "PASS_B1V2A_TARGET_FREE")
    _assert_target_free(B2_MANIFEST, "PASS_B2_TARGET_FREE")
    method = _json(METHOD)
    _assert_hashed(method, METHOD.name)
    if method.get("status") != "FROZEN_BEFORE_TARGET_OUTCOME_READ":
        raise RuntimeError("INDEPENDENT_METHOD_FREEZE_INVALID")
    parameters = _json(PARAMETERS)
    _assert_hashed(parameters, PARAMETERS.name)
    if parameters.get("status") != "FROZEN_BEFORE_INDEPENDENT_TARGET_OUTCOME_READ":
        raise RuntimeError("INDEPENDENT_PARAMETER_FREEZE_INVALID")
    if parameters.get("source_hashes", {}).get("method_freeze") != _sha(METHOD):
        raise RuntimeError("INDEPENDENT_PARAMETER_METHOD_HASH_DRIFT")
    for path in (ORIGINS, BARS, B0_WARMUP, B1, B2):
        if not path.is_file():
            raise RuntimeError(f"INDEPENDENT_INPUT_MISSING:{path.name}")
    return window, method, parameters


def _write_target_access(payload: dict[str, Any]) -> None:
    """Persist a target-read state transition before or after the read."""
    _write_json(TARGET_ACCESS, payload)


def read_target_once() -> None:
    """Read target closes exactly once and persist the immutable target B0."""
    window, method, parameters = _validate_pre_target()
    del method, parameters
    if TARGET_ACCESS.exists():
        existing = _json(TARGET_ACCESS)
        if existing.get("status") != "NOT_STARTED":
            raise RuntimeError("TARGET_READ_ALREADY_ATTEMPTED")
    _write_target_access(
        {
            "schema_version": "b2-independent-replication-target-access-1.0",
            "status": "TARGET_READ_IN_PROGRESS",
            "target_read_count": 1,
            "target_dates": list(window["target_dates"]),
            "target_outcome_read": True,
            "started_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "secret_values_emitted": False,
            "personal_paths_emitted": False,
        }
    )
    origins = pl.read_parquet(ORIGINS).filter(pl.col("role") == "target")
    bars = pl.read_parquet(BARS)
    target = build_b0v2_features(bars, origins, delay_minutes=1, include_target=True)
    if target.height != origins.height:
        raise RuntimeError("TARGET_B0_ORIGIN_ALIGNMENT_FAILURE")
    invalid = target.filter(
        (pl.col("target_price_count") != 31)
        | (pl.col("target_return_count") != 30)
        | pl.col("rv30").is_null()
        | (pl.col("rv30") <= 0)
    )
    if invalid.height:
        raise RuntimeError(f"TARGET_RV30_INVALID:{invalid.height}")
    temporary = B0_TARGET.with_suffix(B0_TARGET.suffix + ".part")
    temporary.parent.mkdir(parents=True, exist_ok=True)
    target.write_parquet(temporary, compression="zstd")
    temporary.replace(B0_TARGET)
    _write_target_access(
        {
            "schema_version": "b2-independent-replication-target-access-1.0",
            "status": "TARGET_READ_COMPLETE",
            "target_read_count": 1,
            "target_dates": list(window["target_dates"]),
            "target_origin_count": target.height,
            "target_b0_sha256": _sha(B0_TARGET),
            "target_price_count": 31,
            "target_return_count": 30,
            "target_outcome_read": True,
            "secret_values_emitted": False,
            "personal_paths_emitted": False,
        }
    )
    print(json.dumps({"status": "TARGET_READ_COMPLETE", "origins": target.height}))


def _add_provider_gap_rows(
    b2: pl.DataFrame, origins: pl.DataFrame, excluded_dates: list[str]
) -> pl.DataFrame:
    """Represent provider gaps explicitly without imputing option activity."""
    if not excluded_dates:
        return b2
    gap_origins = origins.filter(pl.col("session_date").is_in(excluded_dates)).select(
        "origin_id", "asset", "session_date", "forecast_origin_utc"
    )
    if gap_origins.is_empty():
        return b2
    expressions: list[pl.Expr] = []
    for column in b2.columns:
        if column in gap_origins.columns:
            expressions.append(pl.col(column))
        elif column == "b2v2_cutoff_utc":
            expressions.append(
                (pl.col("forecast_origin_utc") - pl.duration(seconds=60)).alias(column)
            )
        elif column == "b2v2_complete":
            expressions.append(pl.lit(False).alias(column))
        else:
            expressions.append(pl.lit(None, dtype=b2.schema[column]).alias(column))
    gap = gap_origins.select(expressions)
    return pl.concat([b2, gap], how="vertical_relaxed").sort("origin_id")


def _build_panel() -> pl.DataFrame:
    """Join warm-up and target rows into the common B0/B1/B2 panel."""
    access = _json(TARGET_ACCESS)
    _assert_hashed(access, TARGET_ACCESS.name)
    if access.get("status") != "TARGET_READ_COMPLETE" or access.get("target_read_count") != 1:
        raise RuntimeError("TARGET_READ_NOT_COMPLETE")
    origins = pl.read_parquet(ORIGINS)
    b0 = pl.concat([pl.read_parquet(B0_WARMUP), pl.read_parquet(B0_TARGET)], how="vertical_relaxed")
    b0 = b0.sort("origin_id")
    b1 = pl.read_parquet(B1).sort("origin_id")
    acquisition = _json(ACQUISITION)
    excluded_dates = sorted(str(item) for item in acquisition.get("excluded_provider_sessions", []))
    b2 = _add_provider_gap_rows(pl.read_parquet(B2).sort("origin_id"), origins, excluded_dates)
    panel, complete = build_phase6_common_panel(origins, b0, b1, b2)
    panel = panel.sort(["session_date", "forecast_origin_utc", "asset"])
    complete = complete.sort(["session_date", "forecast_origin_utc", "asset"])
    PANEL.parent.mkdir(parents=True, exist_ok=True)
    panel.write_parquet(PANEL, compression="zstd")
    complete.write_parquet(COMPLETE_PANEL, compression="zstd")
    _write_json(
        PANEL_MANIFEST,
        {
            "schema_version": "b2-independent-replication-panel-1.0",
            "status": "PASS_COMMON_PANEL_AFTER_SINGLE_TARGET_READ",
            "origin_count": panel.height,
            "complete_origin_count": complete.height,
            "warmup_complete_origin_count": complete.filter(pl.col("role") == "warmup").height,
            "target_complete_origin_count": complete.filter(pl.col("role") == "target").height,
            "asset_count": panel["asset"].n_unique(),
            "session_count": panel["session_date"].n_unique(),
            "panel_sha256": _sha(PANEL),
            "complete_panel_sha256": _sha(COMPLETE_PANEL),
            "target_read_count": 1,
            "excluded_provider_sessions": excluded_dates,
            "provider_gap_rows_explicitly_missing": bool(excluded_dates),
            "secret_values_emitted": False,
            "personal_paths_emitted": False,
        },
    )
    return complete


def _features(information_set: str) -> tuple[str, ...]:
    """Return frozen feature names for one information set."""
    if information_set == "B0v2":
        return B0V2_FEATURES
    if information_set == "B1v2a":
        return (*B0V2_FEATURES, *B1V2A_FEATURES)
    if information_set == "B2v2":
        return (*B0V2_FEATURES, *B1V2A_FEATURES, *B2V2_FEATURES)
    raise RuntimeError(f"UNKNOWN_INFORMATION_SET:{information_set}")


def _fit_predict(
    panel: pl.DataFrame,
    parameters: dict[str, Any],
    *,
    information_sets: tuple[str, ...] = SETS,
    roles: tuple[str, ...] = ROLES,
    timing_variant: str = "PRIMARY",
) -> pl.DataFrame:
    """Fit frozen roles on warm-up rows and forecast target rows."""
    training = panel.filter(pl.col("role") == "warmup")
    testing = panel.filter(pl.col("role") == "target")
    if training.is_empty() or testing.is_empty():
        raise RuntimeError("INDEPENDENT_TRAIN_TEST_EMPTY")
    values = np.asarray(training["b0v2_underlying_rv_30m"].to_numpy(), dtype=np.float64)
    if not np.isfinite(values).all():
        raise RuntimeError("INDEPENDENT_TRAINING_VOLATILITY_INVALID")
    lower, upper = np.quantile(values, [1 / 3, 2 / 3])
    testing = testing.with_columns(
        pl.when(pl.col("b0v2_underlying_rv_30m") <= float(lower))
        .then(pl.lit("low"))
        .when(pl.col("b0v2_underlying_rv_30m") <= float(upper))
        .then(pl.lit("normal"))
        .otherwise(pl.lit("high"))
        .alias("volatility_regime")
    ).with_columns(
        pl.col("forecast_origin_utc")
        .dt.convert_time_zone("America/New_York")
        .dt.hour()
        .alias("session_hour")
    )
    parts: list[pl.DataFrame] = []
    for information_set in information_sets:
        features = _features(information_set)
        for role in roles:
            key = f"{information_set}:{role}"
            if key not in parameters:
                raise RuntimeError(f"INDEPENDENT_PARAMETERS_MISSING:{key}")
            model = fit_positive_model(
                training,
                feature_columns=features,
                categorical_columns=("b0v2_asset_identity",),
                target_column="rv30",
                role=role,
                parameters=parameters[key],
                seed=SEED,
                forecast_floor=FORECAST_FLOOR,
            )
            forecast = model.predict(testing)
            target = np.asarray(testing["rv30"].to_numpy(), dtype=np.float64)
            parts.append(
                testing.select(
                    "origin_id",
                    "asset",
                    "session_date",
                    "forecast_origin_utc",
                    "session_tercile",
                    "volatility_regime",
                    "session_hour",
                    "rv30",
                ).with_columns(
                    pl.lit(1).alias("fold"),
                    pl.lit(role).alias("model_role"),
                    pl.lit(information_set).alias("information_set"),
                    pl.lit(timing_variant).alias("timing_variant"),
                    pl.Series("forecast", forecast),
                    pl.Series("qlike_loss", qlike_losses(target, forecast)),
                    pl.Series("absolute_error", np.abs(target - forecast)),
                    pl.Series("squared_error", np.square(target - forecast)),
                    pl.lit(json.dumps(parameters[key], sort_keys=True)).alias(
                        "selected_parameters"
                    ),
                    pl.lit(canonical_sha256({"features": list(features)})).alias(
                        "feature_schema_sha256"
                    ),
                )
            )
    output = pl.concat(parts).sort(["timing_variant", "model_role", "information_set", "origin_id"])
    expected = testing.height * len(information_sets) * len(roles)
    if output.height != expected:
        raise RuntimeError("INDEPENDENT_FORECAST_PAIRING_FAILURE")
    return output


def _hour_stability(predictions: pl.DataFrame, method: dict[str, Any]) -> list[dict[str, Any]]:
    """Compute descriptive paired contrasts for each New York clock hour."""
    rows: list[dict[str, Any]] = []
    for role in ROLES:
        for name, baseline, expanded in (
            ("delta_b1v2", "B0v2", "B1v2a"),
            ("delta_b2v2", "B1v2a", "B2v2"),
        ):
            for hour in sorted(predictions["session_hour"].unique().to_list()):
                subset = predictions.filter(pl.col("session_hour") == hour)
                if subset["session_date"].n_unique() < 2:
                    continue
                rows.append(
                    {
                        **phase6_contrast(
                            subset,
                            role=role,
                            name=name,
                            baseline=baseline,
                            expanded=expanded,
                            preregistration={"inference": method["inference"]},
                        ),
                        "dimension": "session_hour_new_york",
                        "value": int(hour),
                    }
                )
    return rows


def _calibration(predictions: pl.DataFrame) -> list[dict[str, Any]]:
    """Summarize forecast scale and signed bias without selecting variants."""
    output: list[dict[str, Any]] = []
    for (role, information_set), frame in predictions.group_by(
        "model_role", "information_set", maintain_order=True
    ):
        actual = np.asarray(frame["rv30"].to_numpy(), dtype=np.float64)
        forecast = np.asarray(frame["forecast"].to_numpy(), dtype=np.float64)
        ratio = actual / forecast
        output.append(
            {
                "model_role": role,
                "information_set": information_set,
                "observations": frame.height,
                "mean_actual": float(actual.mean()),
                "mean_forecast": float(forecast.mean()),
                "mean_forecast_minus_actual": float((forecast - actual).mean()),
                "mean_actual_to_forecast": float(ratio.mean()),
                "median_actual_to_forecast": float(np.median(ratio)),
            }
        )
    return sorted(output, key=lambda row: (row["model_role"], row["information_set"]))


def _b0_delay_panel(panel: pl.DataFrame, origins: pl.DataFrame, bars: pl.DataFrame) -> pl.DataFrame:
    """Replace only B0 predictors with a target-free +2-minute variant."""
    delay2 = build_b0v2_features(bars, origins, delay_minutes=2, include_target=False)
    replacements = delay2.select(*KEYS, "max_predictor_available_at_utc", *B0V2_FEATURES)
    drop_columns = [
        name for name in (*B0V2_FEATURES, "max_predictor_available_at_utc") if name in panel.columns
    ]
    joined = panel.drop(*drop_columns).join(replacements, on=list(KEYS), how="left", validate="1:1")
    if joined.height != panel.height:
        raise RuntimeError("INDEPENDENT_FMP_SENSITIVITY_ALIGNMENT_FAILURE")
    return joined


def _b2_sensitivity_panels(
    panel: pl.DataFrame, origins: pl.DataFrame, spec_names: tuple[str, ...]
) -> dict[str, pl.DataFrame]:
    """Build target-free normalized B2 timing variants from cached activity."""
    output: dict[str, pl.DataFrame] = {}
    activity_root = DERIVED / "b2_activity"
    acquisition = _json(ACQUISITION)
    excluded_dates = sorted(str(item) for item in acquisition.get("excluded_provider_sessions", []))
    expected_partition_count = len(_json(WINDOW)["all_dates"]) - len(excluded_dates)
    b2_origins = origins.filter(~pl.col("session_date").is_in(excluded_dates))
    for spec in spec_names:
        paths = sorted((activity_root / spec).glob("date=*.parquet"))
        if len(paths) != expected_partition_count:
            raise RuntimeError(f"INDEPENDENT_B2_SENSITIVITY_PARTITIONS:{spec}")
        activity = pl.scan_parquet([str(path) for path in paths]).collect(engine="streaming")
        b2 = build_b2v2_from_activity(activity, b2_origins)
        b2 = _add_provider_gap_rows(b2, origins, excluded_dates)
        replacements = b2.select(
            *KEYS,
            *B2V2_FEATURES,
            "b2v2_complete",
            "b2v2_cutoff_utc",
            "b2v2_max_created_at_utc",
        )
        b2_drop_columns = [
            name
            for name in (
                *B2V2_FEATURES,
                "b2v2_complete",
                "b2v2_cutoff_utc",
                "b2v2_max_created_at_utc",
            )
            if name in panel.columns
        ]
        dropped = panel.drop(*b2_drop_columns)
        variant = dropped.join(replacements, on=list(KEYS), how="left", validate="1:1")
        if variant.height != panel.height:
            raise RuntimeError(f"INDEPENDENT_B2_SENSITIVITY_ALIGNMENT:{spec}")
        output[spec] = variant
    return output


def evaluate_replication() -> None:
    """Run primary and preregistered timing-sensitivity forecasts once."""
    window, method, parameter_manifest = _validate_pre_target()
    del window
    access = _json(TARGET_ACCESS)
    _assert_hashed(access, TARGET_ACCESS.name)
    if access.get("status") != "TARGET_READ_COMPLETE" or access.get("target_read_count") != 1:
        raise RuntimeError("TARGET_READ_NOT_COMPLETE")
    if RESULTS.exists() or PREDICTIONS.exists():
        raise RuntimeError("INDEPENDENT_RESULTS_ALREADY_EXIST")
    complete = _build_panel()
    params = parameter_manifest["parameters"]
    primary = _fit_predict(complete, params)
    bars = pl.read_parquet(BARS)
    origins = pl.read_parquet(ORIGINS)
    timing_parts: list[pl.DataFrame] = []
    delayed = _b0_delay_panel(complete, origins, bars)
    timing_parts.append(_fit_predict(delayed, params, timing_variant="FMP_DELAY_2_MINUTES"))
    variants = _b2_sensitivity_panels(
        complete,
        origins,
        ("window_15m_60s", "window_30m_60s", "latency_5m_120s", "latency_5m_300s"),
    )
    for name, variant in variants.items():
        timing_parts.append(
            _fit_predict(
                variant,
                params,
                information_sets=("B2v2",),
                timing_variant=name,
            )
        )
    timing = pl.concat(timing_parts).sort(
        ["timing_variant", "model_role", "information_set", "origin_id"]
    )
    PREDICTIONS.parent.mkdir(parents=True, exist_ok=True)
    primary.write_parquet(PREDICTIONS, compression="zstd")
    timing.write_parquet(TIMING_PREDICTIONS, compression="zstd")
    frozen_inference = dict(method["inference"])
    repetition_value: Any = frozen_inference.get(
        "bootstrap_repetitions", frozen_inference.get("repetitions")
    )
    if repetition_value is None:
        raise RuntimeError("INDEPENDENT_BOOTSTRAP_REPETITIONS_MISSING")
    frozen_inference["bootstrap_repetitions"] = int(repetition_value)
    frozen_inference["seed"] = int(frozen_inference.get("seed", SEED))
    eval_method = {
        "inference": frozen_inference,
        "training_mde": _json(ROOT / "artifacts" / "phase6" / "method_freeze.json")["training_mde"],
    }
    results = evaluate_phase6(primary, eval_method, timing_predictions=timing)
    results["hour_stability"] = _hour_stability(primary, eval_method)
    results["calibration"] = _calibration(primary)
    mde = eval_method["training_mde"]
    mde_comparison: dict[str, Any] = {}
    for role in ROLES:
        mde_comparison[role] = {}
        for name in ("delta_b1v2", "delta_b2v2"):
            row = results["global"][role][name]
            threshold = float(mde[name])
            mde_comparison[role][name] = {
                "estimate": float(row["estimate"]),
                "mde": threshold,
                "exceeds_mde": float(row["estimate"]) >= threshold,
                "ci_low": float(row["ci_low"]),
                "ci_high": float(row["ci_high"]),
            }
    result_payload: dict[str, Any] = {
        "schema_version": "b2-independent-replication-results-1.0",
        "status": "INDEPENDENT_REPLICATION_COMPLETE",
        "decision": results["decision"],
        "target": "RV30",
        "target_read_count": 1,
        "primary_information_sets": list(SETS),
        "primary_model_roles": list(ROLES),
        "primary_origin_count": primary["origin_id"].n_unique(),
        "primary_forecast_row_count": primary.height,
        "timing_forecast_row_count": timing.height,
        "primary_coverage_by_asset": {
            str(asset): int(primary.filter(pl.col("asset") == asset)["origin_id"].n_unique())
            for asset in sorted(primary["asset"].unique().to_list())
        },
        "mde_comparison": mde_comparison,
        "evaluation": results,
        "artifacts": {
            "panel": str(PANEL).replace("D:/", "MDS650_DATA_ROOT/"),
            "complete_panel": str(COMPLETE_PANEL).replace("D:/", "MDS650_DATA_ROOT/"),
            "predictions": str(PREDICTIONS).replace("D:/", "MDS650_DATA_ROOT/"),
            "timing_predictions": str(TIMING_PREDICTIONS).replace("D:/", "MDS650_DATA_ROOT/"),
        },
        "hashes": {
            "method_freeze": _sha(METHOD),
            "parameter_freeze": _sha(PARAMETERS),
            "panel": _sha(PANEL),
            "predictions": _sha(PREDICTIONS),
            "timing_predictions": _sha(TIMING_PREDICTIONS),
        },
        "all_signs_retained": True,
        "secret_values_emitted": False,
        "personal_paths_emitted": False,
    }
    _write_json(RESULTS, result_payload)
    print(
        json.dumps(
            {
                "status": result_payload["status"],
                "decision": results["decision"],
                "origins": primary["origin_id"].n_unique(),
            }
        )
    )


def main() -> None:
    """Dispatch the guarded target-read or evaluation stage."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=("target", "evaluate"), required=True)
    stage = parser.parse_args().stage
    if stage == "target":
        read_target_once()
    else:
        evaluate_replication()


if __name__ == "__main__":
    main()
