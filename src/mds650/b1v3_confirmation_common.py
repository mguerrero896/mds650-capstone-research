"""Source-bound common predictor panel for the frozen B1v3 confirmation study."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import polars as pl

from mds650.b1v3 import B1V3A_FEATURES
from mds650.b1v3_confirmation import (
    canonical_sha256,
    sha256_file,
    validate_confirmation_plan_schema,
)
from mds650.b1v3_confirmation_build import (
    B1V3_CANONICAL_ASSETS,
    FrozenBuildInputs,
)
from mds650.b1v3_confirmation_panel import assemble_predictor_panel
from mds650.phase6 import B0V2_FEATURES
from mds650.study_design import B2_FEATURE_NAMES

B1V3_PRIMARY_INFORMATION_SETS: Final[Mapping[str, tuple[str, ...]]] = {
    "B0": tuple(B0V2_FEATURES),
    "B1v3a": (*B0V2_FEATURES, *B1V3A_FEATURES),
    "B2": (*B0V2_FEATURES, *B1V3A_FEATURES, *B2_FEATURE_NAMES),
}
_FORBIDDEN_SERIALIZED_TOKENS: Final[tuple[bytes, ...]] = (
    b"c:\\users\\",
    b"c:/users/",
    b"d:\\mds650",
    b"api_key",
    b"apikey",
    b"authorization",
    b"bearer ",
)


@dataclass(frozen=True, slots=True)
class CommonPredictorArtifacts:
    """Paths and hashes of the sealed target-blind common predictor panel."""

    panel_path: Path
    manifest_path: Path
    panel_sha256: str
    manifest_file_sha256: str
    manifest_sha256: str


def build_common_predictor_frame(
    *,
    origins: pl.DataFrame,
    b0: pl.DataFrame,
    b1: pl.DataFrame,
    b2: pl.DataFrame,
) -> pl.DataFrame:
    """Assemble all origins and freeze nested B0/B1v3a/B2 completeness.

    Parameters
    ----------
    origins:
        Canonical target-free forecast-origin grid.
    b0:
        Underlying/market predictor rows, including ``b0_complete``.
    b1:
        Source-bound B1v3 option-state rows.
    b2:
        Corrected target-blind B2 rows with availability eligibility.

    Returns
    -------
    polars.DataFrame
        One row per canonical origin. The three information-set flags are
        nested by construction; no row is dropped or balanced.

    Raises
    ------
    ValueError
        If input identities, timing, target-blind columns, numeric B2 fields,
        origin preservation, or nested completeness invariants fail.

    Notes
    -----
    B2 is defined as B0 plus the three B1v3a ATM-variance features plus the
    nine owner-approved trade-derived features. Skew and term structure remain
    available in the physical panel for registered robustness analyses, but
    they are not part of the primary B1v3a or B2 information sets.
    """
    panel = assemble_predictor_panel(origins=origins, b0=b0, b1=b1, b2=b2)
    if "role" not in panel.columns:
        raise ValueError("B1V3_COMMON_ROLE_MISSING")
    invalid_roles = set(panel["role"].drop_nulls().cast(pl.String).unique()) - {
        "training_warmup",
        "development",
        "confirmation",
    }
    if invalid_roles:
        raise ValueError("B1V3_COMMON_ROLE_INVALID")
    panel = panel.with_columns(
        pl.when(pl.col("role") == "training_warmup")
        .then(pl.lit("development"))
        .otherwise(pl.col("role"))
        .alias("role")
    )
    b2_numeric_complete = pl.all_horizontal(
        pl.col(feature).cast(pl.Float64, strict=False).is_finite()
        & pl.col(feature).is_not_null()
        for feature in B2_FEATURE_NAMES
    )
    panel = panel.with_columns(
        pl.col("b0_complete").fill_null(False).alias("b0_information_set_complete"),
        (
            pl.col("b0_complete").fill_null(False)
            & pl.col("b1v3a_complete").fill_null(False)
        ).alias("b1v3a_information_set_complete"),
        (
            pl.col("b0_complete").fill_null(False)
            & pl.col("b1v3a_complete").fill_null(False)
            & pl.col("b2v2_availability_eligible").fill_null(False)
            & b2_numeric_complete
        ).alias("b2_information_set_complete"),
    )
    if panel.filter(
        pl.col("b2_information_set_complete")
        & ~pl.col("b1v3a_information_set_complete")
    ).height:
        raise ValueError("B1V3_COMMON_B2_NOT_NESTED_IN_B1V3A")
    if panel.filter(
        pl.col("b1v3a_information_set_complete")
        & ~pl.col("b0_information_set_complete")
    ).height:
        raise ValueError("B1V3_COMMON_B1V3A_NOT_NESTED_IN_B0")
    if panel.height != origins.height or panel["origin_id"].n_unique() != origins.height:
        raise ValueError("B1V3_COMMON_ORIGIN_PRESERVATION_FAILURE")
    return panel


def _load_self_hashed_manifest(
    path: Path,
    schema_path: Path,
) -> tuple[dict[str, Any], str]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("B1V3_COMMON_SOURCE_MANIFEST_INVALID") from exc
    if not isinstance(document, dict):
        raise ValueError("B1V3_COMMON_SOURCE_MANIFEST_INVALID")
    validate_confirmation_plan_schema(document, schema_path)
    stored_hash = document.get("manifest_sha256")
    unsigned = {key: value for key, value in document.items() if key != "manifest_sha256"}
    if not isinstance(stored_hash, str) or stored_hash != canonical_sha256(unsigned):
        raise ValueError("B1V3_COMMON_SOURCE_MANIFEST_HASH_INVALID")
    return document, stored_hash


def _validate_origin_metadata(origins: pl.DataFrame, frame: pl.DataFrame, *, name: str) -> None:
    observed_ids = set(str(value) for value in frame["origin_id"].to_list())
    expected_ids = set(str(value) for value in origins["origin_id"].to_list())
    if observed_ids != expected_ids:
        raise ValueError(f"B1V3_COMMON_{name}_ORIGIN_SCOPE_INVALID")
    comparable = tuple(
        column
        for column in ("asset", "session_date", "forecast_origin_ns")
        if column in frame.columns
    )
    if not comparable:
        return
    expected = origins.select(
        "origin_id",
        *(pl.col(column).alias(f"expected_{column}") for column in comparable),
    )
    joined = frame.select("origin_id", *comparable).join(
        expected,
        on="origin_id",
        how="left",
        validate="1:1",
    )
    mismatch = pl.any_horizontal(
        pl.col(column) != pl.col(f"expected_{column}") for column in comparable
    )
    if joined.filter(mismatch).height:
        raise ValueError(f"B1V3_COMMON_{name}_ORIGIN_METADATA_INVALID")


def _write_parquet_if_identical(frame: pl.DataFrame, destination: Path) -> str:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if not pl.read_parquet(destination).equals(frame, null_equal=True):
            raise ValueError(f"B1V3_COMMON_OUTPUT_CONFLICT:{destination.name}")
        return sha256_file(destination)
    descriptor, name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".part", dir=destination.parent
    )
    os.close(descriptor)
    temporary = Path(name)
    try:
        frame.write_parquet(temporary, compression="zstd", statistics=True)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return sha256_file(destination)


def _write_json_if_identical(destination: Path, document: Mapping[str, Any]) -> str:
    payload = (json.dumps(document, indent=2, sort_keys=True, ensure_ascii=True) + "\n").encode()
    if any(token in payload.lower() for token in _FORBIDDEN_SERIALIZED_TOKENS):
        raise ValueError("B1V3_COMMON_MANIFEST_HYGIENE_INVALID")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if destination.read_bytes() != payload:
            raise ValueError(f"B1V3_COMMON_OUTPUT_CONFLICT:{destination.name}")
    else:
        descriptor, name = tempfile.mkstemp(
            prefix=f".{destination.name}.", suffix=".part", dir=destination.parent
        )
        os.close(descriptor)
        temporary = Path(name)
        try:
            temporary.write_bytes(payload)
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
    return sha256_file(destination)


def _completeness_by_role(panel: pl.DataFrame) -> list[dict[str, Any]]:
    if "role" not in panel.columns:
        raise ValueError("B1V3_COMMON_ROLE_MISSING")
    return [
        dict(row)
        for row in panel.group_by("role")
        .agg(
            pl.len().alias("origin_count"),
            pl.col("b0_information_set_complete").sum().alias("b0_complete_count"),
            pl.col("b1v3a_information_set_complete")
            .sum()
            .alias("b1v3a_complete_count"),
            pl.col("b2_information_set_complete").sum().alias("b2_complete_count"),
        )
        .sort("role")
        .iter_rows(named=True)
    ]


def build_common_predictor_artifacts(
    *,
    inputs: FrozenBuildInputs,
    base_manifest_path: Path,
    base_manifest_schema_path: Path,
    origins_path: Path,
    b0_path: Path,
    b1_source_manifest_path: Path,
    b1_source_manifest_schema_path: Path,
    b1_source_inventory_path: Path,
    b1_manifest_path: Path,
    b1_manifest_schema_path: Path,
    b1_path: Path,
    b2_manifest_path: Path,
    b2_manifest_schema_path: Path,
    b2_path: Path,
    output_path: Path,
    manifest_path: Path,
    manifest_schema_path: Path,
) -> CommonPredictorArtifacts:
    """Validate the full predictor provenance chain and seal one common panel.

    All inputs are target-free and source-bound. The function deliberately
    leaves scientific evaluation closed until T224 tests and T225
    preregistration are complete.
    """
    base, base_hash = _load_self_hashed_manifest(
        base_manifest_path, base_manifest_schema_path
    )
    b1_source, b1_source_hash = _load_self_hashed_manifest(
        b1_source_manifest_path, b1_source_manifest_schema_path
    )
    b1_manifest, b1_manifest_hash = _load_self_hashed_manifest(
        b1_manifest_path, b1_manifest_schema_path
    )
    b2_manifest, b2_manifest_hash = _load_self_hashed_manifest(
        b2_manifest_path, b2_manifest_schema_path
    )
    base_outputs = base.get("outputs")
    base_origin = base_outputs.get("origins") if isinstance(base_outputs, dict) else None
    base_b0 = base_outputs.get("b0") if isinstance(base_outputs, dict) else None
    if (
        base.get("status") != "PASS_TARGET_BLIND_BASE_PREDICTORS"
        or base.get("plan_sha256") != inputs.plan_sha256
        or base.get("target_blind") is not True
        or base.get("outcome_read_count") != 0
        or base.get("safe_to_read_outcomes") is not False
        or base.get("assets") != list(B1V3_CANONICAL_ASSETS)
        or not isinstance(base_origin, dict)
        or not isinstance(base_b0, dict)
        or base_origin.get("sha256") != sha256_file(origins_path)
        or base_b0.get("sha256") != sha256_file(b0_path)
    ):
        raise ValueError("B1V3_COMMON_BASE_BINDING_INVALID")
    source_attempts = b1_source.get("attempts")
    raw_binding = b1_source.get("raw_payload_binding")
    source_scope = b1_source.get("scope")
    if (
        b1_source.get("status") != "PASS_TARGET_BLIND_B1Q_SOURCE_BOUND"
        or b1_source.get("plan_sha256") != inputs.plan_sha256
        or b1_source.get("base_manifest_sha256") != base_hash
        or b1_source.get("target_blind") is not True
        or b1_source.get("outcome_read_count") != 0
        or b1_source.get("safe_to_read_outcomes") is not False
        or not isinstance(source_attempts, dict)
        or not isinstance(raw_binding, dict)
        or not isinstance(source_scope, dict)
        or source_scope.get("origin_count") != base.get("origin_count")
        or raw_binding.get("status") != "PRESENT_AND_VALIDATED"
        or raw_binding.get("inventory_sha256") != sha256_file(b1_source_inventory_path)
    ):
        raise ValueError("B1V3_COMMON_B1_SOURCE_BINDING_INVALID")
    b1_output = b1_manifest.get("output")
    b1_provenance = b1_manifest.get("provenance")
    b1_attempt_source = b1_manifest.get("source")
    if (
        b1_manifest.get("status")
        != "PASS_TARGET_BLIND_SOURCE_BOUND_TECHNICAL_BUILD"
        or b1_manifest.get("target_blind") is not True
        or b1_manifest.get("safe_to_evaluate_scientifically") is not False
        or not isinstance(b1_output, dict)
        or b1_output.get("sha256") != sha256_file(b1_path)
        or not isinstance(b1_provenance, dict)
        or b1_provenance.get("exogenous_raw_payload_binding")
        != "PRESENT_AND_VALIDATED"
        or b1_provenance.get("source_binding_manifest_sha256") != b1_source_hash
        or b1_provenance.get("source_inventory_sha256")
        != raw_binding.get("inventory_sha256")
        or b1_provenance.get("evaluation_blocker") is not None
        or not isinstance(b1_attempt_source, dict)
        or b1_attempt_source.get("sha256") != source_attempts.get("sha256")
    ):
        raise ValueError("B1V3_COMMON_B1_FEATURE_BINDING_INVALID")
    b2_variants = b2_manifest.get("variants")
    b2_primary = (
        b2_variants.get("primary_5m_60s") if isinstance(b2_variants, dict) else None
    )
    if (
        b2_manifest.get("status") != "PASS_TARGET_BLIND_B2_PREDICTORS"
        or b2_manifest.get("plan_sha256") != inputs.plan_sha256
        or b2_manifest.get("base_manifest_sha256") != base_hash
        or b2_manifest.get("target_blind") is not True
        or b2_manifest.get("outcome_read_count") != 0
        or b2_manifest.get("safe_to_read_outcomes") is not False
        or b2_manifest.get("features") != list(B2_FEATURE_NAMES)
        or b2_manifest.get("origin_count") != base.get("origin_count")
        or not isinstance(b2_primary, dict)
        or b2_primary.get("sha256") != sha256_file(b2_path)
    ):
        raise ValueError("B1V3_COMMON_B2_BINDING_INVALID")
    origins = pl.read_parquet(origins_path)
    b0 = pl.read_parquet(b0_path)
    b1 = pl.read_parquet(b1_path)
    b2 = pl.read_parquet(b2_path)
    for name, frame in (("B0", b0), ("B1", b1), ("B2", b2)):
        _validate_origin_metadata(origins, frame, name=name)
    panel = build_common_predictor_frame(origins=origins, b0=b0, b1=b1, b2=b2)
    panel_hash = _write_parquet_if_identical(panel, output_path)
    document: dict[str, Any] = {
        "schema_version": "1.0",
        "status": "PASS_TARGET_BLIND_COMMON_PREDICTOR_PANEL",
        "plan_sha256": inputs.plan_sha256,
        "target_blind": True,
        "outcome_read_count": 0,
        "safe_to_read_outcomes": False,
        "safe_to_evaluate_scientifically": False,
        "evaluation_blocker": "EVALUATION_TESTS_AND_PREREGISTRATION_PENDING",
        "scope": {
            "training_session_count": len(inputs.training_sessions),
            "confirmation_session_count": len(inputs.confirmation_sessions),
            "asset_count": len(B1V3_CANONICAL_ASSETS),
            "assets": list(B1V3_CANONICAL_ASSETS),
            "origin_count": panel.height,
            "origin_identity_sha256": canonical_sha256(
                {"origin_ids": [str(value) for value in panel["origin_id"].to_list()]}
            ),
        },
        "source_bindings": {
            "base_manifest_sha256": base_hash,
            "b1q_source_manifest_sha256": b1_source_hash,
            "b1q_source_inventory_sha256": str(raw_binding["inventory_sha256"]),
            "b1v3_feature_manifest_sha256": b1_manifest_hash,
            "b2_feature_manifest_sha256": b2_manifest_hash,
        },
        "information_sets": {
            name: {"feature_count": len(features), "features": list(features)}
            for name, features in B1V3_PRIMARY_INFORMATION_SETS.items()
        },
        "completeness": {
            "b0_complete_count": int(panel["b0_information_set_complete"].sum()),
            "b1v3a_complete_count": int(
                panel["b1v3a_information_set_complete"].sum()
            ),
            "b2_complete_count": int(panel["b2_information_set_complete"].sum()),
            "by_role": _completeness_by_role(panel),
        },
        "output": {
            "logical_path": "MDS650_B1V3_DATA_ROOT/predictors/common_predictor_panel.parquet",
            "sha256": panel_hash,
            "bytes": output_path.stat().st_size,
            "row_count": panel.height,
            "columns": panel.columns,
        },
        "security": {
            "secret_values_emitted": False,
            "personal_paths_emitted": False,
        },
    }
    document["manifest_sha256"] = canonical_sha256(document)
    validate_confirmation_plan_schema(document, manifest_schema_path)
    manifest_file_hash = _write_json_if_identical(manifest_path, document)
    return CommonPredictorArtifacts(
        panel_path=output_path,
        manifest_path=manifest_path,
        panel_sha256=panel_hash,
        manifest_file_sha256=manifest_file_hash,
        manifest_sha256=str(document["manifest_sha256"]),
    )
