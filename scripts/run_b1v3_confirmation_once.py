"""Execute exactly one preregistered B1v3 confirmation after access is sealed."""

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
    consume_authorization_exclusively,
    join_registered_timing_targets,
)
from mds650.b1v3_evaluation import (  # noqa: E402
    authorize_b1v3_confirmation,
    validate_b1v3_evaluation_panel,
)
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
    b"\"authorization\":",
    b"authorization:",
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


def _write_bytes_exclusive(path: Path, payload: bytes) -> str:
    """Write one sanitized artifact exactly once with durable exclusive create."""
    if any(token in payload.lower() for token in _FORBIDDEN):
        raise ValueError("B1V3_CONFIRMATION_OUTPUT_HYGIENE_INVALID")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise ValueError(f"B1V3_CONFIRMATION_OUTPUT_EXISTS:{path.name}") from exc
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
    payload = (json.dumps(document, indent=2, sort_keys=True, ensure_ascii=True) + "\n").encode(
        "utf-8"
    )
    return _write_bytes_exclusive(path, payload)


def _write_parquet_exclusive(path: Path, frame: pl.DataFrame) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise ValueError(f"B1V3_CONFIRMATION_OUTPUT_EXISTS:{path.name}")
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".part", dir=path.parent)
    os.close(descriptor)
    temporary = Path(name)
    try:
        frame.write_parquet(temporary, compression="zstd", statistics=True)
        try:
            os.rename(temporary, path)
        except FileExistsError as exc:
            raise ValueError(f"B1V3_CONFIRMATION_OUTPUT_EXISTS:{path.name}") from exc
    finally:
        temporary.unlink(missing_ok=True)
    return sha256_file(path)


def _load_contract(path: Path, schema_path: Path, *, error: str) -> dict[str, Any]:
    document = _read_mapping(path, error)
    validate_confirmation_plan_schema(document, schema_path)
    _validate_self_hash(document, f"{error}_SELF_HASH")
    return document


def _identity_sha256(frame: pl.DataFrame, columns: Sequence[str]) -> str:
    ordered = frame.select(*columns).sort(list(columns)).iter_rows(named=True)
    return canonical_sha256({"rows": [dict(row) for row in ordered]})


def _validate_pre_read_sources(
    *,
    preregistration: Mapping[str, Any],
    method_freeze: Mapping[str, Any],
    common_manifest: Mapping[str, Any],
    timing_manifest: Mapping[str, Any],
    quality_report: Mapping[str, Any],
    frozen_access: Mapping[str, Any],
    common_panel_path: Path,
    training_panel_path: Path,
    fmp_bars_path: Path,
    timing_panel_paths: Mapping[str, Path],
    confirmation_code_paths: Sequence[Path],
    uv_lock_path: Path,
) -> None:
    common_output = common_manifest.get("output")
    method_sources = method_freeze.get("source_hashes")
    timing_bindings = timing_manifest.get("source_bindings")
    timing_records = timing_manifest.get("variants")
    common_hash = sha256_file(common_panel_path)
    if not confirmation_code_paths or any(not path.is_file() for path in confirmation_code_paths):
        raise ValueError("B1V3_CONFIRMATION_CODE_MISSING")
    confirmation_code_sha256 = canonical_sha256(
        {
            "files": [
                {"name": path.name, "sha256": sha256_file(path)} for path in confirmation_code_paths
            ]
        }
    )
    invalid = (
        preregistration.get("status") != "FROZEN_BEFORE_CONFIRMATION"
        or preregistration.get("confirmation_read_count") != 0
        or method_freeze.get("status") != "FROZEN_AFTER_TRAINING_BEFORE_CONFIRMATION"
        or method_freeze.get("safe_to_read_confirmation") is not False
        or method_freeze.get("preregistration_manifest_sha256")
        != preregistration.get("manifest_sha256")
        or method_freeze.get("common_panel_sha256") != common_hash
        or not isinstance(method_sources, Mapping)
        or method_sources.get("training_panel_sha256") != sha256_file(training_panel_path)
        or method_sources.get("training_target_source_sha256") != sha256_file(fmp_bars_path)
        or common_manifest.get("status") != "PASS_TARGET_BLIND_COMMON_PREDICTOR_PANEL"
        or not isinstance(common_output, Mapping)
        or common_output.get("sha256") != common_hash
        or preregistration.get("common_predictor_panel_sha256") != common_hash
        or timing_manifest.get("status") != "PASS_TARGET_BLIND_TIMING_COMMON_PANELS"
        or not isinstance(timing_bindings, Mapping)
        or timing_bindings.get("common_panel_sha256") != common_hash
        or frozen_access.get("status") != "METHOD_FROZEN_BEFORE_CONFIRMATION"
        or frozen_access.get("common_panel_sha256") != common_hash
        or frozen_access.get("method_freeze_sha256") != method_freeze.get("manifest_sha256")
        or frozen_access.get("preregistration_manifest_sha256")
        != preregistration.get("manifest_sha256")
        or frozen_access.get("timing_panel_manifest_sha256")
        != timing_manifest.get("manifest_sha256")
        or frozen_access.get("quality_report_sha256") != quality_report.get("manifest_sha256")
        or frozen_access.get("confirmation_code_sha256") != confirmation_code_sha256
        or frozen_access.get("uv_lock_sha256") != sha256_file(uv_lock_path)
        or quality_report.get("status") != "PASS_B1V3_PRE_CONFIRMATION_QUALITY"
        or not isinstance(timing_records, Mapping)
        or set(timing_panel_paths) != set(_TIMING_VARIANTS)
    )
    if invalid:
        raise ValueError("B1V3_CONFIRMATION_SOURCE_BINDING_INVALID")
    assert isinstance(timing_records, Mapping)
    for variant, path in timing_panel_paths.items():
        record = timing_records.get(variant)
        if not isinstance(record, Mapping) or record.get("sha256") != sha256_file(path):
            raise ValueError(f"B1V3_CONFIRMATION_TIMING_BINDING_INVALID:{variant}")


def _recovery_authorization_valid(
    frozen_access: Mapping[str, Any], consumed_access: Mapping[str, Any]
) -> bool:
    """Return whether ``consumed_access`` is the exact one-read transition.

    This comparison permits recovery only after the registered ``0 -> 1``
    confirmation transition and forbids manufacturing a second attempt ledger.
    """

    def self_hash_valid(document: Mapping[str, Any]) -> bool:
        stored = document.get("manifest_sha256")
        unsigned = {key: value for key, value in document.items() if key != "manifest_sha256"}
        return isinstance(stored, str) and stored == canonical_sha256(unsigned)

    if not self_hash_valid(frozen_access) or not self_hash_valid(consumed_access):
        return False
    unsigned = {
        key: value for key, value in frozen_access.items() if key != "manifest_sha256"
    }
    expected: dict[str, Any] = {
        **unsigned,
        "status": "CONFIRMATION_EVALUATION_IN_PROGRESS",
        "outcome_read_count": 2,
        "confirmation_read_count": 1,
        "evaluation_attempt_count": 1,
    }
    expected["manifest_sha256"] = canonical_sha256(expected)
    return dict(consumed_access) == expected


def _result_document(
    *,
    preregistration: Mapping[str, Any],
    method_freeze: Mapping[str, Any],
    frozen_access: Mapping[str, Any],
    authorization: Mapping[str, Any],
    common_manifest: Mapping[str, Any],
    timing_manifest: Mapping[str, Any],
    quality_report: Mapping[str, Any],
    primary_panel: pl.DataFrame,
    primary_forecasts: pl.DataFrame,
    timing_forecasts: pl.DataFrame,
    primary_panel_sha256: str,
    primary_forecasts_sha256: str,
    timing_forecasts_sha256: str,
    evaluation: Mapping[str, Any],
) -> dict[str, Any]:
    """Create the immutable, sign-complete B1v3 result document."""
    confirmation = primary_panel.filter(pl.col("role") == "confirmation")
    training = primary_panel.filter(pl.col("role") == "development")
    document: dict[str, Any] = {
        "schema_version": "1.0",
        "status": "COMPLETED_ONE_READ_B1V3_CONFIRMATION",
        "outcome_read_count": 2,
        "training_read_count": 1,
        "confirmation_read_count": 1,
        "evaluation_attempt_count": 1,
        "all_signs_retained": True,
        "source_bindings": {
            "preregistration_manifest_sha256": preregistration["manifest_sha256"],
            "method_freeze_manifest_sha256": method_freeze["manifest_sha256"],
            "frozen_access_manifest_sha256": frozen_access["manifest_sha256"],
            "consumed_authorization_manifest_sha256": authorization["manifest_sha256"],
            "common_predictor_manifest_sha256": common_manifest["manifest_sha256"],
            "timing_panel_manifest_sha256": timing_manifest["manifest_sha256"],
            "quality_report_manifest_sha256": quality_report["manifest_sha256"],
            "confirmation_code_sha256": authorization["confirmation_code_sha256"],
            "uv_lock_sha256": authorization["uv_lock_sha256"],
        },
        "sample": {
            "training_rows": training.height,
            "confirmation_rows": confirmation.height,
            "training_sessions": training["session_date"].n_unique(),
            "confirmation_sessions": confirmation["session_date"].n_unique(),
            "asset_count": confirmation["asset"].n_unique(),
            "origin_identity_sha256": _identity_sha256(primary_panel, ("origin_id",)),
            "target_identity_sha256": _identity_sha256(primary_panel, ("origin_id", "rv30")),
        },
        "outputs": {
            "evaluation_panel": {
                "logical_path": "MDS650_B1V3_DATA_ROOT/evaluation/evaluation_panel.parquet",
                "sha256": primary_panel_sha256,
                "rows": primary_panel.height,
            },
            "primary_forecasts": {
                "logical_path": "MDS650_B1V3_DATA_ROOT/evaluation/primary_forecasts.parquet",
                "sha256": primary_forecasts_sha256,
                "rows": primary_forecasts.height,
            },
            "timing_forecasts": {
                "logical_path": "MDS650_B1V3_DATA_ROOT/evaluation/timing_forecasts.parquet",
                "sha256": timing_forecasts_sha256,
                "rows": timing_forecasts.height,
            },
        },
        "scientific_result": dict(evaluation),
        "security": {
            "secret_values_emitted": False,
            "personal_paths_emitted": False,
        },
    }
    document["manifest_sha256"] = canonical_sha256(document)
    return document


def _render_report(result: Mapping[str, Any]) -> bytes:
    scientific = result["scientific_result"]
    assert isinstance(scientific, Mapping)
    claims = scientific["claims"]
    assert isinstance(claims, Mapping)
    lines = [
        "# B1v3 independent confirmation result",
        "",
        f"- Decision: `{scientific['decision']}`",
        f"- Result manifest SHA-256: `{result['manifest_sha256']}`",
        "- Confirmation reads: 1",
        "- Evaluation attempts: 1",
        "- Every registered positive, null, and negative sign was retained.",
        "",
        "## Primary registered claims",
        "",
    ]
    for name in ("delta_b1v3", "delta_b2"):
        claim = claims[name]
        assert isinstance(claim, Mapping)
        lines.append(f"- `{name}`: `{claim['status']}`")
    lines.extend(
        [
            "",
            "This is an academic out-of-sample forecasting result, not a live "
            "trading or P&L claim.",
            "",
        ]
    )
    return "\n".join(lines).encode("utf-8")


def _write_evidence_index(path: Path, records: Sequence[tuple[str, str, str]]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise ValueError(f"B1V3_CONFIRMATION_OUTPUT_EXISTS:{path.name}")
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".part", dir=path.parent)
    os.close(descriptor)
    temporary = Path(name)
    try:
        with temporary.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream, lineterminator="\n")
            writer.writerow(("artifact", "logical_path", "sha256"))
            writer.writerows(records)
        payload = temporary.read_bytes()
        if any(token in payload.lower() for token in _FORBIDDEN):
            raise ValueError("B1V3_CONFIRMATION_OUTPUT_HYGIENE_INVALID")
        os.rename(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return sha256_file(path)


def run_b1v3_confirmation_once(
    *,
    preregistration_path: Path,
    preregistration_schema_path: Path,
    method_freeze_path: Path,
    method_freeze_schema_path: Path,
    common_manifest_path: Path,
    common_manifest_schema_path: Path,
    timing_manifest_path: Path,
    timing_manifest_schema_path: Path,
    quality_report_path: Path,
    quality_report_schema_path: Path,
    frozen_access_path: Path,
    access_schema_path: Path,
    common_panel_path: Path,
    training_panel_path: Path,
    fmp_bars_path: Path,
    timing_panel_paths: Mapping[str, Path],
    confirmation_code_paths: Sequence[Path],
    uv_lock_path: Path,
    consumed_access_path: Path,
    evaluation_panel_path: Path,
    primary_forecasts_path: Path,
    timing_forecasts_path: Path,
    result_path: Path,
    result_schema_path: Path,
    report_path: Path,
    evidence_index_path: Path,
) -> dict[str, Any]:
    """Consume authorization, read confirmation RV30 once, and evaluate once."""
    preregistration = _load_contract(
        preregistration_path,
        preregistration_schema_path,
        error="B1V3_CONFIRMATION_PREREGISTRATION_INVALID",
    )
    method_freeze = _load_contract(
        method_freeze_path,
        method_freeze_schema_path,
        error="B1V3_CONFIRMATION_METHOD_FREEZE_INVALID",
    )
    common_manifest = _load_contract(
        common_manifest_path,
        common_manifest_schema_path,
        error="B1V3_CONFIRMATION_COMMON_MANIFEST_INVALID",
    )
    timing_manifest = _load_contract(
        timing_manifest_path,
        timing_manifest_schema_path,
        error="B1V3_CONFIRMATION_TIMING_MANIFEST_INVALID",
    )
    quality_report = _load_contract(
        quality_report_path,
        quality_report_schema_path,
        error="B1V3_CONFIRMATION_QUALITY_REPORT_INVALID",
    )
    frozen_access = _load_contract(
        frozen_access_path,
        access_schema_path,
        error="B1V3_CONFIRMATION_FROZEN_ACCESS_INVALID",
    )
    _validate_pre_read_sources(
        preregistration=preregistration,
        method_freeze=method_freeze,
        common_manifest=common_manifest,
        timing_manifest=timing_manifest,
        quality_report=quality_report,
        frozen_access=frozen_access,
        common_panel_path=common_panel_path,
        training_panel_path=training_panel_path,
        fmp_bars_path=fmp_bars_path,
        timing_panel_paths=timing_panel_paths,
        confirmation_code_paths=confirmation_code_paths,
        uv_lock_path=uv_lock_path,
    )
    outputs = (
        consumed_access_path,
        evaluation_panel_path,
        primary_forecasts_path,
        timing_forecasts_path,
        result_path,
        report_path,
        evidence_index_path,
    )
    results_exist = any(path.exists() for path in outputs)
    authorization = authorize_b1v3_confirmation(
        frozen_access,
        common_panel_sha256=sha256_file(common_panel_path),
        preregistration_manifest_sha256=str(preregistration["manifest_sha256"]),
        results_exist=results_exist,
    )
    validate_confirmation_plan_schema(authorization, access_schema_path)
    authorization_file_sha = consume_authorization_exclusively(consumed_access_path, authorization)

    # This is the sole confirmation-target read and occurs only after the token
    # has been durably consumed above.
    common = pl.read_parquet(common_panel_path)
    confirmation_sessions = [str(value) for value in preregistration["confirmation_sessions"]]
    origins = common.filter(pl.col("role") == "confirmation").select(
        "origin_id",
        "asset",
        "session_date",
        "forecast_origin_utc",
        "role",
        "session_minute",
        "session_tercile",
    )
    confirmation_bars = (
        pl.scan_parquet(fmp_bars_path)
        .filter(pl.col("session_date").cast(pl.String).is_in(confirmation_sessions))
        .collect()
    )
    targets = build_b0v2_features(
        confirmation_bars,
        origins,
        delay_minutes=1,
        include_target=True,
    )
    confirmation_panel = bind_b1v3_confirmation_targets(
        common,
        targets,
        preregistration=preregistration,
        authorization=authorization,
    )
    training_panel = pl.read_parquet(training_panel_path)
    primary_panel = validate_b1v3_evaluation_panel(
        pl.concat([training_panel, confirmation_panel], how="diagonal_relaxed"),
        preregistration=preregistration,
        authorization=authorization,
    )
    primary_forecasts = forecast_b1v3_confirmation(
        primary_panel,
        preregistration=preregistration,
        method_freeze=method_freeze,
    )
    timing_parts: list[pl.DataFrame] = []
    for variant in _TIMING_VARIANTS:
        variant_panel = join_registered_timing_targets(
            pl.read_parquet(timing_panel_paths[variant]),
            primary_panel,
        )
        validated = validate_b1v3_evaluation_panel(
            variant_panel,
            preregistration=preregistration,
            authorization=authorization,
        )
        timing_parts.append(
            forecast_b1v3_confirmation(
                validated,
                preregistration=preregistration,
                method_freeze=method_freeze,
            ).with_columns(pl.lit(variant).alias("timing_variant"))
        )
    timing_forecasts = pl.concat(timing_parts).sort(
        ["timing_variant", "model_role", "information_set", "origin_id"]
    )
    evaluation = evaluate_b1v3_confirmation(
        primary_forecasts,
        method_freeze=method_freeze,
        preregistration=preregistration,
        timing_predictions=timing_forecasts,
    )
    evaluation_panel_sha = _write_parquet_exclusive(evaluation_panel_path, primary_panel)
    primary_forecasts_sha = _write_parquet_exclusive(primary_forecasts_path, primary_forecasts)
    timing_forecasts_sha = _write_parquet_exclusive(timing_forecasts_path, timing_forecasts)
    result = _result_document(
        preregistration=preregistration,
        method_freeze=method_freeze,
        frozen_access=frozen_access,
        authorization=authorization,
        common_manifest=common_manifest,
        timing_manifest=timing_manifest,
        quality_report=quality_report,
        primary_panel=primary_panel,
        primary_forecasts=primary_forecasts,
        timing_forecasts=timing_forecasts,
        primary_panel_sha256=evaluation_panel_sha,
        primary_forecasts_sha256=primary_forecasts_sha,
        timing_forecasts_sha256=timing_forecasts_sha,
        evaluation=evaluation,
    )
    validate_confirmation_plan_schema(result, result_schema_path)
    result_file_sha = _write_json_exclusive(result_path, result)
    _write_bytes_exclusive(report_path, _render_report(result))
    _write_evidence_index(
        evidence_index_path,
        (
            (
                "consumed_access",
                "artifacts/b1v3_confirmation/access_authorization_consumed.json",
                authorization_file_sha,
            ),
            (
                "evaluation_panel",
                str(result["outputs"]["evaluation_panel"]["logical_path"]),
                evaluation_panel_sha,
            ),
            (
                "primary_forecasts",
                str(result["outputs"]["primary_forecasts"]["logical_path"]),
                primary_forecasts_sha,
            ),
            (
                "timing_forecasts",
                str(result["outputs"]["timing_forecasts"]["logical_path"]),
                timing_forecasts_sha,
            ),
            ("result", "artifacts/b1v3_confirmation/result.json", result_file_sha),
        ),
    )
    return result


def finalize_b1v3_confirmation_from_sealed_outputs(
    *,
    preregistration_path: Path,
    preregistration_schema_path: Path,
    method_freeze_path: Path,
    method_freeze_schema_path: Path,
    common_manifest_path: Path,
    common_manifest_schema_path: Path,
    timing_manifest_path: Path,
    timing_manifest_schema_path: Path,
    quality_report_path: Path,
    quality_report_schema_path: Path,
    frozen_access_path: Path,
    consumed_access_path: Path,
    access_schema_path: Path,
    evaluation_panel_path: Path,
    primary_forecasts_path: Path,
    timing_forecasts_path: Path,
    result_path: Path,
    result_schema_path: Path,
    report_path: Path,
    evidence_index_path: Path,
) -> dict[str, Any]:
    """Finalize a consumed run from its three already-sealed derived outputs.

    This recovery path never opens FMP bars, common predictor inputs, provider
    payloads, or model-training inputs.  It is valid only when the exact one-read
    authorization has already been consumed, all three deterministic Parquet
    outputs exist, and no final JSON/report/index exists.  Models are not fitted
    again; registered inference is recomputed from the sealed forecast cube.

    Returns
    -------
    dict[str, Any]
        Schema-valid, self-hashed B1v3 result document.

    Raises
    ------
    ValueError
        If the authorization transition, contracts, output identities, pairing,
        hygiene, or exclusive final-output state is invalid.
    """
    preregistration = _load_contract(
        preregistration_path,
        preregistration_schema_path,
        error="B1V3_RECOVERY_PREREGISTRATION_INVALID",
    )
    method_freeze = _load_contract(
        method_freeze_path,
        method_freeze_schema_path,
        error="B1V3_RECOVERY_METHOD_FREEZE_INVALID",
    )
    common_manifest = _load_contract(
        common_manifest_path,
        common_manifest_schema_path,
        error="B1V3_RECOVERY_COMMON_MANIFEST_INVALID",
    )
    timing_manifest = _load_contract(
        timing_manifest_path,
        timing_manifest_schema_path,
        error="B1V3_RECOVERY_TIMING_MANIFEST_INVALID",
    )
    quality_report = _load_contract(
        quality_report_path,
        quality_report_schema_path,
        error="B1V3_RECOVERY_QUALITY_REPORT_INVALID",
    )
    frozen_access = _load_contract(
        frozen_access_path,
        access_schema_path,
        error="B1V3_RECOVERY_FROZEN_ACCESS_INVALID",
    )
    consumed_access = _load_contract(
        consumed_access_path,
        access_schema_path,
        error="B1V3_RECOVERY_CONSUMED_ACCESS_INVALID",
    )
    if not _recovery_authorization_valid(frozen_access, consumed_access):
        raise ValueError("B1V3_RECOVERY_AUTHORIZATION_TRANSITION_INVALID")
    if any(path.exists() for path in (result_path, report_path, evidence_index_path)):
        raise ValueError("B1V3_RECOVERY_FINAL_OUTPUT_EXISTS")
    sealed_outputs = (
        evaluation_panel_path,
        primary_forecasts_path,
        timing_forecasts_path,
    )
    if any(not path.is_file() for path in sealed_outputs):
        raise ValueError("B1V3_RECOVERY_SEALED_OUTPUT_MISSING")

    primary_panel = validate_b1v3_evaluation_panel(
        pl.read_parquet(evaluation_panel_path),
        preregistration=preregistration,
        authorization=consumed_access,
    )
    primary_forecasts = pl.read_parquet(primary_forecasts_path)
    timing_forecasts = pl.read_parquet(timing_forecasts_path)
    confirmation_targets = primary_panel.filter(pl.col("role") == "confirmation").select(
        "origin_id", "rv30"
    ).sort("origin_id")
    forecast_targets = primary_forecasts.select("origin_id", "rv30").unique().sort("origin_id")
    if not confirmation_targets.equals(forecast_targets, null_equal=True):
        raise ValueError("B1V3_RECOVERY_FORECAST_TARGET_IDENTITY_INVALID")
    evaluation = evaluate_b1v3_confirmation(
        primary_forecasts,
        method_freeze=method_freeze,
        preregistration=preregistration,
        timing_predictions=timing_forecasts,
    )
    evaluation_panel_sha = sha256_file(evaluation_panel_path)
    primary_forecasts_sha = sha256_file(primary_forecasts_path)
    timing_forecasts_sha = sha256_file(timing_forecasts_path)
    result = _result_document(
        preregistration=preregistration,
        method_freeze=method_freeze,
        frozen_access=frozen_access,
        authorization=consumed_access,
        common_manifest=common_manifest,
        timing_manifest=timing_manifest,
        quality_report=quality_report,
        primary_panel=primary_panel,
        primary_forecasts=primary_forecasts,
        timing_forecasts=timing_forecasts,
        primary_panel_sha256=evaluation_panel_sha,
        primary_forecasts_sha256=primary_forecasts_sha,
        timing_forecasts_sha256=timing_forecasts_sha,
        evaluation=evaluation,
    )
    validate_confirmation_plan_schema(result, result_schema_path)
    result_file_sha = _write_json_exclusive(result_path, result)
    _write_bytes_exclusive(report_path, _render_report(result))
    _write_evidence_index(
        evidence_index_path,
        (
            (
                "consumed_access",
                "artifacts/b1v3_confirmation/access_authorization_consumed.json",
                sha256_file(consumed_access_path),
            ),
            (
                "evaluation_panel",
                str(result["outputs"]["evaluation_panel"]["logical_path"]),
                evaluation_panel_sha,
            ),
            (
                "primary_forecasts",
                str(result["outputs"]["primary_forecasts"]["logical_path"]),
                primary_forecasts_sha,
            ),
            (
                "timing_forecasts",
                str(result["outputs"]["timing_forecasts"]["logical_path"]),
                timing_forecasts_sha,
            ),
            ("result", "artifacts/b1v3_confirmation/result.json", result_file_sha),
        ),
    )
    return result


def _arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    contracts = ROOT / "specs/001-pit-options-rv30/contracts"
    artifacts = ROOT / "artifacts/b1v3_confirmation"
    panel_artifacts = ROOT / "artifacts/b1v3_confirmation_panel"
    data = Path("D:/MDS650/b1v3_confirmation")
    evaluation = data / "evaluation"
    timing = data / "predictors/timing/common"
    parser.add_argument(
        "--preregistration",
        type=Path,
        default=ROOT / "artifacts/b1v3_confirmation_preregistration/preregistration.json",
    )
    parser.add_argument(
        "--preregistration-schema",
        type=Path,
        default=contracts / "b1v3-preregistration-v1.schema.json",
    )
    parser.add_argument(
        "--method-freeze",
        type=Path,
        default=ROOT / "artifacts/b1v3_confirmation_method_freeze/method_freeze.json",
    )
    parser.add_argument(
        "--method-freeze-schema", type=Path, default=contracts / "b1v3-method-freeze-v1.schema.json"
    )
    parser.add_argument(
        "--common-manifest", type=Path, default=panel_artifacts / "common_predictor_manifest.json"
    )
    parser.add_argument(
        "--common-schema",
        type=Path,
        default=contracts / "b1v3-confirmation-common-predictor-v1.schema.json",
    )
    parser.add_argument(
        "--timing-manifest", type=Path, default=panel_artifacts / "timing_panel_manifest.json"
    )
    parser.add_argument(
        "--timing-schema",
        type=Path,
        default=contracts / "b1v3-confirmation-timing-panels-v1.schema.json",
    )
    parser.add_argument(
        "--quality-report",
        type=Path,
        default=artifacts / "pre_confirmation_quality_gate.json",
    )
    parser.add_argument(
        "--quality-schema",
        type=Path,
        default=contracts / "b1v3-pre-confirmation-quality-v1.schema.json",
    )
    parser.add_argument(
        "--frozen-access", type=Path, default=artifacts / "access_ledger_frozen.json"
    )
    parser.add_argument(
        "--access-schema", type=Path, default=contracts / "b1v3-access-ledger-v1.schema.json"
    )
    parser.add_argument(
        "--common-panel", type=Path, default=data / "predictors/common_predictor_panel.parquet"
    )
    parser.add_argument(
        "--training-panel", type=Path, default=evaluation / "training_evaluation_panel.parquet"
    )
    parser.add_argument(
        "--fmp-bars", type=Path, default=data / "predictors/underlying_1min_target_blind.parquet"
    )
    for variant in _TIMING_VARIANTS:
        parser.add_argument(
            f"--timing-{variant.lower().replace('_', '-')}",
            dest=f"timing_{variant.lower()}",
            type=Path,
            default=timing / f"{variant}.parquet",
        )
    parser.add_argument(
        "--confirmation-code",
        type=Path,
        action="append",
        default=[
            ROOT / "src/mds650/b1v3_confirmation_evaluation.py",
            ROOT / "src/mds650/b1v3_confirmation_run.py",
            Path(__file__).resolve(),
        ],
    )
    parser.add_argument("--uv-lock", type=Path, default=ROOT / "uv.lock")
    parser.add_argument(
        "--consumed-access", type=Path, default=artifacts / "access_authorization_consumed.json"
    )
    parser.add_argument(
        "--evaluation-panel", type=Path, default=evaluation / "evaluation_panel.parquet"
    )
    parser.add_argument(
        "--primary-forecasts", type=Path, default=evaluation / "primary_forecasts.parquet"
    )
    parser.add_argument(
        "--timing-forecasts", type=Path, default=evaluation / "timing_forecasts.parquet"
    )
    parser.add_argument("--result", type=Path, default=artifacts / "result.json")
    parser.add_argument(
        "--result-schema", type=Path, default=contracts / "b1v3-confirmation-result-v1.schema.json"
    )
    parser.add_argument("--report", type=Path, default=artifacts / "result_report.md")
    parser.add_argument("--evidence-index", type=Path, default=artifacts / "evidence_index.csv")
    parser.add_argument(
        "--finalize-sealed-outputs",
        action="store_true",
        help="Finalize a consumed run from its existing Parquet outputs without a new target read.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the one-read confirmation and print only the registered decision."""
    args = _arguments(argv)
    timing_paths = {
        variant: getattr(args, f"timing_{variant.lower()}") for variant in _TIMING_VARIANTS
    }
    if args.finalize_sealed_outputs:
        result = finalize_b1v3_confirmation_from_sealed_outputs(
            preregistration_path=args.preregistration,
            preregistration_schema_path=args.preregistration_schema,
            method_freeze_path=args.method_freeze,
            method_freeze_schema_path=args.method_freeze_schema,
            common_manifest_path=args.common_manifest,
            common_manifest_schema_path=args.common_schema,
            timing_manifest_path=args.timing_manifest,
            timing_manifest_schema_path=args.timing_schema,
            quality_report_path=args.quality_report,
            quality_report_schema_path=args.quality_schema,
            frozen_access_path=args.frozen_access,
            consumed_access_path=args.consumed_access,
            access_schema_path=args.access_schema,
            evaluation_panel_path=args.evaluation_panel,
            primary_forecasts_path=args.primary_forecasts,
            timing_forecasts_path=args.timing_forecasts,
            result_path=args.result,
            result_schema_path=args.result_schema,
            report_path=args.report,
            evidence_index_path=args.evidence_index,
        )
    else:
        result = run_b1v3_confirmation_once(
            preregistration_path=args.preregistration,
            preregistration_schema_path=args.preregistration_schema,
            method_freeze_path=args.method_freeze,
            method_freeze_schema_path=args.method_freeze_schema,
            common_manifest_path=args.common_manifest,
            common_manifest_schema_path=args.common_schema,
            timing_manifest_path=args.timing_manifest,
            timing_manifest_schema_path=args.timing_schema,
            quality_report_path=args.quality_report,
            quality_report_schema_path=args.quality_schema,
            frozen_access_path=args.frozen_access,
            access_schema_path=args.access_schema,
            common_panel_path=args.common_panel,
            training_panel_path=args.training_panel,
            fmp_bars_path=args.fmp_bars,
            timing_panel_paths=timing_paths,
            confirmation_code_paths=args.confirmation_code,
            uv_lock_path=args.uv_lock,
            consumed_access_path=args.consumed_access,
            evaluation_panel_path=args.evaluation_panel,
            primary_forecasts_path=args.primary_forecasts,
            timing_forecasts_path=args.timing_forecasts,
            result_path=args.result,
            result_schema_path=args.result_schema,
            report_path=args.report,
            evidence_index_path=args.evidence_index,
        )
    scientific = result["scientific_result"]
    assert isinstance(scientific, Mapping)
    print(
        json.dumps(
            {
                "status": result["status"],
                "decision": scientific["decision"],
                "manifest_sha256": result["manifest_sha256"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
