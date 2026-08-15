"""Fail-closed pre-read quality and one-read access gates for replication."""

from __future__ import annotations

import json
import os
import shutil
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final

import polars as pl

from mds650.b1_replication_common import build_replication_common_frame
from mds650.b1v3_confirmation import (
    canonical_sha256,
    sha256_file,
    validate_confirmation_plan_schema,
)
from mds650.b1v3_confirmation_common import _write_json_if_identical

_TIMING_VARIANTS: Final[tuple[str, ...]] = (
    "FMP_DELAY_2_MINUTES",
    "MASSIVE_CUTOFF_60_SECONDS",
    "MASSIVE_CUTOFF_300_SECONDS",
    "UW_CREATED_AT_120_SECONDS",
    "UW_CREATED_AT_300_SECONDS",
)
_FORBIDDEN_BYTES: Final[tuple[bytes, ...]] = (
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


def _self_hash_valid(document: Mapping[str, Any], field: str = "manifest_sha256") -> bool:
    stored = document.get(field)
    unsigned = {key: value for key, value in document.items() if key != field}
    return isinstance(stored, str) and stored == canonical_sha256(unsigned)


def _contract(path: Path, schema_path: Path, *, code: str) -> dict[str, Any]:
    document = _json_object(path, code=code)
    validate_confirmation_plan_schema(document, schema_path)
    if not _self_hash_valid(document):
        raise ValueError(f"{code}_HASH")
    return document


def _provider_report(path: Path, schema_path: Path, *, code: str) -> dict[str, Any]:
    document = _json_object(path, code=code)
    validate_confirmation_plan_schema(document, schema_path)
    security = document.get("security")
    if (
        not _self_hash_valid(document, "report_sha256")
        or document.get("status") != "PASS_PROVIDER_PREFLIGHT_ASSUMPTION_BOUND"
        or document.get("target_blind") is not True
        or document.get("outcome_read_count") != 0
        or document.get("safe_to_read_outcomes") is not False
        or not isinstance(security, Mapping)
        or security.get("secret_values_emitted") is not False
        or security.get("personal_paths_emitted") is not False
    ):
        raise ValueError(code)
    return document


def _manifest_output_hash(document: Mapping[str, Any], path: Path) -> bool:
    output = document.get("output")
    return isinstance(output, Mapping) and output.get("sha256") == sha256_file(path)


def _code_bundle_sha256(paths: Sequence[Path]) -> str:
    if not paths or any(not path.is_file() for path in paths):
        raise ValueError("B1_REPLICATION_ACCESS_CODE_MISSING")
    return canonical_sha256(
        {
            "files": [
                {"name": path.name, "sha256": sha256_file(path)}
                for path in sorted(paths, key=lambda item: item.name)
            ]
        }
    )


def build_pre_read_quality_and_access(
    *,
    preregistration_path: Path,
    preregistration_schema_path: Path,
    method_freeze_path: Path,
    method_freeze_schema_path: Path,
    provider_report_path: Path,
    market_report_path: Path,
    provider_report_schema_path: Path,
    full_tape_manifest_path: Path,
    full_tape_schema_path: Path,
    base_manifest_path: Path,
    base_schema_path: Path,
    b1_source_manifest_path: Path,
    b1_source_schema_path: Path,
    b1_inventory_path: Path,
    b1_feature_manifest_path: Path,
    b1_feature_schema_path: Path,
    b2_manifest_path: Path,
    b2_schema_path: Path,
    common_manifest_path: Path,
    common_schema_path: Path,
    timing_predictor_manifest_path: Path,
    timing_predictor_schema_path: Path,
    timing_common_manifest_path: Path,
    timing_common_schema_path: Path,
    training_timing_manifest_path: Path,
    training_timing_schema_path: Path,
    origins_path: Path,
    b0_path: Path,
    b1_path: Path,
    b2_path: Path,
    common_panel_path: Path,
    timing_panel_paths: Mapping[str, Path],
    training_timing_panel_paths: Mapping[str, Path],
    fmp_bars_path: Path,
    training_snapshot_path: Path,
    code_paths: Sequence[Path],
    uv_lock_path: Path,
    data_root: Path,
    quality_path: Path,
    quality_schema_path: Path,
    access_path: Path,
    access_schema_path: Path,
    minimum_free_gib: float = 80.0,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Seal all target-blind gates and one unconsumed replication token.

    The function replays the primary predictor join, verifies every registered
    timing panel and freezes the terminal rule. It never computes or reads RV30.
    """
    prereg = _contract(
        preregistration_path,
        preregistration_schema_path,
        code="B1_REPLICATION_ACCESS_PREREGISTRATION_INVALID",
    )
    method = _contract(
        method_freeze_path,
        method_freeze_schema_path,
        code="B1_REPLICATION_ACCESS_METHOD_INVALID",
    )
    provider = _provider_report(
        provider_report_path,
        provider_report_schema_path,
        code="B1_REPLICATION_ACCESS_PROVIDER_REPORT_INVALID",
    )
    market = _provider_report(
        market_report_path,
        provider_report_schema_path,
        code="B1_REPLICATION_ACCESS_MARKET_REPORT_INVALID",
    )
    full_tape = _contract(
        full_tape_manifest_path,
        full_tape_schema_path,
        code="B1_REPLICATION_ACCESS_FULL_TAPE_INVALID",
    )
    base = _contract(
        base_manifest_path,
        base_schema_path,
        code="B1_REPLICATION_ACCESS_BASE_INVALID",
    )
    source = _contract(
        b1_source_manifest_path,
        b1_source_schema_path,
        code="B1_REPLICATION_ACCESS_B1_SOURCE_INVALID",
    )
    b1_feature = _contract(
        b1_feature_manifest_path,
        b1_feature_schema_path,
        code="B1_REPLICATION_ACCESS_B1_FEATURE_INVALID",
    )
    b2 = _contract(b2_manifest_path, b2_schema_path, code="B1_REPLICATION_ACCESS_B2_INVALID")
    common = _contract(
        common_manifest_path,
        common_schema_path,
        code="B1_REPLICATION_ACCESS_COMMON_INVALID",
    )
    timing_predictor = _contract(
        timing_predictor_manifest_path,
        timing_predictor_schema_path,
        code="B1_REPLICATION_ACCESS_TIMING_PREDICTOR_INVALID",
    )
    timing_common = _contract(
        timing_common_manifest_path,
        timing_common_schema_path,
        code="B1_REPLICATION_ACCESS_TIMING_COMMON_INVALID",
    )
    training_timing = _contract(
        training_timing_manifest_path,
        training_timing_schema_path,
        code="B1_REPLICATION_ACCESS_TRAINING_TIMING_INVALID",
    )
    if (
        set(timing_panel_paths) != set(_TIMING_VARIANTS)
        or set(training_timing_panel_paths) != set(_TIMING_VARIANTS)
    ):
        raise ValueError("B1_REPLICATION_ACCESS_TIMING_SCOPE_INVALID")
    source_raw = source.get("raw_payload_binding")
    b1_provenance = b1_feature.get("provenance")
    common_acceptance = common.get("technical_acceptance")
    timing_records = timing_common.get("variants")
    training_timing_records = training_timing.get("variants")
    method_sources = method.get("source_bindings")
    b2_variants = b2.get("variants")
    primary_b2 = b2_variants.get("primary_5m_60s") if isinstance(b2_variants, Mapping) else None
    conditions: dict[str, bool] = {
        "preregistration_zero_target_reads": prereg.get("replication_target_reads") == 0,
        "method_frozen_zero_target_reads": method.get("replication_target_read_count") == 0,
        "provider_preflight_pass": provider.get("status")
        == "PASS_PROVIDER_PREFLIGHT_ASSUMPTION_BOUND",
        "market_control_preflight_pass": market.get("status")
        == "PASS_PROVIDER_PREFLIGHT_ASSUMPTION_BOUND",
        "full_tape_all_30_sessions_pass": (
            full_tape.get("status") == "PASS"
            and full_tape.get("completed_session_count") == 30
            and full_tape.get("pending_session_count") == 0
        ),
        "base_predictors_pass": base.get("status") == "PASS_TARGET_BLIND_BASE_PREDICTORS",
        "b1_raw_inventory_bound": (
            isinstance(source_raw, Mapping)
            and source_raw.get("inventory_sha256") == sha256_file(b1_inventory_path)
        ),
        "b1_source_bound": (
            b1_feature.get("status") == "PASS_TARGET_BLIND_SOURCE_BOUND_TECHNICAL_BUILD"
            and isinstance(b1_provenance, Mapping)
            and b1_provenance.get("source_binding_manifest_sha256")
            == source.get("manifest_sha256")
            and _manifest_output_hash(b1_feature, b1_path)
        ),
        "b2_source_bound": (
            b2.get("status") == "PASS_TARGET_BLIND_B2_PREDICTORS"
            and isinstance(primary_b2, Mapping)
            and primary_b2.get("sha256") == sha256_file(b2_path)
        ),
        "primary_common_pass": (
            common.get("status") == "PASS_TARGET_BLIND_COMMON_PREDICTOR_PANEL"
            and isinstance(common_acceptance, Mapping)
            and common_acceptance.get("status") == "PASS"
            and _manifest_output_hash(common, common_panel_path)
        ),
        "timing_predictors_pass": timing_predictor.get("status")
        == "PASS_TARGET_BLIND_TIMING_PREDICTORS",
        "timing_common_all_variants_pass": (
            timing_common.get("status") == "PASS_TARGET_BLIND_TIMING_COMMON_PANELS"
            and isinstance(timing_records, Mapping)
            and set(timing_records) == set(_TIMING_VARIANTS)
        ),
        "training_timing_all_variants_bound": (
            training_timing.get("status") == "PASS_TARGET_BLIND_TIMING_COMMON_PANELS"
            and isinstance(training_timing_records, Mapping)
            and set(training_timing_records) == set(_TIMING_VARIANTS)
        ),
        "training_snapshot_bound": (
            isinstance(method_sources, Mapping)
            and method_sources.get("training_snapshot_sha256")
            == sha256_file(training_snapshot_path)
        ),
        "fmp_target_source_bound": fmp_bars_path.is_file(),
        "uv_lock_present": uv_lock_path.is_file(),
    }
    if isinstance(timing_records, Mapping):
        for variant, path in timing_panel_paths.items():
            record = timing_records.get(variant)
            output = record.get("output") if isinstance(record, Mapping) else None
            acceptance = (
                record.get("technical_acceptance")
                if isinstance(record, Mapping)
                else None
            )
            conditions[f"timing_{variant}_bound"] = (
                isinstance(output, Mapping)
                and output.get("sha256") == sha256_file(path)
                and isinstance(acceptance, Mapping)
                and int(acceptance.get("common_complete_origin_count", 0)) > 0
            )
    if isinstance(training_timing_records, Mapping):
        training_dates = {str(value) for value in prereg["training_sessions"]}
        for variant, path in training_timing_panel_paths.items():
            record = training_timing_records.get(variant)
            conditions[f"training_timing_{variant}_bound"] = (
                isinstance(record, Mapping)
                and record.get("sha256") == sha256_file(path)
            )
            frame = pl.scan_parquet(path).select("session_date", "asset").collect()
            scoped = frame.filter(
                pl.col("session_date").cast(pl.String).is_in(training_dates)
            )
            conditions[f"training_timing_{variant}_scope"] = (
                scoped["session_date"].n_unique() == 60
                and scoped["asset"].n_unique() == 6
            )
    origins = pl.read_parquet(origins_path)
    b0 = pl.read_parquet(b0_path)
    b1_frame = pl.read_parquet(b1_path)
    b2_frame = pl.read_parquet(b2_path)
    replay = build_replication_common_frame(
        origins=origins,
        b0=b0,
        b1=b1_frame,
        b2=b2_frame,
    )
    retained = pl.read_parquet(common_panel_path)
    conditions["deterministic_primary_panel_replay"] = retained.equals(
        replay, null_equal=True
    )
    free_gib = shutil.disk_usage(data_root).free / 1024**3
    conditions["minimum_80_gib_free"] = free_gib >= minimum_free_gib
    code_bundle = _code_bundle_sha256(code_paths)
    conditions["all_target_blind_gates_pass"] = all(conditions.values())
    if not all(conditions.values()):
        failed = sorted(name for name, passed in conditions.items() if not passed)
        raise ValueError(f"B1_REPLICATION_PRE_READ_QUALITY_FAILED:{','.join(failed)}")
    quality: dict[str, Any] = {
        "schema_version": "b1-independent-replication-quality-1.0",
        "status": "PASS_PRE_READ_REPLICATION_QUALITY",
        "target_blind": True,
        "replication_target_read_count": 0,
        "result_sign_selection": "PROHIBITED",
        "conditions": conditions,
        "free_gib_at_gate": round(free_gib, 6),
        "source_bindings": {
            "preregistration_manifest_sha256": prereg["manifest_sha256"],
            "method_freeze_manifest_sha256": method["manifest_sha256"],
            "provider_report_sha256": provider["report_sha256"],
            "market_report_sha256": market["report_sha256"],
            "full_tape_manifest_sha256": full_tape["manifest_sha256"],
            "base_manifest_sha256": base["manifest_sha256"],
            "b1_source_manifest_sha256": source["manifest_sha256"],
            "b1_feature_manifest_sha256": b1_feature["manifest_sha256"],
            "b2_manifest_sha256": b2["manifest_sha256"],
            "common_manifest_sha256": common["manifest_sha256"],
            "timing_predictor_manifest_sha256": timing_predictor["manifest_sha256"],
            "timing_common_manifest_sha256": timing_common["manifest_sha256"],
            "training_timing_manifest_sha256": training_timing["manifest_sha256"],
            "common_panel_sha256": sha256_file(common_panel_path),
            "fmp_bars_sha256": sha256_file(fmp_bars_path),
            "code_bundle_sha256": code_bundle,
            "uv_lock_sha256": sha256_file(uv_lock_path),
        },
        "security": {
            "secret_values_emitted": False,
            "personal_paths_emitted": False,
        },
    }
    quality["manifest_sha256"] = canonical_sha256(quality)
    validate_confirmation_plan_schema(quality, quality_schema_path)
    _write_json_if_identical(quality_path, quality)
    access: dict[str, Any] = {
        "schema_version": "b1-independent-replication-access-1.0",
        "status": "READY_FOR_SINGLE_REPLICATION_READ",
        "replication_target_read_count": 0,
        "evaluation_attempt_count": 0,
        "available_read_tokens": 1,
        "results_inspected": False,
        "result_sign_selection": "PROHIBITED",
        "preregistration_manifest_sha256": prereg["manifest_sha256"],
        "method_freeze_manifest_sha256": method["manifest_sha256"],
        "quality_manifest_sha256": quality["manifest_sha256"],
        "common_panel_sha256": sha256_file(common_panel_path),
        "timing_common_manifest_sha256": timing_common["manifest_sha256"],
        "training_timing_manifest_sha256": training_timing["manifest_sha256"],
        "fmp_bars_sha256": sha256_file(fmp_bars_path),
        "code_bundle_sha256": code_bundle,
        "uv_lock_sha256": sha256_file(uv_lock_path),
        "terminal_rule": {
            "version": "b1-independent-replication-terminal-rule-1.0",
            "gamma_required": [
                "delta_b2_estimate_positive",
                "delta_b2_ci_low_above_zero",
                "delta_b2_holm_p_below_0_05",
                "delta_b2_estimate_at_least_training_mde",
            ],
            "model_independent_additional_requirement": (
                "lightgbm_delta_b2_estimate_positive"
            ),
            "otherwise": "NOT_REPLICATED",
            "valid_states": [
                "REPLICATED_MODEL_INDEPENDENT",
                "REPLICATED_GAMMA_ONLY",
                "NOT_REPLICATED",
                "INVALID_REPLICATION",
            ],
        },
        "security": {
            "secret_values_emitted": False,
            "personal_paths_emitted": False,
        },
    }
    access["manifest_sha256"] = canonical_sha256(access)
    validate_confirmation_plan_schema(access, access_schema_path)
    _write_json_if_identical(access_path, access)
    return quality, access


def consume_replication_access_exclusively(
    frozen_access: Mapping[str, Any],
    *,
    path: Path,
    access_schema_path: Path,
) -> dict[str, Any]:
    """Consume the only target-read token with a durable exclusive create."""
    if (
        not _self_hash_valid(frozen_access)
        or frozen_access.get("status") != "READY_FOR_SINGLE_REPLICATION_READ"
        or frozen_access.get("replication_target_read_count") != 0
        or frozen_access.get("evaluation_attempt_count") != 0
        or frozen_access.get("available_read_tokens") != 1
        or frozen_access.get("results_inspected") is not False
        or frozen_access.get("result_sign_selection") != "PROHIBITED"
    ):
        raise ValueError("B1_REPLICATION_ACCESS_FROZEN_INVALID")
    unsigned = {
        key: value for key, value in frozen_access.items() if key != "manifest_sha256"
    }
    consumed: dict[str, Any] = {
        **unsigned,
        "status": "REPLICATION_EVALUATION_IN_PROGRESS",
        "replication_target_read_count": 1,
        "evaluation_attempt_count": 1,
        "available_read_tokens": 0,
    }
    consumed["manifest_sha256"] = canonical_sha256(consumed)
    validate_confirmation_plan_schema(consumed, access_schema_path)
    payload = (
        json.dumps(consumed, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    ).encode("utf-8")
    if any(token in payload.lower() for token in _FORBIDDEN_BYTES):
        raise ValueError("B1_REPLICATION_ACCESS_OUTPUT_HYGIENE_INVALID")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise ValueError("B1_REPLICATION_ACCESS_ALREADY_CONSUMED") from exc
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return consumed
