"""Execute the sole prospective Phase 5 holdout read after every gate passes."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
import run_phase5_development_evaluation as development

from mds650.holdout import (
    EXPECTED_HOLDOUT_SESSIONS,
    HOLDOUT_PERIOD_COMPLETE_UTC,
    authorize_holdout_read,
)
from mds650.metrics import holm_adjust, qlike_losses
from mds650.modeling import fit_positive_model
from mds650.study_design import canonical_sha256, source_sha256

ROOT = Path(__file__).resolve().parents[1]
PHASE5 = ROOT / "artifacts" / "phase5"
DEFAULT_LEDGER = PHASE5 / "holdout_access_ledger.json"
DEFAULT_METHOD_FREEZE = PHASE5 / "method_freeze.json"
DEFAULT_DEVELOPMENT_PANEL = PHASE5 / "common_development_80d.parquet"
DEFAULT_HOLDOUT_PANEL = Path("D:/MDS650/data/phase5_holdout/common_holdout_10d.parquet")
DEFAULT_FORECASTS = PHASE5 / "holdout_forecasts.parquet"
DEFAULT_RESULTS = PHASE5 / "holdout_results.json"
REQUIRED_SOURCE_PATHS = frozenset(
    {
        "scripts/run_phase5_development_evaluation.py",
        "scripts/run_phase5_holdout.py",
        "src/mds650/holdout.py",
        "src/mds650/metrics.py",
        "src/mds650/modeling.py",
        "src/mds650/study_design.py",
        "src/mds650/temporal_validation.py",
    }
)


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
        "b1q_max_sip_timestamp_ns",
        "b2_window_end",
        "b2_max_operational_time",
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


def execute_holdout(
    *,
    ledger_path: Path = DEFAULT_LEDGER,
    method_freeze_path: Path = DEFAULT_METHOD_FREEZE,
    development_panel_path: Path = DEFAULT_DEVELOPMENT_PANEL,
    holdout_panel_path: Path = DEFAULT_HOLDOUT_PANEL,
    forecasts_path: Path = DEFAULT_FORECASTS,
    results_path: Path = DEFAULT_RESULTS,
    now_utc: datetime | None = None,
) -> dict[str, Any]:
    """Consume the single access token and evaluate the frozen holdout.

    The holdout Parquet is hashed before authorization but is not parsed until
    the access ledger has atomically transitioned from zero reads to one.

    Parameters
    ----------
    ledger_path, method_freeze_path:
        Metadata gates created before analytical access.
    development_panel_path, holdout_panel_path:
        Frozen training panel and acquired prospective panel.
    forecasts_path, results_path:
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
    if forecasts_path.exists() or results_path.exists():
        raise FileExistsError("HOLDOUT_OUTPUT_ALREADY_EXISTS")
    if _sha256_file(holdout_panel_path) != ledger.get("panel_sha256"):
        raise PermissionError("HOLDOUT_PANEL_HASH_MISMATCH")
    if _sha256_file(development_panel_path) != method_freeze.get("input_hashes", {}).get(
        "common_development_80d.parquet"
    ):
        raise PermissionError("DEVELOPMENT_PANEL_HASH_MISMATCH")
    frozen_features = {
        key: tuple(value) for key, value in method_freeze.get("information_sets", {}).items()
    }
    if frozen_features != development.INFORMATION_SETS:
        raise PermissionError("HOLDOUT_FEATURE_SCHEMA_MISMATCH")
    b2_delay_seconds = method_freeze.get("timing", {}).get("b2_primary_delay_seconds")
    if not isinstance(b2_delay_seconds, int) or b2_delay_seconds < 0:
        raise PermissionError("METHOD_FREEZE_TIMING_INVALID")
    _validate_source_code_hashes(method_freeze)
    authorized = authorize_holdout_read(
        ledger,
        method_freeze,
        execution_time,
    )
    _write_json(ledger_path, authorized)

    training = pl.read_parquet(development_panel_path).filter(
        pl.col("asset").is_in(method_freeze["selected_assets"])
    )
    testing = _validate_panel(
        pl.read_parquet(holdout_panel_path),
        selected_assets=method_freeze["selected_assets"],
        b2_delay_seconds=b2_delay_seconds,
    )
    parameters = _parameter_lookup(method_freeze)
    forecasts = pl.concat(
        [
            _forecast_block(
                training,
                testing,
                information_set=information_set,
                role=role,
                features=features,
                parameters=parameters[(information_set, role)],
                method_freeze=method_freeze,
            )
            for information_set, features in frozen_features.items()
            for role in development.MODEL_ROLES
        ]
    ).sort(["model_role", "information_set", "origin_id"])
    if (
        forecasts.height != testing.height * 6
        or forecasts.group_by(["origin_id", "model_role"])
        .agg(pl.col("information_set").n_unique().alias("sets"))
        .filter(pl.col("sets") != 3)
        .height
    ):
        raise ValueError("HOLDOUT_FORECAST_PAIRING_INVALID")
    forecasts.write_parquet(forecasts_path, compression="zstd")

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
        "--holdout-panel",
        type=Path,
        default=DEFAULT_HOLDOUT_PANEL,
    )
    return parser.parse_args()


def main() -> None:
    """Run the one-time holdout command with explicit local paths."""
    arguments = _arguments()
    result = execute_holdout(
        ledger_path=arguments.ledger,
        method_freeze_path=arguments.method_freeze,
        development_panel_path=arguments.development_panel,
        holdout_panel_path=arguments.holdout_panel,
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
