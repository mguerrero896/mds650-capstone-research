"""Consume one token and execute the preregistered independent replication."""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final

import polars as pl

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from mds650.b1_replication_access import (  # noqa: E402
    consume_replication_access_exclusively,
)
from mds650.b1_replication_evaluation import (  # noqa: E402
    build_consumed_authorization_adapter,
    build_legacy_evaluation_adapters,
    classify_b2_replication,
)
from mds650.b1v3_confirmation import (  # noqa: E402
    canonical_sha256,
    sha256_file,
    validate_confirmation_plan_schema,
)
from mds650.b1v3_confirmation_evaluation import (  # noqa: E402
    evaluate_b1v3_confirmation,
    forecast_b1v3_confirmation,
)
from mds650.b1v3_confirmation_run import (  # noqa: E402
    bind_b1v3_confirmation_targets,
    join_registered_timing_targets,
)
from mds650.b1v3_evaluation import validate_b1v3_evaluation_panel  # noqa: E402
from mds650.phase6 import build_b0v2_features  # noqa: E402

_TIMING_VARIANTS: Final[tuple[str, ...]] = (
    "FMP_DELAY_2_MINUTES",
    "MASSIVE_CUTOFF_60_SECONDS",
    "MASSIVE_CUTOFF_300_SECONDS",
    "UW_CREATED_AT_120_SECONDS",
    "UW_CREATED_AT_300_SECONDS",
)
_FORBIDDEN: Final[tuple[bytes, ...]] = (
    b"c:\\users\\",
    b"c:/users/",
    b"d:\\mds650",
    b"d:/mds650",
    b"api_key",
    b"apikey",
    b"authorization:",
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


def _contract(path: Path, schema_path: Path, *, code: str) -> dict[str, Any]:
    document = _json_object(path, code=code)
    validate_confirmation_plan_schema(document, schema_path)
    if not _self_hash_valid(document):
        raise ValueError(f"{code}_HASH")
    return document


def _code_bundle_sha256(paths: Sequence[Path]) -> str:
    if not paths or any(not path.is_file() for path in paths):
        raise ValueError("B1_REPLICATION_RUN_CODE_MISSING")
    return canonical_sha256(
        {
            "files": [
                {"name": path.name, "sha256": sha256_file(path)}
                for path in sorted(paths, key=lambda item: item.name)
            ]
        }
    )


def _write_parquet_exclusive(path: Path, frame: pl.DataFrame) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise ValueError(f"B1_REPLICATION_OUTPUT_EXISTS:{path.name}")
    descriptor, name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".part", dir=path.parent
    )
    os.close(descriptor)
    temporary = Path(name)
    try:
        frame.write_parquet(temporary, compression="zstd", statistics=True)
        os.rename(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return sha256_file(path)


def _write_bytes_exclusive(path: Path, payload: bytes) -> str:
    if any(token in payload.lower() for token in _FORBIDDEN):
        raise ValueError("B1_REPLICATION_OUTPUT_HYGIENE_INVALID")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise ValueError(f"B1_REPLICATION_OUTPUT_EXISTS:{path.name}") from exc
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return sha256_file(path)


def _write_json_exclusive(path: Path, document: Mapping[str, Any]) -> str:
    return _write_bytes_exclusive(
        path,
        (
            json.dumps(
                document,
                indent=2,
                sort_keys=True,
                ensure_ascii=True,
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8"),
    )


def _identity_sha256(frame: pl.DataFrame, columns: Sequence[str]) -> str:
    rows = frame.select(*columns).sort(list(columns)).iter_rows(named=True)
    return canonical_sha256({"rows": [dict(row) for row in rows]})


def _pre_read_validate(
    *,
    preregistration: Mapping[str, Any],
    method: Mapping[str, Any],
    quality: Mapping[str, Any],
    frozen_access: Mapping[str, Any],
    common_panel_path: Path,
    timing_common_manifest: Mapping[str, Any],
    training_timing_manifest: Mapping[str, Any],
    fmp_bars_path: Path,
    code_paths: Sequence[Path],
    uv_lock_path: Path,
    outputs: Sequence[Path],
) -> None:
    code_hash = _code_bundle_sha256(code_paths)
    invalid = (
        preregistration.get("replication_target_reads") != 0
        or preregistration.get("result_sign_selection") != "PROHIBITED"
        or method.get("replication_target_read_count") != 0
        or method.get("result_sign_selection") != "PROHIBITED"
        or quality.get("status") != "PASS_PRE_READ_REPLICATION_QUALITY"
        or quality.get("replication_target_read_count") != 0
        or frozen_access.get("status") != "READY_FOR_SINGLE_REPLICATION_READ"
        or frozen_access.get("replication_target_read_count") != 0
        or frozen_access.get("available_read_tokens") != 1
        or frozen_access.get("results_inspected") is not False
        or frozen_access.get("preregistration_manifest_sha256")
        != preregistration.get("manifest_sha256")
        or frozen_access.get("method_freeze_manifest_sha256")
        != method.get("manifest_sha256")
        or frozen_access.get("quality_manifest_sha256")
        != quality.get("manifest_sha256")
        or frozen_access.get("common_panel_sha256")
        != sha256_file(common_panel_path)
        or frozen_access.get("timing_common_manifest_sha256")
        != timing_common_manifest.get("manifest_sha256")
        or frozen_access.get("training_timing_manifest_sha256")
        != training_timing_manifest.get("manifest_sha256")
        or frozen_access.get("fmp_bars_sha256") != sha256_file(fmp_bars_path)
        or frozen_access.get("code_bundle_sha256") != code_hash
        or frozen_access.get("uv_lock_sha256") != sha256_file(uv_lock_path)
        or any(path.exists() for path in outputs)
    )
    if invalid:
        raise ValueError("B1_REPLICATION_PRE_READ_SOURCE_BINDING_INVALID")


def _result_document(
    *,
    preregistration: Mapping[str, Any],
    method: Mapping[str, Any],
    quality: Mapping[str, Any],
    frozen_access: Mapping[str, Any],
    consumed_access: Mapping[str, Any],
    common_manifest: Mapping[str, Any],
    timing_common_manifest: Mapping[str, Any],
    training_timing_manifest: Mapping[str, Any],
    panel: pl.DataFrame,
    primary_forecasts: pl.DataFrame,
    timing_forecasts: pl.DataFrame,
    panel_sha256: str,
    primary_sha256: str,
    timing_sha256: str,
    evaluation: Mapping[str, Any],
    decision: Mapping[str, Any],
) -> dict[str, Any]:
    training = panel.filter(pl.col("role") == "development")
    replication = panel.filter(pl.col("role") == "confirmation")
    document: dict[str, Any] = {
        "schema_version": "b1-independent-replication-result-1.0",
        "status": "COMPLETED_ONE_READ_INDEPENDENT_REPLICATION",
        "terminal_state": decision["terminal_state"],
        "replication_target_read_count": 1,
        "evaluation_attempt_count": 1,
        "all_registered_signs_retained": True,
        "sample": {
            "training_rows": training.height,
            "replication_rows": replication.height,
            "training_sessions": training["session_date"].n_unique(),
            "replication_sessions": replication["session_date"].n_unique(),
            "asset_count": replication["asset"].n_unique(),
            "origin_identity_sha256": _identity_sha256(panel, ("origin_id",)),
            "target_identity_sha256": _identity_sha256(
                panel, ("origin_id", "rv30")
            ),
        },
        "source_bindings": {
            "preregistration_manifest_sha256": preregistration["manifest_sha256"],
            "method_freeze_manifest_sha256": method["manifest_sha256"],
            "quality_manifest_sha256": quality["manifest_sha256"],
            "frozen_access_manifest_sha256": frozen_access["manifest_sha256"],
            "consumed_access_manifest_sha256": consumed_access["manifest_sha256"],
            "common_manifest_sha256": common_manifest["manifest_sha256"],
            "timing_common_manifest_sha256": timing_common_manifest[
                "manifest_sha256"
            ],
            "training_timing_manifest_sha256": training_timing_manifest[
                "manifest_sha256"
            ],
            "common_panel_sha256": frozen_access["common_panel_sha256"],
            "fmp_bars_sha256": frozen_access["fmp_bars_sha256"],
            "code_bundle_sha256": frozen_access["code_bundle_sha256"],
            "uv_lock_sha256": frozen_access["uv_lock_sha256"],
        },
        "outputs": {
            "evaluation_panel": {
                "logical_path": (
                    "MDS650_B1_REPLICATION_DATA_ROOT/evaluation/evaluation_panel.parquet"
                ),
                "sha256": panel_sha256,
                "rows": panel.height,
            },
            "primary_forecasts": {
                "logical_path": (
                    "MDS650_B1_REPLICATION_DATA_ROOT/evaluation/primary_forecasts.parquet"
                ),
                "sha256": primary_sha256,
                "rows": primary_forecasts.height,
            },
            "timing_forecasts": {
                "logical_path": (
                    "MDS650_B1_REPLICATION_DATA_ROOT/evaluation/timing_forecasts.parquet"
                ),
                "sha256": timing_sha256,
                "rows": timing_forecasts.height,
            },
        },
        "scientific_evaluation": dict(evaluation),
        "replication_decision": dict(decision),
        "claim_boundary": [
            "ACADEMIC_OUT_OF_SAMPLE_FORECASTING_ONLY",
            "NO_CAUSAL_INFORMED_TRADING_CLAIM",
            "NO_LIVE_PROFITABILITY_CLAIM",
            "NO_TRANSACTION_COST_ADJUSTED_EDGE_CLAIM",
            "NO_PRODUCTION_READINESS_CLAIM",
        ],
        "security": {
            "secret_values_emitted": False,
            "personal_paths_emitted": False,
        },
    }
    document["manifest_sha256"] = canonical_sha256(document)
    return document


def _render_report(result: Mapping[str, Any]) -> bytes:
    evaluation = result["scientific_evaluation"]
    decision = result["replication_decision"]
    assert isinstance(evaluation, Mapping)
    assert isinstance(decision, Mapping)
    global_rows = evaluation["global"]
    assert isinstance(global_rows, Mapping)
    lines = [
        "# Independent B1/B2 replication result",
        "",
        f"- Terminal state: `{result['terminal_state']}`",
        "- Replication target reads: 1",
        "- Evaluation attempts: 1",
        "- Positive, null and negative registered results were retained.",
        "",
        "## Registered global contrasts",
        "",
    ]
    for role in ("gamma_glm_confirmatory", "lightgbm_robustness"):
        role_rows = global_rows[role]
        assert isinstance(role_rows, Mapping)
        for contrast in ("delta_b1v3", "delta_b2"):
            row = role_rows[contrast]
            assert isinstance(row, Mapping)
            lines.append(
                f"- `{role}` / `{contrast}`: estimate={float(row['estimate']):.8g}, "
                f"95% CI=[{float(row['ci_low']):.8g}, {float(row['ci_high']):.8g}]"
            )
    lines.extend(
        [
            "",
            "## Interpretation boundary",
            "",
            "This is a preregistered academic forecasting replication. It is not "
            "a causal informed-trading, live profitability, transaction-cost, or "
            "production-readiness claim.",
            "",
        ]
    )
    return "\n".join(lines).encode("utf-8")


def _write_evidence_index(
    path: Path, records: Sequence[tuple[str, str, str]]
) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise ValueError(f"B1_REPLICATION_OUTPUT_EXISTS:{path.name}")
    descriptor, name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".part", dir=path.parent
    )
    os.close(descriptor)
    temporary = Path(name)
    try:
        with temporary.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream, lineterminator="\n")
            writer.writerow(("artifact", "logical_path", "sha256"))
            writer.writerows(records)
        payload = temporary.read_bytes()
        if any(token in payload.lower() for token in _FORBIDDEN):
            raise ValueError("B1_REPLICATION_OUTPUT_HYGIENE_INVALID")
        os.rename(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return sha256_file(path)


def run_once(args: argparse.Namespace) -> dict[str, Any]:
    """Execute exactly one outcome read and registered evaluation."""
    contracts = ROOT / "specs/001-pit-options-rv30/contracts"
    preregistration = _contract(
        args.preregistration,
        contracts / "b1-independent-replication-preregistration-v1.schema.json",
        code="B1_REPLICATION_RUN_PREREGISTRATION_INVALID",
    )
    method = _contract(
        args.method_freeze,
        contracts / "b1-independent-replication-method-freeze-v1.schema.json",
        code="B1_REPLICATION_RUN_METHOD_INVALID",
    )
    quality = _contract(
        args.quality,
        contracts / "b1-independent-replication-quality-v1.schema.json",
        code="B1_REPLICATION_RUN_QUALITY_INVALID",
    )
    frozen_access = _contract(
        args.frozen_access,
        contracts / "b1-independent-replication-access-v1.schema.json",
        code="B1_REPLICATION_RUN_ACCESS_INVALID",
    )
    common_manifest = _contract(
        args.common_manifest,
        contracts / "b1-independent-replication-common-v1.schema.json",
        code="B1_REPLICATION_RUN_COMMON_INVALID",
    )
    timing_common_manifest = _contract(
        args.timing_common_manifest,
        contracts / "b1-independent-replication-timing-common-v1.schema.json",
        code="B1_REPLICATION_RUN_TIMING_INVALID",
    )
    training_timing_manifest = _contract(
        args.training_timing_manifest,
        contracts / "b1v3-confirmation-timing-panels-v1.schema.json",
        code="B1_REPLICATION_RUN_TRAINING_TIMING_INVALID",
    )
    code_paths = (
        ROOT / "src/mds650/b1_replication_access.py",
        ROOT / "src/mds650/b1_replication_evaluation.py",
        ROOT / "src/mds650/b1v3_confirmation_evaluation.py",
        ROOT / "src/mds650/b1v3_confirmation_run.py",
        Path(__file__),
    )
    outputs = (
        args.consumed_access,
        args.evaluation_panel,
        args.primary_forecasts,
        args.timing_forecasts,
        args.result,
        args.report,
        args.evidence_index,
    )
    _pre_read_validate(
        preregistration=preregistration,
        method=method,
        quality=quality,
        frozen_access=frozen_access,
        common_panel_path=args.common_panel,
        timing_common_manifest=timing_common_manifest,
        training_timing_manifest=training_timing_manifest,
        fmp_bars_path=args.fmp_bars,
        code_paths=code_paths,
        uv_lock_path=ROOT / "uv.lock",
        outputs=outputs,
    )
    consumed_access = consume_replication_access_exclusively(
        frozen_access,
        path=args.consumed_access,
        access_schema_path=contracts / "b1-independent-replication-access-v1.schema.json",
    )

    # Sole replication-target read. The durable token exists before this line.
    common = pl.read_parquet(args.common_panel)
    replication_dates = [str(value) for value in preregistration["replication_sessions"]]
    origins = common.select(
        "origin_id",
        "asset",
        "session_date",
        "forecast_origin_utc",
        "role",
        "session_minute",
        "session_tercile",
    )
    bars = (
        pl.scan_parquet(args.fmp_bars)
        .filter(pl.col("session_date").cast(pl.String).is_in(replication_dates))
        .collect()
    )
    targets = build_b0v2_features(
        bars,
        origins,
        delay_minutes=1,
        include_target=True,
    )
    prereg_adapter, method_adapter = build_legacy_evaluation_adapters(
        preregistration,
        method,
        common_panel_sha256=sha256_file(args.common_panel),
    )
    authorization_adapter = build_consumed_authorization_adapter(prereg_adapter)
    replication_panel = bind_b1v3_confirmation_targets(
        common,
        targets,
        preregistration=prereg_adapter,
        authorization=authorization_adapter,
    )
    training = pl.read_parquet(args.training_panel).with_columns(
        pl.lit("development").alias("role")
    )
    primary_panel = validate_b1v3_evaluation_panel(
        pl.concat([training, replication_panel], how="diagonal_relaxed"),
        preregistration=prereg_adapter,
        authorization=authorization_adapter,
    )
    primary = forecast_b1v3_confirmation(
        primary_panel,
        preregistration=prereg_adapter,
        method_freeze=method_adapter,
    )
    training_dates = [str(value) for value in preregistration["training_sessions"]]
    timing_parts: list[pl.DataFrame] = []
    for variant in _TIMING_VARIANTS:
        training_predictors = (
            pl.scan_parquet(args.training_timing_root / f"{variant}.parquet")
            .filter(pl.col("session_date").cast(pl.String).is_in(training_dates))
            .collect()
            .with_columns(pl.lit("development").alias("role"))
        )
        replication_predictors = pl.read_parquet(
            args.replication_timing_root
            / variant.lower()
            / "common_predictor_panel.parquet"
        ).with_columns(pl.lit("confirmation").alias("role"))
        training_bound = join_registered_timing_targets(
            training_predictors, primary_panel
        ).with_columns(pl.lit("development").alias("role"))
        replication_bound = join_registered_timing_targets(
            replication_predictors, primary_panel
        ).with_columns(pl.lit("confirmation").alias("role"))
        timing_panel = validate_b1v3_evaluation_panel(
            pl.concat([training_bound, replication_bound], how="diagonal_relaxed"),
            preregistration=prereg_adapter,
            authorization=authorization_adapter,
        )
        timing_parts.append(
            forecast_b1v3_confirmation(
                timing_panel,
                preregistration=prereg_adapter,
                method_freeze=method_adapter,
            ).with_columns(pl.lit(variant).alias("timing_variant"))
        )
    timing_forecasts = pl.concat(timing_parts).sort(
        ["timing_variant", "model_role", "information_set", "origin_id"]
    )
    evaluation = evaluate_b1v3_confirmation(
        primary,
        method_freeze=method_adapter,
        preregistration=prereg_adapter,
        timing_predictions=timing_forecasts,
    )
    decision = classify_b2_replication(
        evaluation,
        training_mde=float(method["training_mde"]["delta_b2"]),
    )
    panel_hash = _write_parquet_exclusive(args.evaluation_panel, primary_panel)
    primary_hash = _write_parquet_exclusive(args.primary_forecasts, primary)
    timing_hash = _write_parquet_exclusive(args.timing_forecasts, timing_forecasts)
    result = _result_document(
        preregistration=preregistration,
        method=method,
        quality=quality,
        frozen_access=frozen_access,
        consumed_access=consumed_access,
        common_manifest=common_manifest,
        timing_common_manifest=timing_common_manifest,
        training_timing_manifest=training_timing_manifest,
        panel=primary_panel,
        primary_forecasts=primary,
        timing_forecasts=timing_forecasts,
        panel_sha256=panel_hash,
        primary_sha256=primary_hash,
        timing_sha256=timing_hash,
        evaluation=evaluation,
        decision=decision,
    )
    validate_confirmation_plan_schema(
        result,
        contracts / "b1-independent-replication-result-v1.schema.json",
    )
    result_hash = _write_json_exclusive(args.result, result)
    report_hash = _write_bytes_exclusive(args.report, _render_report(result))
    _write_evidence_index(
        args.evidence_index,
        (
            (
                "consumed_access",
                "artifacts/b1_diagnostic_replication/access/access_ledger_consumed.json",
                sha256_file(args.consumed_access),
            ),
            (
                "evaluation_panel",
                "MDS650_B1_REPLICATION_DATA_ROOT/evaluation/evaluation_panel.parquet",
                panel_hash,
            ),
            (
                "primary_forecasts",
                "MDS650_B1_REPLICATION_DATA_ROOT/evaluation/primary_forecasts.parquet",
                primary_hash,
            ),
            (
                "timing_forecasts",
                "MDS650_B1_REPLICATION_DATA_ROOT/evaluation/timing_forecasts.parquet",
                timing_hash,
            ),
            (
                "result",
                "artifacts/b1_diagnostic_replication/result/result.json",
                result_hash,
            ),
            (
                "report",
                "docs/recovery/b1_independent_replication_result_20260815.md",
                report_hash,
            ),
        ),
    )
    return result


def _arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    data = Path("D:/MDS650/b1_diagnostic_replication")
    artifacts = ROOT / "artifacts/b1_diagnostic_replication"
    panel = artifacts / "panel"
    evaluation = data / "evaluation"
    parser.add_argument(
        "--preregistration",
        type=Path,
        default=artifacts / "preregistration/preregistration.json",
    )
    parser.add_argument(
        "--method-freeze",
        type=Path,
        default=artifacts / "method_freeze/method_freeze.json",
    )
    parser.add_argument(
        "--quality", type=Path, default=artifacts / "access/quality_report.json"
    )
    parser.add_argument(
        "--frozen-access",
        type=Path,
        default=artifacts / "access/access_ledger_frozen.json",
    )
    parser.add_argument(
        "--consumed-access",
        type=Path,
        default=artifacts / "access/access_ledger_consumed.json",
    )
    parser.add_argument(
        "--common-manifest", type=Path, default=panel / "common_predictor_manifest.json"
    )
    parser.add_argument(
        "--timing-common-manifest",
        type=Path,
        default=panel / "timing_common_manifest.json",
    )
    parser.add_argument(
        "--training-timing-manifest",
        type=Path,
        default=ROOT / "artifacts/b1v3_confirmation_panel/timing_panel_manifest.json",
    )
    parser.add_argument(
        "--common-panel",
        type=Path,
        default=data / "predictors/common_predictor_panel.parquet",
    )
    parser.add_argument(
        "--fmp-bars",
        type=Path,
        default=data / "predictors/underlying_1min_target_blind.parquet",
    )
    parser.add_argument(
        "--training-panel",
        type=Path,
        default=data / "method/development_training_panel.parquet",
    )
    parser.add_argument(
        "--training-timing-root",
        type=Path,
        default=Path("D:/MDS650/b1v3_confirmation/predictors/timing/common"),
    )
    parser.add_argument(
        "--replication-timing-root",
        type=Path,
        default=data / "predictors/timing_common",
    )
    parser.add_argument("--output-root", type=Path, default=evaluation)
    parser.add_argument(
        "--evaluation-panel", type=Path, default=evaluation / "evaluation_panel.parquet"
    )
    parser.add_argument(
        "--primary-forecasts", type=Path, default=evaluation / "primary_forecasts.parquet"
    )
    parser.add_argument(
        "--timing-forecasts", type=Path, default=evaluation / "timing_forecasts.parquet"
    )
    parser.add_argument(
        "--result", type=Path, default=artifacts / "result/result.json"
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=ROOT / "docs/recovery/b1_independent_replication_result_20260815.md",
    )
    parser.add_argument(
        "--evidence-index",
        type=Path,
        default=artifacts / "result/evidence_index.csv",
    )
    parser.add_argument("--execute", action="store_true", required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _arguments(argv)
    result = run_once(args)
    print(
        json.dumps(
            {
                "status": result["status"],
                "terminal_state": result["terminal_state"],
                "replication_target_read_count": 1,
                "evaluation_attempt_count": 1,
                "manifest_sha256": result["manifest_sha256"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
