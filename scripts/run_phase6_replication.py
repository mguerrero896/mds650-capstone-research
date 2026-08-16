"""Execute the sole preregistered Phase 6 five-fold OOS replication."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import polars as pl

from mds650.phase6_evaluation import (
    add_training_volatility_regime,
    authorize_phase6_oos,
    forecast_phase6_fold,
    phase6_fold_definitions,
    phase6_information_sets,
    replace_phase6_features,
    select_phase6_parameters,
    validate_phase6_evaluation_panel,
)
from mds650.study_design import canonical_sha256
from mds650.temporal_validation import split_expanding_fold

ROOT = Path(__file__).resolve().parents[1]
PHASE6 = ROOT / "artifacts" / "phase6"
PANEL_PATH = PHASE6 / "common_panel.parquet"
COMMON_MANIFEST_PATH = PHASE6 / "common_panel_manifest.json"
PREREGISTRATION_PATH = PHASE6 / "preregistration.json"
METHOD_FREEZE_PATH = PHASE6 / "method_freeze.json"
ACCESS_LEDGER_PATH = PHASE6 / "oos_access_ledger.json"
PREDICTIONS_PATH = PHASE6 / "oos_predictions.parquet"
SENSITIVITY_PREDICTIONS_PATH = PHASE6 / "oos_sensitivity_predictions.parquet"
VARIANT_LEDGER_PATH = PHASE6 / "oos_variant_ledger.json"
REPLICATION_MANIFEST_PATH = PHASE6 / "replication_manifest.json"
B0_SENSITIVITY_PATH = PHASE6 / "b0v2_sensitivities.parquet"
B2_SENSITIVITY_PATH = PHASE6 / "b2v2_sensitivities.parquet"
MODEL_ROLES = ("gamma_glm_confirmatory", "lightgbm_robustness")
KEYS = ("origin_id", "asset", "session_date", "forecast_origin_utc")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"PHASE6_JSON_OBJECT_REQUIRED:{path.name}")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _aligned_sensitivity(
    panel: pl.DataFrame, sensitivity: pl.DataFrame, spec: str
) -> pl.DataFrame:
    selected = sensitivity.filter(pl.col("sensitivity_spec") == spec).drop(
        "sensitivity_spec"
    )
    aligned = panel.select(KEYS).join(selected, on=KEYS, how="inner", validate="1:1")
    if aligned.height != panel.height:
        raise RuntimeError(f"PHASE6_SENSITIVITY_ORIGIN_MISMATCH:{spec}")
    return aligned


def _complete_feature_rows(
    panel: pl.DataFrame, features: tuple[str, ...]
) -> pl.DataFrame:
    numeric = tuple(name for name in features if name != "b0v2_asset_identity")
    return panel.filter(
        pl.all_horizontal(pl.col(name).is_finite() for name in numeric)
        & pl.col("b0v2_asset_identity").is_not_null()
    )


def main() -> None:
    """Consume the one-read gate and write all registered OOS forecasts once."""
    preregistration = _read_json(PREREGISTRATION_PATH)
    method = _read_json(METHOD_FREEZE_PATH)
    common = _read_json(COMMON_MANIFEST_PATH)
    ledger = _read_json(ACCESS_LEDGER_PATH)
    method_unsigned = {
        key: value for key, value in method.items() if key != "manifest_sha256"
    }
    if (
        method.get("status") != "FROZEN_AFTER_TRAINING_BEFORE_OOS"
        or method.get("oos_read_count") != 0
        or method.get("manifest_sha256") != canonical_sha256(method_unsigned)
        or method.get("input_hashes", {}).get("common_panel.parquet")
        != _sha256(PANEL_PATH)
        or common.get("status") != "SEALED_BEFORE_OOS"
        or common.get("common_panel_sha256") != _sha256(PANEL_PATH)
    ):
        raise RuntimeError("PHASE6_METHOD_OR_PANEL_FREEZE_INVALID")
    authorized = authorize_phase6_oos(
        ledger,
        common_panel_sha256=_sha256(PANEL_PATH),
        preregistration_manifest_sha256=preregistration["manifest_sha256"],
        results_exist=any(
            path.exists()
            for path in (
                PREDICTIONS_PATH,
                SENSITIVITY_PREDICTIONS_PATH,
                VARIANT_LEDGER_PATH,
                REPLICATION_MANIFEST_PATH,
            )
        ),
    )
    _write_json(ACCESS_LEDGER_PATH, authorized)

    panel = validate_phase6_evaluation_panel(
        pl.read_parquet(PANEL_PATH), preregistration
    )
    information_sets = phase6_information_sets()
    if (
        method.get("input_hashes", {}).get("b0v2_sensitivities.parquet")
        != _sha256(B0_SENSITIVITY_PATH)
        or method.get("input_hashes", {}).get("b2v2_sensitivities.parquet")
        != _sha256(B2_SENSITIVITY_PATH)
    ):
        raise RuntimeError("PHASE6_SENSITIVITY_FREEZE_INVALID")
    b0_sensitivity = _aligned_sensitivity(
        panel, pl.read_parquet(B0_SENSITIVITY_PATH), "FMP_DELAY_2_MINUTES"
    )
    fmp_delay_panel = _complete_feature_rows(
        replace_phase6_features(
            panel,
            b0_sensitivity,
            columns=information_sets["B0v2"],
        ),
        information_sets["B2v2"],
    )
    b2_sensitivity_source = pl.read_parquet(B2_SENSITIVITY_PATH)
    b2_sensitivity_panels = {
        spec: _complete_feature_rows(
            replace_phase6_features(
                panel,
                _aligned_sensitivity(panel, b2_sensitivity_source, spec),
                columns=information_sets["B2v2"][
                    -len(preregistration["b2v2_feature_names"]) :
                ],
            ),
            information_sets["B2v2"],
        )
        for spec in (
            "window_15m_60s",
            "window_30m_60s",
            "latency_5m_120s",
            "latency_5m_300s",
        )
    }
    guard = int(preregistration["models"]["purge_embargo_minutes"])
    forecast_parts: list[pl.DataFrame] = []
    sensitivity_parts: list[pl.DataFrame] = []
    variants: list[dict[str, Any]] = []
    selections: list[dict[str, Any]] = []
    regime_cutpoints: list[dict[str, Any]] = []
    for fold in phase6_fold_definitions(preregistration):
        training, testing = split_expanding_fold(
            panel,
            fold,
            purge_minutes=guard,
            embargo_minutes=guard,
        )
        testing, cutpoints = add_training_volatility_regime(training, testing)
        regime_cutpoints.append({"fold": fold.fold, **cutpoints})
        selected_by_set_role: dict[tuple[str, str], dict[str, float | int]] = {}
        for information_set, features in information_sets.items():
            for role in MODEL_ROLES:
                selected, records = select_phase6_parameters(
                    training,
                    fold=fold,
                    information_set=information_set,
                    features=features,
                    role=role,
                    preregistration=preregistration,
                )
                variants.extend(records)
                selected_by_set_role[(information_set, role)] = selected
                selections.append(
                    {
                        "fold": fold.fold,
                        "information_set": information_set,
                        "model_role": role,
                        "parameters": selected,
                    }
                )
                forecast_parts.append(
                    forecast_phase6_fold(
                        training,
                        testing,
                        fold=fold,
                        information_set=information_set,
                        features=features,
                        role=role,
                        parameters=selected,
                        preregistration=preregistration,
                    ).with_columns(pl.lit("PRIMARY").alias("timing_variant"))
                )
        delayed_training, delayed_testing = split_expanding_fold(
            fmp_delay_panel,
            fold,
            purge_minutes=guard,
            embargo_minutes=guard,
        )
        delayed_testing, _ = add_training_volatility_regime(
            delayed_training, delayed_testing
        )
        for information_set, features in information_sets.items():
            for role in MODEL_ROLES:
                sensitivity_parts.append(
                    forecast_phase6_fold(
                        delayed_training,
                        delayed_testing,
                        fold=fold,
                        information_set=information_set,
                        features=features,
                        role=role,
                        parameters=selected_by_set_role[(information_set, role)],
                        preregistration=preregistration,
                    ).with_columns(
                        pl.lit("FMP_DELAY_2_MINUTES").alias("timing_variant")
                    )
                )
        for spec, sensitivity_panel in b2_sensitivity_panels.items():
            variant_training, variant_testing = split_expanding_fold(
                sensitivity_panel,
                fold,
                purge_minutes=guard,
                embargo_minutes=guard,
            )
            variant_testing, _ = add_training_volatility_regime(
                variant_training, variant_testing
            )
            for role in MODEL_ROLES:
                sensitivity_parts.append(
                    forecast_phase6_fold(
                        variant_training,
                        variant_testing,
                        fold=fold,
                        information_set="B2v2",
                        features=information_sets["B2v2"],
                        role=role,
                        parameters=selected_by_set_role[("B2v2", role)],
                        preregistration=preregistration,
                    ).with_columns(pl.lit(spec).alias("timing_variant"))
                )
        print(json.dumps({"fold": fold.fold, "status": "PASS"}), flush=True)
    forecasts = pl.concat(forecast_parts).sort(
        ["fold", "model_role", "information_set", "origin_id"]
    )
    expected = forecasts["origin_id"].n_unique()
    if (
        expected == 0
        or forecasts.height != expected * len(information_sets) * len(MODEL_ROLES)
        or forecasts.group_by(["origin_id", "model_role"])
        .agg(pl.col("information_set").n_unique().alias("sets"))
        .filter(pl.col("sets") != len(information_sets))
        .height
    ):
        raise RuntimeError("PHASE6_OOS_FORECAST_PAIRING_FAILURE")
    forecasts.write_parquet(PREDICTIONS_PATH, compression="zstd")
    sensitivity_forecasts = pl.concat(sensitivity_parts).sort(
        ["timing_variant", "fold", "model_role", "information_set", "origin_id"]
    )
    sensitivity_forecasts.write_parquet(
        SENSITIVITY_PREDICTIONS_PATH, compression="zstd"
    )
    variant_ledger = {
        "schema_version": "phase6-oos-variant-ledger-1.0",
        "status": "COMPLETE_UNREPORTED",
        "oos_read_count": 1,
        "variants": variants,
        "selected_variants": selections,
        "volatility_regime_cutpoints": regime_cutpoints,
        "all_variants_retained": True,
    }
    variant_ledger["manifest_sha256"] = canonical_sha256(variant_ledger)
    _write_json(VARIANT_LEDGER_PATH, variant_ledger)
    manifest = {
        "schema_version": "phase6-replication-1.0",
        "status": "OOS_EVALUATION_COMPLETE_UNREPORTED",
        "oos_read_count": 1,
        "evaluated_origin_count": expected,
        "forecast_row_count": forecasts.height,
        "fold_count": 5,
        "information_sets": list(information_sets),
        "model_roles": list(MODEL_ROLES),
        "predictions_sha256": _sha256(PREDICTIONS_PATH),
        "sensitivity_predictions_sha256": _sha256(SENSITIVITY_PREDICTIONS_PATH),
        "variant_ledger_sha256": _sha256(VARIANT_LEDGER_PATH),
        "method_freeze_sha256": _sha256(METHOD_FREEZE_PATH),
        "common_panel_sha256": _sha256(PANEL_PATH),
        "results_inspected": False,
        "all_signs_retained": True,
        "secret_values_emitted": False,
        "personal_paths_emitted": False,
    }
    manifest["manifest_sha256"] = canonical_sha256(manifest)
    _write_json(REPLICATION_MANIFEST_PATH, manifest)
    completed_ledger = {
        **{
            key: value
            for key, value in authorized.items()
            if key != "manifest_sha256"
        },
        "status": "OOS_CONSUMED_RESULTS_UNREPORTED",
        "replication_manifest_sha256": manifest["manifest_sha256"],
        "results_inspected": False,
    }
    completed_ledger["manifest_sha256"] = canonical_sha256(completed_ledger)
    _write_json(ACCESS_LEDGER_PATH, completed_ledger)
    print(json.dumps(manifest, sort_keys=True))


if __name__ == "__main__":
    main()
