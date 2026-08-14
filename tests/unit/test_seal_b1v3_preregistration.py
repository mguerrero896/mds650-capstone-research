"""Contract tests for the B1v3 preregistration sealer."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from scripts.seal_b1v3_preregistration import seal_b1v3_preregistration

from mds650.b1v3_confirmation import canonical_sha256, sha256_file
from mds650.b1v3_confirmation_common import B1V3_PRIMARY_INFORMATION_SETS

ROOT = Path(__file__).resolve().parents[2]
COMMON_SCHEMA = (
    ROOT
    / "specs"
    / "001-pit-options-rv30"
    / "contracts"
    / "b1v3-confirmation-common-predictor-v1.schema.json"
)
PREREG_SCHEMA = (
    ROOT
    / "specs"
    / "001-pit-options-rv30"
    / "contracts"
    / "b1v3-preregistration-v1.schema.json"
)
PLAN = (
    ROOT
    / "artifacts"
    / "b1v3_confirmation_plan"
    / "confirmation_plan_provider_passed.json"
)


def _write_common_manifest(path: Path) -> Path:
    information_sets = {
        name: {"feature_count": len(features), "features": list(features)}
        for name, features in B1V3_PRIMARY_INFORMATION_SETS.items()
    }
    document: dict[str, Any] = {
        "schema_version": "1.0",
        "status": "PASS_TARGET_BLIND_COMMON_PREDICTOR_PANEL",
        "plan_sha256": "8b68411094d2638b6608e02a4f9dc3205cb834e1a6205d5a0cf0f73a95544b70",
        "target_blind": True,
        "outcome_read_count": 0,
        "safe_to_read_outcomes": False,
        "safe_to_evaluate_scientifically": False,
        "evaluation_blocker": "EVALUATION_TESTS_AND_PREREGISTRATION_PENDING",
        "scope": {
            "training_session_count": 60,
            "confirmation_session_count": 30,
            "asset_count": 6,
            "assets": ["AAPL", "AMZN", "META", "MSFT", "NVDA", "TSLA"],
            "origin_count": 38_664,
            "origin_identity_sha256": "a" * 64,
        },
        "source_bindings": {
            "base_manifest_sha256": "b" * 64,
            "b1q_source_manifest_sha256": "c" * 64,
            "b1q_source_inventory_sha256": "d" * 64,
            "b1v3_feature_manifest_sha256": "e" * 64,
            "b2_feature_manifest_sha256": "f" * 64,
        },
        "information_sets": information_sets,
        "completeness": {
            "b0_complete_count": 35_424,
            "b1v3a_complete_count": 32_000,
            "b2_complete_count": 30_000,
            "by_role": [
                {
                    "role": "development",
                    "origin_count": 25_776,
                    "b0_complete_count": 23_616,
                    "b1v3a_complete_count": 21_000,
                    "b2_complete_count": 20_000,
                },
                {
                    "role": "confirmation",
                    "origin_count": 12_888,
                    "b0_complete_count": 11_808,
                    "b1v3a_complete_count": 11_000,
                    "b2_complete_count": 10_000,
                },
            ],
        },
        "output": {
            "logical_path": "MDS650_B1V3_DATA_ROOT/predictors/common_predictor_panel.parquet",
            "sha256": "1" * 64,
            "bytes": 1024,
            "row_count": 38_664,
            "columns": ["origin_id", *B1V3_PRIMARY_INFORMATION_SETS["B2"]],
        },
        "security": {"secret_values_emitted": False, "personal_paths_emitted": False},
    }
    document["manifest_sha256"] = canonical_sha256(document)
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def test_sealer_is_schema_valid_self_hashed_and_idempotent(tmp_path: Path) -> None:
    common = _write_common_manifest(tmp_path / "common.json")
    design = tmp_path / "design.md"
    code = tmp_path / "evaluation.py"
    lock = tmp_path / "uv.lock"
    design.write_text("frozen design\n", encoding="utf-8")
    code.write_text("# frozen adapter\n", encoding="utf-8")
    lock.write_text("version = 1\n", encoding="utf-8")
    output = tmp_path / "preregistration.json"
    markdown = tmp_path / "b1v3_preregistration.md"

    first = seal_b1v3_preregistration(
        plan_path=PLAN,
        common_manifest_path=common,
        common_manifest_schema_path=COMMON_SCHEMA,
        design_path=design,
        evaluation_code_path=code,
        uv_lock_path=lock,
        preregistration_schema_path=PREREG_SCHEMA,
        output_path=output,
        markdown_path=markdown,
    )
    first_json = output.read_bytes()
    first_markdown = markdown.read_bytes()
    second = seal_b1v3_preregistration(
        plan_path=PLAN,
        common_manifest_path=common,
        common_manifest_schema_path=COMMON_SCHEMA,
        design_path=design,
        evaluation_code_path=code,
        uv_lock_path=lock,
        preregistration_schema_path=PREREG_SCHEMA,
        output_path=output,
        markdown_path=markdown,
    )

    assert second == first
    assert output.read_bytes() == first_json
    assert markdown.read_bytes() == first_markdown
    assert first["manifest_sha256"] == canonical_sha256(
        {key: value for key, value in first.items() if key != "manifest_sha256"}
    )
    assert first["source_hashes"] == {
        "design_sha256": sha256_file(design),
        "evaluation_code_sha256": sha256_file(code),
        "uv_lock_sha256": sha256_file(lock),
    }
    assert first["safe_to_evaluate_b1v3"] == "NO"
    assert first["confirmation_read_count"] == 0
    rendered = markdown.read_text(encoding="utf-8")
    assert str(first["manifest_sha256"]) in rendered
    assert "2024-08-02" in rendered
    assert "2024-12-09" in rendered
    assert "SAFE_TO_EVALUATE_B1V3: NO" in rendered
    assert "C:\\Users\\" not in rendered
    assert "D:\\MDS650" not in rendered


def test_sealer_refuses_conflicting_frozen_output(tmp_path: Path) -> None:
    common = _write_common_manifest(tmp_path / "common.json")
    design = tmp_path / "design.md"
    code = tmp_path / "evaluation.py"
    lock = tmp_path / "uv.lock"
    for path in (design, code, lock):
        path.write_text(path.name, encoding="utf-8")
    output = tmp_path / "preregistration.json"
    markdown = tmp_path / "b1v3_preregistration.md"
    output.write_text("{}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="B1V3_PREREG_OUTPUT_CONFLICT"):
        seal_b1v3_preregistration(
            plan_path=PLAN,
            common_manifest_path=common,
            common_manifest_schema_path=COMMON_SCHEMA,
            design_path=design,
            evaluation_code_path=code,
            uv_lock_path=lock,
            preregistration_schema_path=PREREG_SCHEMA,
            output_path=output,
            markdown_path=markdown,
        )
