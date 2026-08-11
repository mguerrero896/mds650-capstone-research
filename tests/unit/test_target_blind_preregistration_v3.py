"""Tests for the source-bound, pre-method-freeze preregistration v3."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from mds650.target_blind_preregistration_v3 import (
    build_sourcebound_preregistration_v3,
)


def test_v3_preregistration_binds_sourcebound_panel_without_opening_oos() -> None:
    """The next-study seal inherits methods but never turns an evaluation gate on."""
    result = build_sourcebound_preregistration_v3(
        panel_manifest=_panel_manifest(),
        template_preregistration=_template_preregistration(),
        panel_manifest_file_sha256="a" * 64,
        template_file_sha256="b" * 64,
        source_commit="c" * 40,
    )

    assert result["schema_version"] == "target-blind-confirmation-preregistration-v3.0"
    assert result["safe_to_reconcile_existing_results"] == "NO"
    assert result["safe_to_open_or_evaluate_oos"] == "NO"
    assert result["model_fit_performed"] is False
    assert result["bound_panel"]["panel_manifest_sha256"] == "a" * 64
    assert result["method_template_v22_sha256"] == "b" * 64
    assert result["preregistration_sha256"]


def test_v3_preregistration_rejects_an_open_panel_gate() -> None:
    """A panel that permits reconciliation or OOS cannot seed a future freeze."""
    manifest = _panel_manifest()
    manifest["safe_to_reconcile_existing_results"] = "YES"

    with pytest.raises(ValueError, match="TARGET_BLIND_V3_PANEL_GATE_INVALID"):
        build_sourcebound_preregistration_v3(
            panel_manifest=manifest,
            template_preregistration=_template_preregistration(),
            panel_manifest_file_sha256="a" * 64,
            template_file_sha256="b" * 64,
            source_commit="c" * 40,
        )


def test_v3_preregistration_rejects_template_hash_drift() -> None:
    """A changed v2 method template cannot be silently carried into v3."""
    template = _template_preregistration()
    template["preregistration_sha256"] = "0" * 64

    with pytest.raises(ValueError, match="TARGET_BLIND_V3_TEMPLATE_SELF_HASH_INVALID"):
        build_sourcebound_preregistration_v3(
            panel_manifest=_panel_manifest(),
            template_preregistration=template,
            panel_manifest_file_sha256="a" * 64,
            template_file_sha256="b" * 64,
            source_commit="c" * 40,
        )


def test_v3_preregistration_rejects_invalid_panel_hash_and_b2_definition() -> None:
    """Panel identity and the exactly-nine B2 contract are both fail-closed."""
    manifest = _panel_manifest()
    assert isinstance(manifest["output"], dict)
    manifest["output"]["panel_sha256"] = "not-a-sha"

    with pytest.raises(ValueError, match="TARGET_BLIND_V3_PANEL_OUTPUT_HASH_INVALID"):
        build_sourcebound_preregistration_v3(
            panel_manifest=manifest,
            template_preregistration=_template_preregistration(),
            panel_manifest_file_sha256="a" * 64,
            template_file_sha256="b" * 64,
            source_commit="c" * 40,
        )

    template = _template_preregistration()
    assert isinstance(template["information_sets"], dict)
    template["information_sets"]["B2_addition"] = ["only-one"]
    from mds650.provider_timing_v21 import canonical_sha256

    unsigned = {key: value for key, value in template.items() if key != "preregistration_sha256"}
    template["preregistration_sha256"] = canonical_sha256(unsigned)

    with pytest.raises(ValueError, match="TARGET_BLIND_V3_TEMPLATE_B2_FEATURES_INVALID"):
        build_sourcebound_preregistration_v3(
            panel_manifest=_panel_manifest(),
            template_preregistration=template,
            panel_manifest_file_sha256="a" * 64,
            template_file_sha256="b" * 64,
            source_commit="c" * 40,
        )


def test_v3_preregistration_rejects_template_without_bound_panel_mapping() -> None:
    """A malformed v2 method template returns a stable validation error, not an assertion."""
    template = _template_preregistration()
    template["bound_panel"] = None
    from mds650.provider_timing_v21 import canonical_sha256

    unsigned = {key: value for key, value in template.items() if key != "preregistration_sha256"}
    template["preregistration_sha256"] = canonical_sha256(unsigned)

    with pytest.raises(ValueError, match="TARGET_BLIND_V3_TEMPLATE_STRUCTURE_INVALID"):
        build_sourcebound_preregistration_v3(
            panel_manifest=_panel_manifest(),
            template_preregistration=template,
            panel_manifest_file_sha256="a" * 64,
            template_file_sha256="b" * 64,
            source_commit="c" * 40,
        )


def test_v3_preregistration_conforms_to_its_json_schema() -> None:
    """The sealed source-bound contract is machine-valid before it reaches disk."""
    schema_path = (
        Path(__file__).resolve().parents[2]
        / "specs"
        / "001-pit-options-rv30"
        / "contracts"
        / "target-blind-confirmation-preregistration-v3.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    result = build_sourcebound_preregistration_v3(
        panel_manifest=_panel_manifest(),
        template_preregistration=_template_preregistration(),
        panel_manifest_file_sha256="a" * 64,
        template_file_sha256="b" * 64,
        source_commit="c" * 40,
    )

    assert list(Draft202012Validator(schema).iter_errors(result)) == []


def _panel_manifest() -> dict[str, object]:
    return {
        "schema_version": "target-blind-common-predictor-manifest-v2.3",
        "status": "PASS_TARGET_BLIND_INPUTS_RECONCILIATION_REMAINS_BLOCKED",
        "no_target_or_metric_payload_read": True,
        "model_fit_performed": False,
        "safe_to_reconcile_existing_results": "NO",
        "SAFE_TO_OPEN_OR_EVALUATE_OOS": "NO",
        "input_provenance": {
            "availability_sidecar_status": "PASS_WITH_EXCLUSIONS",
            "edge_conclusion": "NOT_EVALUATED_TARGET_BLIND",
            "primary_excluded_row_count": 451,
            "reconciliation_gate_status": "CONDITIONAL_NOT_CLOSED",
        },
        "timing_rules": {
            "fmp_primary_delay_minutes": 1,
            "fmp_sensitivity_delay_minutes": 2,
            "b1q_primary_state": "SIP_ASOF_ORIGIN_MAX_AGE_60S",
            "massive_reselection_sensitivity_cutoff_seconds": [60, 300],
            "b2_primary_variant": "primary_5m_60s",
            "b2_created_at_rule": "OPERATIONAL_AVAILABILITY_PROXY_ORIGIN_MINUS_60_SECONDS",
        },
        "source_hashes": {"placeholder": "d" * 64},
        "builder_hashes": {"placeholder": "e" * 64},
        "output": {
            "panel_sha256": "f" * 64,
            "common_complete_sha256": "0" * 64,
            "row_count": 10,
            "common_complete_row_count": 8,
        },
        "source_commit": "1" * 40,
    }


def _template_preregistration() -> dict[str, object]:
    template: dict[str, object] = {
        "schema_version": "target-blind-confirmation-preregistration-v2.0",
        "status": "SEALED_PRE_METHOD_FREEZE_NOT_AUTHORIZED_FOR_OOS",
        "purpose": "bind_corrected_target_blind_inputs_before_successor_method_freeze",
        "no_target_or_metric_payload_read": True,
        "model_fit_performed": False,
        "sealed_result_reconciliation": "BLOCKED",
        "safe_to_reconcile_existing_results": "NO",
        "safe_to_open_or_evaluate_oos": "NO",
        "bound_panel": {"panel_sha256": "f" * 64},
        "information_sets": {
            "B0": ["b0v2_log_spot"],
            "B1a_addition": ["b1v2_atm_iv_30_60_dte"],
            "B1b_addition": ["b1v2_skew_symmetric_moneyness"],
            "B1c_addition": ["b1v2_term_short_to_medium"],
            "B2_addition": [f"b2v2_feature_{index}" for index in range(9)],
        },
        "fixed_claim_boundary": {
            "fmp": "TIMESTAMP_RAW_PLUS_1_MINUTE_CONSERVATIVE_STUDY_ASSUMPTION",
            "massive": "SIP_ASOF_ORIGIN_PRIMARY_WITH_60_300_SECOND_RESELECTION_SENSITIVITIES",
            "unusual_whales": (
                "CREATED_AT_OPERATIONAL_AVAILABILITY_PROXY_NOT_PUBLICATION_OR_RECEIPT"
            ),
        },
        "forbidden_before_successor_method_freeze": ["fit_or_tune_a_model"],
        "required_before_any_oos_access": ["explicit_human_authorization_for_one_oos_access"],
        "successor_method_freeze_minimum_contents": ["bound_panel_sha256"],
        "source_commit": "2" * 40,
    }
    from mds650.provider_timing_v21 import canonical_sha256

    template["preregistration_sha256"] = canonical_sha256(template)
    return deepcopy(template)
