"""One-read access controls for independent replication."""

from __future__ import annotations

import json
from collections import namedtuple
from importlib import import_module
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from mds650.b1_replication_access import (
    _contract,
    _json_object,
    _provider_report,
    build_pre_read_quality_and_access,
    consume_replication_access_exclusively,
)
from mds650.b1v3_confirmation import sha256_file
from mds650.study_design import canonical_sha256

ROOT = Path(__file__).resolve().parents[2]


def _frozen() -> dict[str, object]:
    document: dict[str, object] = {
        "schema_version": "b1-independent-replication-access-1.0",
        "status": "READY_FOR_SINGLE_REPLICATION_READ",
        "replication_target_read_count": 0,
        "evaluation_attempt_count": 0,
        "available_read_tokens": 1,
        "results_inspected": False,
        "result_sign_selection": "PROHIBITED",
        "preregistration_manifest_sha256": "a" * 64,
        "method_freeze_manifest_sha256": "b" * 64,
        "quality_manifest_sha256": "c" * 64,
        "common_panel_sha256": "d" * 64,
        "timing_common_manifest_sha256": "e" * 64,
        "training_timing_manifest_sha256": "3" * 64,
        "fmp_bars_sha256": "f" * 64,
        "code_bundle_sha256": "1" * 64,
        "uv_lock_sha256": "2" * 64,
        "terminal_rule": {
            "version": "b1-independent-replication-terminal-rule-1.0",
            "gamma_required": ["a", "b", "c", "d"],
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
    document["manifest_sha256"] = canonical_sha256(document)
    return document


def test_access_token_is_consumed_exactly_once(tmp_path: Path) -> None:
    destination = tmp_path / "consumed.json"
    schema = (
        ROOT
        / "specs/001-pit-options-rv30/contracts/"
        "b1-independent-replication-access-v1.schema.json"
    )
    consumed = consume_replication_access_exclusively(
        _frozen(), path=destination, access_schema_path=schema
    )
    assert consumed["status"] == "REPLICATION_EVALUATION_IN_PROGRESS"
    assert consumed["replication_target_read_count"] == 1
    assert json.loads(destination.read_text(encoding="utf-8")) == consumed
    with pytest.raises(ValueError, match="B1_REPLICATION_ACCESS_ALREADY_CONSUMED"):
        consume_replication_access_exclusively(
            _frozen(), path=destination, access_schema_path=schema
        )


def test_access_token_rejects_nonfrozen_contract(tmp_path: Path) -> None:
    frozen = _frozen()
    frozen["result_sign_selection"] = "POSITIVE_ONLY"
    frozen["manifest_sha256"] = canonical_sha256(
        {key: value for key, value in frozen.items() if key != "manifest_sha256"}
    )
    with pytest.raises(ValueError, match="B1_REPLICATION_ACCESS_FROZEN_INVALID"):
        consume_replication_access_exclusively(
            frozen,
            path=tmp_path / "consumed.json",
            access_schema_path=tmp_path / "schema.json",
        )


def test_access_contract_helpers_fail_closed_on_content_and_hashes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    schema = tmp_path / "schema.json"
    monkeypatch.setattr(
        "mds650.b1_replication_access.validate_confirmation_plan_schema",
        lambda document, schema_path: None,
    )
    invalid = tmp_path / "invalid.json"
    invalid.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="INVALID_OBJECT"):
        _json_object(invalid, code="INVALID_OBJECT")

    contract_path = tmp_path / "contract.json"
    contract = {"status": "PASS"}
    contract["manifest_sha256"] = canonical_sha256(contract)
    contract_path.write_text(json.dumps(contract), encoding="utf-8")
    assert _contract(contract_path, schema, code="CONTRACT")["status"] == "PASS"
    contract["manifest_sha256"] = "0" * 64
    contract_path.write_text(json.dumps(contract), encoding="utf-8")
    with pytest.raises(ValueError, match="CONTRACT_HASH"):
        _contract(contract_path, schema, code="CONTRACT")

    report_path = tmp_path / "report.json"
    report: dict[str, object] = {
        "status": "PASS_PROVIDER_PREFLIGHT_ASSUMPTION_BOUND",
        "target_blind": True,
        "outcome_read_count": 0,
        "safe_to_read_outcomes": False,
        "security": {
            "secret_values_emitted": False,
            "personal_paths_emitted": False,
        },
    }
    report["report_sha256"] = canonical_sha256(report)
    report_path.write_text(json.dumps(report), encoding="utf-8")
    assert _provider_report(report_path, schema, code="REPORT")["status"] == (
        "PASS_PROVIDER_PREFLIGHT_ASSUMPTION_BOUND"
    )
    report["outcome_read_count"] = 1
    report["report_sha256"] = canonical_sha256(
        {key: value for key, value in report.items() if key != "report_sha256"}
    )
    report_path.write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(ValueError, match="REPORT"):
        _provider_report(report_path, schema, code="REPORT")


def test_pre_read_gate_replays_panel_and_binds_all_timing_views(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    variants = (
        "FMP_DELAY_2_MINUTES",
        "MASSIVE_CUTOFF_60_SECONDS",
        "MASSIVE_CUTOFF_300_SECONDS",
        "UW_CREATED_AT_120_SECONDS",
        "UW_CREATED_AT_300_SECONDS",
    )
    training_sessions = [f"S{index:02d}" for index in range(60)]
    assets = ("AAPL", "AMZN", "META", "MSFT", "NVDA", "TSLA")

    files: dict[str, Path] = {}
    for name in (
        "inventory",
        "fmp",
        "training_snapshot",
        "code",
        "uv_lock",
    ):
        path = tmp_path / name
        path.write_bytes(name.encode("ascii"))
        files[name] = path
    replay = pl.DataFrame({"origin_id": ["AAPL:1"], "value": [1.0]})
    panel_paths: dict[str, Path] = {}
    for name in ("origins", "b0", "b1", "b2", "common"):
        path = tmp_path / f"{name}.parquet"
        replay.write_parquet(path)
        panel_paths[name] = path
    timing_paths: dict[str, Path] = {}
    training_timing_paths: dict[str, Path] = {}
    training_scope = pl.DataFrame(
        {
            "session_date": [
                session for session in training_sessions for _ in assets
            ],
            "asset": [asset for _ in training_sessions for asset in assets],
        }
    )
    for variant in variants:
        timing_path = tmp_path / f"timing-{variant}.parquet"
        replay.write_parquet(timing_path)
        timing_paths[variant] = timing_path
        training_path = tmp_path / f"training-{variant}.parquet"
        training_scope.write_parquet(training_path)
        training_timing_paths[variant] = training_path

    documents: dict[str, dict[str, object]] = {
        "prereg": {
            "manifest_sha256": "a" * 64,
            "replication_target_reads": 0,
            "training_sessions": training_sessions,
        },
        "method": {
            "manifest_sha256": "b" * 64,
            "replication_target_read_count": 0,
            "source_bindings": {
                "training_snapshot_sha256": sha256_file(files["training_snapshot"])
            },
        },
        "full_tape": {
            "manifest_sha256": "c" * 64,
            "status": "PASS",
            "completed_session_count": 30,
            "pending_session_count": 0,
        },
        "base": {
            "manifest_sha256": "d" * 64,
            "status": "PASS_TARGET_BLIND_BASE_PREDICTORS",
        },
        "source": {
            "manifest_sha256": "e" * 64,
            "raw_payload_binding": {
                "inventory_sha256": sha256_file(files["inventory"])
            },
        },
        "b1": {
            "manifest_sha256": "f" * 64,
            "status": "PASS_TARGET_BLIND_SOURCE_BOUND_TECHNICAL_BUILD",
            "provenance": {"source_binding_manifest_sha256": "e" * 64},
            "output": {"sha256": sha256_file(panel_paths["b1"])},
        },
        "b2": {
            "manifest_sha256": "1" * 64,
            "status": "PASS_TARGET_BLIND_B2_PREDICTORS",
            "variants": {
                "primary_5m_60s": {"sha256": sha256_file(panel_paths["b2"])}
            },
        },
        "common": {
            "manifest_sha256": "2" * 64,
            "status": "PASS_TARGET_BLIND_COMMON_PREDICTOR_PANEL",
            "technical_acceptance": {"status": "PASS"},
            "output": {"sha256": sha256_file(panel_paths["common"])},
        },
        "timing_predictor": {
            "manifest_sha256": "3" * 64,
            "status": "PASS_TARGET_BLIND_TIMING_PREDICTORS",
        },
        "timing_common": {
            "manifest_sha256": "4" * 64,
            "status": "PASS_TARGET_BLIND_TIMING_COMMON_PANELS",
            "variants": {
                variant: {
                    "output": {"sha256": sha256_file(timing_paths[variant])},
                    "technical_acceptance": {"common_complete_origin_count": 1},
                }
                for variant in variants
            },
        },
        "training_timing": {
            "manifest_sha256": "5" * 64,
            "status": "PASS_TARGET_BLIND_TIMING_COMMON_PANELS",
            "variants": {
                variant: {"sha256": sha256_file(training_timing_paths[variant])}
                for variant in variants
            },
        },
    }
    path_to_document: dict[Path, dict[str, object]] = {}
    for name, document in documents.items():
        path = tmp_path / f"{name}.json"
        path.write_text("{}", encoding="utf-8")
        path_to_document[path] = document

    provider = {
        "status": "PASS_PROVIDER_PREFLIGHT_ASSUMPTION_BOUND",
        "report_sha256": "6" * 64,
    }
    monkeypatch.setattr(
        "mds650.b1_replication_access._contract",
        lambda path, schema, code: path_to_document[path],
    )
    monkeypatch.setattr(
        "mds650.b1_replication_access._provider_report",
        lambda path, schema, code: provider,
    )
    monkeypatch.setattr(
        "mds650.b1_replication_access.build_replication_common_frame",
        lambda **kwargs: replay,
    )
    monkeypatch.setattr(
        "mds650.b1_replication_access.validate_confirmation_plan_schema",
        lambda document, schema: None,
    )
    DiskUsage = namedtuple("DiskUsage", "total used free")
    monkeypatch.setattr(
        "mds650.b1_replication_access.shutil.disk_usage",
        lambda path: DiskUsage(200 * 1024**3, 20 * 1024**3, 180 * 1024**3),
    )
    quality_path = tmp_path / "quality.json"
    access_path = tmp_path / "access.json"
    quality, access = build_pre_read_quality_and_access(
        preregistration_path=tmp_path / "prereg.json",
        preregistration_schema_path=tmp_path / "schema.json",
        method_freeze_path=tmp_path / "method.json",
        method_freeze_schema_path=tmp_path / "schema.json",
        provider_report_path=tmp_path / "provider.json",
        market_report_path=tmp_path / "market.json",
        provider_report_schema_path=tmp_path / "schema.json",
        full_tape_manifest_path=tmp_path / "full_tape.json",
        full_tape_schema_path=tmp_path / "schema.json",
        base_manifest_path=tmp_path / "base.json",
        base_schema_path=tmp_path / "schema.json",
        b1_source_manifest_path=tmp_path / "source.json",
        b1_source_schema_path=tmp_path / "schema.json",
        b1_inventory_path=files["inventory"],
        b1_feature_manifest_path=tmp_path / "b1.json",
        b1_feature_schema_path=tmp_path / "schema.json",
        b2_manifest_path=tmp_path / "b2.json",
        b2_schema_path=tmp_path / "schema.json",
        common_manifest_path=tmp_path / "common.json",
        common_schema_path=tmp_path / "schema.json",
        timing_predictor_manifest_path=tmp_path / "timing_predictor.json",
        timing_predictor_schema_path=tmp_path / "schema.json",
        timing_common_manifest_path=tmp_path / "timing_common.json",
        timing_common_schema_path=tmp_path / "schema.json",
        training_timing_manifest_path=tmp_path / "training_timing.json",
        training_timing_schema_path=tmp_path / "schema.json",
        origins_path=panel_paths["origins"],
        b0_path=panel_paths["b0"],
        b1_path=panel_paths["b1"],
        b2_path=panel_paths["b2"],
        common_panel_path=panel_paths["common"],
        timing_panel_paths=timing_paths,
        training_timing_panel_paths=training_timing_paths,
        fmp_bars_path=files["fmp"],
        training_snapshot_path=files["training_snapshot"],
        code_paths=[files["code"]],
        uv_lock_path=files["uv_lock"],
        data_root=tmp_path,
        quality_path=quality_path,
        quality_schema_path=tmp_path / "quality.schema.json",
        access_path=access_path,
        access_schema_path=tmp_path / "access.schema.json",
    )
    assert quality["status"] == "PASS_PRE_READ_REPLICATION_QUALITY"
    assert access["status"] == "READY_FOR_SINGLE_REPLICATION_READ"
    assert all(quality["conditions"].values())
    assert json.loads(access_path.read_text(encoding="utf-8")) == access


@pytest.mark.parametrize(
    "schema_name",
    [
        "b1-independent-replication-quality-v1.schema.json",
        "b1-independent-replication-access-v1.schema.json",
    ],
)
def test_replication_access_schema_is_valid(schema_name: str) -> None:
    schema = json.loads(
        (ROOT / "specs/001-pit-options-rv30/contracts" / schema_name).read_text(
            encoding="utf-8"
        )
    )
    jsonschema: Any = import_module("jsonschema")
    jsonschema.Draft202012Validator.check_schema(schema)
