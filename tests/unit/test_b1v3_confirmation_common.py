"""Nested information-set tests for the B1v3 target-blind common panel."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import polars as pl
import pytest

from mds650.b1v3 import B1V3_FEATURES, B1V3A_FEATURES
from mds650.b1v3_confirmation import canonical_sha256, sha256_file
from mds650.b1v3_confirmation_build import (
    B1V3_CANONICAL_ASSETS,
    FrozenBuildInputs,
)
from mds650.b1v3_confirmation_common import (
    B1V3_PRIMARY_INFORMATION_SETS,
    CommonPredictorArtifacts,
    build_common_predictor_artifacts,
    build_common_predictor_frame,
)
from mds650.phase6 import B0V2_FEATURES
from mds650.study_design import B2_FEATURE_NAMES

ROOT = Path(__file__).resolve().parents[2]
OUTPUT_SCHEMA = (
    ROOT
    / "specs"
    / "001-pit-options-rv30"
    / "contracts"
    / "b1v3-confirmation-common-predictor-v1.schema.json"
)


@dataclass(frozen=True, slots=True)
class ArtifactFixture:
    origins: Path
    b0: Path
    b1: Path
    b2: Path
    inventory: Path
    schema: Path
    base_manifest: Path
    b1_source_manifest: Path
    b1_manifest: Path
    b2_manifest: Path
    inputs: FrozenBuildInputs


def _frames() -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    origins_rows: list[dict[str, object]] = []
    b0_rows: list[dict[str, object]] = []
    b1_rows: list[dict[str, object]] = []
    b2_rows: list[dict[str, object]] = []
    start = datetime(2024, 8, 2, 13, 35, tzinfo=UTC)
    for index in range(2):
        origin = start + timedelta(minutes=5 * index)
        origin_id = f"AAPL|2024-08-02|{index}"
        origin_ns = int(origin.timestamp() * 1_000_000_000)
        complete = index == 0
        origins_rows.append(
            {
                "origin_id": origin_id,
                "asset": "AAPL",
                "session_date": "2024-08-02",
                "forecast_origin_utc": origin,
                "forecast_origin_ns": origin_ns,
                "role": "development",
            }
        )
        b0_row: dict[str, object] = {
            "origin_id": origin_id,
            "b0_complete": True,
            "b0_missing_reason": None,
            "max_predictor_available_at_utc": origin - timedelta(seconds=1),
        }
        for feature in B0V2_FEATURES:
            b0_row[feature] = "AAPL" if feature == "b0v2_asset_identity" else 1.0
        b0_rows.append(b0_row)
        b1_row: dict[str, object] = {
            "origin_id": origin_id,
            "b1v3a_complete": complete,
            "b1v3b_complete": complete,
            "b1v3c_complete": complete,
            "b1v3_missing_reason": None if complete else "ATM_CURRENT_MISSING",
            "max_sip_timestamp_ns": origin_ns - 1_000_000_000 if complete else None,
            "source_request_hashes": ["a" * 64] if complete else [],
        }
        for feature in B1V3_FEATURES:
            b1_row[feature] = 0.2 if complete else None
        b1_rows.append(b1_row)
        b2_row: dict[str, object] = {
            "origin_id": origin_id,
            "b2v2_availability_eligible": complete,
            "b2v2_availability_status": "ELIGIBLE" if complete else "EXCLUDED",
            "source_temporal_state": "OBSERVED_ON_TIME" if complete else "DELAYED",
            "b2v2_max_created_at_utc": origin - timedelta(seconds=61) if complete else None,
            "b2v2_cutoff_utc": origin - timedelta(seconds=60),
        }
        for feature in B2_FEATURE_NAMES:
            b2_row[feature] = 0.1 if complete else None
        b2_rows.append(b2_row)
    return (
        pl.DataFrame(origins_rows),
        pl.DataFrame(b0_rows, strict=False),
        pl.DataFrame(b1_rows, strict=False),
        pl.DataFrame(b2_rows, strict=False),
    )


def test_common_panel_preserves_origins_and_nested_information_sets() -> None:
    origins, b0, b1, b2 = _frames()
    panel = build_common_predictor_frame(origins=origins, b0=b0, b1=b1, b2=b2)

    assert panel.height == 2
    assert panel["origin_id"].n_unique() == 2
    assert panel["b0_information_set_complete"].to_list() == [True, True]
    assert panel["b1v3a_information_set_complete"].to_list() == [True, False]
    assert panel["b2_information_set_complete"].to_list() == [True, False]
    assert B1V3_PRIMARY_INFORMATION_SETS["B0"] == tuple(B0V2_FEATURES)
    assert B1V3_PRIMARY_INFORMATION_SETS["B1v3a"] == (
        *B0V2_FEATURES,
        *B1V3A_FEATURES,
    )
    assert B1V3_PRIMARY_INFORMATION_SETS["B2"] == (
        *B0V2_FEATURES,
        *B1V3A_FEATURES,
        *B2_FEATURE_NAMES,
    )


def test_common_panel_rejects_outcome_column() -> None:
    origins, b0, b1, b2 = _frames()
    with pytest.raises(ValueError, match="B1V3_PANEL_TARGET_COLUMN_FORBIDDEN"):
        build_common_predictor_frame(
            origins=origins.with_columns(pl.lit(0.1).alias("rv30")),
            b0=b0,
            b1=b1,
            b2=b2,
        )


def _write_manifest(path: Path, document: dict[str, object]) -> str:
    document["manifest_sha256"] = canonical_sha256(document)
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return str(document["manifest_sha256"])


def _canonical_frames() -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    template_origins, template_b0, template_b1, template_b2 = _frames()
    origins: list[pl.DataFrame] = []
    b0_rows: list[pl.DataFrame] = []
    b1_rows: list[pl.DataFrame] = []
    b2_rows: list[pl.DataFrame] = []
    for asset in B1V3_CANONICAL_ASSETS:
        replacements = {
            "origin_id": pl.col("origin_id").str.replace("AAPL", asset),
        }
        origins.append(
            template_origins.with_columns(
                replacements["origin_id"],
                pl.lit(asset).alias("asset"),
            )
        )
        b0_rows.append(
            template_b0.with_columns(
                replacements["origin_id"],
                pl.lit(asset).alias("b0v2_asset_identity"),
            )
        )
        b1_rows.append(template_b1.with_columns(replacements["origin_id"]))
        b2_rows.append(template_b2.with_columns(replacements["origin_id"]))
    return (
        pl.concat(origins, how="vertical_relaxed"),
        pl.concat(b0_rows, how="vertical_relaxed"),
        pl.concat(b1_rows, how="vertical_relaxed"),
        pl.concat(b2_rows, how="vertical_relaxed"),
    )


def _artifact_fixture(tmp_path: Path) -> ArtifactFixture:
    tmp_path.mkdir(parents=True, exist_ok=True)
    origins, b0, b1, b2 = _canonical_frames()
    paths = {
        "origins": tmp_path / "forecast_origins_target_blind.parquet",
        "b0": tmp_path / "b0_target_blind.parquet",
        "b1": tmp_path / "b1v3_features.parquet",
        "b2": tmp_path / "b2_primary_target_blind.parquet",
        "inventory": tmp_path / "b1q_raw_payload_inventory.parquet",
    }
    for name, frame in (("origins", origins), ("b0", b0), ("b1", b1), ("b2", b2)):
        frame.write_parquet(paths[name])
    pl.DataFrame({"cache_file_sha256": ["f" * 64]}).write_parquet(paths["inventory"])
    schema = tmp_path / "permissive.schema.json"
    schema.write_text(
        json.dumps(
            {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "type": "object",
            }
        ),
        encoding="utf-8",
    )
    plan_hash = "a" * 64
    base_path = tmp_path / "base.json"
    base: dict[str, object] = {
        "status": "PASS_TARGET_BLIND_BASE_PREDICTORS",
        "plan_sha256": plan_hash,
        "target_blind": True,
        "outcome_read_count": 0,
        "safe_to_read_outcomes": False,
        "assets": list(B1V3_CANONICAL_ASSETS),
        "origin_count": origins.height,
        "outputs": {
            "origins": {"sha256": sha256_file(paths["origins"])},
            "b0": {"sha256": sha256_file(paths["b0"])},
        },
    }
    base_hash = _write_manifest(base_path, base)
    source_path = tmp_path / "b1_source.json"
    source: dict[str, object] = {
        "status": "PASS_TARGET_BLIND_B1Q_SOURCE_BOUND",
        "plan_sha256": plan_hash,
        "base_manifest_sha256": base_hash,
        "target_blind": True,
        "outcome_read_count": 0,
        "safe_to_read_outcomes": False,
        "scope": {"origin_count": origins.height},
        "attempts": {"sha256": "b" * 64},
        "raw_payload_binding": {
            "status": "PRESENT_AND_VALIDATED",
            "inventory_sha256": sha256_file(paths["inventory"]),
        },
    }
    source_hash = _write_manifest(source_path, source)
    b1_manifest_path = tmp_path / "b1_manifest.json"
    b1_manifest: dict[str, object] = {
        "status": "PASS_TARGET_BLIND_SOURCE_BOUND_TECHNICAL_BUILD",
        "target_blind": True,
        "safe_to_evaluate_scientifically": False,
        "source": {"sha256": "b" * 64},
        "provenance": {
            "exogenous_raw_payload_binding": "PRESENT_AND_VALIDATED",
            "source_binding_manifest_sha256": source_hash,
            "source_inventory_sha256": sha256_file(paths["inventory"]),
            "evaluation_blocker": None,
        },
        "output": {"sha256": sha256_file(paths["b1"])},
    }
    _write_manifest(b1_manifest_path, b1_manifest)
    b2_manifest_path = tmp_path / "b2_manifest.json"
    b2_manifest: dict[str, object] = {
        "status": "PASS_TARGET_BLIND_B2_PREDICTORS",
        "plan_sha256": plan_hash,
        "base_manifest_sha256": base_hash,
        "target_blind": True,
        "outcome_read_count": 0,
        "safe_to_read_outcomes": False,
        "origin_count": origins.height,
        "features": list(B2_FEATURE_NAMES),
        "variants": {"primary_5m_60s": {"sha256": sha256_file(paths["b2"])}},
    }
    _write_manifest(b2_manifest_path, b2_manifest)
    return ArtifactFixture(
        origins=paths["origins"],
        b0=paths["b0"],
        b1=paths["b1"],
        b2=paths["b2"],
        inventory=paths["inventory"],
        schema=schema,
        base_manifest=base_path,
        b1_source_manifest=source_path,
        b1_manifest=b1_manifest_path,
        b2_manifest=b2_manifest_path,
        inputs=FrozenBuildInputs(
            plan_sha256=plan_hash,
            report_sha256="c" * 64,
            provider_candidate_plan_sha256="d" * 64,
            source_confirmation_plan_sha256="e" * 64,
            training_sessions=("2024-08-02",),
            confirmation_sessions=(),
            fmp_records=(),
        ),
    )


def _build_artifacts(
    values: ArtifactFixture, tmp_path: Path
) -> CommonPredictorArtifacts:
    return build_common_predictor_artifacts(
        inputs=values.inputs,
        base_manifest_path=values.base_manifest,
        base_manifest_schema_path=values.schema,
        origins_path=values.origins,
        b0_path=values.b0,
        b1_source_manifest_path=values.b1_source_manifest,
        b1_source_manifest_schema_path=values.schema,
        b1_source_inventory_path=values.inventory,
        b1_manifest_path=values.b1_manifest,
        b1_manifest_schema_path=values.schema,
        b1_path=values.b1,
        b2_manifest_path=values.b2_manifest,
        b2_manifest_schema_path=values.schema,
        b2_path=values.b2,
        output_path=tmp_path / "out" / "common_predictor_panel.parquet",
        manifest_path=tmp_path / "out" / "common_predictor_manifest.json",
        manifest_schema_path=OUTPUT_SCHEMA,
    )


def test_artifact_builder_validates_chain_and_is_idempotent(tmp_path: Path) -> None:
    values = _artifact_fixture(tmp_path)
    first = _build_artifacts(values, tmp_path)
    second = _build_artifacts(values, tmp_path)

    assert first == second
    manifest = json.loads(first.manifest_path.read_text(encoding="utf-8"))
    assert manifest["status"] == "PASS_TARGET_BLIND_COMMON_PREDICTOR_PANEL"
    assert manifest["scope"]["origin_count"] == 12
    assert manifest["information_sets"]["B2"]["feature_count"] == 24
    assert manifest["safe_to_read_outcomes"] is False
    assert manifest["safe_to_evaluate_scientifically"] is False


def test_artifact_builder_rejects_b1_source_inventory_drift(tmp_path: Path) -> None:
    values = _artifact_fixture(tmp_path)
    pl.DataFrame({"tampered": [1]}).write_parquet(values.inventory)

    with pytest.raises(ValueError, match="B1V3_COMMON_B1_SOURCE_BINDING_INVALID"):
        _build_artifacts(values, tmp_path)


def test_artifact_builder_rejects_manifest_and_output_tamper(tmp_path: Path) -> None:
    values = _artifact_fixture(tmp_path)
    source = json.loads(values.b1_source_manifest.read_text(encoding="utf-8"))
    source["status"] = "TAMPERED"
    values.b1_source_manifest.write_text(json.dumps(source), encoding="utf-8")
    with pytest.raises(ValueError, match="B1V3_COMMON_SOURCE_MANIFEST_HASH_INVALID"):
        _build_artifacts(values, tmp_path)

    values = _artifact_fixture(tmp_path / "output")
    artifacts = _build_artifacts(values, tmp_path / "output")
    pl.DataFrame({"broken": [1]}).write_parquet(artifacts.panel_path)
    with pytest.raises(ValueError, match="B1V3_COMMON_OUTPUT_CONFLICT"):
        _build_artifacts(values, tmp_path / "output")
