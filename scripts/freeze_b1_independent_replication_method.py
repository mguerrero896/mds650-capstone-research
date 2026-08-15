"""Freeze the sign-agnostic replication method from development outcomes only."""

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
from mds650.b1v3_evaluation import b1v3_phase6_adapter_contract  # noqa: E402
from mds650.b1v3_method_freeze import (  # noqa: E402
    select_b1v3_final_parameters,
    training_mde_from_b1v3_forecasts,
    training_only_b1v3_oof_forecasts,
    training_volatility_regime_cutpoints,
)

_ASSETS = ("AAPL", "AMZN", "META", "MSFT", "NVDA", "TSLA")
_FORBIDDEN_BYTES = (
    b"c:\\users\\",
    b"c:/users/",
    b"d:\\mds650",
    b"d:/mds650",
    b"api_key",
    b"apikey",
    b"authorization",
    b"bearer ",
)


def _json_object(path: Path, *, code: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(code) from exc
    if not isinstance(value, dict):
        raise ValueError(code)
    return value


def _self_hash_valid(document: Mapping[str, Any]) -> bool:
    stored = document.get("manifest_sha256")
    unsigned = {key: value for key, value in document.items() if key != "manifest_sha256"}
    return isinstance(stored, str) and stored == canonical_sha256(unsigned)


def _adapter(preregistration: Mapping[str, Any]) -> dict[str, Any]:
    document: dict[str, Any] = {
        "schema_version": "b1-independent-replication-method-adapter-1.0",
        "status": "FROZEN_BEFORE_CONFIRMATION",
        "safe_to_evaluate_b1v3": "NO",
        "outcome_read_count": 0,
        "confirmation_read_count": 0,
        "training_sessions": list(preregistration["training_sessions"]),
        "confirmation_sessions": list(preregistration["replication_sessions"]),
        "information_sets": dict(preregistration["information_sets"]),
        "method": dict(preregistration["method"]),
    }
    document["manifest_sha256"] = canonical_sha256(document)
    b1v3_phase6_adapter_contract(document)
    return document


def _validate_preregistration(document: Mapping[str, Any]) -> None:
    training = document.get("training_sessions")
    replication = document.get("replication_sessions")
    if (
        not _self_hash_valid(document)
        or document.get("status") != "FROZEN_BEFORE_PROVIDER_PAYLOAD"
        or document.get("target_blind") is not True
        or document.get("replication_target_reads") != 0
        or document.get("safe_to_access_replication_targets") != "NO"
        or document.get("result_sign_selection") != "PROHIBITED"
        or not isinstance(training, list)
        or len(training) != 60
        or not isinstance(replication, list)
        or len(replication) != 30
        or set(training) & set(replication)
        or set(document.get("information_sets", {})) != {"B0", "B1v3a", "B2"}
    ):
        raise ValueError("B1_REPLICATION_METHOD_PREREGISTRATION_INVALID")


def _training_frame(path: Path, preregistration: Mapping[str, Any]) -> pl.DataFrame:
    if not path.is_file():
        raise ValueError("B1_REPLICATION_TRAINING_PANEL_MISSING")
    training = [str(value) for value in preregistration["training_sessions"]]
    replication = [str(value) for value in preregistration["replication_sessions"]]
    required = {
        "origin_id",
        "asset",
        "session_date",
        "forecast_origin_utc",
        "session_tercile",
        "rv30",
        *preregistration["information_sets"]["B2"],
    }
    schema = pl.read_parquet_schema(path)
    if not required <= set(schema):
        raise ValueError("B1_REPLICATION_TRAINING_PANEL_SCHEMA_INVALID")
    frame = (
        pl.scan_parquet(path)
        .filter(pl.col("session_date").cast(pl.String).is_in(training))
        .collect()
    )
    if (
        frame.is_empty()
        or frame["origin_id"].n_unique() != frame.height
        or set(frame["session_date"].cast(pl.String).unique()) != set(training)
        or set(frame["asset"].cast(pl.String).unique()) != set(_ASSETS)
        or frame.filter(pl.col("session_date").cast(pl.String).is_in(replication)).height
        or frame.filter(~pl.col("rv30").is_finite() | (pl.col("rv30") <= 0)).height
        or frame.select(pl.any_horizontal(pl.col(required).is_null())).to_series().any()
    ):
        raise ValueError("B1_REPLICATION_TRAINING_PANEL_SCOPE_INVALID")
    return frame.sort(["session_date", "forecast_origin_utc", "asset"])


def _write_parquet_if_identical(path: Path, frame: pl.DataFrame) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if not pl.read_parquet(path).equals(frame, null_equal=True):
            raise ValueError(f"B1_REPLICATION_METHOD_OUTPUT_CONFLICT:{path.name}")
        return sha256_file(path)
    with tempfile.NamedTemporaryFile(dir=path.parent, suffix=".part", delete=False) as handle:
        temporary = Path(handle.name)
    try:
        frame.write_parquet(temporary, compression="zstd", statistics=True)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return sha256_file(path)


def _write_json_if_identical(path: Path, document: Mapping[str, Any]) -> str:
    payload = (
        json.dumps(document, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False)
        + "\n"
    ).encode("utf-8")
    if any(token in payload.lower() for token in _FORBIDDEN_BYTES):
        raise ValueError("B1_REPLICATION_METHOD_OUTPUT_HYGIENE_INVALID")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != payload:
            raise ValueError(f"B1_REPLICATION_METHOD_OUTPUT_CONFLICT:{path.name}")
        return sha256_file(path)
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".part", dir=path.parent)
    os.close(descriptor)
    temporary = Path(name)
    try:
        temporary.write_bytes(payload)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return sha256_file(path)


def freeze_method(
    *,
    preregistration_path: Path,
    training_panel_path: Path,
    output_root: Path,
    artifact_root: Path,
    schema_path: Path,
) -> dict[str, Any]:
    """Freeze all training-derived choices before any replication outcome read."""
    preregistration = _json_object(
        preregistration_path, code="B1_REPLICATION_METHOD_PREREGISTRATION_INVALID"
    )
    _validate_preregistration(preregistration)
    adapter = _adapter(preregistration)
    training = _training_frame(training_panel_path, preregistration)
    training_snapshot = output_root / "development_training_panel.parquet"
    oof_path = output_root / "development_oof_forecasts.parquet"
    tuning_path = output_root / "development_tuning_ledger.json"
    training_hash = _write_parquet_if_identical(training_snapshot, training)
    forecasts, oof_records = training_only_b1v3_oof_forecasts(training, adapter)
    oof_hash = _write_parquet_if_identical(oof_path, forecasts)
    selected, final_records = select_b1v3_final_parameters(training, adapter)
    tuning: dict[str, Any] = {
        "schema_version": "b1-independent-replication-tuning-1.0",
        "status": "PASS_DEVELOPMENT_ONLY_TUNING",
        "replication_target_reads": 0,
        "records": [
            *({**record, "stage": "OOF_MDE"} for record in oof_records),
            *({**record, "stage": "FINAL_SELECTION"} for record in final_records),
        ],
    }
    tuning["manifest_sha256"] = canonical_sha256(tuning)
    tuning_hash = _write_json_if_identical(tuning_path, tuning)
    inference = preregistration["method"]["inference"]
    mde = training_mde_from_b1v3_forecasts(
        forecasts,
        draws=int(inference["bootstrap_repetitions"]),
        seed=int(inference["seed"]),
    )
    cutpoints = training_volatility_regime_cutpoints(training)
    document: dict[str, Any] = {
        "schema_version": "b1-independent-replication-method-freeze-1.0",
        "status": "FROZEN_AFTER_TRAINING_BEFORE_REPLICATION",
        "preregistration_manifest_sha256": preregistration["manifest_sha256"],
        "target_blind_replication": True,
        "training_outcome_read_count": 1,
        "replication_target_read_count": 0,
        "safe_to_read_replication_targets": False,
        "result_sign_selection": "PROHIBITED",
        "scope": {
            "training_session_count": 60,
            "replication_session_count": 30,
            "asset_count": 6,
            "assets": list(_ASSETS),
            "training_row_count": training.height,
        },
        "selected_parameters": selected,
        "training_mde": {key: float(value) for key, value in sorted(mde.items())},
        "volatility_regime_cutpoints": {
            "lower": float(cutpoints["lower"]),
            "upper": float(cutpoints["upper"]),
        },
        "source_bindings": {
            "preregistration_file_sha256": sha256_file(preregistration_path),
            "development_source_panel_sha256": sha256_file(training_panel_path),
            "training_snapshot_sha256": training_hash,
            "oof_forecasts_sha256": oof_hash,
            "tuning_ledger_sha256": tuning_hash,
            "method_module_sha256": sha256_file(
                ROOT / "src" / "mds650" / "b1v3_method_freeze.py"
            ),
            "runner_sha256": sha256_file(Path(__file__)),
            "uv_lock_sha256": sha256_file(ROOT / "uv.lock"),
        },
    }
    document["manifest_sha256"] = canonical_sha256(document)
    validate_confirmation_plan_schema(document, schema_path)
    if not _self_hash_valid(document):
        raise ValueError("B1_REPLICATION_METHOD_FREEZE_HASH_INVALID")
    _write_json_if_identical(artifact_root / "method_freeze.json", document)
    return document


def _arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--preregistration",
        type=Path,
        default=ROOT
        / "artifacts/b1_diagnostic_replication/preregistration/preregistration.json",
    )
    parser.add_argument(
        "--training-panel",
        type=Path,
        default=Path("D:/MDS650/b1v3_confirmation/evaluation/evaluation_panel.parquet"),
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("D:/MDS650/b1_diagnostic_replication/method"),
    )
    parser.add_argument(
        "--artifact-root",
        type=Path,
        default=ROOT / "artifacts/b1_diagnostic_replication/method_freeze",
    )
    parser.add_argument(
        "--schema",
        type=Path,
        default=ROOT
        / "specs/001-pit-options-rv30/contracts/"
        "b1-independent-replication-method-freeze-v1.schema.json",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _arguments(argv)
    document = freeze_method(
        preregistration_path=args.preregistration,
        training_panel_path=args.training_panel,
        output_root=args.output_root,
        artifact_root=args.artifact_root,
        schema_path=args.schema,
    )
    print(
        json.dumps(
            {
                "status": document["status"],
                "training_rows": document["scope"]["training_row_count"],
                "replication_target_read_count": 0,
                "manifest_sha256": document["manifest_sha256"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
