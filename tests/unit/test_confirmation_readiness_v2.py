"""Tests for the v2 source-bound, target-blind confirmation-readiness gate."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import polars as pl

from mds650.confirmation_readiness_v2 import (
    SourceBoundConfirmationReadinessV2Config,
    build_source_bound_confirmation_readiness_v2,
)
from mds650.study_design import canonical_sha256


def _sha256(path: Path) -> str:
    """Return the ordinary SHA-256 of one local fixture file."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_source_bound_fixture(
    tmp_path: Path,
) -> SourceBoundConfirmationReadinessV2Config:
    """Create complete target-blind v2.3 inputs with independently bound hashes."""
    panel = pl.DataFrame(
        {
            "origin_id": ["origin-a", "origin-b"],
            "asset": ["AAPL", "AAPL"],
            "common_predictor_complete": [True, False],
            "b0v2_log_spot": [1.0, 2.0],
            "b1q_atm_iv": [0.2, 0.3],
            "b2v2_z_log_trade_count": [0.1, 0.2],
        }
    )
    common = panel.filter(pl.col("common_predictor_complete"))
    panel_path = tmp_path / "target_blind_common_predictors_v23.parquet"
    common_path = tmp_path / "target_blind_common_complete_v23.parquet"
    sidecar_path = tmp_path / "b2_row_availability_v22.parquet"
    panel.write_parquet(panel_path)
    common.write_parquet(common_path)
    sidecar_path.write_bytes(b"target-blind-b2-sidecar")

    source_hashes = {
        "b1q_source_sha256": "1" * 64,
        "b2_availability_manifest_v22_sha256": "2" * 64,
        "b2_availability_sidecar_sha256": _sha256(sidecar_path),
        "b2_primary_inputs_sha256": "3" * 64,
        "fmp_bars_sha256": "4" * 64,
        "massive_reselection_recomputed_v21_sha256": "5" * 64,
        "origins_sha256": "6" * 64,
        "pit_reconciliation_gate_v21_sha256": "7" * 64,
    }
    builder_hashes = {
        "panel_module_sha256": "8" * 64,
        "provenance_module_sha256": "9" * 64,
        "script_sha256": "a" * 64,
    }
    timing_rules = {
        "b1q_primary_state": "SIP_ASOF_ORIGIN_MAX_AGE_60S",
        "b2_created_at_rule": "OPERATIONAL_AVAILABILITY_PROXY_ORIGIN_MINUS_60_SECONDS",
        "b2_primary_variant": "primary_5m_60s",
        "fmp_primary_delay_minutes": 1,
        "fmp_sensitivity_delay_minutes": 2,
        "massive_reselection_sensitivity_cutoff_seconds": [60, 300],
    }
    input_provenance = {
        "availability_sidecar_status": "PASS_WITH_EXCLUSIONS",
        "edge_conclusion": "NOT_EVALUATED_TARGET_BLIND",
        "primary_excluded_row_count": 451,
        "reconciliation_gate_status": "CONDITIONAL_NOT_CLOSED",
    }
    manifest: dict[str, object] = {
        "SAFE_TO_OPEN_OR_EVALUATE_OOS": "NO",
        "builder_hashes": builder_hashes,
        "input_provenance": input_provenance,
        "model_fit_performed": False,
        "no_target_or_metric_payload_read": True,
        "output": {
            "common_complete_row_count": common.height,
            "common_complete_sha256": _sha256(common_path),
            "panel_sha256": _sha256(panel_path),
            "row_count": panel.height,
        },
        "output_locations": {
            "common_complete": "D:/MDS650/fixture/common.parquet",
            "panel": "D:/MDS650/fixture/panel.parquet",
        },
        "safe_to_reconcile_existing_results": "NO",
        "schema_version": "target-blind-common-predictor-manifest-v2.3",
        "scope": "offline_target_blind_predictor_construction_only",
        "source_commit": "b" * 40,
        "source_hashes": source_hashes,
        "status": "PASS_TARGET_BLIND_INPUTS_RECONCILIATION_REMAINS_BLOCKED",
        "summary": {
            "asset_count": 1,
            "completion_counts": {"common_predictor_complete": common.height},
            "completion_rates": {"common_predictor_complete": 0.5},
            "model_fit_performed": False,
            "no_target_or_metric_payload_read": True,
            "row_count": panel.height,
            "schema_version": "target-blind-common-predictor-summary-v2.3",
            "scope": "offline_target_blind_predictor_construction_only",
            "session_count": 1,
            "status": "PASS_TARGET_BLIND_INPUTS_RECONCILIATION_REMAINS_BLOCKED",
        },
        "timing_rules": timing_rules,
    }
    manifest_path = tmp_path / "target_blind_common_predictor_manifest_v23.json"
    manifest_path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")

    preregistration: dict[str, object] = {
        "bound_panel": {
            "builder_hashes": builder_hashes,
            "common_complete_row_count": common.height,
            "common_complete_sha256": _sha256(common_path),
            "input_provenance": input_provenance,
            "panel_builder_source_commit": "b" * 40,
            "panel_manifest_sha256": _sha256(manifest_path),
            "panel_sha256": _sha256(panel_path),
            "row_count": panel.height,
            "source_hashes": source_hashes,
            "timing_rules": timing_rules,
        },
        "fixed_claim_boundary": {
            "fmp": "TIMESTAMP_RAW_PLUS_1_MINUTE_CONSERVATIVE_STUDY_ASSUMPTION",
            "massive": "SIP_ASOF_ORIGIN_PRIMARY_WITH_60_300_SECOND_RESELECTION_SENSITIVITIES",
            "unusual_whales": (
                "CREATED_AT_OPERATIONAL_AVAILABILITY_PROXY_NOT_PUBLICATION_OR_RECEIPT"
            ),
        },
        "forbidden_before_successor_method_freeze": ["fit_models"],
        "information_sets": {
            "B0": ["b0v2_log_spot"],
            "B1a_addition": ["b1q_atm_iv"],
            "B1b_addition": ["b1q_skew"],
            "B1c_addition": ["b1q_term_structure"],
            "B2_addition": [f"b2_feature_{index}" for index in range(9)],
        },
        "method_template_v22_preregistration_sha256": "c" * 64,
        "method_template_v22_sha256": "d" * 64,
        "method_template_v22_source_commit": "e" * 40,
        "model_fit_performed": False,
        "no_target_or_metric_payload_read": True,
        "purpose": "bind_source_bound_target_blind_inputs_before_successor_method_freeze",
        "required_before_any_oos_access": ["successor_method_freeze"],
        "safe_to_open_or_evaluate_oos": "NO",
        "safe_to_reconcile_existing_results": "NO",
        "schema_version": "target-blind-confirmation-preregistration-v3.0",
        "sealed_result_reconciliation": "BLOCKED",
        "source_commit": "f" * 40,
        "status": "SEALED_SOURCE_BOUND_PRE_METHOD_FREEZE_NOT_AUTHORIZED_FOR_OOS",
        "successor_method_freeze_minimum_contents": ["method"],
    }
    preregistration["preregistration_sha256"] = canonical_sha256(preregistration)

    docs_audit: dict[str, object] = {
        "SAFE_TO_OPEN_OR_EVALUATE_OOS": "NO",
        "SAFE_TO_RECONCILE_EXISTING_RESULTS": "NO",
        "fmp": {"provider_semantics_status": "UNVERIFIED"},
        "historical_source_availability": {
            "status": "PASS_SEPARATE_FROM_PIT_TIMESTAMP_SEMANTICS",
            "fmp": {
                "evidence_sha256": (
                    "97c3b57707a953629ff57e485cde918e52ecdd1777a246e84072b5c4150771dc"
                ),
                "historical_availability_status": "PASS_90_OF_90_SESSIONS",
                "session_count": 90,
            },
            "unusual_whales": {
                "evidence_sha256": (
                    "244690e15054f518e5d12083e6b81d2bcbfcd8f5f009304f4127cbb5c1c4a3f3"
                ),
                "historical_availability_status": "PASS_90_OF_90_FILE_METADATA",
                "row_level_pit_claim": False,
                "session_count": 90,
            },
        },
        "massive": {"sip_timestamp_status": "EVENT_TIME_TECHNICAL_ONLY"},
        "no_provider_data_requests_performed": True,
        "no_targets_or_predictive_artifacts_read": True,
        "schema_version": "provider-timing-official-docs-audit-v1.0",
        "status": "PASS_LIMITATIONS_RECORDED_NO_PIT_SEMANTICS_UPGRADE",
        "unusual_whales": {"created_at_status": "PROXY_ONLY"},
    }
    docs_audit["manifest_sha256"] = canonical_sha256(docs_audit)
    docs_audit_path = tmp_path / "official_docs_audit_v1.json"
    docs_audit_path.write_text(json.dumps(docs_audit, sort_keys=True), encoding="utf-8")

    return SourceBoundConfirmationReadinessV2Config(
        panel_manifest=manifest,
        panel_manifest_path=manifest_path,
        preregistration=preregistration,
        provider_docs_audit=docs_audit,
        provider_docs_audit_path=docs_audit_path,
        panel_path=panel_path,
        common_path=common_path,
        availability_sidecar_path=sidecar_path,
    )


def test_source_bound_readiness_v2_binds_v23_inputs_without_authorising_oos(
    tmp_path: Path,
) -> None:
    """Source-bound valid inputs support method-freeze preparation, never OOS access."""
    result = build_source_bound_confirmation_readiness_v2(
        _write_source_bound_fixture(tmp_path)
    )

    assert result["status"] == "PASS_SOURCE_BOUND_METHOD_FREEZE_PREPARATION"
    assert result["bound_artifact_integrity"]["status"] == "PASS"
    assert result["common_subset_validation"]["status"] == "PASS"
    assert result["provider_timing_boundary"]["status"] == "PASS_LIMITATIONS_RETAINED"
    assert result["safe_to_reconcile_existing_results"] == "NO"
    assert result["safe_to_open_or_evaluate_oos"] == "NO"
    assert result["safe_to_acquire_new_sample"] == "NO"
    assert result["model_fit_performed"] is False


def test_source_bound_readiness_v2_rejects_historical_source_claim_that_overrides_pit(
    tmp_path: Path,
) -> None:
    """Historical files cannot silently upgrade FMP or UW timestamp semantics."""
    config = _write_source_bound_fixture(tmp_path)
    audit: dict[str, object] = deepcopy(dict(config.provider_docs_audit))
    audit["historical_source_availability"] = {
        "status": "PASS_SEPARATE_FROM_PIT_TIMESTAMP_SEMANTICS",
        "fmp": {"historical_availability_status": "PASS_BUT_PIT_CONFIRMED"},
        "unusual_whales": {
            "historical_availability_status": "PASS_90_OF_90_FILE_METADATA",
            "row_level_pit_claim": False,
        },
    }
    audit["manifest_sha256"] = canonical_sha256(
        {key: value for key, value in audit.items() if key != "manifest_sha256"}
    )
    config.provider_docs_audit_path.write_text(
        json.dumps(audit, sort_keys=True), encoding="utf-8"
    )

    result = build_source_bound_confirmation_readiness_v2(
        replace(config, provider_docs_audit=audit)
    )

    assert result["status"] == "FAIL_SOURCE_BOUND_READINESS"
    assert result["provider_timing_boundary"]["status"] == "FAIL"
    assert "FMP_HISTORICAL_SOURCE_AVAILABILITY_BOUNDARY_INVALID" in result[
        "provider_timing_boundary"
    ]["failure_codes"]


def test_source_bound_readiness_v2_rejects_tampered_manifest_and_preregistration(
    tmp_path: Path,
) -> None:
    """Malformed source bindings cannot reach a successor method freeze."""
    config = _write_source_bound_fixture(tmp_path)
    manifest: dict[str, object] = deepcopy(dict(config.panel_manifest))
    preregistration: dict[str, object] = deepcopy(dict(config.preregistration))
    manifest["schema_version"] = "target-blind-common-predictor-manifest-v0"
    manifest["SAFE_TO_OPEN_OR_EVALUATE_OOS"] = "YES"
    manifest["model_fit_performed"] = True
    config.panel_manifest_path.write_text(
        json.dumps(manifest, sort_keys=True), encoding="utf-8"
    )
    bound_panel = preregistration["bound_panel"]
    assert isinstance(bound_panel, dict)
    bound_panel["panel_manifest_sha256"] = "0" * 64
    preregistration["safe_to_open_or_evaluate_oos"] = "YES"
    preregistration["preregistration_sha256"] = canonical_sha256(
        {key: value for key, value in preregistration.items() if key != "preregistration_sha256"}
    )

    result = build_source_bound_confirmation_readiness_v2(
        replace(config, panel_manifest=manifest, preregistration=preregistration)
    )

    assert result["status"] == "FAIL_SOURCE_BOUND_READINESS"
    failures = result["bound_artifact_integrity"]["failure_codes"]
    assert "PANEL_MANIFEST_SCHEMA_VERSION_INVALID" in failures
    assert "PANEL_MANIFEST_SAFE_TO_OPEN_OR_EVALUATE_OOS_INVALID" in failures
    assert "PREREGISTRATION_MANIFEST_FILE_HASH_MISMATCH" in failures
    assert "PREREGISTRATION_SAFE_TO_OPEN_OR_EVALUATE_OOS_INVALID" in failures


def test_source_bound_readiness_v2_rejects_target_column_in_predictor_panel(
    tmp_path: Path,
) -> None:
    """A target-like column cannot be carried into a target-blind predictor matrix."""
    config = _write_source_bound_fixture(tmp_path)
    panel = pl.read_parquet(config.panel_path).with_columns(pl.lit(0.01).alias("rv30"))
    panel.write_parquet(config.panel_path)
    panel.filter(pl.col("common_predictor_complete")).write_parquet(config.common_path)

    result = build_source_bound_confirmation_readiness_v2(config)

    assert result["status"] == "FAIL_SOURCE_BOUND_READINESS"
    assert result["common_subset_validation"]["status"] == "FAIL"
    assert "TARGET_BLIND_OUTCOME_LIKE_COLUMN_PRESENT" in result["common_subset_validation"][
        "failure_codes"
    ]


def test_source_bound_readiness_v2_fails_closed_for_unreadable_predictor_panel(
    tmp_path: Path,
) -> None:
    """A deleted source file is explicit failure rather than an empty predictor panel."""
    config = _write_source_bound_fixture(tmp_path)
    config.panel_path.unlink()

    result = build_source_bound_confirmation_readiness_v2(config)

    assert result["status"] == "FAIL_SOURCE_BOUND_READINESS"
    assert result["common_subset_validation"] == {
        "status": "FAIL",
        "failure_codes": ["TARGET_BLIND_PARQUET_UNREADABLE"],
        "panel_row_count": None,
        "common_complete_row_count": None,
    }


def test_source_bound_readiness_v2_rejects_missing_b2_availability_sidecar(
    tmp_path: Path,
) -> None:
    """A missing sidecar is a provenance failure, not evidence of no B2 activity."""
    config = _write_source_bound_fixture(tmp_path)
    config.availability_sidecar_path.unlink()

    result = build_source_bound_confirmation_readiness_v2(config)

    assert result["status"] == "FAIL_SOURCE_BOUND_READINESS"
    assert "B2_AVAILABILITY_SIDECAR_HASH_MISMATCH" in result["bound_artifact_integrity"][
        "failure_codes"
    ]
