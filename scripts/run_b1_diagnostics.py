"""Run the 60-session development-only B1v3 mechanism diagnostic."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

import exchange_calendars as xcals  # type: ignore[import-untyped]
import polars as pl

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from mds650.b1_diagnostics import (  # noqa: E402
    build_b1_diagnostic_document,
    chronological_b1_loss_deltas,
    extract_gamma_coefficients,
)
from mds650.b1v3_confirmation import (  # noqa: E402
    canonical_sha256,
    sha256_file,
    validate_confirmation_plan_schema,
    write_json_if_identical,
)
from mds650.b1v3_evaluation import (  # noqa: E402
    b1v3_information_sets,
    b1v3_method_contract,
    b1v3_phase6_adapter_contract,
)
from mds650.b1v3_method_freeze import (  # noqa: E402
    training_only_b1v3_oof_forecasts,
)
from mds650.modeling import fit_positive_model  # noqa: E402
from mds650.phase6_evaluation import (  # noqa: E402
    FORECAST_FLOOR,
    select_phase6_parameters,
)
from mds650.temporal_validation import FoldDefinition  # noqa: E402


def _sessions(start: str, end: str) -> list[str]:
    calendar = xcals.get_calendar("XNYS")
    return [str(value.date()) for value in calendar.sessions_in_range(start, end)]


def _diagnostic_preregistration(
    training: list[str], replication: list[str]
) -> dict[str, Any]:
    document: dict[str, Any] = {
        "schema_version": "b1-diagnostic-adapter-1.0",
        "status": "FROZEN_BEFORE_CONFIRMATION",
        "safe_to_evaluate_b1v3": "NO",
        "outcome_read_count": 0,
        "confirmation_read_count": 0,
        "training_sessions": training,
        "confirmation_sessions": replication,
        "information_sets": {
            name: list(features) for name, features in b1v3_information_sets().items()
        },
        "method": b1v3_method_contract(),
    }
    document["manifest_sha256"] = canonical_sha256(document)
    b1v3_phase6_adapter_contract(document)
    return document


def _json_payload(document: dict[str, Any]) -> bytes:
    return (
        json.dumps(
            document,
            indent=2,
            sort_keys=True,
            ensure_ascii=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _write_csv_immutable(path: Path, frame: pl.DataFrame) -> None:
    payload = frame.write_csv().encode("utf-8")
    write_json_if_identical(path, payload)


def _write_parquet_immutable(path: Path, frame: pl.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, suffix=".parquet", delete=False) as handle:
        temporary = Path(handle.name)
    try:
        frame.write_parquet(temporary, compression="zstd", statistics=True)
        if path.exists():
            if path.read_bytes() != temporary.read_bytes():
                raise ValueError("B1_DIAGNOSTIC_OUTPUT_CONFLICT")
        else:
            os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _read_training_frame(path: Path, sessions: list[str]) -> pl.DataFrame:
    if not path.is_file():
        raise ValueError(f"B1_DIAGNOSTIC_INPUT_MISSING:{path.name}")
    return (
        pl.scan_parquet(path)
        .filter(pl.col("session_date").cast(pl.String).is_in(sessions))
        .collect()
    )


def _assert_scope(frame: pl.DataFrame, sessions: list[str], *, code: str) -> None:
    if (
        frame.is_empty()
        or frame["origin_id"].n_unique() != frame.height
        or set(frame["session_date"].cast(pl.String).unique()) != set(sessions)
        or frame["asset"].n_unique() != 6
    ):
        raise ValueError(code)


def run_diagnostic(args: argparse.Namespace) -> dict[str, Any]:
    """Execute and immutably persist the development-only diagnostic."""
    training = _sessions("2024-09-16", "2024-12-09")
    replication = _sessions("2024-12-10", "2025-01-24")
    preregistration = _diagnostic_preregistration(training, replication)
    predictors = _read_training_frame(args.predictors, training)
    evaluation = _read_training_frame(args.evaluation_panel, training)
    attempts = _read_training_frame(args.iv_attempts, training)
    _assert_scope(predictors, training, code="B1_DIAGNOSTIC_PREDICTOR_SCOPE_INVALID")
    _assert_scope(evaluation, training, code="B1_DIAGNOSTIC_EVALUATION_SCOPE_INVALID")
    attempts = attempts.join(
        predictors.select("origin_id"), on="origin_id", how="inner", validate="m:1"
    )
    if attempts.is_empty() or set(attempts["session_date"].cast(pl.String).unique()) != set(
        training
    ):
        raise ValueError("B1_DIAGNOSTIC_ATTEMPT_SCOPE_INVALID")
    if evaluation.filter(
        ~pl.col("rv30").is_finite() | (pl.col("rv30") <= 0)
    ).height:
        raise ValueError("B1_DIAGNOSTIC_TRAINING_TARGET_INVALID")

    forecasts, tuning_records = training_only_b1v3_oof_forecasts(
        evaluation, preregistration
    )
    loss_deltas = chronological_b1_loss_deltas(forecasts)
    adapter = b1v3_phase6_adapter_contract(preregistration)
    fold = FoldDefinition(
        fold=900,
        train_end=date.fromisoformat(training[-1]),
        test_start=date.fromisoformat(replication[0]),
        test_end=date.fromisoformat(replication[-1]),
    )
    coefficient_rows: list[dict[str, Any]] = []
    final_tuning: list[dict[str, Any]] = []
    for information_set in ("B0", "B1v3a"):
        features = b1v3_information_sets()[information_set]
        selected, records = select_phase6_parameters(
            evaluation,
            fold=fold,
            information_set=information_set,
            features=features,
            role="gamma_glm_confirmatory",
            preregistration=adapter,
        )
        final_tuning.extend(records)
        fitted = fit_positive_model(
            evaluation,
            feature_columns=features,
            categorical_columns=("b0v2_asset_identity",),
            target_column="rv30",
            role="gamma_glm_confirmatory",
            parameters=selected,
            seed=int(adapter["inference"]["seed"]),
            forecast_floor=FORECAST_FLOOR,
        )
        coefficient_rows.extend(
            extract_gamma_coefficients(
                fitted,
                information_set=information_set,
                selected_parameters=selected,
            )
        )

    source_hashes = {
        "common_predictor_panel": sha256_file(args.predictors),
        "development_evaluation_panel": sha256_file(args.evaluation_panel),
        "iv_attempts": sha256_file(args.iv_attempts),
        "diagnostic_module": sha256_file(ROOT / "src/mds650/b1_diagnostics.py"),
        "diagnostic_runner": sha256_file(Path(__file__)),
    }
    document = build_b1_diagnostic_document(
        feature_frame=predictors,
        attempt_frame=attempts,
        training_sessions=training,
        replication_sessions=replication,
        source_hashes=source_hashes,
        chronological_loss_deltas=loss_deltas,
        gamma_coefficients=coefficient_rows,
    )
    validate_confirmation_plan_schema(document, args.schema)
    if document["manifest_sha256"] != canonical_sha256(
        {key: value for key, value in document.items() if key != "manifest_sha256"}
    ):
        raise ValueError("B1_DIAGNOSTIC_SELF_HASH_INVALID")
    payload = _json_payload(document)
    if any(
        token in payload.lower()
        for token in (b"c:\\users\\", b"c:/users/", b"api_key", b"bearer ")
    ):
        raise ValueError("B1_DIAGNOSTIC_HYGIENE_FAILURE")
    args.output_root.mkdir(parents=True, exist_ok=True)
    output_paths = {
        "diagnostic": args.output_root / "diagnostic.json",
        "reason_waterfall": args.output_root / "reason_waterfall.csv",
        "quote_quality": args.output_root / "quote_quality.csv",
        "iv_geometry": args.output_root / "iv_geometry.csv",
        "lag_availability": args.output_root / "lag_availability.csv",
        "feature_distributions": args.output_root / "feature_distributions.csv",
        "chronological_loss_deltas": args.output_root
        / "chronological_loss_deltas.csv",
        "gamma_coefficients": args.output_root / "gamma_coefficients.csv",
        "oof_forecasts": args.output_root / "chronological_oof_forecasts.parquet",
        "tuning_ledger": args.output_root / "training_tuning_ledger.json",
    }
    write_json_if_identical(output_paths["diagnostic"], payload)
    for key in (
        "reason_waterfall",
        "quote_quality",
        "iv_geometry",
        "lag_availability",
        "feature_distributions",
        "chronological_loss_deltas",
        "gamma_coefficients",
    ):
        _write_csv_immutable(
            output_paths[key], pl.DataFrame(document[key], infer_schema_length=None)
        )
    _write_parquet_immutable(output_paths["oof_forecasts"], forecasts)
    tuning_document: dict[str, Any] = {
        "schema_version": "b1-diagnostic-tuning-ledger-1.0",
        "replication_target_reads": 0,
        "oof_records": tuning_records,
        "final_gamma_records": final_tuning,
    }
    tuning_document["manifest_sha256"] = canonical_sha256(tuning_document)
    write_json_if_identical(
        output_paths["tuning_ledger"], _json_payload(tuning_document)
    )
    evidence = pl.DataFrame(
        [
            {
                "logical_path": f"diagnostic/{path.name}",
                "sha256": sha256_file(path),
                "bytes": path.stat().st_size,
            }
            for path in output_paths.values()
        ]
    ).sort("logical_path")
    _write_csv_immutable(args.output_root / "evidence_index.csv", evidence)
    return document


def _parser() -> argparse.ArgumentParser:
    data_root = Path(
        os.environ.get(
            "MDS650_B1V3_DATA_ROOT", r"D:\MDS650\b1v3_confirmation"
        )
    )
    parser = argparse.ArgumentParser(
        description="Run the development-only B1v3 mechanism diagnostic."
    )
    parser.add_argument(
        "--predictors",
        type=Path,
        default=data_root / "predictors/common_predictor_panel.parquet",
    )
    parser.add_argument(
        "--evaluation-panel",
        type=Path,
        default=data_root / "evaluation/evaluation_panel.parquet",
    )
    parser.add_argument(
        "--iv-attempts",
        type=Path,
        default=data_root / "tmp/b1q_acquisition_v1/b1_iv_attempts_20d.parquet",
    )
    parser.add_argument(
        "--schema",
        type=Path,
        default=ROOT
        / "specs/001-pit-options-rv30/contracts/b1-diagnostic-v1.schema.json",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=ROOT / "artifacts/b1_diagnostic_replication/diagnostic",
    )
    return parser


def main() -> int:
    """Execute the diagnostic and print a sanitized completion summary."""
    document = run_diagnostic(_parser().parse_args())
    print(
        json.dumps(
            {
                "status": document["status"],
                "feature_origin_count": document["scope"]["feature_origin_count"],
                "attempt_count": document["scope"]["attempt_count"],
                "replication_target_reads": 0,
                "manifest_sha256": document["manifest_sha256"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
