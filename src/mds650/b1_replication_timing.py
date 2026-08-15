"""Target-blind timing sensitivities for the independent B1/B2 replication.

The module derives registered FMP, Massive and Unusual Whales predictor views
without reading RV30, predictions, losses or model results.  Every derived
Massive/FMP attempt table remains bound to the original validated raw-payload
inventory through an immutable, self-hashed source manifest.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final, cast

import polars as pl
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from mds650.b1_replication_common import (
    _coverage,
    _technical_acceptance,
    build_replication_common_frame,
)
from mds650.b1v3_confirmation import (
    canonical_sha256,
    sha256_file,
    validate_confirmation_plan_schema,
)
from mds650.b1v3_confirmation_common import (
    _validate_origin_metadata,
    _write_json_if_identical,
    _write_parquet_if_identical,
)
from mds650.b1v3_confirmation_panel import build_spot_frame
from mds650.b1v3_massive_sensitivity import (
    write_fmp_delayed_attempts,
    write_massive_reselected_attempt_variants,
)

_VARIANTS: Final[tuple[str, ...]] = (
    "FMP_DELAY_2_MINUTES",
    "MASSIVE_CUTOFF_60_SECONDS",
    "MASSIVE_CUTOFF_300_SECONDS",
    "UW_CREATED_AT_120_SECONDS",
    "UW_CREATED_AT_300_SECONDS",
)
_ASSETS: Final[tuple[str, ...]] = (
    "AAPL",
    "AMZN",
    "META",
    "MSFT",
    "NVDA",
    "TSLA",
)
_FORBIDDEN_COLUMNS: Final[tuple[str, ...]] = (
    "rv30",
    "qlike",
    "prediction",
    "residual",
    "loss",
    "target",
)
_TARGET_BLIND_TARGET_NAMED_COLUMNS: Final[frozenset[str]] = frozenset({"target_moneyness"})


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


def _validate_target_blind_columns(path: Path) -> tuple[str, ...]:
    if not path.is_file():
        raise ValueError("B1_REPLICATION_TIMING_ATTEMPTS_MISSING")
    columns = tuple(pq.ParquetFile(path).schema_arrow.names)
    forbidden = [
        column
        for column in columns
        if column.lower() not in _TARGET_BLIND_TARGET_NAMED_COLUMNS
        and any(token in column.lower() for token in _FORBIDDEN_COLUMNS)
    ]
    if forbidden:
        raise ValueError("B1_REPLICATION_TIMING_FORBIDDEN_COLUMN")
    return columns


def _attempt_record(path: Path) -> dict[str, Any]:
    columns = _validate_target_blind_columns(path)
    metadata = pq.ParquetFile(path).metadata
    return {
        "logical_path": (f"MDS650_B1_REPLICATION_DATA_ROOT/predictors/timing/{path.name}"),
        "sha256": sha256_file(path),
        "bytes": path.stat().st_size,
        "row_count": metadata.num_rows,
        "columns": list(columns),
    }


def _file_record(path: Path, logical_path: str) -> dict[str, Any]:
    if not path.is_file() or path.stat().st_size <= 0:
        raise ValueError("B1_REPLICATION_TIMING_OUTPUT_MISSING")
    return {
        "logical_path": logical_path,
        "sha256": sha256_file(path),
        "bytes": path.stat().st_size,
    }


def _validate_primary_sources(
    *,
    preregistration_path: Path,
    base_manifest_path: Path,
    base_schema_path: Path,
    source_manifest_path: Path,
    source_schema_path: Path,
    source_inventory_path: Path,
    primary_attempts_path: Path,
    origins_path: Path,
    fmp_bars_path: Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    preregistration = _json_object(
        preregistration_path, code="B1_REPLICATION_TIMING_PREREGISTRATION_INVALID"
    )
    base = _json_object(base_manifest_path, code="B1_REPLICATION_TIMING_BASE_INVALID")
    source = _json_object(source_manifest_path, code="B1_REPLICATION_TIMING_SOURCE_INVALID")
    validate_confirmation_plan_schema(base, base_schema_path)
    validate_confirmation_plan_schema(source, source_schema_path)
    base_outputs = base.get("outputs")
    origin_record = base_outputs.get("origins") if isinstance(base_outputs, Mapping) else None
    bars_record = base_outputs.get("fmp_bars") if isinstance(base_outputs, Mapping) else None
    source_attempts = source.get("attempts")
    raw_binding = source.get("raw_payload_binding")
    prereg_hash = preregistration.get("manifest_sha256")
    if (
        not _self_hash_valid(preregistration)
        or preregistration.get("status") != "FROZEN_BEFORE_PROVIDER_PAYLOAD"
        or preregistration.get("replication_target_reads") != 0
        or preregistration.get("result_sign_selection") != "PROHIBITED"
        or not _self_hash_valid(base)
        or base.get("status") != "PASS_TARGET_BLIND_BASE_PREDICTORS"
        or base.get("preregistration_sha256") != prereg_hash
        or not isinstance(origin_record, Mapping)
        or origin_record.get("sha256") != sha256_file(origins_path)
        or not isinstance(bars_record, Mapping)
        or bars_record.get("sha256") != sha256_file(fmp_bars_path)
        or not _self_hash_valid(source)
        or source.get("status") != "PASS_TARGET_BLIND_B1Q_SOURCE_BOUND"
        or source.get("preregistration_manifest_sha256") != prereg_hash
        or source.get("base_manifest_sha256") != base.get("manifest_sha256")
        or not isinstance(source_attempts, Mapping)
        or source_attempts.get("sha256") != sha256_file(primary_attempts_path)
        or not isinstance(raw_binding, Mapping)
        or raw_binding.get("inventory_sha256") != sha256_file(source_inventory_path)
    ):
        raise ValueError("B1_REPLICATION_TIMING_SOURCE_BINDING_INVALID")
    _validate_target_blind_columns(primary_attempts_path)
    return preregistration, base, source


def seal_derived_attempt_source(
    *,
    variant: str,
    attempts_path: Path,
    original_source: Mapping[str, Any],
    derivation_summary: Mapping[str, Any],
    quote_cutoff_seconds: int,
    fmp_delay_minutes: int,
    inventory_path: Path,
    manifest_path: Path,
    schema_path: Path,
    derivation_code_path: Path,
) -> dict[str, Any]:
    """Seal one target-blind attempt derivation to the original raw inventory.

    Parameters
    ----------
    variant:
        Registered FMP or Massive sensitivity name.
    attempts_path:
        Newly materialized target-free attempt Parquet.
    original_source:
        Validated primary B1Q source manifest.
    derivation_summary:
        Deterministic counters emitted by the local derivation.
    quote_cutoff_seconds, fmp_delay_minutes:
        Exact registered timing assumptions.
    inventory_path, manifest_path, schema_path, derivation_code_path:
        Immutable raw inventory, output contract and implementation identity.

    Returns
    -------
    dict[str, Any]
        Schema-valid self-hashed derived source manifest.

    Raises
    ------
    ValueError
        If the variant, timing, target-blind schema or raw binding is invalid.
    """
    if variant not in _VARIANTS[:3]:
        raise ValueError("B1_REPLICATION_TIMING_VARIANT_INVALID")
    registered = {
        "FMP_DELAY_2_MINUTES": (0, 2),
        "MASSIVE_CUTOFF_60_SECONDS": (60, 1),
        "MASSIVE_CUTOFF_300_SECONDS": (300, 1),
    }
    if registered[variant] != (quote_cutoff_seconds, fmp_delay_minutes):
        raise ValueError("B1_REPLICATION_TIMING_ASSUMPTION_INVALID")
    raw_binding = original_source.get("raw_payload_binding")
    pit = original_source.get("pit_invariants")
    scope = original_source.get("scope")
    if (
        not _self_hash_valid(original_source)
        or original_source.get("status") != "PASS_TARGET_BLIND_B1Q_SOURCE_BOUND"
        or not isinstance(raw_binding, Mapping)
        or raw_binding.get("inventory_sha256") != sha256_file(inventory_path)
        or not isinstance(pit, Mapping)
        or not isinstance(scope, Mapping)
    ):
        raise ValueError("B1_REPLICATION_TIMING_PRIMARY_SOURCE_INVALID")
    attempt_record = _attempt_record(attempts_path)
    frame = pl.scan_parquet(attempts_path).select("forecast_origin_ns", "sip_timestamp")
    future = (
        frame.filter(
            pl.col("sip_timestamp").is_not_null()
            & (
                pl.col("sip_timestamp")
                > pl.col("forecast_origin_ns") - quote_cutoff_seconds * 1_000_000_000
            )
        )
        .collect()
        .height
    )
    if future:
        raise ValueError("B1_REPLICATION_TIMING_FUTURE_QUOTE")
    document: dict[str, Any] = {
        "schema_version": "b1-independent-replication-derived-b1q-source-1.0",
        "status": "PASS_TARGET_BLIND_B1Q_SOURCE_BOUND",
        "preregistration_manifest_sha256": original_source["preregistration_manifest_sha256"],
        "base_manifest_sha256": original_source["base_manifest_sha256"],
        "primary_source_manifest_sha256": original_source["manifest_sha256"],
        "target_blind": True,
        "outcome_read_count": 0,
        "safe_to_read_outcomes": False,
        "scope": dict(scope),
        "attempts": attempt_record,
        "derivation": {
            "variant": variant,
            "quote_cutoff_seconds": quote_cutoff_seconds,
            "fmp_delay_minutes": fmp_delay_minutes,
            "input_attempts_sha256": str(
                cast(Mapping[str, Any], original_source["attempts"])["sha256"]
            ),
            "derivation_code_sha256": sha256_file(derivation_code_path),
            "summary": dict(derivation_summary),
        },
        "raw_payload_binding": dict(raw_binding),
        "pit_invariants": {
            **dict(pit),
            "future_selected_quote_rows": 0,
            "derived_cutoff_validated": True,
        },
        "security": {
            "secret_values_emitted": False,
            "personal_paths_emitted": False,
        },
    }
    document["manifest_sha256"] = canonical_sha256(document)
    validate_confirmation_plan_schema(document, schema_path)
    _write_json_if_identical(manifest_path, document)
    return document


def materialize_replication_timing_attempts(
    *,
    preregistration_path: Path,
    base_manifest_path: Path,
    base_schema_path: Path,
    source_manifest_path: Path,
    source_schema_path: Path,
    source_inventory_path: Path,
    primary_attempts_path: Path,
    origins_path: Path,
    fmp_bars_path: Path,
    cache_root: Path,
    output_root: Path,
    derived_schema_path: Path,
    derivation_code_path: Path,
    batch_size: int = 65_536,
) -> dict[str, Any]:
    """Materialize all registered FMP/Massive attempt sensitivities locally.

    Returns a mapping containing immutable attempt and source-binding paths.
    Provider transport and outcome access are intentionally absent.
    """
    if batch_size <= 0:
        raise ValueError("B1_REPLICATION_TIMING_BATCH_SIZE_INVALID")
    _, _, source = _validate_primary_sources(
        preregistration_path=preregistration_path,
        base_manifest_path=base_manifest_path,
        base_schema_path=base_schema_path,
        source_manifest_path=source_manifest_path,
        source_schema_path=source_schema_path,
        source_inventory_path=source_inventory_path,
        primary_attempts_path=primary_attempts_path,
        origins_path=origins_path,
        fmp_bars_path=fmp_bars_path,
    )
    origins = pl.read_parquet(origins_path)
    bars = pl.read_parquet(fmp_bars_path)
    fmp_root = output_root / "fmp_delay_2"
    fmp_spots_path = fmp_root / "spots.parquet"
    fmp_attempts_path = fmp_root / "attempts.parquet"
    spots = build_spot_frame(bars, origins, delay_minutes=2)
    if spots.filter(~pl.col("spot_available")).height:
        raise ValueError("B1_REPLICATION_TIMING_FMP_SPOT_COVERAGE_INVALID")
    _write_parquet_if_identical(spots, fmp_spots_path)
    fmp_summary = write_fmp_delayed_attempts(
        attempts_path=primary_attempts_path,
        delayed_spots_path=fmp_spots_path,
        output_path=fmp_attempts_path,
        delay_minutes=2,
        batch_size=batch_size,
    )
    massive_outputs = {
        60: output_root / "massive/cutoff_60/attempts.parquet",
        300: output_root / "massive/cutoff_300/attempts.parquet",
    }
    massive_summary = write_massive_reselected_attempt_variants(
        attempts_path=primary_attempts_path,
        cache_root=cache_root,
        output_paths=massive_outputs,
        batch_size=batch_size,
    )
    variants = cast(Mapping[str, Any], massive_summary["variants"])
    definitions = {
        "FMP_DELAY_2_MINUTES": (fmp_attempts_path, fmp_summary, 0, 2),
        "MASSIVE_CUTOFF_60_SECONDS": (
            massive_outputs[60],
            cast(Mapping[str, Any], variants["60"]),
            60,
            1,
        ),
        "MASSIVE_CUTOFF_300_SECONDS": (
            massive_outputs[300],
            cast(Mapping[str, Any], variants["300"]),
            300,
            1,
        ),
    }
    result: dict[str, Any] = {}
    for variant, (attempts, summary, cutoff, fmp_delay) in definitions.items():
        source_path = attempts.parent / "derived_source_manifest.json"
        manifest = seal_derived_attempt_source(
            variant=variant,
            attempts_path=attempts,
            original_source=source,
            derivation_summary=summary,
            quote_cutoff_seconds=cutoff,
            fmp_delay_minutes=fmp_delay,
            inventory_path=source_inventory_path,
            manifest_path=source_path,
            schema_path=derived_schema_path,
            derivation_code_path=derivation_code_path,
        )
        result[variant] = {
            "attempts_path": attempts,
            "source_manifest_path": source_path,
            "source_manifest_sha256": manifest["manifest_sha256"],
            "summary": dict(summary),
        }
    return result


def finalize_replication_timing_predictors(
    *,
    preregistration_path: Path,
    base_manifest_path: Path,
    source_manifest_path: Path,
    source_inventory_path: Path,
    fmp_delay2_manifest_path: Path,
    variant_paths: Mapping[str, Mapping[str, Path]],
    output_path: Path,
    schema_path: Path,
    orchestrator_code_path: Path,
) -> dict[str, Any]:
    """Seal the three technical B1 timing packages after feature construction."""
    prereg = _json_object(preregistration_path, code="B1_REPLICATION_TIMING_PREREG_INVALID")
    base = _json_object(base_manifest_path, code="B1_REPLICATION_TIMING_BASE_INVALID")
    source = _json_object(source_manifest_path, code="B1_REPLICATION_TIMING_SOURCE_INVALID")
    delay2 = _json_object(fmp_delay2_manifest_path, code="B1_REPLICATION_TIMING_FMP_DELAY_INVALID")
    if set(variant_paths) != set(_VARIANTS[:3]):
        raise ValueError("B1_REPLICATION_TIMING_VARIANT_SCOPE_INVALID")
    variants: dict[str, Any] = {}
    for variant, paths in variant_paths.items():
        if set(paths) != {"attempts", "source", "features", "coverage", "manifest"}:
            raise ValueError("B1_REPLICATION_TIMING_OUTPUT_SCOPE_INVALID")
        derived = _json_object(paths["source"], code="B1_REPLICATION_TIMING_DERIVED_INVALID")
        feature_manifest = _json_object(
            paths["manifest"], code="B1_REPLICATION_TIMING_FEATURE_MANIFEST_INVALID"
        )
        if (
            not _self_hash_valid(derived)
            or not _self_hash_valid(feature_manifest)
            or feature_manifest.get("provenance", {}).get("source_binding_manifest_sha256")
            != derived.get("manifest_sha256")
        ):
            raise ValueError("B1_REPLICATION_TIMING_FEATURE_BINDING_INVALID")
        variants[variant] = {
            "attempts": _file_record(
                paths["attempts"],
                f"MDS650_B1_REPLICATION_DATA_ROOT/predictors/timing/{variant}/attempts.parquet",
            ),
            "source_manifest": _file_record(
                paths["source"],
                f"MDS650_B1_REPLICATION_DATA_ROOT/predictors/timing/{variant}/source.json",
            ),
            "features": _file_record(
                paths["features"],
                f"MDS650_B1_REPLICATION_DATA_ROOT/predictors/timing/{variant}/b1.parquet",
            ),
            "coverage": _file_record(
                paths["coverage"],
                f"MDS650_B1_REPLICATION_DATA_ROOT/predictors/timing/{variant}/coverage.json",
            ),
            "feature_manifest": _file_record(
                paths["manifest"],
                f"MDS650_B1_REPLICATION_DATA_ROOT/predictors/timing/{variant}/manifest.json",
            ),
        }
    document: dict[str, Any] = {
        "schema_version": "b1-independent-replication-timing-predictors-1.0",
        "status": "PASS_TARGET_BLIND_TIMING_PREDICTORS",
        "target_blind": True,
        "outcome_read_count": 0,
        "safe_to_read_outcomes": False,
        "source_bindings": {
            "preregistration_manifest_sha256": prereg["manifest_sha256"],
            "base_manifest_sha256": base["manifest_sha256"],
            "primary_b1q_source_manifest_sha256": source["manifest_sha256"],
            "source_inventory_sha256": sha256_file(source_inventory_path),
            "fmp_delay2_manifest_sha256": delay2["manifest_sha256"],
            "orchestrator_code_sha256": sha256_file(orchestrator_code_path),
        },
        "variants": variants,
        "security": {
            "secret_values_emitted": False,
            "personal_paths_emitted": False,
        },
    }
    document["manifest_sha256"] = canonical_sha256(document)
    validate_confirmation_plan_schema(document, schema_path)
    _write_json_if_identical(output_path, document)
    return document


def build_replication_timing_common_artifacts(
    *,
    preregistration_path: Path,
    primary_common_manifest_path: Path,
    base_manifest_path: Path,
    base_schema_path: Path,
    b1_feature_manifest_path: Path,
    b1_feature_schema_path: Path,
    fmp_delay2_manifest_path: Path,
    fmp_delay2_schema_path: Path,
    timing_predictor_manifest_path: Path,
    b2_manifest_path: Path,
    origins_path: Path,
    primary_b0_path: Path,
    fmp_delay2_b0_path: Path,
    primary_b1_path: Path,
    timing_b1_paths: Mapping[str, Path],
    primary_b2_path: Path,
    uw_b2_paths: Mapping[str, Path],
    output_root: Path,
    manifest_path: Path,
    schema_path: Path,
) -> dict[str, Any]:
    """Build all five registered target-blind common timing panels.

    Each panel retains the natural origin grid. Missing predictors stay missing;
    the function never imputes or balances rows.
    """
    if set(timing_b1_paths) != set(_VARIANTS[:3]) or set(uw_b2_paths) != {
        "UW_CREATED_AT_120_SECONDS",
        "UW_CREATED_AT_300_SECONDS",
    }:
        raise ValueError("B1_REPLICATION_TIMING_COMMON_VARIANT_SCOPE_INVALID")
    prereg = _json_object(preregistration_path, code="B1_REPLICATION_TIMING_COMMON_PREREG_INVALID")
    primary = _json_object(
        primary_common_manifest_path, code="B1_REPLICATION_TIMING_COMMON_PRIMARY_INVALID"
    )
    base = _json_object(base_manifest_path, code="B1_REPLICATION_TIMING_COMMON_BASE_INVALID")
    b1_feature = _json_object(
        b1_feature_manifest_path,
        code="B1_REPLICATION_TIMING_COMMON_B1_FEATURE_INVALID",
    )
    delay2 = _json_object(
        fmp_delay2_manifest_path,
        code="B1_REPLICATION_TIMING_COMMON_FMP_DELAY_INVALID",
    )
    validate_confirmation_plan_schema(base, base_schema_path)
    validate_confirmation_plan_schema(b1_feature, b1_feature_schema_path)
    validate_confirmation_plan_schema(delay2, fmp_delay2_schema_path)
    timing = _json_object(
        timing_predictor_manifest_path, code="B1_REPLICATION_TIMING_COMMON_B1_INVALID"
    )
    b2_manifest = _json_object(b2_manifest_path, code="B1_REPLICATION_TIMING_COMMON_B2_INVALID")
    if (
        not _self_hash_valid(prereg)
        or prereg.get("replication_target_reads") != 0
        or not _self_hash_valid(primary)
        or primary.get("status") != "PASS_TARGET_BLIND_COMMON_PREDICTOR_PANEL"
        or not _self_hash_valid(base)
        or not _self_hash_valid(b1_feature)
        or not _self_hash_valid(delay2)
        or not _self_hash_valid(timing)
        or timing.get("status") != "PASS_TARGET_BLIND_TIMING_PREDICTORS"
        or not _self_hash_valid(b2_manifest)
        or b2_manifest.get("status") != "PASS_TARGET_BLIND_B2_PREDICTORS"
    ):
        raise ValueError("B1_REPLICATION_TIMING_COMMON_SOURCE_INVALID")
    base_outputs = base.get("outputs")
    base_origins = base_outputs.get("origins") if isinstance(base_outputs, Mapping) else None
    base_b0 = base_outputs.get("b0") if isinstance(base_outputs, Mapping) else None
    b1_output = b1_feature.get("output")
    delay_output = delay2.get("output")
    timing_variants = timing.get("variants")
    b2_variants = b2_manifest.get("variants")
    if (
        not isinstance(base_origins, Mapping)
        or base_origins.get("sha256") != sha256_file(origins_path)
        or not isinstance(base_b0, Mapping)
        or base_b0.get("sha256") != sha256_file(primary_b0_path)
        or not isinstance(b1_output, Mapping)
        or b1_output.get("sha256") != sha256_file(primary_b1_path)
        or not isinstance(delay_output, Mapping)
        or delay_output.get("sha256") != sha256_file(fmp_delay2_b0_path)
        or not isinstance(timing_variants, Mapping)
        or not isinstance(b2_variants, Mapping)
    ):
        raise ValueError("B1_REPLICATION_TIMING_COMMON_FILE_BINDING_INVALID")
    for variant, path in timing_b1_paths.items():
        record = timing_variants.get(variant)
        features = record.get("features") if isinstance(record, Mapping) else None
        if not isinstance(features, Mapping) or features.get("sha256") != sha256_file(path):
            raise ValueError("B1_REPLICATION_TIMING_COMMON_B1_BINDING_INVALID")
    b2_path_bindings = {
        "primary_5m_60s": primary_b2_path,
        "latency_5m_120s": uw_b2_paths["UW_CREATED_AT_120_SECONDS"],
        "latency_5m_300s": uw_b2_paths["UW_CREATED_AT_300_SECONDS"],
    }
    for variant, path in b2_path_bindings.items():
        record = b2_variants.get(variant)
        if not isinstance(record, Mapping) or record.get("sha256") != sha256_file(path):
            raise ValueError("B1_REPLICATION_TIMING_COMMON_B2_BINDING_INVALID")
    origins = pl.read_parquet(origins_path)
    primary_b0 = pl.read_parquet(primary_b0_path)
    delay_b0 = pl.read_parquet(fmp_delay2_b0_path)
    primary_b1 = pl.read_parquet(primary_b1_path)
    primary_b2 = pl.read_parquet(primary_b2_path)
    definitions: dict[str, tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]] = {
        "FMP_DELAY_2_MINUTES": (
            delay_b0,
            pl.read_parquet(timing_b1_paths["FMP_DELAY_2_MINUTES"]),
            primary_b2,
        ),
        "MASSIVE_CUTOFF_60_SECONDS": (
            primary_b0,
            pl.read_parquet(timing_b1_paths["MASSIVE_CUTOFF_60_SECONDS"]),
            primary_b2,
        ),
        "MASSIVE_CUTOFF_300_SECONDS": (
            primary_b0,
            pl.read_parquet(timing_b1_paths["MASSIVE_CUTOFF_300_SECONDS"]),
            primary_b2,
        ),
        "UW_CREATED_AT_120_SECONDS": (
            primary_b0,
            primary_b1,
            pl.read_parquet(uw_b2_paths["UW_CREATED_AT_120_SECONDS"]),
        ),
        "UW_CREATED_AT_300_SECONDS": (
            primary_b0,
            primary_b1,
            pl.read_parquet(uw_b2_paths["UW_CREATED_AT_300_SECONDS"]),
        ),
    }
    records: dict[str, Any] = {}
    for variant in _VARIANTS:
        b0, b1, b2 = definitions[variant]
        for name, frame in (("B0", b0), ("B1", b1), ("B2", b2)):
            _validate_origin_metadata(origins, frame, name=f"{variant}_{name}")
        panel = build_replication_common_frame(origins=origins, b0=b0, b1=b1, b2=b2)
        if (
            panel.height != origins.height
            or panel["origin_id"].n_unique() != panel.height
            or set(panel["session_date"].cast(pl.String).unique())
            != set(str(value) for value in prereg["replication_sessions"])
            or set(panel["asset"].cast(pl.String).unique()) != set(_ASSETS)
        ):
            raise ValueError("B1_REPLICATION_TIMING_COMMON_SCOPE_INVALID")
        destination = output_root / variant.lower() / "common_predictor_panel.parquet"
        output_hash = _write_parquet_if_identical(panel, destination)
        acceptance = _technical_acceptance(panel)
        complete = panel.filter(pl.col("b2_information_set_complete"))
        if (
            complete.is_empty()
            or complete["asset"].n_unique() != 6
            or complete["session_date"].n_unique() != 30
        ):
            raise ValueError("B1_REPLICATION_TIMING_COMMON_COMPLETE_SAMPLE_INVALID")
        records[variant] = {
            "output": {
                "logical_path": (
                    "MDS650_B1_REPLICATION_DATA_ROOT/predictors/timing_common/"
                    f"{variant}/common_predictor_panel.parquet"
                ),
                "sha256": output_hash,
                "bytes": destination.stat().st_size,
                "row_count": panel.height,
            },
            "technical_acceptance": acceptance,
            "coverage": {
                "by_asset": _coverage(panel, "asset"),
                "by_session_tercile": _coverage(panel, "session_tercile"),
            },
        }
    document: dict[str, Any] = {
        "schema_version": "b1-independent-replication-timing-common-1.0",
        "status": "PASS_TARGET_BLIND_TIMING_COMMON_PANELS",
        "target_blind": True,
        "outcome_read_count": 0,
        "safe_to_read_outcomes": False,
        "source_bindings": {
            "preregistration_manifest_sha256": prereg["manifest_sha256"],
            "primary_common_manifest_sha256": primary["manifest_sha256"],
            "base_manifest_sha256": base["manifest_sha256"],
            "b1_feature_manifest_sha256": b1_feature["manifest_sha256"],
            "fmp_delay2_manifest_sha256": delay2["manifest_sha256"],
            "timing_predictor_manifest_sha256": timing["manifest_sha256"],
            "b2_manifest_sha256": b2_manifest["manifest_sha256"],
        },
        "variants": records,
        "security": {
            "secret_values_emitted": False,
            "personal_paths_emitted": False,
        },
    }
    document["manifest_sha256"] = canonical_sha256(document)
    validate_confirmation_plan_schema(document, schema_path)
    _write_json_if_identical(manifest_path, document)
    return document
