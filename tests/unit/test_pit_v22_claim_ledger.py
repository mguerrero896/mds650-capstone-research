"""Tests for the target-blind PIT v2.2 claims-and-limitations ledger."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from mds650.pit_v22_claim_ledger import (
    build_claim_ledger,
    canonical_sha256,
    render_claims_markdown,
)

ROOT = Path(__file__).resolve().parents[2]


def _panel_manifest() -> dict[str, object]:
    """Return a valid minimal target-blind panel-manifest fixture."""
    return {
        "schema_version": "target-blind-common-predictor-manifest-v2.2",
        "status": "PASS_TARGET_BLIND_INPUTS_RECONCILIATION_REMAINS_BLOCKED",
        "no_target_or_metric_payload_read": True,
        "model_fit_performed": False,
        "safe_to_reconcile_existing_results": "NO",
        "output": {
            "panel_sha256": "a" * 64,
            "row_count": 100,
            "common_complete_row_count": 80,
        },
        "summary": {
            "asset_count": 6,
            "b2_availability": {
                "eligible_row_count": 98,
                "excluded_row_count": 2,
            },
        },
    }


def _readiness() -> dict[str, object]:
    """Return a valid readiness fixture with its canonical self-hash."""
    payload: dict[str, object] = {
        "schema_version": "confirmation-readiness-v1.0",
        "status": "PASS_READY_FOR_CONFIRMATION_ACQUISITION_NOT_REQUESTED",
        "no_target_or_metric_payload_read": True,
        "model_fit_performed": False,
        "safe_to_reconcile_existing_results": "NO",
        "safe_to_open_or_evaluate_oos": "NO",
        "ready_for_confirmation": "YES",
        "safe_to_acquire_new_sample": "NO",
    }
    payload["readiness_sha256"] = canonical_sha256(payload)
    return payload


def _availability_manifest() -> dict[str, object]:
    """Return a B2 availability manifest fixture with an unclosed reconciliation gate."""
    return {
        "schema_version": "2.2",
        "generation_mode": "deterministic_target_blind_rebuild",
        "model_or_metric_payload_read": False,
        "oos_payload_read": False,
        "safe_to_reconcile_existing_results": "NO",
    }


def _availability_summary() -> dict[str, object]:
    """Return minimal target-free availability counts for the primary variant."""
    return {
        "schema_version": "2.2",
        "variant_totals": [
            {
                "canonical_variant": "primary_5m_60s",
                "row_count": 100,
                "eligible_row_count": 98,
                "excluded_row_count": 2,
            }
        ],
    }


def _source_hashes() -> dict[str, str]:
    """Return deterministic logical-source hashes without paths or secret values."""
    return {
        "panel_manifest": "1" * 64,
        "confirmation_readiness": "2" * 64,
        "availability_manifest": "3" * 64,
        "availability_summary": "4" * 64,
        "pit_contract_v21": "5" * 64,
        "claim_matrix_v21": "6" * 64,
    }


def test_claim_ledger_preserves_proxy_and_not_evaluated_boundaries() -> None:
    """The ledger must separate data readiness from predictive claims."""
    ledger = build_claim_ledger(
        _panel_manifest(),
        _readiness(),
        _availability_manifest(),
        _availability_summary(),
        _source_hashes(),
    )

    statuses = {claim["claim_id"]: claim["status"] for claim in ledger["claims"]}
    assert statuses["PITV22-C001"] == "SUPPORTED_TARGET_BLIND"
    assert statuses["PITV22-C002"] == "PROXY_ONLY"
    assert statuses["PITV22-C006"] == "NOT_EVALUATED_AFTER_PIT_CORRECTION"
    assert statuses["PITV22-C007"] == "NOT_EVALUATED_AFTER_PIT_CORRECTION"
    assert ledger["safe_to_open_or_evaluate_oos"] == "NO"
    assert ledger["model_fit_performed"] is False
    assert all(claim["evidence"] for claim in ledger["claims"])
    assert (
        canonical_sha256(
            {key: value for key, value in ledger.items() if key != "claim_ledger_sha256"}
        )
        == ledger["claim_ledger_sha256"]
    )


def test_claim_ledger_rejects_any_input_that_opens_reconciliation_or_oos() -> None:
    """A permissive source cannot create a target-blind defensive ledger."""
    readiness = _readiness()
    readiness["safe_to_open_or_evaluate_oos"] = "YES"

    with pytest.raises(ValueError, match="PIT_V22_CLAIM_LEDGER_READINESS_INVALID"):
        build_claim_ledger(
            _panel_manifest(),
            readiness,
            _availability_manifest(),
            _availability_summary(),
            _source_hashes(),
        )


def test_claim_ledger_markdown_is_evidence_bound_and_forbids_universal_edge() -> None:
    """Human-readable claims cannot relabel preparation as a positive result."""
    ledger = build_claim_ledger(
        _panel_manifest(),
        _readiness(),
        _availability_manifest(),
        _availability_summary(),
        _source_hashes(),
    )
    markdown = render_claims_markdown(ledger)

    assert "NOT_EVALUATED_AFTER_PIT_CORRECTION" in markdown
    assert "universal positive edge" not in markdown.casefold()
    assert "trading profit" not in markdown.casefold()
    assert "C:\\Users\\" not in markdown
    assert json.dumps(_source_hashes()["panel_manifest"]) in json.dumps(ledger)


def test_claim_ledger_conforms_to_committed_json_schema() -> None:
    """The ledger's machine-readable form remains bound to its public contract."""
    ledger = build_claim_ledger(
        _panel_manifest(),
        _readiness(),
        _availability_manifest(),
        _availability_summary(),
        _source_hashes(),
    )
    schema_path = (
        ROOT
        / "specs"
        / "001-pit-options-rv30"
        / "contracts"
        / "pit-v22-claim-ledger-v1.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    assert list(Draft202012Validator(schema).iter_errors(ledger)) == []


def test_claim_ledger_schema_rejects_extra_or_duplicate_claims() -> None:
    """The public contract permits exactly the eight pre-registered claims once each."""
    ledger = build_claim_ledger(
        _panel_manifest(),
        _readiness(),
        _availability_manifest(),
        _availability_summary(),
        _source_hashes(),
    )
    schema_path = (
        ROOT
        / "specs"
        / "001-pit-options-rv30"
        / "contracts"
        / "pit-v22-claim-ledger-v1.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    mutated = json.loads(json.dumps(ledger))
    mutated["claims"].append(dict(mutated["claims"][0]))

    assert list(Draft202012Validator(schema).iter_errors(mutated))

    duplicate_identifier = json.loads(json.dumps(ledger))
    duplicate_identifier["claims"][1]["claim_id"] = duplicate_identifier["claims"][0]["claim_id"]

    assert list(Draft202012Validator(schema).iter_errors(duplicate_identifier))


def test_claim_ledger_fails_closed_when_evidence_identity_is_invalid() -> None:
    """Required target-blind sources cannot be downgraded to malformed evidence."""
    invalid_panel = _panel_manifest()
    invalid_panel["status"] = "PASS"
    with pytest.raises(ValueError, match="PIT_V22_CLAIM_LEDGER_PANEL_MANIFEST_INVALID"):
        build_claim_ledger(
            invalid_panel,
            _readiness(),
            _availability_manifest(),
            _availability_summary(),
            _source_hashes(),
        )

    invalid_readiness = _readiness()
    invalid_readiness["readiness_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="PIT_V22_CLAIM_LEDGER_READINESS_INVALID"):
        build_claim_ledger(
            _panel_manifest(),
            invalid_readiness,
            _availability_manifest(),
            _availability_summary(),
            _source_hashes(),
        )

    invalid_hashes = _source_hashes()
    invalid_hashes["panel_manifest"] = "not-a-sha256"
    with pytest.raises(ValueError, match="PIT_V22_CLAIM_LEDGER_SOURCE_HASHES_INVALID"):
        build_claim_ledger(
            _panel_manifest(),
            _readiness(),
            _availability_manifest(),
            _availability_summary(),
            invalid_hashes,
        )


def test_claim_ledger_rejects_malformed_target_blind_availability_totals() -> None:
    """Primary availability totals must remain arithmetically and semantically valid."""
    invalid_manifest = _availability_manifest()
    invalid_manifest["model_or_metric_payload_read"] = True
    with pytest.raises(ValueError, match="PIT_V22_CLAIM_LEDGER_AVAILABILITY_MANIFEST_INVALID"):
        build_claim_ledger(
            _panel_manifest(),
            _readiness(),
            invalid_manifest,
            _availability_summary(),
            _source_hashes(),
        )

    invalid_summary = _availability_summary()
    totals = invalid_summary["variant_totals"]
    assert isinstance(totals, list)
    assert isinstance(totals[0], dict)
    totals[0]["eligible_row_count"] = 99
    with pytest.raises(ValueError, match="PIT_V22_CLAIM_LEDGER_AVAILABILITY_SUMMARY_INVALID"):
        build_claim_ledger(
            _panel_manifest(),
            _readiness(),
            _availability_manifest(),
            invalid_summary,
            _source_hashes(),
        )


def test_claim_ledger_markdown_rejects_unsafe_or_malformed_structures() -> None:
    """Human-readable output must fail instead of rendering an unsafe ledger shape."""
    ledger = build_claim_ledger(
        _panel_manifest(),
        _readiness(),
        _availability_manifest(),
        _availability_summary(),
        _source_hashes(),
    )

    unsafe_status = dict(ledger)
    unsafe_status["status"] = "PASS"
    with pytest.raises(ValueError, match="PIT_V22_CLAIM_LEDGER_RENDER_INPUT_INVALID"):
        render_claims_markdown(unsafe_status)

    malformed_claims = dict(ledger)
    malformed_claims["claims"] = ["not-a-claim"]
    with pytest.raises(ValueError, match="PIT_V22_CLAIM_LEDGER_RENDER_INPUT_INVALID"):
        render_claims_markdown(malformed_claims)

    malformed_evidence = dict(ledger)
    claim = dict(ledger["claims"][0])
    claim["evidence"] = "not-a-list"
    malformed_evidence["claims"] = [claim]
    with pytest.raises(ValueError, match="PIT_V22_CLAIM_LEDGER_RENDER_INPUT_INVALID"):
        render_claims_markdown(malformed_evidence)

    malformed_questions = dict(ledger)
    malformed_questions["evaluation_questions"] = ["not-a-question"]
    with pytest.raises(ValueError, match="PIT_V22_CLAIM_LEDGER_RENDER_INPUT_INVALID"):
        render_claims_markdown(malformed_questions)
