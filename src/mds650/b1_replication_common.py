"""Build the source-bound predictor-only panel for independent replication."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final, cast

import polars as pl

from mds650.b1v3_confirmation import (
    canonical_sha256,
    sha256_file,
    validate_confirmation_plan_schema,
)
from mds650.b1v3_confirmation_common import (
    B1V3_PRIMARY_INFORMATION_SETS,
    _validate_origin_metadata,
    _write_json_if_identical,
    _write_parquet_if_identical,
    build_common_predictor_frame,
)
from mds650.study_design import B2_FEATURE_NAMES

_ASSETS: Final[tuple[str, ...]] = (
    "AAPL",
    "AMZN",
    "META",
    "MSFT",
    "NVDA",
    "TSLA",
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


def build_replication_common_frame(
    *,
    origins: pl.DataFrame,
    b0: pl.DataFrame,
    b1: pl.DataFrame,
    b2: pl.DataFrame,
) -> pl.DataFrame:
    """Assemble nested predictors while retaining every replication origin."""
    replication_origins = origins.with_columns(pl.lit("confirmation").alias("role"))
    panel = build_common_predictor_frame(
        origins=replication_origins,
        b0=b0,
        b1=b1,
        b2=b2,
    )
    if set(panel["role"].unique()) != {"confirmation"}:
        raise ValueError("B1_REPLICATION_COMMON_ROLE_INVALID")
    return panel


def _coverage(frame: pl.DataFrame, dimension: str) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in (
            frame.group_by(dimension)
            .agg(
                pl.len().alias("origin_count"),
                pl.col("b0_information_set_complete").mean().alias("b0_coverage"),
                pl.col("b1v3a_information_set_complete").mean().alias(
                    "b1v3a_coverage"
                ),
                pl.col("b2_information_set_complete").mean().alias("b2_coverage"),
            )
            .sort(dimension)
            .to_dicts()
        )
    ]


def _technical_acceptance(panel: pl.DataFrame) -> dict[str, Any]:
    global_coverage = float(
        cast(float, panel["b1v3a_information_set_complete"].mean())
    )
    asset_rows = _coverage(panel, "asset")
    tercile_rows = _coverage(panel, "session_tercile")
    common = panel.filter(pl.col("b2_information_set_complete"))
    conditions = {
        "b1v3a_global_at_least_80_percent": global_coverage >= 0.80,
        "b1v3a_each_asset_at_least_65_percent": all(
            float(cast(float, row["b1v3a_coverage"])) >= 0.65 for row in asset_rows
        ),
        "b1v3a_each_tercile_at_least_60_percent": all(
            float(cast(float, row["b1v3a_coverage"])) >= 0.60
            for row in tercile_rows
        ),
        "common_sample_has_all_30_sessions": common["session_date"].n_unique() == 30,
        "common_sample_has_all_6_assets": common["asset"].n_unique() == 6,
        "common_sample_nonempty": not common.is_empty(),
    }
    return {
        "status": "PASS" if all(conditions.values()) else "FAIL",
        "conditions": conditions,
        "b1v3a_global_coverage": global_coverage,
        "common_complete_origin_count": common.height,
    }


def build_replication_common_artifacts(
    *,
    preregistration_path: Path,
    base_manifest_path: Path,
    base_schema_path: Path,
    b1_source_manifest_path: Path,
    b1_source_schema_path: Path,
    b1_inventory_path: Path,
    b1_manifest_path: Path,
    b1_schema_path: Path,
    b2_manifest_path: Path,
    b2_schema_path: Path,
    origins_path: Path,
    b0_path: Path,
    b1_path: Path,
    b2_path: Path,
    output_path: Path,
    manifest_path: Path,
    manifest_schema_path: Path,
) -> dict[str, Any]:
    """Validate source hashes and build the primary target-blind common panel."""
    preregistration = _json_object(
        preregistration_path, code="B1_REPLICATION_COMMON_PREREGISTRATION_INVALID"
    )
    sources = {
        "base": (base_manifest_path, base_schema_path),
        "b1_source": (b1_source_manifest_path, b1_source_schema_path),
        "b1": (b1_manifest_path, b1_schema_path),
        "b2": (b2_manifest_path, b2_schema_path),
    }
    documents: dict[str, dict[str, Any]] = {}
    for name, (path, schema) in sources.items():
        document = _json_object(path, code=f"B1_REPLICATION_COMMON_{name.upper()}_INVALID")
        validate_confirmation_plan_schema(document, schema)
        if not _self_hash_valid(document):
            raise ValueError(f"B1_REPLICATION_COMMON_{name.upper()}_HASH_INVALID")
        documents[name] = document
    base = documents["base"]
    b1_source = documents["b1_source"]
    b1_manifest = documents["b1"]
    b2_manifest = documents["b2"]
    preregistration_hash = preregistration.get("manifest_sha256")
    base_outputs = base.get("outputs")
    base_origin = base_outputs.get("origins") if isinstance(base_outputs, Mapping) else None
    base_b0 = base_outputs.get("b0") if isinstance(base_outputs, Mapping) else None
    b1_output = b1_manifest.get("output")
    b1_provenance = b1_manifest.get("provenance")
    b2_variants = b2_manifest.get("variants")
    b2_primary = (
        b2_variants.get("primary_5m_60s") if isinstance(b2_variants, Mapping) else None
    )
    raw_binding = b1_source.get("raw_payload_binding")
    if (
        not _self_hash_valid(preregistration)
        or preregistration.get("replication_target_reads") != 0
        or preregistration.get("result_sign_selection") != "PROHIBITED"
        or base.get("preregistration_sha256") != preregistration_hash
        or not isinstance(base_origin, Mapping)
        or base_origin.get("sha256") != sha256_file(origins_path)
        or not isinstance(base_b0, Mapping)
        or base_b0.get("sha256") != sha256_file(b0_path)
        or b1_source.get("preregistration_manifest_sha256") != preregistration_hash
        or b1_source.get("base_manifest_sha256") != base.get("manifest_sha256")
        or not isinstance(raw_binding, Mapping)
        or raw_binding.get("inventory_sha256") != sha256_file(b1_inventory_path)
        or not isinstance(b1_output, Mapping)
        or b1_output.get("sha256") != sha256_file(b1_path)
        or not isinstance(b1_provenance, Mapping)
        or b1_provenance.get("source_binding_manifest_sha256")
        != b1_source.get("manifest_sha256")
        or not isinstance(b2_primary, Mapping)
        or b2_primary.get("sha256") != sha256_file(b2_path)
        or b2_manifest.get("preregistration_sha256") != preregistration_hash
        or b2_manifest.get("features") != list(B2_FEATURE_NAMES)
    ):
        raise ValueError("B1_REPLICATION_COMMON_SOURCE_BINDING_INVALID")
    origins = pl.read_parquet(origins_path)
    b0 = pl.read_parquet(b0_path)
    b1 = pl.read_parquet(b1_path)
    b2 = pl.read_parquet(b2_path)
    for name, frame in (("B0", b0), ("B1", b1), ("B2", b2)):
        _validate_origin_metadata(origins, frame, name=name)
    panel = build_replication_common_frame(origins=origins, b0=b0, b1=b1, b2=b2)
    if (
        panel.height != int(base["origin_count"])
        or panel["origin_id"].n_unique() != panel.height
        or set(panel["session_date"].cast(pl.String).unique())
        != set(str(value) for value in preregistration["replication_sessions"])
        or set(panel["asset"].cast(pl.String).unique()) != set(_ASSETS)
    ):
        raise ValueError("B1_REPLICATION_COMMON_SCOPE_INVALID")
    acceptance = _technical_acceptance(panel)
    panel_hash = _write_parquet_if_identical(panel, output_path)
    document = {
        "schema_version": "b1-independent-replication-common-1.0",
        "status": (
            "PASS_TARGET_BLIND_COMMON_PREDICTOR_PANEL"
            if acceptance["status"] == "PASS"
            else "FAIL_TARGET_BLIND_COMMON_PREDICTOR_PANEL"
        ),
        "preregistration_manifest_sha256": preregistration_hash,
        "target_blind": True,
        "outcome_read_count": 0,
        "safe_to_read_outcomes": False,
        "scope": {
            "replication_session_count": 30,
            "asset_count": 6,
            "assets": list(_ASSETS),
            "origin_count": panel.height,
            "origin_identity_sha256": canonical_sha256(
                {"origin_ids": [str(value) for value in panel["origin_id"].to_list()]}
            ),
        },
        "source_bindings": {
            "base_manifest_sha256": base["manifest_sha256"],
            "b1q_source_manifest_sha256": b1_source["manifest_sha256"],
            "b1v3_feature_manifest_sha256": b1_manifest["manifest_sha256"],
            "b2_feature_manifest_sha256": b2_manifest["manifest_sha256"],
        },
        "information_sets": {
            name: {"feature_count": len(features), "features": list(features)}
            for name, features in B1V3_PRIMARY_INFORMATION_SETS.items()
        },
        "technical_acceptance": acceptance,
        "coverage": {
            "by_asset": _coverage(panel, "asset"),
            "by_session_tercile": _coverage(panel, "session_tercile"),
            "by_date": _coverage(panel, "session_date"),
        },
        "output": {
            "logical_path": (
                "MDS650_B1_REPLICATION_DATA_ROOT/predictors/"
                "common_predictor_panel.parquet"
            ),
            "sha256": panel_hash,
            "bytes": output_path.stat().st_size,
            "row_count": panel.height,
            "columns": panel.columns,
        },
        "security": {"secret_values_emitted": False, "personal_paths_emitted": False},
    }
    document["manifest_sha256"] = canonical_sha256(document)
    validate_confirmation_plan_schema(document, manifest_schema_path)
    _write_json_if_identical(manifest_path, document)
    return document
