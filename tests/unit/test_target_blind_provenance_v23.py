"""Tests for the v2.3 target-blind provenance preflight."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from mds650.target_blind_provenance_v23 import validate_target_blind_provenance_v23

ROOT = Path(__file__).resolve().parents[2]
AVAILABILITY_SCHEMA = (
    ROOT
    / "specs"
    / "001-pit-options-rv30"
    / "contracts"
    / "b2-availability-manifest-v22.schema.json"
)
GATE_SCHEMA = (
    ROOT
    / "specs"
    / "001-pit-options-rv30"
    / "contracts"
    / "pit-reconciliation-gate-v21.schema.json"
)


def test_provenance_preflight_binds_origin_sidecar_massive_and_gate(tmp_path: Path) -> None:
    """All approved source identities must match their two contract records."""
    sources = _write_valid_sources(tmp_path)

    hashes = validate_target_blind_provenance_v23(
        availability_manifest_path=sources["availability_manifest_path"],
        availability_manifest_schema_path=AVAILABILITY_SCHEMA,
        availability_sidecar_path=sources["availability_sidecar_path"],
        massive_reselection_path=sources["massive_reselection_path"],
        origins_path=sources["origins_path"],
        reconciliation_gate_path=sources["reconciliation_gate_path"],
        reconciliation_gate_schema_path=GATE_SCHEMA,
    )

    assert hashes["origins_sha256"] == _sha256_file(sources["origins_path"])
    assert hashes["b2_availability_sidecar_sha256"] == _sha256_file(
        sources["availability_sidecar_path"]
    )
    assert hashes["massive_reselection_recomputed_v21_sha256"] == _sha256_file(
        sources["massive_reselection_path"]
    )
    assert hashes["b2_availability_manifest_v22_sha256"] == _sha256_file(
        sources["availability_manifest_path"]
    )
    assert hashes["pit_reconciliation_gate_v21_sha256"] == _sha256_file(
        sources["reconciliation_gate_path"]
    )


def test_provenance_preflight_rejects_sidecar_hash_drift(tmp_path: Path) -> None:
    """A changed sidecar cannot be accepted under an unchanged v2.2 manifest."""
    sources = _write_valid_sources(tmp_path)
    sources["availability_sidecar_path"].write_bytes(b"different-sidecar")

    with pytest.raises(ValueError, match="TARGET_BLIND_V23_SIDECAR_HASH_MISMATCH"):
        validate_target_blind_provenance_v23(
            availability_manifest_path=sources["availability_manifest_path"],
            availability_manifest_schema_path=AVAILABILITY_SCHEMA,
            availability_sidecar_path=sources["availability_sidecar_path"],
            massive_reselection_path=sources["massive_reselection_path"],
            origins_path=sources["origins_path"],
            reconciliation_gate_path=sources["reconciliation_gate_path"],
            reconciliation_gate_schema_path=GATE_SCHEMA,
        )


def test_provenance_preflight_rejects_gate_massive_hash_drift(tmp_path: Path) -> None:
    """A gate with a different Massive identity cannot authorize construction."""
    sources = _write_valid_sources(tmp_path)
    gate = _read_json(sources["reconciliation_gate_path"])
    gate["source_evidence"][0]["file_sha256"] = "f" * 64
    _write_gate(sources["reconciliation_gate_path"], gate)

    with pytest.raises(ValueError, match="TARGET_BLIND_V23_GATE_MASSIVE_HASH_MISMATCH"):
        validate_target_blind_provenance_v23(
            availability_manifest_path=sources["availability_manifest_path"],
            availability_manifest_schema_path=AVAILABILITY_SCHEMA,
            availability_sidecar_path=sources["availability_sidecar_path"],
            massive_reselection_path=sources["massive_reselection_path"],
            origins_path=sources["origins_path"],
            reconciliation_gate_path=sources["reconciliation_gate_path"],
            reconciliation_gate_schema_path=GATE_SCHEMA,
        )


def _write_valid_sources(tmp_path: Path) -> dict[str, Path]:
    origins_path = tmp_path / "origins.parquet"
    availability_sidecar_path = tmp_path / "b2_row_availability_v22.parquet"
    massive_reselection_path = tmp_path / "massive_recomputed.json"
    availability_manifest_path = tmp_path / "availability_manifest.json"
    reconciliation_gate_path = tmp_path / "pit_gate.json"
    origins_path.write_bytes(b"target-free-origin-grid")
    availability_sidecar_path.write_bytes(b"target-free-b2-sidecar")
    massive = {
        "schema_version": "provider-timing-v2.1",
        "status": "PASS",
        "no_provider_http_requests_performed": True,
        "no_targets_or_predictive_metrics_read": True,
        "selection_rule": (
            "last_quote_by_sip_timestamp_then_sequence_at_or_before_origin_minus_delay"
        ),
    }
    massive["recomputed_result_sha256"] = _canonical_sha256(massive)
    _write_json(massive_reselection_path, massive)
    manifest = {
        "schema_version": "2.2",
        "b2_availability_sidecar_status": "PASS_WITH_EXCLUSIONS",
        "corrected_pit_panel_preparation": (
            "PASS_MASK_READY_REQUIRES_NEW_TARGET_BLIND_PANEL_BUILD"
        ),
        "expected_origins_sha256": _sha256_file(origins_path),
        "generation_mode": "deterministic_target_blind_rebuild",
        "limitations": ["fixture"],
        "model_or_metric_payload_read": False,
        "oos_payload_read": False,
        "safe_to_reconcile_existing_results": "NO",
        "scope": "target_blind_offline_no_provider_requests",
        "sealed_result_reconciliation": "BLOCKED",
        "sidecar_sha256": _sha256_file(availability_sidecar_path),
        "sidecar_storage": "D-resident derived artefact",
        "traceability_sha256": "0" * 64,
        "summary": {
            "schema_version": "2.2",
            "row_count": 1,
            "eligible_row_count": 1,
            "excluded_row_count": 0,
            "primary_delayed_raw_zero_exclusion_count": 0,
            "canonical_raw_count_mismatch_count": 0,
            "row_status_counts": {"PIT_USABLE_ELIGIBLE_ACTIVITY": 1},
            "variant_totals": [
                {
                    "canonical_variant": "primary_5m_60s",
                    "row_count": 1,
                    "eligible_row_count": 1,
                    "excluded_row_count": 0,
                }
            ],
        },
    }
    _write_json(availability_manifest_path, manifest)
    gate = {
        "schema_version": "pit-reconciliation-gate-v2.1",
        "status": "CONDITIONAL_NOT_CLOSED",
        "PIT_V21": "CONDITIONAL_NOT_CLOSED",
        "SAFE_TO_RECONCILE_EXISTING_RESULTS": "NO",
        "SAFE_TO_OPEN_OR_EVALUATE_OOS": "NO",
        "edge_conclusion": "NOT_EVALUATED_TARGET_BLIND",
        "fmp_bar_availability": {
            "baseline_study_rule": "timestamp_raw_plus_1_minute",
            "sensitivity_study_rule": "timestamp_raw_plus_2_minutes",
            "provider_semantics_status": "UNVERIFIED",
            "conclusion": "CONSERVATIVE_STUDY_ASSUMPTION_NOT_PROVIDER_CONFIRMATION",
        },
        "massive_b1q_reselection": {
            "status": "PASS_TECHNICAL_TARGET_FREE",
            "source_status": "PASS",
            "selection_rule": (
                "last_quote_by_sip_timestamp_then_sequence_at_or_before_origin_minus_delay"
            ),
            "conclusion": (
                "TECHNICAL_CACHE_RESELECTION_PASS_NOT_HISTORICAL_DELIVERY_LATENCY_PROOF"
            ),
        },
        "legacy_uw_b2_raw_diagnostic": {
            "status": "FAIL_ZERO_CONFOUNDED_BY_OBSERVED_CREATED_AT_DELAY",
            "source_gate": "FAIL",
            "failure_reason": "ZERO_CONFOUNDED_BY_OBSERVED_CREATED_AT_DELAY",
            "conclusion": "B2_ZERO_CANNOT_BE_INTERPRETED_AS_CONFIRMED_NO_ACTIVITY",
        },
        "corrected_uw_b2_availability_sidecar_v22": {
            "status": "PASS_WITH_EXCLUSIONS",
            "primary_excluded_row_count": 451,
            "corrected_panel_preparation": (
                "PASS_MASK_READY_REQUIRES_NEW_TARGET_BLIND_PANEL_BUILD"
            ),
            "conclusion": "SIDE_CAR_MASK_READY_NEW_TARGET_BLIND_PANEL_REQUIRED",
        },
        "blocking_reasons": [
            "SEALED_RESULTS_RECONCILIATION_PROHIBITED",
            "NEW_TARGET_BLIND_COMMON_PANEL_REQUIRED",
        ],
        "source_evidence": _source_evidence(massive_reselection_path, availability_manifest_path),
        "no_provider_http_requests_performed": True,
        "no_targets_or_predictive_metrics_read": True,
        "no_oos_or_predictive_artifacts_read": True,
        "secret_values_emitted": False,
        "personal_paths_emitted": False,
    }
    _write_gate(reconciliation_gate_path, gate)
    return {
        "origins_path": origins_path,
        "availability_sidecar_path": availability_sidecar_path,
        "massive_reselection_path": massive_reselection_path,
        "availability_manifest_path": availability_manifest_path,
        "reconciliation_gate_path": reconciliation_gate_path,
    }


def _source_evidence(massive_path: Path, manifest_path: Path) -> list[dict[str, str | None]]:
    return [
        {
            "role": "MASSIVE_RESELECTION",
            "logical_path": (
                "artifacts/provider_timing_v21/"
                "massive_reselection_sensitivity_v21_recomputed_20260812.json"
            ),
            "file_sha256": _sha256_file(massive_path),
            "semantic_sha256": "1" * 64,
        },
        {
            "role": "UW_ANOMALY",
            "logical_path": "artifacts/provider_timing_v21/uw_anomaly_evidence_v21.json",
            "file_sha256": "2" * 64,
            "semantic_sha256": "3" * 64,
        },
        {
            "role": "PIT_CONTRACT",
            "logical_path": "docs/provider_timing_pit_contract_v21.md",
            "file_sha256": "4" * 64,
            "semantic_sha256": None,
        },
        {
            "role": "PIT_DECISION_LEDGER",
            "logical_path": "docs/pit_v21_decision_ledger.md",
            "file_sha256": "5" * 64,
            "semantic_sha256": None,
        },
        {
            "role": "UW_AVAILABILITY_MANIFEST_V22",
            "logical_path": "artifacts/provider_timing_v22/b2_availability_manifest_v22.json",
            "file_sha256": _sha256_file(manifest_path),
            "semantic_sha256": None,
        },
        {
            "role": "PIT_CONTRACT_V22",
            "logical_path": "docs/provider_timing_pit_contract_v22.md",
            "file_sha256": "6" * 64,
            "semantic_sha256": None,
        },
    ]


def _write_gate(path: Path, payload: dict[str, object]) -> None:
    unsigned = {key: value for key, value in payload.items() if key != "aggregation_sha256"}
    _write_json(path, {**unsigned, "aggregation_sha256": _canonical_sha256(unsigned)})


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")


def _read_json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()
