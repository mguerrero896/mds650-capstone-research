"""Run one preregistered reevaluation with corrected independent B1 inputs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import polars as pl
import run_independent_replication as legacy

from mds650.phase6 import build_phase6_common_panel
from mds650.phase6_evaluation import evaluate_phase6
from mds650.study_design import canonical_sha256

ROOT = Path(__file__).resolve().parents[1]
DATA = Path("D:/MDS650/independent_replication_30/derived")
OUTPUT_DATA = DATA / "pit_v2_evaluation"
ARTIFACT = ROOT / "artifacts" / "independent_replication_pit_v2"
PREREGISTRATION = ARTIFACT / "preregistration.json"
CORRECTED_B1 = DATA / "b1_pit_v2" / "b1v2a_90d_pit_v2.parquet"
PANEL = OUTPUT_DATA / "common_panel_90d_pit_v2.parquet"
COMPLETE_PANEL = OUTPUT_DATA / "common_complete_90d_pit_v2.parquet"
PREDICTIONS = OUTPUT_DATA / "predictions_pit_v2.parquet"
TIMING_PREDICTIONS = OUTPUT_DATA / "timing_predictions_pit_v2.parquet"
RESULTS = ARTIFACT / "results.json"
PANEL_MANIFEST = ARTIFACT / "panel_manifest.json"
TARGET_ACCESS = ARTIFACT / "target_access_ledger.json"
EVALUATION_ACCESS = ARTIFACT / "evaluation_access_ledger.json"
RUN_LOCK = ARTIFACT / "evaluation_run.lock"


def _current_input_hashes() -> dict[str, str]:
    """Recompute every preregistered analytical-input identity."""
    from seal_corrected_independent_preregistration_v1 import _input_hashes

    return _input_hashes()


def _current_source_hashes() -> dict[str, str]:
    """Recompute every preregistered code and environment identity."""
    from seal_corrected_independent_preregistration_v1 import _source_hashes

    return _source_hashes()


def _validate_preregistration(
    path: Path, current_input_hashes: dict[str, str]
) -> dict[str, Any]:
    """Fail closed when preregistration or frozen input identity drifts."""
    payload = legacy._json(path)
    unsigned = {key: value for key, value in payload.items() if key != "preregistration_sha256"}
    if payload.get("preregistration_sha256") != canonical_sha256(unsigned):
        raise RuntimeError("CORRECTED_PREREG_SELF_HASH_INVALID")
    required = {
        "schema_version": "independent-corrected-reevaluation-v1.0",
        "status": "FROZEN_AUTHORIZED_BEFORE_CORRECTED_REEVALUATION",
        "authorized_evaluation_count": 1,
        "corrected_evaluation_performed": False,
        "selection_by_sign": "PROHIBITED",
        "pristine_first_read": False,
    }
    if any(payload.get(key) != value for key, value in required.items()):
        raise RuntimeError("CORRECTED_PREREG_GATE_INVALID")
    frozen = payload.get("input_hashes")
    if not isinstance(frozen, dict) or frozen != current_input_hashes:
        raise RuntimeError("CORRECTED_PREREG_INPUT_HASH_DRIFT")
    if payload.get("secret_values_emitted") or payload.get("personal_paths_emitted"):
        raise RuntimeError("CORRECTED_PREREG_UNSANITIZED")
    return payload


def _validate_runtime() -> dict[str, Any]:
    """Validate preregistration, code hashes, and retained target ledger."""
    preregistration = _validate_preregistration(PREREGISTRATION, _current_input_hashes())
    source_hashes = preregistration.get("source_hashes")
    if not isinstance(source_hashes, dict) or source_hashes != _current_source_hashes():
        raise RuntimeError("CORRECTED_PREREG_SOURCE_HASH_DRIFT")
    access = legacy._json(legacy.TARGET_ACCESS)
    legacy._assert_hashed(access, legacy.TARGET_ACCESS.name)
    if (
        access.get("status") != "TARGET_READ_COMPLETE"
        or access.get("target_read_count") != 1
        or access.get("target_outcome_read") is not True
    ):
        raise RuntimeError("CORRECTED_PRIOR_TARGET_LEDGER_INVALID")
    return preregistration


def _write_parquet_once(frame: pl.DataFrame, path: Path) -> None:
    """Write a Parquet artifact atomically without overwriting evidence."""
    if path.exists():
        raise RuntimeError(f"CORRECTED_OUTPUT_EXISTS:{path.name}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    frame.write_parquet(temporary, compression="zstd")
    temporary.replace(path)


def _claim_evaluation_run(path: Path, preregistration_sha256: str) -> None:
    """Atomically claim the single preregistered evaluation attempt."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="ascii") as handle:
            handle.write(preregistration_sha256)
    except FileExistsError as exc:
        raise RuntimeError(f"CORRECTED_EVALUATION_ALREADY_ATTEMPTED:{path.name}") from exc


def build_panel_once() -> None:
    """Build corrected common panel and record one forensic target reuse."""
    preregistration = _validate_runtime()
    for path in (PANEL, COMPLETE_PANEL, PANEL_MANIFEST, TARGET_ACCESS):
        if path.exists():
            raise RuntimeError(f"CORRECTED_PANEL_ALREADY_ATTEMPTED:{path.name}")
    legacy._write_json(
        TARGET_ACCESS,
        {
            "schema_version": "independent-corrected-target-access-v1.0",
            "status": "CORRECTED_TARGET_REUSE_IN_PROGRESS",
            "prior_target_read_count": 1,
            "corrected_target_reuse_count": 1,
            "pristine_first_read": False,
            "preregistration_sha256": preregistration["preregistration_sha256"],
            "secret_values_emitted": False,
            "personal_paths_emitted": False,
        },
    )
    origins = pl.read_parquet(legacy.ORIGINS)
    b0 = pl.concat(
        [pl.read_parquet(legacy.B0_WARMUP), pl.read_parquet(legacy.B0_TARGET)],
        how="vertical_relaxed",
    ).sort("origin_id")
    b1 = pl.read_parquet(CORRECTED_B1).sort("origin_id")
    acquisition = legacy._json(legacy.ACQUISITION)
    excluded = sorted(str(value) for value in acquisition.get("excluded_provider_sessions", []))
    b2 = legacy._add_provider_gap_rows(
        pl.read_parquet(legacy.B2).sort("origin_id"), origins, excluded
    )
    panel, complete = build_phase6_common_panel(origins, b0, b1, b2)
    panel = panel.sort(["session_date", "forecast_origin_utc", "asset"])
    complete = complete.sort(["session_date", "forecast_origin_utc", "asset"])
    if complete.filter(pl.col("role") == "target").is_empty():
        raise RuntimeError("CORRECTED_TARGET_PANEL_EMPTY")
    _write_parquet_once(panel, PANEL)
    _write_parquet_once(complete, COMPLETE_PANEL)
    legacy._write_json(
        PANEL_MANIFEST,
        {
            "schema_version": "independent-corrected-panel-v1.0",
            "status": "PASS_CORRECTED_COMMON_PANEL",
            "origin_count": panel.height,
            "complete_origin_count": complete.height,
            "target_complete_origin_count": complete.filter(pl.col("role") == "target").height,
            "asset_count": panel["asset"].n_unique(),
            "session_count": panel["session_date"].n_unique(),
            "corrected_b1_sha256": legacy._sha(CORRECTED_B1),
            "panel_sha256": legacy._sha(PANEL),
            "complete_panel_sha256": legacy._sha(COMPLETE_PANEL),
            "preregistration_sha256": preregistration["preregistration_sha256"],
            "pristine_first_read": False,
            "secret_values_emitted": False,
            "personal_paths_emitted": False,
        },
    )
    legacy._write_json(
        TARGET_ACCESS,
        {
            "schema_version": "independent-corrected-target-access-v1.0",
            "status": "CORRECTED_TARGET_REUSE_COMPLETE",
            "prior_target_read_count": 1,
            "corrected_target_reuse_count": 1,
            "cumulative_target_payload_reads": 2,
            "pristine_first_read": False,
            "target_b0_sha256": legacy._sha(legacy.B0_TARGET),
            "complete_panel_sha256": legacy._sha(COMPLETE_PANEL),
            "preregistration_sha256": preregistration["preregistration_sha256"],
            "secret_values_emitted": False,
            "personal_paths_emitted": False,
        },
    )
    print(json.dumps({"status": "PASS_CORRECTED_COMMON_PANEL", "rows": complete.height}))


def evaluate_once() -> None:
    """Fit frozen models and evaluate the corrected independent panel once."""
    preregistration = _validate_runtime()
    target_access = legacy._json(TARGET_ACCESS)
    legacy._assert_hashed(target_access, TARGET_ACCESS.name)
    if target_access.get("status") != "CORRECTED_TARGET_REUSE_COMPLETE":
        raise RuntimeError("CORRECTED_TARGET_REUSE_NOT_COMPLETE")
    for path in (RESULTS, PREDICTIONS, TIMING_PREDICTIONS, EVALUATION_ACCESS, RUN_LOCK):
        if path.exists():
            raise RuntimeError(f"CORRECTED_EVALUATION_ALREADY_ATTEMPTED:{path.name}")
    _claim_evaluation_run(RUN_LOCK, str(preregistration["preregistration_sha256"]))
    legacy._write_json(
        EVALUATION_ACCESS,
        {
            "schema_version": "independent-corrected-evaluation-access-v1.0",
            "status": "CORRECTED_EVALUATION_IN_PROGRESS",
            "evaluation_count": 1,
            "preregistration_sha256": preregistration["preregistration_sha256"],
            "secret_values_emitted": False,
            "personal_paths_emitted": False,
        },
    )
    complete = pl.read_parquet(COMPLETE_PANEL)
    method = legacy._json(legacy.METHOD)
    parameter_manifest = legacy._json(legacy.PARAMETERS)
    parameters = parameter_manifest["parameters"]
    primary = legacy._fit_predict(complete, parameters)
    bars = pl.read_parquet(legacy.BARS)
    origins = pl.read_parquet(legacy.ORIGINS)
    timing_parts = [
        legacy._fit_predict(
            legacy._b0_delay_panel(complete, origins, bars),
            parameters,
            timing_variant="FMP_DELAY_2_MINUTES",
        )
    ]
    variants = legacy._b2_sensitivity_panels(
        complete,
        origins,
        ("window_15m_60s", "window_30m_60s", "latency_5m_120s", "latency_5m_300s"),
    )
    for name, variant in variants.items():
        timing_parts.append(
            legacy._fit_predict(
                variant,
                parameters,
                information_sets=("B2v2",),
                timing_variant=name,
            )
        )
    timing = pl.concat(timing_parts).sort(
        ["timing_variant", "model_role", "information_set", "origin_id"]
    )
    _write_parquet_once(primary, PREDICTIONS)
    _write_parquet_once(timing, TIMING_PREDICTIONS)

    inference = dict(method["inference"])
    inference["bootstrap_repetitions"] = int(inference.get("repetitions", 10000))
    inference["seed"] = int(inference.get("seed", legacy.SEED))
    evaluation_method = {
        "inference": inference,
        "training_mde": legacy._json(ROOT / "artifacts/phase6/method_freeze.json")[
            "training_mde"
        ],
    }
    evaluation = evaluate_phase6(primary, evaluation_method, timing_predictions=timing)
    evaluation["hour_stability"] = legacy._hour_stability(primary, evaluation_method)
    evaluation["calibration"] = legacy._calibration(primary)
    mde = evaluation_method["training_mde"]
    mde_comparison: dict[str, Any] = {}
    for role in legacy.ROLES:
        mde_comparison[role] = {}
        for name in ("delta_b1v2", "delta_b2v2"):
            row = evaluation["global"][role][name]
            threshold = float(mde[name])
            mde_comparison[role][name] = {
                "estimate": float(row["estimate"]),
                "mde": threshold,
                "exceeds_mde": float(row["estimate"]) >= threshold,
                "ci_low": float(row["ci_low"]),
                "ci_high": float(row["ci_high"]),
            }
    legacy._write_json(
        RESULTS,
        {
            "schema_version": "independent-corrected-results-v1.0",
            "status": "CORRECTED_FORENSIC_REEVALUATION_COMPLETE",
            "scientific_role": "CORRECTED_FORENSIC_REEVALUATION",
            "sample_independent_from_phase6": True,
            "pristine_first_read": False,
            "prior_results_input_invalid": True,
            "evaluation_count": 1,
            "target": "RV30",
            "decision": evaluation["decision"],
            "primary_origin_count": primary["origin_id"].n_unique(),
            "primary_forecast_row_count": primary.height,
            "timing_forecast_row_count": timing.height,
            "mde_comparison": mde_comparison,
            "evaluation": evaluation,
            "hashes": {
                "preregistration": legacy._sha(PREREGISTRATION),
                "panel": legacy._sha(PANEL),
                "complete_panel": legacy._sha(COMPLETE_PANEL),
                "predictions": legacy._sha(PREDICTIONS),
                "timing_predictions": legacy._sha(TIMING_PREDICTIONS),
            },
            "all_signs_retained": True,
            "selection_by_sign": "PROHIBITED",
            "secret_values_emitted": False,
            "personal_paths_emitted": False,
        },
    )
    legacy._write_json(
        EVALUATION_ACCESS,
        {
            "schema_version": "independent-corrected-evaluation-access-v1.0",
            "status": "CORRECTED_EVALUATION_COMPLETE",
            "evaluation_count": 1,
            "results_sha256": legacy._sha(RESULTS),
            "preregistration_sha256": preregistration["preregistration_sha256"],
            "secret_values_emitted": False,
            "personal_paths_emitted": False,
        },
    )
    print(
        json.dumps(
            {
                "status": "CORRECTED_FORENSIC_REEVALUATION_COMPLETE",
                "origins": primary["origin_id"].n_unique(),
            }
        )
    )


def main() -> None:
    """Run the corrected panel or its single fixed evaluation."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=("panel", "evaluate"), required=True)
    stage = parser.parse_args().stage
    if stage == "panel":
        build_panel_once()
    else:
        evaluate_once()


if __name__ == "__main__":
    main()
