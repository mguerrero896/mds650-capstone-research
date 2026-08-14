"""Freeze B1v3 model choices and MDE using only the 60 development sessions."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import polars as pl

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from mds650.b1v3_confirmation import (  # noqa: E402
    canonical_sha256,
    sha256_file,
    validate_confirmation_plan_schema,
)
from mds650.b1v3_method_freeze import (  # noqa: E402
    bind_b1v3_training_targets,
    build_b1v3_method_freeze,
    select_b1v3_final_parameters,
    training_mde_from_b1v3_forecasts,
    training_only_b1v3_oof_forecasts,
    training_volatility_regime_cutpoints,
)
from mds650.phase6 import build_b0v2_features  # noqa: E402

_FORBIDDEN = (
    b"c:\\users\\",
    b"c:/users/",
    b"d:\\mds650",
    b"d:/mds650",
    b"api_key",
    b"apikey",
    b"authorization",
    b"bearer ",
)


def _read_mapping(path: Path, error: str) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(error) from exc
    if not isinstance(document, dict):
        raise ValueError(error)
    return document


def _validate_self_hash(document: Mapping[str, Any], error: str) -> None:
    stored = document.get("manifest_sha256")
    unsigned = {key: value for key, value in document.items() if key != "manifest_sha256"}
    if not isinstance(stored, str) or stored != canonical_sha256(unsigned):
        raise ValueError(error)


def _write_json_if_identical(path: Path, document: Mapping[str, Any]) -> str:
    payload = (json.dumps(document, indent=2, sort_keys=True, ensure_ascii=True) + "\n").encode(
        "utf-8"
    )
    if any(token in payload.lower() for token in _FORBIDDEN):
        raise ValueError("B1V3_METHOD_OUTPUT_HYGIENE_INVALID")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != payload:
            raise ValueError(f"B1V3_METHOD_OUTPUT_CONFLICT:{path.name}")
        return sha256_file(path)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".part", dir=path.parent
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        temporary.write_bytes(payload)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return sha256_file(path)


def _write_parquet_if_identical(path: Path, frame: pl.DataFrame) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if not pl.read_parquet(path).equals(frame, null_equal=True):
            raise ValueError(f"B1V3_METHOD_OUTPUT_CONFLICT:{path.name}")
        return sha256_file(path)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".part", dir=path.parent
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        frame.write_parquet(temporary, compression="zstd", statistics=True)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return sha256_file(path)


def _validate_sources(
    *,
    preregistration: Mapping[str, Any],
    common_manifest: Mapping[str, Any],
    base_manifest: Mapping[str, Any],
    common_manifest_path: Path,
    common_panel_path: Path,
    fmp_bars_path: Path,
) -> None:
    common_output = common_manifest.get("output")
    source_bindings = common_manifest.get("source_bindings")
    base_outputs = base_manifest.get("outputs")
    fmp_output = base_outputs.get("fmp_bars") if isinstance(base_outputs, Mapping) else None
    invalid = (
        preregistration.get("status") != "FROZEN_BEFORE_CONFIRMATION"
        or preregistration.get("outcome_read_count") != 0
        or preregistration.get("confirmation_read_count") != 0
        or preregistration.get("safe_to_evaluate_b1v3") != "NO"
        or common_manifest.get("status")
        != "PASS_TARGET_BLIND_COMMON_PREDICTOR_PANEL"
        or common_manifest.get("target_blind") is not True
        or common_manifest.get("outcome_read_count") != 0
        or preregistration.get("common_predictor_manifest_sha256")
        != common_manifest.get("manifest_sha256")
        or preregistration.get("common_predictor_manifest_file_sha256")
        != sha256_file(common_manifest_path)
        or not isinstance(common_output, Mapping)
        or common_output.get("sha256") != sha256_file(common_panel_path)
        or preregistration.get("common_predictor_panel_sha256")
        != common_output.get("sha256")
        or not isinstance(source_bindings, Mapping)
        or source_bindings.get("base_manifest_sha256")
        != base_manifest.get("manifest_sha256")
        or base_manifest.get("status") != "PASS_TARGET_BLIND_BASE_PREDICTORS"
        or base_manifest.get("target_blind") is not True
        or base_manifest.get("outcome_read_count") != 0
        or base_manifest.get("plan_sha256") != preregistration.get("plan_sha256")
        or not isinstance(fmp_output, Mapping)
        or fmp_output.get("sha256") != sha256_file(fmp_bars_path)
    )
    if invalid:
        raise ValueError("B1V3_METHOD_SOURCE_BINDING_INVALID")


def freeze_b1v3_method(
    *,
    preregistration_path: Path,
    preregistration_schema_path: Path,
    common_manifest_path: Path,
    common_manifest_schema_path: Path,
    common_panel_path: Path,
    base_manifest_path: Path,
    base_manifest_schema_path: Path,
    fmp_bars_path: Path,
    method_code_path: Path,
    runner_code_path: Path,
    uv_lock_path: Path,
    training_panel_path: Path,
    oof_forecasts_path: Path,
    tuning_ledger_path: Path,
    method_freeze_path: Path,
    method_freeze_schema_path: Path,
) -> dict[str, Any]:
    """Build and seal the development-only B1v3 method freeze.

    Parameters
    ----------
    preregistration_path, common_manifest_path, base_manifest_path:
        Immutable source-bound control manifests.
    common_panel_path, fmp_bars_path:
        Target-blind common predictors and authenticated FMP one-minute bars.
    method_code_path, runner_code_path, uv_lock_path:
        Exact implementation and environment identities.
    training_panel_path, oof_forecasts_path, tuning_ledger_path,
    method_freeze_path:
        Immutable destinations for training-only evidence.
    *_schema_path:
        Draft 2020-12 input and output contracts.

    Returns
    -------
    dict[str, Any]
        Self-hashed method freeze with confirmation reads still equal to zero.

    Raises
    ------
    ValueError
        If a source, date, target, model, hash, schema, hygiene, or idempotence
        invariant fails.

    Notes
    -----
    Confirmation rows are removed before target construction.  The FMP scan is
    filtered to the 60 development sessions, so this command does not compute
    or expose the 30-session confirmation target.
    """
    preregistration = _read_mapping(
        preregistration_path, "B1V3_METHOD_PREREGISTRATION_INVALID"
    )
    common_manifest = _read_mapping(
        common_manifest_path, "B1V3_METHOD_COMMON_MANIFEST_INVALID"
    )
    base_manifest = _read_mapping(base_manifest_path, "B1V3_METHOD_BASE_MANIFEST_INVALID")
    validate_confirmation_plan_schema(preregistration, preregistration_schema_path)
    validate_confirmation_plan_schema(common_manifest, common_manifest_schema_path)
    validate_confirmation_plan_schema(base_manifest, base_manifest_schema_path)
    _validate_self_hash(preregistration, "B1V3_METHOD_PREREGISTRATION_HASH_INVALID")
    _validate_self_hash(common_manifest, "B1V3_METHOD_COMMON_MANIFEST_HASH_INVALID")
    _validate_self_hash(base_manifest, "B1V3_METHOD_BASE_MANIFEST_HASH_INVALID")
    for source in (
        common_panel_path,
        fmp_bars_path,
        method_code_path,
        runner_code_path,
        uv_lock_path,
    ):
        if not source.is_file():
            raise ValueError(f"B1V3_METHOD_SOURCE_MISSING:{source.name}")
    _validate_sources(
        preregistration=preregistration,
        common_manifest=common_manifest,
        base_manifest=base_manifest,
        common_manifest_path=common_manifest_path,
        common_panel_path=common_panel_path,
        fmp_bars_path=fmp_bars_path,
    )
    common = pl.read_parquet(common_panel_path)
    training_sessions = [str(value) for value in preregistration["training_sessions"]]
    development_origins = common.filter(pl.col("role") == "development").select(
        "origin_id",
        "asset",
        "session_date",
        "forecast_origin_utc",
        "role",
        "session_minute",
        "session_tercile",
    )
    training_bars = (
        pl.scan_parquet(fmp_bars_path)
        .filter(pl.col("session_date").cast(pl.String).is_in(training_sessions))
        .collect()
    )
    targets = build_b0v2_features(
        training_bars,
        development_origins,
        delay_minutes=1,
        include_target=True,
    )
    training_panel = bind_b1v3_training_targets(
        common,
        targets,
        preregistration=preregistration,
    )
    training_panel_hash = _write_parquet_if_identical(
        training_panel_path, training_panel
    )
    forecasts, oof_records = training_only_b1v3_oof_forecasts(
        training_panel,
        preregistration,
    )
    oof_hash = _write_parquet_if_identical(oof_forecasts_path, forecasts)
    selected, final_records = select_b1v3_final_parameters(
        training_panel,
        preregistration,
    )
    tuning_document: dict[str, Any] = {
        "schema_version": "1.0",
        "status": "PASS_TRAINING_ONLY_TUNING",
        "training_read_count": 1,
        "confirmation_read_count": 0,
        "preregistration_manifest_sha256": preregistration["manifest_sha256"],
        "record_count": len(oof_records) + len(final_records),
        "records": [
            {**record, "stage": "OOF_MDE"} for record in oof_records
        ]
        + [{**record, "stage": "FINAL_SELECTION"} for record in final_records],
    }
    tuning_document["manifest_sha256"] = canonical_sha256(tuning_document)
    tuning_hash = _write_json_if_identical(tuning_ledger_path, tuning_document)
    adapter = preregistration["method"]["inference"]
    mde = training_mde_from_b1v3_forecasts(
        forecasts,
        draws=int(adapter["bootstrap_repetitions"]),
        seed=int(adapter["seed"]),
    )
    cutpoints = training_volatility_regime_cutpoints(training_panel)
    code_bundle_sha256 = canonical_sha256(
        {
            "method_module_sha256": sha256_file(method_code_path),
            "runner_sha256": sha256_file(runner_code_path),
        }
    )
    method_freeze = build_b1v3_method_freeze(
        preregistration,
        common_panel_sha256=sha256_file(common_panel_path),
        training_panel_sha256=training_panel_hash,
        training_target_source_sha256=sha256_file(fmp_bars_path),
        oof_forecasts_sha256=oof_hash,
        tuning_ledger_sha256=tuning_hash,
        method_freeze_code_sha256=code_bundle_sha256,
        uv_lock_sha256=sha256_file(uv_lock_path),
        selected_parameters=selected,
        training_mde=mde,
        volatility_regime_cutpoints=cutpoints,
        row_count=training_panel.height,
    )
    validate_confirmation_plan_schema(method_freeze, method_freeze_schema_path)
    _validate_self_hash(method_freeze, "B1V3_METHOD_FREEZE_HASH_INVALID")
    _write_json_if_identical(method_freeze_path, method_freeze)
    return method_freeze


def _arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    contracts = ROOT / "specs" / "001-pit-options-rv30" / "contracts"
    evaluation_root = Path("D:/MDS650/b1v3_confirmation/evaluation")
    parser.add_argument(
        "--preregistration",
        type=Path,
        default=ROOT
        / "artifacts"
        / "b1v3_confirmation_preregistration"
        / "preregistration.json",
    )
    parser.add_argument(
        "--preregistration-schema",
        type=Path,
        default=contracts / "b1v3-preregistration-v1.schema.json",
    )
    parser.add_argument(
        "--common-manifest",
        type=Path,
        default=ROOT
        / "artifacts"
        / "b1v3_confirmation_panel"
        / "common_predictor_manifest.json",
    )
    parser.add_argument(
        "--common-manifest-schema",
        type=Path,
        default=contracts / "b1v3-confirmation-common-predictor-v1.schema.json",
    )
    parser.add_argument(
        "--common-panel",
        type=Path,
        default=Path(
            "D:/MDS650/b1v3_confirmation/predictors/common_predictor_panel.parquet"
        ),
    )
    parser.add_argument(
        "--base-manifest",
        type=Path,
        default=ROOT
        / "artifacts"
        / "b1v3_confirmation_panel"
        / "base_predictor_manifest.json",
    )
    parser.add_argument(
        "--base-manifest-schema",
        type=Path,
        default=contracts / "b1v3-confirmation-base-predictors-v1.schema.json",
    )
    parser.add_argument(
        "--fmp-bars",
        type=Path,
        default=Path(
            "D:/MDS650/b1v3_confirmation/predictors/underlying_1min_target_blind.parquet"
        ),
    )
    parser.add_argument(
        "--method-code",
        type=Path,
        default=ROOT / "src" / "mds650" / "b1v3_method_freeze.py",
    )
    parser.add_argument("--runner-code", type=Path, default=Path(__file__).resolve())
    parser.add_argument("--uv-lock", type=Path, default=ROOT / "uv.lock")
    parser.add_argument(
        "--training-panel",
        type=Path,
        default=evaluation_root / "training_evaluation_panel.parquet",
    )
    parser.add_argument(
        "--oof-forecasts",
        type=Path,
        default=evaluation_root / "training_oof_forecasts.parquet",
    )
    parser.add_argument(
        "--tuning-ledger",
        type=Path,
        default=evaluation_root / "training_tuning_ledger.json",
    )
    parser.add_argument(
        "--method-freeze",
        type=Path,
        default=ROOT
        / "artifacts"
        / "b1v3_confirmation_method_freeze"
        / "method_freeze.json",
    )
    parser.add_argument(
        "--method-freeze-schema",
        type=Path,
        default=contracts / "b1v3-method-freeze-v1.schema.json",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Execute the development-only freeze and print sanitized identities."""
    args = _arguments(argv)
    document = freeze_b1v3_method(
        preregistration_path=args.preregistration,
        preregistration_schema_path=args.preregistration_schema,
        common_manifest_path=args.common_manifest,
        common_manifest_schema_path=args.common_manifest_schema,
        common_panel_path=args.common_panel,
        base_manifest_path=args.base_manifest,
        base_manifest_schema_path=args.base_manifest_schema,
        fmp_bars_path=args.fmp_bars,
        method_code_path=args.method_code,
        runner_code_path=args.runner_code,
        uv_lock_path=args.uv_lock,
        training_panel_path=args.training_panel,
        oof_forecasts_path=args.oof_forecasts,
        tuning_ledger_path=args.tuning_ledger,
        method_freeze_path=args.method_freeze,
        method_freeze_schema_path=args.method_freeze_schema,
    )
    print(
        json.dumps(
            {
                "status": document["status"],
                "training_read_count": document["training_read_count"],
                "confirmation_read_count": document["confirmation_read_count"],
                "safe_to_read_confirmation": document["safe_to_read_confirmation"],
                "manifest_sha256": document["manifest_sha256"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
