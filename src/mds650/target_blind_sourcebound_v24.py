"""Fail-closed v2.4 guard for a source-bound target-blind predictor panel.

The module validates only predictor-column contracts, already-acquired
provenance hashes, and output identities.  It cannot inspect outcomes,
predictions, metrics, model artefacts, sealed results, or OOS payloads.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import polars as pl
from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

from mds650.phase6 import (
    B0V2_FEATURES,
    B1V2A_FEATURES,
    B1V2B_FEATURES,
    B1V2C_FEATURES,
    B2V2_FEATURES,
)
from mds650.target_blind_panel_v22 import (
    KEY_COLUMNS,
)

_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_FORBIDDEN_TOKENS = frozenset(
    {
        "oos",
        "holdout",
        "outcome",
        "target",
        "prediction",
        "qlike",
        "metric",
        "model",
        "report",
        "evaluation",
        "result",
    }
)

B0_ALLOWED_COLUMNS = frozenset(
    (
        *KEY_COLUMNS,
        *B0V2_FEATURES,
        "b0v2_max_predictor_available_at_utc",
        "b0v2_predictor_missing_reason",
    )
)
B1_ALLOWED_COLUMNS = frozenset(
    (
        *KEY_COLUMNS,
        "forecast_origin_ns",
        "max_sip_timestamp_ns",
        *B1V2A_FEATURES,
        *B1V2B_FEATURES,
        *B1V2C_FEATURES,
        "b1v2a_complete",
        "b1v2b_complete",
        "b1v2c_complete",
        "b1q_source_time_rule",
        "b1v2_predictor_missing_reason",
    )
)
B2_ALLOWED_COLUMNS = frozenset(
    (
        *KEY_COLUMNS,
        *B2V2_FEATURES,
        "b2v2_complete",
        "b2v2_cutoff_utc",
        "b2v2_max_created_at_utc",
        "b2v2_availability_status",
        "b2v2_availability_eligible",
        "b2v2_corrected_pit_complete",
        "b2v2_predictor_missing_reason",
    )
)
_COMPLETENESS_COLUMNS = frozenset(
    {
        "b0v2_predictor_complete",
        "b1v2a_predictor_complete",
        "b1v2b_predictor_complete",
        "b1v2c_predictor_complete",
        "b2v2_predictor_complete",
        "common_predictor_complete",
        "predictor_exclusion_reason",
    }
)
PANEL_ALLOWED_COLUMNS = frozenset(
    B0_ALLOWED_COLUMNS | B1_ALLOWED_COLUMNS | B2_ALLOWED_COLUMNS | _COMPLETENESS_COLUMNS
)
_PROVENANCE_HASH_KEYS = (
    "origins_sha256",
    "b2_availability_sidecar_sha256",
    "massive_reselection_recomputed_v21_sha256",
    "b2_availability_manifest_v22_sha256",
    "pit_reconciliation_gate_v21_sha256",
)


def assert_safe_target_blind_paths_v24(paths: Mapping[str, Path]) -> None:
    """Reject result-like paths before any local input reader is invoked.

    ``target_blind`` and ``target-blind`` directory names are intentionally
    allowed because they identify this sealed preparation layer, not a target
    payload.  All other standalone outcome/target/metric/model-like tokens are
    rejected without echoing the supplied path.
    """
    for role, path in paths.items():
        for component in path.parts:
            normalised = component.casefold()
            if normalised.replace("-", "_").startswith("target_blind"):
                continue
            tokens = (token for token in re.split(r"[^a-z0-9]+", normalised) if token)
            if any(token in _FORBIDDEN_TOKENS for token in tokens):
                raise ValueError(f"TARGET_BLIND_V24_FORBIDDEN_INPUT_PATH:{role}")


def validate_sourcebound_panel_v24(
    *, origins: pl.DataFrame, panel: pl.DataFrame, common: pl.DataFrame
) -> None:
    """Require exact target-blind columns, preserved origins, and null B2 exclusions."""
    _assert_no_forbidden_columns({"origins": origins, "panel": panel, "common": common})
    _assert_exact_columns("origins", origins, frozenset(KEY_COLUMNS))
    _assert_exact_columns("panel", panel, PANEL_ALLOWED_COLUMNS)
    _assert_exact_columns("common", common, PANEL_ALLOWED_COLUMNS)
    _assert_unique_origins("origins", origins)
    _assert_unique_origins("panel", panel)
    _assert_unique_origins("common", common)

    canonical_origins = origins.select(*KEY_COLUMNS).sort("origin_id")
    observed_origins = panel.select(*KEY_COLUMNS).sort("origin_id")
    if panel.height != origins.height or not observed_origins.equals(canonical_origins):
        raise ValueError("TARGET_BLIND_V24_ORIGIN_PRESERVATION_FAILURE")

    expected_common = panel.filter(pl.col("common_predictor_complete")).sort("origin_id")
    if not expected_common.equals(common.sort("origin_id")):
        raise ValueError("TARGET_BLIND_V24_COMMON_SUBSET_MISMATCH")

    excluded = panel.filter(~pl.col("b2v2_availability_eligible").fill_null(False))
    if excluded.is_empty():
        return
    if excluded.get_column("b2v2_availability_eligible").null_count():
        raise ValueError("TARGET_BLIND_V24_B2_EXCLUSION_FLAG_NULL")
    for feature in B2V2_FEATURES:
        if excluded.get_column(feature).null_count() != excluded.height:
            raise ValueError("TARGET_BLIND_V24_B2_EXCLUDED_FEATURE_NOT_NULL")
    invalid_reason = excluded.filter(
        pl.col("b2v2_availability_status").is_null()
        | (
            pl.col("b2v2_predictor_missing_reason")
            != pl.lit("B2V2_DELAYED_OR_UNAVAILABLE_ACTIVITY")
        )
    )
    if invalid_reason.height:
        raise ValueError("TARGET_BLIND_V24_B2_EXCLUSION_CODE_INVALID")


def assert_preflight_hashes_unchanged_v24(
    *, before: Mapping[str, str], after: Mapping[str, str]
) -> None:
    """Reject evidence byte drift between preflight and completed panel construction."""
    for key in _PROVENANCE_HASH_KEYS:
        _require_sha256(before.get(key), "TARGET_BLIND_V24_PREFLIGHT_HASH_INVALID")
        _require_sha256(after.get(key), "TARGET_BLIND_V24_POSTBUILD_HASH_INVALID")
        if before[key] != after[key]:
            if key == "b2_availability_sidecar_sha256":
                raise ValueError("TARGET_BLIND_V24_SIDECAR_CHANGED_AFTER_PREFLIGHT")
            raise ValueError("TARGET_BLIND_V24_PROVENANCE_CHANGED_AFTER_PREFLIGHT")


def write_if_new_or_identical_v24(path: Path, writer: Callable[[Path], None]) -> None:
    """Atomically retain byte-identical output and reject any conflicting replay."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.part")
    try:
        writer(temporary)
        if path.exists():
            if not _files_equal(temporary, path):
                raise FileExistsError("TARGET_BLIND_V24_OUTPUT_EXISTS_WITH_DIFFERENT_BYTES")
            return
        try:
            os.link(temporary, path)
        except FileExistsError:
            if not _files_equal(temporary, path):
                raise FileExistsError(
                    "TARGET_BLIND_V24_OUTPUT_EXISTS_WITH_DIFFERENT_BYTES"
                ) from None
    finally:
        temporary.unlink(missing_ok=True)


def build_sourcebound_manifest_v24(
    *,
    panel: pl.DataFrame,
    common: pl.DataFrame,
    panel_path: Path,
    common_path: Path,
    provenance_hashes: Mapping[str, str],
    source_hashes: Mapping[str, str],
    summary: Mapping[str, Any],
    builder_hashes: Mapping[str, str],
    source_commit: str,
    panel_location: str,
    common_location: str,
) -> dict[str, Any]:
    """Create a deterministic v2.4 manifest without values from the predictor matrix."""
    for key in _PROVENANCE_HASH_KEYS:
        _require_sha256(provenance_hashes.get(key), "TARGET_BLIND_V24_PROVENANCE_HASH_INVALID")
    required_source = (
        "fmp_bars_sha256",
        "b1q_source_sha256",
        "b2_primary_inputs_sha256",
        "origins_sha256",
        "b2_availability_sidecar_sha256",
        "massive_reselection_sensitivity_v21_sha256",
    )
    for key in required_source:
        _require_sha256(source_hashes.get(key), "TARGET_BLIND_V24_SOURCE_HASH_INVALID")
    for key in (
        "script_sha256",
        "panel_module_sha256",
        "base_panel_module_sha256",
        "provenance_module_sha256",
    ):
        _require_sha256(builder_hashes.get(key), "TARGET_BLIND_V24_BUILDER_HASH_INVALID")
    if re.fullmatch(r"[0-9a-f]{40}", source_commit) is None:
        raise ValueError("TARGET_BLIND_V24_SOURCE_COMMIT_INVALID")
    if not panel_location.startswith("D:/MDS650/") or not common_location.startswith("D:/MDS650/"):
        raise ValueError("TARGET_BLIND_V24_OUTPUT_LOCATION_INVALID")

    manifest: dict[str, Any] = {
        "schema_version": "target-blind-common-predictor-manifest-v2.4",
        "status": "PASS_TARGET_BLIND_INPUTS_RECONCILIATION_REMAINS_BLOCKED",
        "scope": "offline_target_blind_predictor_construction_only",
        "no_target_or_metric_payload_read": True,
        "model_fit_performed": False,
        "safe_to_reconcile_existing_results": "NO",
        "SAFE_TO_OPEN_OR_EVALUATE_OOS": "NO",
        "input_provenance": {
            "availability_sidecar_status": "PASS_WITH_EXCLUSIONS",
            "reconciliation_gate_status": "CONDITIONAL_NOT_CLOSED",
            "edge_conclusion": "NOT_EVALUATED_TARGET_BLIND",
            "primary_excluded_row_count": 451,
        },
        "timing_rules": {
            "fmp_primary_delay_minutes": 1,
            "fmp_sensitivity_delay_minutes": 2,
            "b1q_primary_state": "SIP_ASOF_ORIGIN_MAX_AGE_60S",
            "massive_reselection_sensitivity_cutoff_seconds": [60, 300],
            "b2_primary_variant": "primary_5m_60s",
            "b2_created_at_rule": "OPERATIONAL_AVAILABILITY_PROXY_ORIGIN_MINUS_60_SECONDS",
        },
        "column_contract": {
            "b0_allowlist": sorted(B0_ALLOWED_COLUMNS),
            "b1_allowlist": sorted(B1_ALLOWED_COLUMNS),
            "b2_allowlist": sorted(B2_ALLOWED_COLUMNS),
            "panel_allowlist": sorted(PANEL_ALLOWED_COLUMNS),
            "forbidden_input_path_guard": "ENFORCED",
            "b2_exclusion_encoding": "ALL_B2_FEATURES_NULL_WITH_ELIGIBILITY_FLAG_AND_REASON",
        },
        "source_hashes": {
            "origins_sha256": provenance_hashes["origins_sha256"],
            "fmp_bars_sha256": source_hashes["fmp_bars_sha256"],
            "b1q_source_sha256": source_hashes["b1q_source_sha256"],
            "b2_primary_inputs_sha256": source_hashes["b2_primary_inputs_sha256"],
            "b2_availability_sidecar_sha256": provenance_hashes["b2_availability_sidecar_sha256"],
            "massive_reselection_recomputed_v21_sha256": provenance_hashes[
                "massive_reselection_recomputed_v21_sha256"
            ],
            "b2_availability_manifest_v22_sha256": provenance_hashes[
                "b2_availability_manifest_v22_sha256"
            ],
            "pit_reconciliation_gate_v21_sha256": provenance_hashes[
                "pit_reconciliation_gate_v21_sha256"
            ],
        },
        "builder_hashes": dict(builder_hashes),
        "output": {
            "panel_sha256": _sha256_file(panel_path),
            "common_complete_sha256": _sha256_file(common_path),
            "row_count": panel.height,
            "common_complete_row_count": common.height,
        },
        "summary": dict(summary),
        "source_commit": source_commit,
        "output_locations": {
            "panel": panel_location,
            "common_complete": common_location,
        },
    }
    manifest["manifest_sha256"] = _canonical_sha256(manifest)
    return manifest


def validate_sourcebound_manifest_v24(manifest: Mapping[str, Any], schema_path: Path) -> None:
    """Validate the v2.4 JSON Schema and semantic manifest self-hash."""
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        errors = list(Draft202012Validator(schema).iter_errors(manifest))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("TARGET_BLIND_V24_OUTPUT_MANIFEST_SCHEMA_UNREADABLE") from exc
    if errors:
        raise ValueError("TARGET_BLIND_V24_OUTPUT_MANIFEST_SCHEMA_VIOLATION")
    recorded_hash = manifest.get("manifest_sha256")
    if not isinstance(recorded_hash, str):
        raise ValueError("TARGET_BLIND_V24_OUTPUT_MANIFEST_SELF_HASH_INVALID")
    unsigned = dict(manifest)
    unsigned.pop("manifest_sha256", None)
    if _canonical_sha256(unsigned) != recorded_hash:
        raise ValueError("TARGET_BLIND_V24_OUTPUT_MANIFEST_SELF_HASH_MISMATCH")


def _assert_no_forbidden_columns(frames: Mapping[str, pl.DataFrame]) -> None:
    for label, frame in frames.items():
        for column in frame.columns:
            tokens = (token for token in re.split(r"[^a-z0-9]+", column.casefold()) if token)
            if any(token in _FORBIDDEN_TOKENS for token in tokens):
                raise ValueError(f"TARGET_BLIND_V24_FORBIDDEN_COLUMN:{label}:{column}")


def _assert_exact_columns(label: str, frame: pl.DataFrame, allowed: frozenset[str]) -> None:
    observed = frozenset(frame.columns)
    if observed == allowed:
        return
    if observed - allowed:
        raise ValueError(f"TARGET_BLIND_V24_COLUMN_NOT_ALLOWLISTED:{label}")
    raise ValueError(f"TARGET_BLIND_V24_REQUIRED_COLUMNS_MISSING:{label}")


def _assert_unique_origins(label: str, frame: pl.DataFrame) -> None:
    origin_ids = frame.get_column("origin_id")
    if origin_ids.null_count() or origin_ids.n_unique() != frame.height:
        raise ValueError(f"TARGET_BLIND_V24_DUPLICATE_ORIGIN:{label}")


def _require_sha256(value: object, error_code: str) -> None:
    if not isinstance(value, str) or _SHA256_PATTERN.fullmatch(value) is None:
        raise ValueError(error_code)


def _files_equal(left: Path, right: Path) -> bool:
    if left.stat().st_size != right.stat().st_size:
        return False
    with left.open("rb") as left_handle, right.open("rb") as right_handle:
        while left_chunk := left_handle.read(1024 * 1024):
            if left_chunk != right_handle.read(1024 * 1024):
                return False
        return right_handle.read(1) == b""


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_sha256(payload: Mapping[str, Any]) -> str:
    rendered = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()
