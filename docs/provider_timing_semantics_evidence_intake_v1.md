# Provider Timing Semantics Evidence Intake v1

## Purpose

This local contract records whether a sanitized provider document or support
case response contains every claim required for a **technical review** of one
currently unresolved timing block. It does not decide whether the provider's
statement is true and it cannot change a research gate automatically.

The current historical-availability findings remain separate:

- FMP: `PASS_90_OF_90_SESSIONS`;
- Unusual Whales Full Tape metadata: `PASS_90_OF_90_FILE_METADATA`.

Those findings show historical availability, not verified bar availability,
customer receipt time, or complete point-in-time semantics.

## Current hard blocks

| Provider | Block | Evidence required for review |
| --- | --- | --- |
| FMP | `FMP_DATE_BOUNDED_ONLY_NO_PIT_CLAIM` | timezone, bar-label convention, REST availability latency, historical correction behavior |
| Unusual Whales | `UW_FULL_TAPE_ZIP_ROUTE_DOCUMENTED_EXECUTION_GATED` | `executed_at`, `created_at`, customer-visible availability, archive corrections, stable event identifier |
| Massive | `MASSIVE_CONTRACT_SELECTION_RULE_UNRESOLVED_NO_EXECUTION` | `as_of`, pagination, corrections, deterministic historical contract-selection rule |
| Massive | `MASSIVE_QUOTE_AS_OF_PARAMETERS_DOCUMENTED_LOCAL_SIP_CHECK_REQUIRED` | `.lte` wire format, inclusivity, ordering/tie-break, `sip_timestamp` semantics |

Only either of these source types can be submitted:

1. `OFFICIAL_VERSIONED_SPECIFICATION`: an HTTPS page on the provider's
   documented official domain, with a stated version or capture version.
2. `PROVIDER_SUPPORT_CASE_RESPONSE`: a sanitized provider support response
   identified by a case ID such as `FMP-12345`; the original restricted record
   remains outside the repository.

An HTTP status, endpoint existence, plan description, marketing statement or
oral assertion is not sufficient.

## Safe submission procedure

1. Retain the original provider material in the approved restricted location.
2. Create a sanitized JSON submission following
   [the input schema](../specs/001-pit-options-rv30/contracts/provider-timing-semantics-evidence-submission-v1.schema.json).
   Include only the provider, block, source identity, source-content SHA-256,
   claim IDs, a non-sensitive locator, and concise factual statements.
3. Exclude credentials, authorization headers, query strings, email addresses,
   local paths, raw payloads and personal information.
4. Run the local assessment:

```powershell
uv run --offline python scripts/assess_provider_timing_semantics_evidence_v1.py `
  --submission <sanitized-submission.json> `
  --output <immutable-assessment.json>
```

5. Submit the immutable assessment and the restricted original to independent
   technical review. Only that review, followed by the registered bounded
   probe, can recommend a separate gate amendment.

## Interpretation

`EVIDENCE_COMPLETE_REQUIRES_INDEPENDENT_TECHNICAL_REVIEW` means only that the
required claim identifiers, source identity and hygiene checks are present.
It does **not** mean the source is verified, PIT is validated, acquisition may
begin, a sealed result may be reconciled, or OOS may be opened.

Every assessment permanently retains:

```text
hard_gate_action = NONE
network_permitted = false
safe_to_reconcile_existing_results = NO
safe_to_open_or_evaluate_oos = NO
```

The writer is immutable: replaying identical evidence preserves bytes;
attempting to replace an existing assessment with divergent evidence fails.

## Validation

```powershell
uv run --offline pytest -q tests/unit/test_provider_timing_semantics_evidence_intake_v1.py
uv run --offline ruff check src/mds650/provider_timing_semantics_evidence_intake_v1.py scripts/assess_provider_timing_semantics_evidence_v1.py tests/unit/test_provider_timing_semantics_evidence_intake_v1.py
uv run --offline mypy src/mds650/provider_timing_semantics_evidence_intake_v1.py scripts/assess_provider_timing_semantics_evidence_v1.py
```
