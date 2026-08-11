"""Evidence-bound, target-blind claims and limitations for MDS650 PIT v2.2.

This module is intentionally unable to accept predictions, RV30, QLIKE or any
out-of-sample payload. It records only the claims that current provider-timing,
availability and target-blind input artefacts support after the v2.2 correction.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from typing import Any

_SHA256 = re.compile(r"^[a-f0-9]{64}$")
_SOURCE_KEYS = (
    "panel_manifest",
    "confirmation_readiness",
    "availability_manifest",
    "availability_summary",
    "pit_contract_v21",
    "claim_matrix_v21",
)


def canonical_sha256(value: Mapping[str, Any]) -> str:
    """Return the stable SHA-256 digest for one JSON-compatible mapping.

    Parameters
    ----------
    value:
        Mapping to encode with sorted keys and compact JSON separators.

    Returns
    -------
    str
        Lowercase 64-character SHA-256 digest.

    Notes
    -----
    The function never serializes filesystem paths supplied by a caller; path
    strings in the ledger are fixed logical repository-relative identifiers.
    """
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def build_claim_ledger(
    panel_manifest: Mapping[str, Any],
    readiness: Mapping[str, Any],
    availability_manifest: Mapping[str, Any],
    availability_summary: Mapping[str, Any],
    source_hashes: Mapping[str, str],
) -> dict[str, Any]:
    """Build a self-hashing PIT v2.2 claim ledger without evaluation data.

    Parameters
    ----------
    panel_manifest:
        Target-blind v2.2 common-predictor manifest.
    readiness:
        Confirmation-readiness v1 report.
    availability_manifest, availability_summary:
        Target-blind B2 availability-sidecar evidence.
    source_hashes:
        SHA-256 values keyed by the fixed logical evidence identifiers.

    Returns
    -------
    dict[str, Any]
        Self-hashing ledger of supported, proxy-only, conservative-rule and
        not-evaluated claims. It never contains a predictive metric or result.

    Raises
    ------
    ValueError
        If any input opens reconciliation/OOS access, fails target-blind
        identity validation, lacks the primary availability totals, or has an
        invalid source hash.

    Notes
    -----
    The resulting ledger marks the three scientific questions as not evaluated
    after the PIT correction. It must be replaced by a separately authorised
    evaluation ledger only after a successor method freeze and OOS-access gate.
    """
    _validate_panel_manifest(panel_manifest)
    _validate_readiness(readiness)
    _validate_availability_manifest(availability_manifest)
    _validate_source_hashes(source_hashes)
    primary = _primary_availability_totals(availability_summary)

    panel_output = _mapping(panel_manifest, "output", "PIT_V22_CLAIM_LEDGER_PANEL_INVALID")
    panel_summary = _mapping(panel_manifest, "summary", "PIT_V22_CLAIM_LEDGER_PANEL_INVALID")
    row_count = _positive_int(panel_output, "row_count", "PIT_V22_CLAIM_LEDGER_PANEL_INVALID")
    common_count = _positive_int(
        panel_output,
        "common_complete_row_count",
        "PIT_V22_CLAIM_LEDGER_PANEL_INVALID",
    )
    asset_count = _positive_int(panel_summary, "asset_count", "PIT_V22_CLAIM_LEDGER_PANEL_INVALID")
    claims = _claims(
        row_count=row_count,
        common_count=common_count,
        asset_count=asset_count,
        primary=primary,
        source_hashes=source_hashes,
    )
    ledger: dict[str, Any] = {
        "schema_version": "pit-v22-claim-ledger-v1.0",
        "status": "PASS_TARGET_BLIND_CLAIMS_NO_EVALUATION",
        "scope": "target_blind_pit_and_readiness_claims_only",
        "no_target_or_metric_payload_read": True,
        "model_fit_performed": False,
        "safe_to_reconcile_existing_results": "NO",
        "safe_to_open_or_evaluate_oos": "NO",
        "source_hashes": {key: source_hashes[key] for key in _SOURCE_KEYS},
        "claims": claims,
        "evaluation_questions": [
            {
                "question_id": "Q1_B1_VERSUS_B0",
                "status": "NOT_EVALUATED_AFTER_PIT_CORRECTION",
                "reason": "A corrected successor evaluation has not been authorised or run.",
            },
            {
                "question_id": "Q2_B2_INCREMENTAL_OVER_B1",
                "status": "NOT_EVALUATED_AFTER_PIT_CORRECTION",
                "reason": "Pre-v2.2 sealed results are not eligible for reconciliation.",
            },
            {
                "question_id": "Q3_STABILITY_BY_ASSET_TIME_REGIME_AND_LATENCY",
                "status": "NOT_EVALUATED_AFTER_PIT_CORRECTION",
                "reason": "No corrected model/evaluation payload has been read.",
            },
        ],
        "next_required_gate": "SUCCESSOR_METHOD_FREEZE_AND_EXPLICIT_OOS_ACCESS_AUTHORIZATION",
    }
    ledger["claim_ledger_sha256"] = canonical_sha256(ledger)
    return ledger


def render_claims_markdown(ledger: Mapping[str, Any]) -> str:
    """Render a compact, evidence-bound human-readable claim ledger.

    Parameters
    ----------
    ledger:
        Validated output from :func:`build_claim_ledger`.

    Returns
    -------
    str
        Markdown that names every claim, status, evidence location and
        limitation without universal-edge or profitability language.

    Raises
    ------
    ValueError
        If the supplied ledger is not the expected target-blind, no-evaluation
        format.
    """
    if ledger.get("status") != "PASS_TARGET_BLIND_CLAIMS_NO_EVALUATION":
        raise ValueError("PIT_V22_CLAIM_LEDGER_RENDER_INPUT_INVALID")
    claims = ledger.get("claims")
    questions = ledger.get("evaluation_questions")
    if not isinstance(claims, list) or not isinstance(questions, list):
        raise ValueError("PIT_V22_CLAIM_LEDGER_RENDER_INPUT_INVALID")
    lines = [
        "# MDS650 PIT v2.2 — Claims and Limitations Ledger",
        "",
        "## Scope",
        "",
        "This ledger is target-blind. It contains no RV30, forecast, loss, QLIKE,",
        "model-fit or sealed out-of-sample payload. It records what the corrected",
        "PIT input evidence supports and what remains untested.",
        "",
        "```text",
        "SAFE_TO_RECONCILE_EXISTING_RESULTS=NO",
        "SAFE_TO_OPEN_OR_EVALUATE_OOS=NO",
        "MODEL_FIT_PERFORMED=NO",
        "```",
        "",
        "## Claims",
        "",
        "| ID | Status | Claim | Limitation | Evidence |",
        "| --- | --- | --- | --- | --- |",
    ]
    for claim in claims:
        if not isinstance(claim, Mapping):
            raise ValueError("PIT_V22_CLAIM_LEDGER_RENDER_INPUT_INVALID")
        evidence = claim.get("evidence")
        if not isinstance(evidence, list):
            raise ValueError("PIT_V22_CLAIM_LEDGER_RENDER_INPUT_INVALID")
        evidence_text = "; ".join(
            str(item.get("path", "")) for item in evidence if isinstance(item, Mapping)
        )
        lines.append(
            "| {claim_id} | {status} | {claim_text} | {limitation} | {evidence} |".format(
                claim_id=_markdown_cell(claim.get("claim_id")),
                status=_markdown_cell(claim.get("status")),
                claim_text=_markdown_cell(claim.get("claim_text")),
                limitation=_markdown_cell(claim.get("limitation")),
                evidence=_markdown_cell(evidence_text),
            )
        )
    lines.extend(
        [
            "",
            "## Scientific questions not yet evaluated",
            "",
            "| Question | Status | Reason |",
            "| --- | --- | --- |",
        ]
    )
    for question in questions:
        if not isinstance(question, Mapping):
            raise ValueError("PIT_V22_CLAIM_LEDGER_RENDER_INPUT_INVALID")
        lines.append(
            "| {question_id} | {status} | {reason} |".format(
                question_id=_markdown_cell(question.get("question_id")),
                status=_markdown_cell(question.get("status")),
                reason=_markdown_cell(question.get("reason")),
            )
        )
    lines.extend(
        [
            "",
            "## Required next gate",
            "",
            "A successor method freeze must bind the corrected panel, temporal splits,",
            "estimand, bootstrap, multiplicity policy, development-only MDE and a zero-OOS",
            "access ledger before a separate explicit authorization can permit evaluation.",
            "",
        ]
    )
    return "\n".join(lines)


def _claims(
    *,
    row_count: int,
    common_count: int,
    asset_count: int,
    primary: Mapping[str, int],
    source_hashes: Mapping[str, str],
) -> list[dict[str, Any]]:
    """Create fixed claims whose status cannot depend on an evaluation result."""
    panel_evidence = _evidence(source_hashes, "panel_manifest", "confirmation_readiness")
    timing_evidence = _evidence(source_hashes, "pit_contract_v21", "claim_matrix_v21")
    availability_evidence = _evidence(
        source_hashes,
        "availability_manifest",
        "availability_summary",
        "panel_manifest",
    )
    return [
        {
            "claim_id": "PITV22-C001",
            "status": "SUPPORTED_TARGET_BLIND",
            "claim_text": (
                f"The corrected B0/B1Q/B2 predictor construction preserved {row_count} "
                f"forecast origins and {common_count} common-complete origins across "
                f"{asset_count} outcome assets."
            ),
            "limitation": "These are input-coverage counts, not predictive metrics.",
            "allowed_presentation_context": "data_engineering_and_pit_readiness",
            "evidence": panel_evidence,
        },
        {
            "claim_id": "PITV22-C002",
            "status": "PROXY_ONLY",
            "claim_text": (
                "Unusual Whales created_at is retained only as an operational availability "
                "proxy at the registered cutoff."
            ),
            "limitation": "It is not provider-proven publication time or client receipt time.",
            "allowed_presentation_context": "timing_assumption",
            "evidence": timing_evidence,
        },
        {
            "claim_id": "PITV22-C003",
            "status": "STUDY_CONSERVATIVE_RULE",
            "claim_text": (
                "FMP plus one minute (with plus two minutes sensitivity) and Massive SIP "
                "as-of selection remain conservative study rules."
            ),
            "limitation": "They do not prove provider or client-side message receipt latency.",
            "allowed_presentation_context": "timing_assumption",
            "evidence": timing_evidence,
        },
        {
            "claim_id": "PITV22-C004",
            "status": "SUPPORTED_TARGET_BLIND",
            "claim_text": (
                "The primary B2 availability sidecar marks "
                f"{primary['excluded_row_count']} of {primary['row_count']} rows as excluded "
                "rather than treating delayed source records as zero activity."
            ),
            "limitation": (
                "The correction changes eligibility only; it does not validate performance."
            ),
            "allowed_presentation_context": "data_quality_and_pit_readiness",
            "evidence": availability_evidence,
        },
        {
            "claim_id": "PITV22-C005",
            "status": "BLOCKED_RECONCILIATION",
            "claim_text": "Pre-v2.2 sealed results are not eligible for reconciliation.",
            "limitation": "No prior sign, metric or ranking may be carried into a corrected claim.",
            "allowed_presentation_context": "methodological_limitation",
            "evidence": panel_evidence + availability_evidence,
        },
        {
            "claim_id": "PITV22-C006",
            "status": "NOT_EVALUATED_AFTER_PIT_CORRECTION",
            "claim_text": "Whether B1 improves B0 for RV30 is not yet evaluated after PIT v2.2.",
            "limitation": "A successor method freeze and authorized evaluation are required.",
            "allowed_presentation_context": "research_question_status",
            "evidence": panel_evidence + availability_evidence,
        },
        {
            "claim_id": "PITV22-C007",
            "status": "NOT_EVALUATED_AFTER_PIT_CORRECTION",
            "claim_text": (
                "Whether B2 adds incremental value over B1 is not yet evaluated after PIT v2.2."
            ),
            "limitation": "The target-blind ledger contains no loss or model output.",
            "allowed_presentation_context": "research_question_status",
            "evidence": panel_evidence + availability_evidence,
        },
        {
            "claim_id": "PITV22-C008",
            "status": "NOT_EVALUATED_AFTER_PIT_CORRECTION",
            "claim_text": (
                "Stability by asset, session segment, volatility regime and latency assumption "
                "is not yet evaluated after PIT v2.2."
            ),
            "limitation": "No corrected forecasts, contrasts or stability payloads were read.",
            "allowed_presentation_context": "research_question_status",
            "evidence": panel_evidence + timing_evidence,
        },
    ]


def _validate_panel_manifest(panel_manifest: Mapping[str, Any]) -> None:
    """Fail closed unless the panel remains target-blind and unreconciled."""
    required = {
        "schema_version": "target-blind-common-predictor-manifest-v2.2",
        "status": "PASS_TARGET_BLIND_INPUTS_RECONCILIATION_REMAINS_BLOCKED",
        "no_target_or_metric_payload_read": True,
        "model_fit_performed": False,
        "safe_to_reconcile_existing_results": "NO",
    }
    if any(panel_manifest.get(key) != value for key, value in required.items()):
        raise ValueError("PIT_V22_CLAIM_LEDGER_PANEL_MANIFEST_INVALID")


def _validate_readiness(readiness: Mapping[str, Any]) -> None:
    """Fail closed unless readiness itself remains before acquisition/OOS access."""
    required = {
        "schema_version": "confirmation-readiness-v1.0",
        "status": "PASS_READY_FOR_CONFIRMATION_ACQUISITION_NOT_REQUESTED",
        "no_target_or_metric_payload_read": True,
        "model_fit_performed": False,
        "safe_to_reconcile_existing_results": "NO",
        "safe_to_open_or_evaluate_oos": "NO",
        "ready_for_confirmation": "YES",
        "safe_to_acquire_new_sample": "NO",
    }
    if any(readiness.get(key) != value for key, value in required.items()):
        raise ValueError("PIT_V22_CLAIM_LEDGER_READINESS_INVALID")
    expected_hash = readiness.get("readiness_sha256")
    unsigned = {key: value for key, value in readiness.items() if key != "readiness_sha256"}
    if not isinstance(expected_hash, str) or expected_hash != canonical_sha256(unsigned):
        raise ValueError("PIT_V22_CLAIM_LEDGER_READINESS_INVALID")


def _validate_availability_manifest(availability_manifest: Mapping[str, Any]) -> None:
    """Require a target-blind availability sidecar with reconciliation blocked."""
    required = {
        "schema_version": "2.2",
        "generation_mode": "deterministic_target_blind_rebuild",
        "model_or_metric_payload_read": False,
        "oos_payload_read": False,
        "safe_to_reconcile_existing_results": "NO",
    }
    if any(availability_manifest.get(key) != value for key, value in required.items()):
        raise ValueError("PIT_V22_CLAIM_LEDGER_AVAILABILITY_MANIFEST_INVALID")


def _validate_source_hashes(source_hashes: Mapping[str, str]) -> None:
    """Require every fixed logical source to carry a complete SHA-256 value."""
    if set(source_hashes) != set(_SOURCE_KEYS):
        raise ValueError("PIT_V22_CLAIM_LEDGER_SOURCE_HASHES_INVALID")
    if any(
        not isinstance(value, str) or not _SHA256.fullmatch(value)
        for value in source_hashes.values()
    ):
        raise ValueError("PIT_V22_CLAIM_LEDGER_SOURCE_HASHES_INVALID")


def _primary_availability_totals(summary: Mapping[str, Any]) -> Mapping[str, int]:
    """Return validated primary-variant counts from target-free availability evidence."""
    if summary.get("schema_version") != "2.2":
        raise ValueError("PIT_V22_CLAIM_LEDGER_AVAILABILITY_SUMMARY_INVALID")
    totals = summary.get("variant_totals")
    if not isinstance(totals, list):
        raise ValueError("PIT_V22_CLAIM_LEDGER_AVAILABILITY_SUMMARY_INVALID")
    primary = next(
        (
            value
            for value in totals
            if isinstance(value, Mapping) and value.get("canonical_variant") == "primary_5m_60s"
        ),
        None,
    )
    if not isinstance(primary, Mapping):
        raise ValueError("PIT_V22_CLAIM_LEDGER_AVAILABILITY_SUMMARY_INVALID")
    row_count = _positive_int(
        primary,
        "row_count",
        "PIT_V22_CLAIM_LEDGER_AVAILABILITY_SUMMARY_INVALID",
    )
    eligible_count = _nonnegative_int(
        primary,
        "eligible_row_count",
        "PIT_V22_CLAIM_LEDGER_AVAILABILITY_SUMMARY_INVALID",
    )
    excluded_count = _nonnegative_int(
        primary,
        "excluded_row_count",
        "PIT_V22_CLAIM_LEDGER_AVAILABILITY_SUMMARY_INVALID",
    )
    if eligible_count + excluded_count != row_count:
        raise ValueError("PIT_V22_CLAIM_LEDGER_AVAILABILITY_SUMMARY_INVALID")
    return {
        "row_count": row_count,
        "eligible_row_count": eligible_count,
        "excluded_row_count": excluded_count,
    }


def _evidence(source_hashes: Mapping[str, str], *keys: str) -> list[dict[str, str]]:
    """Return logical relative evidence identifiers paired with validated hashes."""
    logical_paths = {
        "panel_manifest": (
            "artifacts/target_blind_v22/target_blind_common_predictor_manifest_v22.json"
        ),
        "confirmation_readiness": "artifacts/target_blind_v22/confirmation_readiness_v1.json",
        "availability_manifest": "artifacts/provider_timing_v22/b2_availability_manifest_v22.json",
        "availability_summary": "artifacts/provider_timing_v22/b2_availability_summary_v22.json",
        "pit_contract_v21": "docs/provider_timing_pit_contract_v21.md",
        "claim_matrix_v21": "docs/provider_timing_claim_matrix_v21.md",
    }
    return [{"path": logical_paths[key], "sha256": source_hashes[key]} for key in keys]


def _mapping(payload: Mapping[str, Any], key: str, error_code: str) -> Mapping[str, Any]:
    """Return one nested mapping or fail with the caller's evidence code."""
    value = payload.get(key)
    if not isinstance(value, Mapping):
        raise ValueError(error_code)
    return value


def _positive_int(payload: Mapping[str, Any], key: str, error_code: str) -> int:
    """Return a strictly positive integer or fail with the caller's evidence code."""
    value = payload.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(error_code)
    return value


def _nonnegative_int(payload: Mapping[str, Any], key: str, error_code: str) -> int:
    """Return a nonnegative integer or fail with the caller's evidence code."""
    value = payload.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(error_code)
    return value


def _markdown_cell(value: object) -> str:
    """Render one scalar safely inside a Markdown table cell."""
    return str(value).replace("|", "\\|").replace("\n", " ")
