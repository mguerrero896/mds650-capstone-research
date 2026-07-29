"""Execute the sole prospective Phase 5 holdout read after every gate passes."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
import run_phase5_development_evaluation as development
from jsonschema import Draft202012Validator

from mds650.holdout import (
    EXPECTED_HOLDOUT_SESSIONS,
    FROZEN_PHASE5_SOURCE_PATHS,
    HOLDOUT_PERIOD_COMPLETE_UTC,
    authorize_holdout_read,
)
from mds650.metrics import holm_adjust, qlike_losses
from mds650.modeling import fit_positive_model
from mds650.stability import (
    B2_DELAYS_SECONDS,
    FMP_DELAYS_MINUTES,
    SESSION_TERCILE_BOUNDS,
    add_stability_strata,
    apply_b2_delay,
    apply_fmp_delay,
    b2_sensitivity_column,
    development_volatility_cutpoints,
)
from mds650.study_design import canonical_sha256, source_sha256

ROOT = Path(__file__).resolve().parents[1]
PHASE5 = ROOT / "artifacts" / "phase5"
DEFAULT_LEDGER = PHASE5 / "holdout_access_ledger.json"
DEFAULT_METHOD_FREEZE = PHASE5 / "method_freeze.json"
DEFAULT_DEVELOPMENT_PANEL = PHASE5 / "common_development_80d.parquet"
DEFAULT_DEVELOPMENT_STABILITY = Path(
    "D:/MDS650/data/phase5_stability/development_stability_inputs_80d.parquet"
)
DEFAULT_HOLDOUT_PANEL = Path("D:/MDS650/data/phase5_holdout/common_holdout_10d.parquet")
DEFAULT_HOLDOUT_STABILITY = Path(
    "D:/MDS650/data/phase5_holdout/holdout_stability_inputs_10d.parquet"
)
DEFAULT_FORECASTS = PHASE5 / "holdout_forecasts.parquet"
DEFAULT_RESULTS = PHASE5 / "holdout_results.json"
DEFAULT_STABILITY_RESULTS = PHASE5 / "stability_results.json"
STABILITY_RESULTS_SCHEMA = (
    ROOT / "specs" / "001-pit-options-rv30" / "contracts" / "phase5-stability-results.schema.json"
)
REQUIRED_CONTRACT_PATHS = frozenset(
    {"specs/001-pit-options-rv30/contracts/phase5-stability-results.schema.json"}
)
REQUIRED_SOURCE_PATHS = frozenset(FROZEN_PHASE5_SOURCE_PATHS)


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"HOLDOUT_JSON_OBJECT_REQUIRED:{path.name}")
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


def _validate_source_code_hashes(method_freeze: Mapping[str, Any]) -> None:
    hashes = method_freeze.get("source_code_hashes")
    if not isinstance(hashes, dict) or not set(hashes) >= REQUIRED_SOURCE_PATHS:
        raise PermissionError("METHOD_FREEZE_SOURCE_HASHES_INCOMPLETE")
    root = ROOT.resolve()
    for relative_path, expected in sorted(hashes.items()):
        path = (ROOT / relative_path).resolve()
        if (
            not isinstance(relative_path, str)
            or not isinstance(expected, str)
            or root not in path.parents
            or not path.is_file()
            or source_sha256(path) != expected
        ):
            raise PermissionError(f"METHOD_FREEZE_SOURCE_HASH_MISMATCH:{relative_path}")


def _validate_contract_hashes(method_freeze: Mapping[str, Any]) -> None:
    hashes = method_freeze.get("contract_hashes")
    if not isinstance(hashes, dict) or not set(hashes) >= REQUIRED_CONTRACT_PATHS:
        raise PermissionError("METHOD_FREEZE_CONTRACT_HASHES_INCOMPLETE")
    for relative_path, expected in sorted(hashes.items()):
        path = ROOT / str(relative_path)
        if not isinstance(expected, str) or not path.is_file() or _sha256_file(path) != expected:
            raise PermissionError(f"METHOD_FREEZE_CONTRACT_HASH_MISMATCH:{relative_path}")


def _validate_panel(
    frame: pl.DataFrame,
    *,
    selected_assets: Sequence[str],
    b2_delay_seconds: int,
) -> pl.DataFrame:
    required = {
        "origin_id",
        "asset",
        "session_date",
        "forecast_origin_utc",
        "rv30",
        "target_price_count",
        "target_future_close_count",
        "target_validity",
        "common_complete",
        "b0_available_at_utc",
        "b0_plus2_available_at_utc",
        "b0_plus2_availability_valid",
        "b1q_max_sip_timestamp_ns",
        "b2_window_end",
        "b2_max_operational_time",
        *(
            source
            for source in (
                "b0_plus2_spot",
                "b0_plus2_rv_5m_lag",
                "b0_plus2_rv_30m_lag",
                "b0_plus2_return_5m_lag",
                "b0_plus2_volume_5m_lag",
            )
        ),
        *development.INFORMATION_SETS["B2"],
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"HOLDOUT_PANEL_COLUMNS_MISSING:{','.join(missing)}")
    selected = frame.filter(pl.col("asset").is_in(selected_assets))
    coverage = selected.group_by("asset", "session_date").len()
    origin_ns = pl.col("forecast_origin_utc").dt.epoch("ns")
    b2_cutoff_ns = origin_ns - b2_delay_seconds * 1_000_000_000
    if (
        b2_delay_seconds < 0
        or sorted(selected["asset"].unique().to_list()) != sorted(selected_assets)
        or sorted(selected["session_date"].unique().to_list()) != list(EXPECTED_HOLDOUT_SESSIONS)
        or coverage.height != len(selected_assets) * len(EXPECTED_HOLDOUT_SESSIONS)
        or selected["origin_id"].n_unique() != selected.height
        or selected.filter(~pl.col("common_complete")).height
        or selected.filter(
            (pl.col("target_price_count") != 31)
            | (pl.col("target_future_close_count") != 30)
            | (pl.col("target_validity") != "valid")
            | (pl.col("rv30") <= 0)
            | (pl.col("b0_available_at_utc") > pl.col("forecast_origin_utc"))
            | ~pl.col("b0_plus2_availability_valid")
            | (pl.col("b0_plus2_available_at_utc") > pl.col("forecast_origin_utc"))
            | (pl.col("b1q_max_sip_timestamp_ns") > origin_ns)
            | pl.col("b2_window_end").is_null()
            | (pl.col("b2_window_end").dt.epoch("ns") > b2_cutoff_ns)
            | (
                pl.col("b2_max_operational_time").is_not_null()
                & (pl.col("b2_max_operational_time") > pl.col("b2_window_end"))
            )
        ).height
    ):
        raise ValueError("HOLDOUT_PANEL_CONTRACT_INVALID")
    return selected.sort("origin_id")


def _validate_stability_sidecar(
    sidecar: pl.DataFrame,
    *,
    primary: pl.DataFrame,
    delays_seconds: Sequence[int],
) -> pl.DataFrame:
    delays = tuple(int(value) for value in delays_seconds)
    if delays != (120, 300):
        raise ValueError("HOLDOUT_STABILITY_DELAYS_INVALID")
    required = {"origin_id"}
    for delay in delays:
        required.update(
            {
                f"b2_window_start__{delay}s",
                f"b2_window_end__{delay}s",
                f"b2_max_operational_time__{delay}s",
                f"b2_option_activity_present__{delay}s",
                *(
                    b2_sensitivity_column(feature, delay)
                    for feature in development.B2_FEATURE_NAMES
                ),
            }
        )
    missing = sorted(required - set(sidecar.columns))
    if missing:
        raise ValueError(f"HOLDOUT_STABILITY_COLUMNS_MISSING:{','.join(missing)}")
    if (
        sidecar.height != primary.height
        or sidecar["origin_id"].n_unique() != sidecar.height
        or set(sidecar["origin_id"]) != set(primary["origin_id"])
    ):
        raise ValueError("HOLDOUT_STABILITY_ORIGIN_MISMATCH")
    checked = sidecar.join(
        primary.select("origin_id", "forecast_origin_utc"),
        on="origin_id",
        how="inner",
    )
    invalid = pl.lit(False)
    for delay in delays:
        end = pl.col(f"b2_window_end__{delay}s")
        start = pl.col(f"b2_window_start__{delay}s")
        operational = pl.col(f"b2_max_operational_time__{delay}s")
        expected_end = pl.col("forecast_origin_utc") - pl.duration(seconds=delay)
        invalid = (
            invalid
            | end.is_null()
            | (end != expected_end)
            | (start != end - pl.duration(minutes=5))
            | (operational.is_not_null() & (operational > end))
            | pl.any_horizontal(
                [
                    ~pl.col(b2_sensitivity_column(feature, delay)).cast(pl.Float64).is_finite()
                    for feature in development.B2_FEATURE_NAMES
                ]
            )
        )
    if checked.filter(invalid).height:
        raise ValueError("HOLDOUT_STABILITY_PANEL_CONTRACT_INVALID")
    return sidecar.sort("origin_id")


def _stability_definition(method_freeze: Mapping[str, Any]) -> dict[str, Any]:
    definition = method_freeze.get("stability_definition")
    if not isinstance(definition, dict):
        raise PermissionError("METHOD_FREEZE_STABILITY_DEFINITION_MISSING")
    regime = definition.get("volatility_regime")
    reversal = definition.get("systematic_reversal_rule")
    if (
        definition.get("session_tercile_upper_bounds") != list(SESSION_TERCILE_BOUNDS)
        or definition.get("fmp_delay_minutes") != list(FMP_DELAYS_MINUTES)
        or definition.get("b2_delay_seconds") != list(B2_DELAYS_SECONDS)
        or definition.get("sensitivity_hyperparameters") != "FROZEN_PRIMARY_WITHOUT_RETUNING"
        or definition.get("confirmatory_role") != "gamma_glm_confirmatory"
        or definition.get("confirmatory_family_expanded") is not False
        or definition.get("operationalization_timing") != "AFTER_DEVELOPMENT_BEFORE_HOLDOUT"
        or definition.get("preregistration_scope")
        != (
            "STABILITY_DIMENSIONS_PREDECLARED;MATERIAL_REVERSAL_THRESHOLD_PRE_HOLDOUT_CLARIFICATION"
        )
        or not isinstance(regime, dict)
        or regime.get("source") != "b0_rv_30m_lag"
        or regime.get("quantiles") != [1 / 3, 2 / 3]
        or regime.get("interpolation") != "linear"
        or regime.get("fit_scope") != "SELECTED_ASSET_DEVELOPMENT_PANEL_ONLY"
        or not isinstance(regime.get("lower_cutpoint"), int | float)
        or not isinstance(regime.get("upper_cutpoint"), int | float)
        or not float(regime["lower_cutpoint"]) < float(regime["upper_cutpoint"])
        or reversal
        != {
            "minimum_sessions_per_stratum": 2,
            "material_negative_definition": "BOOTSTRAP_CI_HIGH_STRICTLY_BELOW_ZERO",
            "minimum_material_negative_strata": 2,
            "minimum_negative_origin_share": 0.5,
            "timing_variant_rule": "ANY_NONPRIMARY_VARIANT_WITH_CI_HIGH_STRICTLY_BELOW_ZERO",
        }
    ):
        raise PermissionError("METHOD_FREEZE_STABILITY_DEFINITION_INVALID")
    return definition


def _parameter_lookup(
    method_freeze: Mapping[str, Any],
) -> dict[tuple[str, str], Mapping[str, float | int]]:
    rows = method_freeze.get("holdout_hyperparameters")
    if not isinstance(rows, list):
        raise ValueError("HOLDOUT_PARAMETERS_MISSING")
    lookup = {
        (str(row["information_set"]), str(row["model_role"])): row["parameters"]
        for row in rows
        if isinstance(row, dict)
    }
    expected = {
        (information_set, role)
        for information_set in development.INFORMATION_SETS
        for role in development.MODEL_ROLES
    }
    if set(lookup) != expected:
        raise ValueError("HOLDOUT_PARAMETERS_INCOMPLETE")
    return lookup


def _forecast_block(
    training: pl.DataFrame,
    testing: pl.DataFrame,
    *,
    information_set: str,
    role: str,
    features: Sequence[str],
    parameters: Mapping[str, float | int],
    method_freeze: Mapping[str, Any],
) -> pl.DataFrame:
    fitted = fit_positive_model(
        training,
        feature_columns=features,
        categorical_columns=("asset",),
        target_column="rv30",
        role=role,
        parameters=parameters,
        seed=int(method_freeze["seed"]),
        forecast_floor=float(method_freeze["forecast_floor"]),
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
        pl.lit(5).alias("fold"),
        pl.lit(role).alias("model_role"),
        pl.lit(information_set).alias("information_set"),
        pl.Series("forecast", predictions),
        pl.Series(
            "qlike_loss",
            qlike_losses(
                target,
                predictions,
                floor=float(method_freeze["forecast_floor"]),
            ),
        ),
        pl.Series("absolute_error", np.abs(errors)),
        pl.Series("squared_error", np.square(errors)),
        pl.lit(json.dumps(parameters, sort_keys=True)).alias("selected_parameters"),
    )


def _stability_contrast_rows(
    forecasts: pl.DataFrame,
    *,
    method_freeze: Mapping[str, Any],
    variant_id: str,
    contrasts: Sequence[tuple[str, str, str]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for role in development.MODEL_ROLES:
        for name, baseline, expanded in contrasts:
            row = development._contrast(
                forecasts,
                role=role,
                name=name,
                baseline=baseline,
                expanded=expanded,
                preregistration=method_freeze,
            )
            row.update(
                {
                    "variant_id": variant_id,
                    "confirmatory_family_member": False,
                    "p_value_holm": None,
                }
            )
            rows.append(row)
    return rows


def _primary_strata(
    forecasts: pl.DataFrame,
    testing: pl.DataFrame,
    *,
    method_freeze: Mapping[str, Any],
    lower: float,
    upper: float,
) -> list[dict[str, Any]]:
    strata = add_stability_strata(testing, lower=lower, upper=upper).select(
        "origin_id",
        "asset",
        "session_tercile",
        "volatility_regime",
    )
    enriched = forecasts.join(strata, on=["origin_id", "asset"], how="inner")
    rows: list[dict[str, Any]] = []
    for dimension in ("asset", "session_tercile", "volatility_regime"):
        for level in sorted(enriched[dimension].unique().to_list()):
            subset = enriched.filter(pl.col(dimension) == level)
            for row in _stability_contrast_rows(
                subset,
                method_freeze=method_freeze,
                variant_id="PRIMARY_FMP_1M_B2_60S",
                contrasts=(
                    ("delta_b1", "B0", "B1a"),
                    ("delta_b2", "B1a", "B2"),
                ),
            ):
                row.update(
                    {
                        "dimension": dimension,
                        "level": level,
                        "origin_count": subset["origin_id"].n_unique(),
                        "session_count": subset["session_date"].n_unique(),
                    }
                )
                rows.append(row)
    return rows


def _fit_frozen_forecasts(
    training: pl.DataFrame,
    testing: pl.DataFrame,
    *,
    method_freeze: Mapping[str, Any],
    parameters: Mapping[tuple[str, str], Mapping[str, float | int]],
    information_sets: Sequence[str],
) -> pl.DataFrame:
    return pl.concat(
        [
            _forecast_block(
                training,
                testing,
                information_set=information_set,
                role=role,
                features=development.INFORMATION_SETS[information_set],
                parameters=parameters[(information_set, role)],
                method_freeze=method_freeze,
            )
            for information_set in information_sets
            for role in development.MODEL_ROLES
        ]
    ).sort(["model_role", "information_set", "origin_id"])


def _timing_sensitivity(
    training: pl.DataFrame,
    testing: pl.DataFrame,
    primary_forecasts: pl.DataFrame,
    *,
    method_freeze: Mapping[str, Any],
    parameters: Mapping[tuple[str, str], Mapping[str, float | int]],
) -> list[dict[str, Any]]:
    paired_contrasts = (
        ("delta_b1", "B0", "B1a"),
        ("delta_b2", "B1a", "B2"),
    )
    rows = _stability_contrast_rows(
        primary_forecasts,
        method_freeze=method_freeze,
        variant_id="FMP_DELAY_1_MINUTE",
        contrasts=paired_contrasts,
    )
    plus2_forecasts = _fit_frozen_forecasts(
        apply_fmp_delay(training, delay_minutes=2),
        apply_fmp_delay(testing, delay_minutes=2),
        method_freeze=method_freeze,
        parameters=parameters,
        information_sets=tuple(development.INFORMATION_SETS),
    )
    rows.extend(
        _stability_contrast_rows(
            plus2_forecasts,
            method_freeze=method_freeze,
            variant_id="FMP_DELAY_2_MINUTES",
            contrasts=paired_contrasts,
        )
    )
    rows.extend(
        _stability_contrast_rows(
            primary_forecasts,
            method_freeze=method_freeze,
            variant_id="B2_DELAY_60_SECONDS",
            contrasts=(("delta_b2", "B1a", "B2"),),
        )
    )
    primary_b1a = primary_forecasts.filter(pl.col("information_set") == "B1a")
    for delay in (120, 300):
        b2_forecasts = _fit_frozen_forecasts(
            apply_b2_delay(training, delay_seconds=delay),
            apply_b2_delay(testing, delay_seconds=delay),
            method_freeze=method_freeze,
            parameters=parameters,
            information_sets=("B2",),
        )
        paired = pl.concat([primary_b1a, b2_forecasts])
        rows.extend(
            _stability_contrast_rows(
                paired,
                method_freeze=method_freeze,
                variant_id=f"B2_DELAY_{delay}_SECONDS",
                contrasts=(("delta_b2", "B1a", "B2"),),
            )
        )
    return rows


def _assess_reversals(
    primary_strata: Sequence[Mapping[str, Any]],
    timing_sensitivity: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for contrast in ("delta_b1", "delta_b2"):
        systematic: list[dict[str, Any]] = []
        for dimension in ("asset", "session_tercile", "volatility_regime"):
            eligible = [
                row
                for row in primary_strata
                if row.get("model_role") == "gamma_glm_confirmatory"
                and row.get("contrast") == contrast
                and row.get("dimension") == dimension
                and int(row.get("session_count", 0)) >= 2
            ]
            adverse = [row for row in eligible if float(row["ci_high"]) < 0]
            total_origins = sum(int(row["origin_count"]) for row in eligible)
            adverse_origins = sum(int(row["origin_count"]) for row in adverse)
            adverse_share = adverse_origins / total_origins if total_origins else 0.0
            if len(adverse) >= 2 and adverse_share >= 0.5:
                systematic.append(
                    {
                        "dimension": dimension,
                        "material_negative_strata": sorted(str(row["level"]) for row in adverse),
                        "negative_origin_share": adverse_share,
                    }
                )
        material_timing = sorted(
            str(row["variant_id"])
            for row in timing_sensitivity
            if row.get("model_role") == "gamma_glm_confirmatory"
            and row.get("contrast") == contrast
            and row.get("variant_id") not in {"FMP_DELAY_1_MINUTE", "B2_DELAY_60_SECONDS"}
            and float(row["ci_high"]) < 0
        )
        result[contrast] = {
            "systematic_stratum_reversals": systematic,
            "material_timing_reversals": material_timing,
            "pass": not systematic and not material_timing,
        }
    return result


def execute_holdout(
    *,
    ledger_path: Path = DEFAULT_LEDGER,
    method_freeze_path: Path = DEFAULT_METHOD_FREEZE,
    development_panel_path: Path = DEFAULT_DEVELOPMENT_PANEL,
    development_stability_path: Path = DEFAULT_DEVELOPMENT_STABILITY,
    holdout_panel_path: Path = DEFAULT_HOLDOUT_PANEL,
    holdout_stability_path: Path = DEFAULT_HOLDOUT_STABILITY,
    forecasts_path: Path = DEFAULT_FORECASTS,
    results_path: Path = DEFAULT_RESULTS,
    stability_results_path: Path = DEFAULT_STABILITY_RESULTS,
    now_utc: datetime | None = None,
) -> dict[str, Any]:
    """Consume the single access token and evaluate the frozen holdout.

    The holdout Parquet is hashed before authorization but is not parsed until
    the access ledger has atomically transitioned from zero reads to one.

    Parameters
    ----------
    ledger_path, method_freeze_path:
        Metadata gates created before analytical access.
    development_panel_path, development_stability_path:
        Frozen training panel and target-blind timing sidecar.
    holdout_panel_path, holdout_stability_path:
        Acquired prospective panel and its sealed timing sidecar.
    forecasts_path, results_path, stability_results_path:
        New compact evidence destinations; existing files fail closed.
    now_utc:
        Aware execution time. Defaults to the current UTC time.

    Returns
    -------
    dict[str, Any]
        Self-hashed one-read holdout result.

    Raises
    ------
    FileExistsError
        If a holdout output already exists.
    PermissionError
        If an access or evidence gate fails.
    ValueError
        If a panel, method or output contract is invalid.
    """
    execution_time = now_utc or datetime.now(UTC)
    if execution_time.astimezone(UTC) < HOLDOUT_PERIOD_COMPLETE_UTC:
        raise PermissionError("HOLDOUT_PERIOD_INCOMPLETE")
    ledger = _read_json(ledger_path)
    method_freeze = _read_json(method_freeze_path)
    if ledger.get("holdout_reads") != 0:
        raise PermissionError("HOLDOUT_ALREADY_READ")
    if forecasts_path.exists() or results_path.exists() or stability_results_path.exists():
        raise FileExistsError("HOLDOUT_OUTPUT_ALREADY_EXISTS")
    if _sha256_file(holdout_panel_path) != ledger.get("panel_sha256"):
        raise PermissionError("HOLDOUT_PANEL_HASH_MISMATCH")
    if _sha256_file(holdout_stability_path) != ledger.get("stability_panel_sha256"):
        raise PermissionError("HOLDOUT_STABILITY_PANEL_HASH_MISMATCH")
    if _sha256_file(development_panel_path) != method_freeze.get("input_hashes", {}).get(
        "common_development_80d.parquet"
    ):
        raise PermissionError("DEVELOPMENT_PANEL_HASH_MISMATCH")
    if _sha256_file(development_stability_path) != method_freeze.get("input_hashes", {}).get(
        "development_stability_inputs_80d.parquet"
    ):
        raise PermissionError("DEVELOPMENT_STABILITY_HASH_MISMATCH")
    frozen_features = {
        key: tuple(value) for key, value in method_freeze.get("information_sets", {}).items()
    }
    if frozen_features != development.INFORMATION_SETS:
        raise PermissionError("HOLDOUT_FEATURE_SCHEMA_MISMATCH")
    b2_delay_seconds = method_freeze.get("timing", {}).get("b2_primary_delay_seconds")
    if not isinstance(b2_delay_seconds, int) or b2_delay_seconds < 0:
        raise PermissionError("METHOD_FREEZE_TIMING_INVALID")
    stability_definition = _stability_definition(method_freeze)
    _validate_source_code_hashes(method_freeze)
    _validate_contract_hashes(method_freeze)
    authorized = authorize_holdout_read(
        ledger,
        method_freeze,
        execution_time,
    )
    _write_json(ledger_path, authorized)

    primary_training = pl.read_parquet(development_panel_path).filter(
        pl.col("asset").is_in(method_freeze["selected_assets"])
    )
    primary_testing = _validate_panel(
        pl.read_parquet(holdout_panel_path),
        selected_assets=method_freeze["selected_assets"],
        b2_delay_seconds=b2_delay_seconds,
    )
    development_sidecar = _validate_stability_sidecar(
        pl.read_parquet(development_stability_path),
        primary=primary_training,
        delays_seconds=(120, 300),
    )
    holdout_sidecar = _validate_stability_sidecar(
        pl.read_parquet(holdout_stability_path),
        primary=primary_testing,
        delays_seconds=(120, 300),
    )
    training = primary_training.join(development_sidecar, on="origin_id", how="inner")
    testing = primary_testing.join(holdout_sidecar, on="origin_id", how="inner")
    regime = stability_definition["volatility_regime"]
    observed_cutpoints = development_volatility_cutpoints(primary_training)
    frozen_cutpoints = (
        float(regime["lower_cutpoint"]),
        float(regime["upper_cutpoint"]),
    )
    if any(
        not math.isclose(observed, frozen, rel_tol=1e-12, abs_tol=1e-18)
        for observed, frozen in zip(observed_cutpoints, frozen_cutpoints, strict=True)
    ):
        raise PermissionError("METHOD_FREEZE_VOLATILITY_CUTPOINT_MISMATCH")
    parameters = _parameter_lookup(method_freeze)
    forecasts = _fit_frozen_forecasts(
        training,
        testing,
        method_freeze=method_freeze,
        parameters=parameters,
        information_sets=tuple(frozen_features),
    )
    if (
        forecasts.height != testing.height * 6
        or forecasts.group_by(["origin_id", "model_role"])
        .agg(pl.col("information_set").n_unique().alias("sets"))
        .filter(pl.col("sets") != 3)
        .height
    ):
        raise ValueError("HOLDOUT_FORECAST_PAIRING_INVALID")
    forecasts.write_parquet(forecasts_path, compression="zstd")

    primary_strata = _primary_strata(
        forecasts,
        testing,
        method_freeze=method_freeze,
        lower=frozen_cutpoints[0],
        upper=frozen_cutpoints[1],
    )
    timing_sensitivity = _timing_sensitivity(
        training,
        testing,
        forecasts,
        method_freeze=method_freeze,
        parameters=parameters,
    )
    stability: dict[str, Any] = {
        "schema_version": "phase5-stability-results-1.0",
        "status": "PASS_SINGLE_HOLDOUT_READ_STABILITY",
        "holdout_reads": 1,
        "evaluated_origin_count": testing.height,
        "stability_definition": stability_definition,
        "primary_strata": primary_strata,
        "timing_sensitivity": timing_sensitivity,
        "reversal_assessment": _assess_reversals(
            primary_strata,
            timing_sensitivity,
        ),
        "confirmatory_family_expanded": False,
        "outcome_reporting": method_freeze["outcome_reporting"],
        "method_freeze_sha256": method_freeze["manifest_sha256"],
        "development_stability_sha256": method_freeze["input_hashes"][
            "development_stability_inputs_80d.parquet"
        ],
        "holdout_stability_sha256": ledger["stability_panel_sha256"],
    }
    stability["manifest_sha256"] = canonical_sha256(stability)
    stability_schema = _read_json(STABILITY_RESULTS_SCHEMA)
    Draft202012Validator.check_schema(stability_schema)
    Draft202012Validator(stability_schema).validate(stability)
    _write_json(stability_results_path, stability)

    metrics = development._metrics(forecasts)
    contrasts = [
        development._contrast(
            forecasts,
            role=role,
            name=name,
            baseline=baseline,
            expanded=expanded,
            preregistration=method_freeze,
        )
        for role in development.MODEL_ROLES
        for name, baseline, expanded in (
            ("delta_b1", "B0", "B1a"),
            ("delta_b2", "B1a", "B2"),
        )
    ]
    adjusted = holm_adjust(
        {
            row["contrast"]: row["p_value_raw"]
            for row in contrasts
            if row["model_role"] == "gamma_glm_confirmatory"
        }
    )
    for row in contrasts:
        row["p_value_holm"] = (
            adjusted[row["contrast"]] if row["model_role"] == "gamma_glm_confirmatory" else None
        )
    result: dict[str, Any] = {
        "schema_version": "phase5-holdout-results-1.0",
        "status": "PASS_HOLDOUT_READ_ONCE",
        "holdout_reads": 1,
        "session_count": len(EXPECTED_HOLDOUT_SESSIONS),
        "evaluated_origin_count": testing.height,
        "forecast_row_count": forecasts.height,
        "selected_assets": method_freeze["selected_assets"],
        "metrics": metrics,
        "contrasts": contrasts,
        "method_freeze_sha256": method_freeze["manifest_sha256"],
        "holdout_access_sha256": authorized["manifest_sha256"],
        "holdout_panel_sha256": ledger["panel_sha256"],
        "forecast_sha256": _sha256_file(forecasts_path),
        "stability_results_sha256": _sha256_file(stability_results_path),
        "outcome_reporting": method_freeze["outcome_reporting"],
    }
    result["manifest_sha256"] = canonical_sha256(result)
    _write_json(results_path, result)
    return result


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Execute the sole frozen Phase 5 holdout read.")
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    parser.add_argument(
        "--method-freeze",
        type=Path,
        default=DEFAULT_METHOD_FREEZE,
    )
    parser.add_argument(
        "--development-panel",
        type=Path,
        default=DEFAULT_DEVELOPMENT_PANEL,
    )
    parser.add_argument(
        "--development-stability",
        type=Path,
        default=DEFAULT_DEVELOPMENT_STABILITY,
    )
    parser.add_argument(
        "--holdout-panel",
        type=Path,
        default=DEFAULT_HOLDOUT_PANEL,
    )
    parser.add_argument(
        "--holdout-stability",
        type=Path,
        default=DEFAULT_HOLDOUT_STABILITY,
    )
    return parser.parse_args()


def main() -> None:
    """Run the one-time holdout command with explicit local paths."""
    arguments = _arguments()
    result = execute_holdout(
        ledger_path=arguments.ledger,
        method_freeze_path=arguments.method_freeze,
        development_panel_path=arguments.development_panel,
        development_stability_path=arguments.development_stability,
        holdout_panel_path=arguments.holdout_panel,
        holdout_stability_path=arguments.holdout_stability,
    )
    print(
        json.dumps(
            {
                "status": result["status"],
                "holdout_reads": result["holdout_reads"],
                "evaluated_origins": result["evaluated_origin_count"],
                "manifest_sha256": result["manifest_sha256"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
