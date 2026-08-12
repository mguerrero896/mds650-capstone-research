"""Contract tests for fail-closed provider timing-evidence intake v1."""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Protocol, cast

import pytest

MODULE_NAME = "mds650.provider_timing_semantics_evidence_intake_v1"
ROOT = Path(__file__).resolve().parents[2]
PLAN_PATH = ROOT / "artifacts/preflight/date_level_pit_preflight_plan_v1.json"
CATALOG_PATH = ROOT / "config/date_level_pit_preflight_endpoint_catalog_v2.json"
BUDGET_PATH = ROOT / "artifacts/preflight/date_level_pit_preflight_request_budget_v2.json"


class _EvidenceIntake(Protocol):
    """Public evidence-intake surface used by this contract test."""

    def assess_provider_timing_semantics_evidence_submission_v1(
        self, submission: Mapping[str, object]
    ) -> dict[str, object]:
        """Assess one sanitized evidence submission without changing a network gate."""

    def validate_provider_timing_semantics_evidence_assessment_v1(
        self, assessment: Mapping[str, object]
    ) -> None:
        """Reject an invalid assessment or a changed fail-closed policy literal."""

    def write_provider_timing_semantics_evidence_assessment_v1(
        self, *, submission_path: Path, output_path: Path
    ) -> Path:
        """Write one deterministic assessment without overwriting divergent evidence."""


def _module() -> _EvidenceIntake:
    """Load the real intake implementation expected by the contract tests."""
    assert importlib.util.find_spec(MODULE_NAME) is not None, (
        "provider timing semantics evidence intake v1 is required"
    )
    return cast(_EvidenceIntake, importlib.import_module(MODULE_NAME))


def _sha256(value: str) -> str:
    """Create a stable synthetic source-content digest for a local fixture."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical_sha256(document: Mapping[str, object]) -> str:
    """Calculate the assessment self-hash independently of production code."""
    rendered = json.dumps(
        document,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return "sha256:" + hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def _fmp_submission(*, claim_ids: list[str] | None = None) -> dict[str, object]:
    """Return a complete, sanitized synthetic FMP support-evidence submission."""
    all_claim_ids = [
        "FMP_RESPONSE_TIMESTAMP_TIMEZONE",
        "FMP_BAR_INTERVAL_LABEL",
        "FMP_REST_AVAILABILITY_LATENCY",
        "FMP_HISTORICAL_CORRECTION_BEHAVIOR",
    ]
    selected_claim_ids = all_claim_ids if claim_ids is None else claim_ids
    statements = {
        "FMP_RESPONSE_TIMESTAMP_TIMEZONE": (
            "The source states the timestamp timezone used for US-equity intraday responses."
        ),
        "FMP_BAR_INTERVAL_LABEL": (
            "The source states whether each returned timestamp labels interval start or close."
        ),
        "FMP_REST_AVAILABILITY_LATENCY": (
            "The source states how completed historical one-minute bars become available."
        ),
        "FMP_HISTORICAL_CORRECTION_BEHAVIOR": (
            "The source states whether historical bars can be corrected and how "
            "corrections are marked."
        ),
    }
    return {
        "schema_version": "provider-timing-semantics-evidence-submission-v1.0",
        "provider": "FMP",
        "blocking_status": "FMP_DATE_BOUNDED_ONLY_NO_PIT_CLAIM",
        "source": {
            "source_type": "OFFICIAL_VERSIONED_SPECIFICATION",
            "reference": (
                "https://site.financialmodelingprep.com/developer/docs/stable/intraday-1-min"
            ),
            "source_version": "2026-08-12",
            "captured_at_utc": "2026-08-12T00:00:00Z",
            "source_content_sha256": _sha256("synthetic-fmp-timing-evidence"),
        },
        "claims": [
            {
                "claim_id": claim_id,
                "locator": "section/timing",
                "statement": statements[claim_id],
            }
            for claim_id in selected_claim_ids
        ],
    }


def _uw_support_submission() -> dict[str, object]:
    """Return a complete, sanitized synthetic UW support-case submission."""
    claim_ids = [
        "UW_EXECUTED_AT_SEMANTICS",
        "UW_CREATED_AT_SEMANTICS",
        "UW_CUSTOMER_VISIBLE_AVAILABILITY",
        "UW_ARCHIVE_CORRECTION_BEHAVIOR",
        "UW_STABLE_EVENT_IDENTIFIER",
    ]
    return {
        "schema_version": "provider-timing-semantics-evidence-submission-v1.0",
        "provider": "UNUSUAL_WHALES",
        "blocking_status": "UW_FULL_TAPE_ZIP_ROUTE_DOCUMENTED_EXECUTION_GATED",
        "source": {
            "source_type": "PROVIDER_SUPPORT_CASE_RESPONSE",
            "reference": "UW-12345",
            "source_version": "2026-08-12",
            "captured_at_utc": "2026-08-12T00:00:00Z",
            "source_content_sha256": _sha256("synthetic-uw-support-evidence"),
        },
        "claims": [
            {
                "claim_id": claim_id,
                "locator": "case-response/answer",
                "statement": (
                    "The sanitized provider response explicitly addresses this timing "
                    "claim for independent technical review."
                ),
            }
            for claim_id in claim_ids
        ],
    }


def test_complete_submission_is_reviewable_but_cannot_open_network() -> None:
    """A gate-opening branch would make a complete evidence intake unsafe."""
    intake = _module()

    assessment = intake.assess_provider_timing_semantics_evidence_submission_v1(_fmp_submission())

    assert assessment["status"] == "EVIDENCE_COMPLETE_REQUIRES_INDEPENDENT_TECHNICAL_REVIEW"
    assert assessment["hard_gate_action"] == "NONE"
    assert assessment["network_permitted"] is False
    assert assessment["safe_to_reconcile_existing_results"] == "NO"
    assert assessment["safe_to_open_or_evaluate_oos"] == "NO"
    assert assessment["missing_claim_ids"] == []
    assert assessment["required_claim_ids"] == [
        "FMP_RESPONSE_TIMESTAMP_TIMEZONE",
        "FMP_BAR_INTERVAL_LABEL",
        "FMP_REST_AVAILABILITY_LATENCY",
        "FMP_HISTORICAL_CORRECTION_BEHAVIOR",
    ]
    assert assessment["semantic_self_hash"] == _canonical_sha256(
        {key: value for key, value in assessment.items() if key != "semantic_self_hash"}
    )


def test_missing_required_claim_remains_insufficient_and_fail_closed() -> None:
    """Dropping a material FMP timing claim must not create a review-ready record."""
    intake = _module()
    submission = _fmp_submission(
        claim_ids=[
            "FMP_RESPONSE_TIMESTAMP_TIMEZONE",
            "FMP_BAR_INTERVAL_LABEL",
            "FMP_REST_AVAILABILITY_LATENCY",
        ]
    )

    assessment = intake.assess_provider_timing_semantics_evidence_submission_v1(submission)

    assert assessment["status"] == "EVIDENCE_INSUFFICIENT"
    assert assessment["missing_claim_ids"] == ["FMP_HISTORICAL_CORRECTION_BEHAVIOR"]
    assert assessment["hard_gate_action"] == "NONE"
    assert assessment["network_permitted"] is False


def test_complete_support_case_stays_review_only_for_unusual_whales() -> None:
    """Treating a complete UW support case as a gate closure would be a regression."""
    intake = _module()

    assessment = intake.assess_provider_timing_semantics_evidence_submission_v1(
        _uw_support_submission()
    )

    assert assessment["provider"] == "UNUSUAL_WHALES"
    source = cast(Mapping[str, object], assessment["source"])
    assert source["source_type"] == "PROVIDER_SUPPORT_CASE_RESPONSE"
    assert assessment["status"] == "EVIDENCE_COMPLETE_REQUIRES_INDEPENDENT_TECHNICAL_REVIEW"
    assert assessment["hard_gate_action"] == "NONE"
    assert assessment["network_permitted"] is False


def test_review_ready_evidence_cannot_mutate_the_current_preflight_gate() -> None:
    """A hidden intake-to-transport path would make this target-blind regression fail."""
    from mds650.date_level_pit_preflight_v2 import (
        NetworkGateStatus,
        build_operation_plan,
    )

    intake = _module()
    assessment = intake.assess_provider_timing_semantics_evidence_submission_v1(_fmp_submission())
    operation_plan = build_operation_plan(
        cast(dict[str, object], json.loads(PLAN_PATH.read_text(encoding="utf-8"))),
        cast(dict[str, object], json.loads(CATALOG_PATH.read_text(encoding="utf-8"))),
        cast(dict[str, object], json.loads(BUDGET_PATH.read_text(encoding="utf-8"))),
    )

    assert assessment["status"] == "EVIDENCE_COMPLETE_REQUIRES_INDEPENDENT_TECHNICAL_REVIEW"
    assert assessment["hard_gate_action"] == "NONE"
    assert operation_plan.network_gate.status is NetworkGateStatus.NETWORK_BLOCKED
    assert operation_plan.network_gate.execution_permitted is False
    assert operation_plan.network_gate.attempts_sent == 0


def test_provider_block_mismatch_and_query_reference_are_rejected() -> None:
    """A wrong provider or non-versioned query URL must not enter the evidence ledger."""
    intake = _module()
    mismatched = _fmp_submission()
    mismatched["provider"] = "MASSIVE"
    with pytest.raises(ValueError, match="PIT_EVIDENCE_INTAKE_PROVIDER_BLOCK_MISMATCH"):
        intake.assess_provider_timing_semantics_evidence_submission_v1(mismatched)

    query_reference = _fmp_submission()
    source = cast(dict[str, object], query_reference["source"])
    source["reference"] = (
        "https://site.financialmodelingprep.com/developer/docs/stable/intraday-1-min?view=full"
    )
    with pytest.raises(ValueError, match="PIT_EVIDENCE_INTAKE_SOURCE_REFERENCE_INVALID"):
        intake.assess_provider_timing_semantics_evidence_submission_v1(query_reference)


def test_duplicate_or_secret_like_submission_is_rejected_before_assessment() -> None:
    """Duplicated claims or a credential-like source reference must not be retained."""
    intake = _module()
    duplicate_claims = _fmp_submission()
    claims = cast(list[dict[str, object]], duplicate_claims["claims"])
    claims.append(dict(claims[0]))

    with pytest.raises(ValueError, match="PIT_EVIDENCE_INTAKE_DUPLICATE_CLAIM"):
        intake.assess_provider_timing_semantics_evidence_submission_v1(duplicate_claims)

    secret_like = _fmp_submission()
    source = cast(dict[str, object], secret_like["source"])
    source["reference"] = "https://example.invalid/docs?apiKey=redacted"
    with pytest.raises(ValueError, match="PIT_EVIDENCE_INTAKE_UNSAFE_CONTENT"):
        intake.assess_provider_timing_semantics_evidence_submission_v1(secret_like)


def test_assessment_validator_rejects_post_assessment_gate_mutation() -> None:
    """Changing a review-only result into a network authorization must invalidate it."""
    intake = _module()
    assessment = intake.assess_provider_timing_semantics_evidence_submission_v1(_fmp_submission())
    assessment["network_permitted"] = True

    with pytest.raises(ValueError, match="PIT_EVIDENCE_ASSESSMENT_SELF_HASH_INVALID"):
        intake.validate_provider_timing_semantics_evidence_assessment_v1(assessment)


def test_validator_rejects_claim_status_contradiction_with_recomputed_hash() -> None:
    """A forged complete status with missing claims must fail beyond self-hash validation."""
    intake = _module()
    assessment = intake.assess_provider_timing_semantics_evidence_submission_v1(_fmp_submission())
    assessment["missing_claim_ids"] = ["FMP_HISTORICAL_CORRECTION_BEHAVIOR"]
    assessment["semantic_self_hash"] = _canonical_sha256(
        {key: value for key, value in assessment.items() if key != "semantic_self_hash"}
    )

    with pytest.raises(ValueError, match="PIT_EVIDENCE_ASSESSMENT_CLAIM_STATE_INVALID"):
        intake.validate_provider_timing_semantics_evidence_assessment_v1(assessment)


def test_writer_is_idempotent_and_rejects_divergent_evidence(tmp_path: Path) -> None:
    """Replacing an approved evidence intake with different bytes must fail closed."""
    intake = _module()
    submission_path = tmp_path / "submission.json"
    output_path = tmp_path / "assessment.json"
    submission_path.write_text(json.dumps(_fmp_submission()), encoding="utf-8")

    first = intake.write_provider_timing_semantics_evidence_assessment_v1(
        submission_path=submission_path,
        output_path=output_path,
    )
    expected = output_path.read_bytes()
    assert first == output_path
    assert (
        intake.write_provider_timing_semantics_evidence_assessment_v1(
            submission_path=submission_path,
            output_path=output_path,
        )
        == output_path
    )
    assert output_path.read_bytes() == expected

    changed = _fmp_submission()
    source = cast(dict[str, object], changed["source"])
    source["source_content_sha256"] = _sha256("different-synthetic-fmp-timing-evidence")
    submission_path.write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises(ValueError, match="PIT_EVIDENCE_ASSESSMENT_OUTPUT_CONFLICT"):
        intake.write_provider_timing_semantics_evidence_assessment_v1(
            submission_path=submission_path,
            output_path=output_path,
        )


def test_cli_writes_only_the_review_assessment(tmp_path: Path) -> None:
    """A CLI that emitted a gate authorization instead would fail this local smoke test."""
    submission_path = tmp_path / "submission.json"
    output_path = tmp_path / "assessment.json"
    submission_path.write_text(json.dumps(_fmp_submission()), encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/assess_provider_timing_semantics_evidence_v1.py",
            "--submission",
            str(submission_path),
            "--output",
            str(output_path),
        ],
        check=False,
        cwd=ROOT,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout == "PIT_EVIDENCE_ASSESSMENT_WRITTEN\n"
    assessment = cast(dict[str, object], json.loads(output_path.read_text(encoding="utf-8")))
    assert assessment["hard_gate_action"] == "NONE"
    assert assessment["network_permitted"] is False
