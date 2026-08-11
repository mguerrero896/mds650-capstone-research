# PIT v2.2 Decision Ledger

## Decision 37 — B2 numeric-zero availability remediation

**Status:** accepted for target-blind data engineering; not an evaluation
authorization.

**Evidence:** `artifacts/provider_timing_v22/b2_availability_manifest_v22.json`
and `docs/provider_timing_pit_contract_v22.md`.

**Decision:** retain the canonical B2 matrices unchanged and attach a
row-level, deterministic availability sidecar. A B2 row with delayed raw
execution-window trades is excluded from any future corrected panel rather than
treated as zero activity.

**Reason:** v2.1 established that `b2v2_max_created_at_utc` is provenance, not
an availability indicator. Full Tape partitions with nonempty raw activity can
produce all-zero canonical B2 rows when `created_at` occurs after the registered
cutoff.

**Primary observed scope:** 451 of 77,328 `primary_5m_60s` rows are excluded:
8 on 2025-08-21, 11 on 2025-09-18 and 432 on 2025-10-20. This is a data-timing
classification only; it says nothing about predictive value.

**Permitted claims:**

- The v2.2 mask preserves eligibility under the registered 60-second
  `created_at` operational proxy.
- Existing canonical zeroes in the delayed incidents are not used as evidence
  of no option activity.
- A future panel may be rebuilt target-blind after applying the mask.

**Forbidden claims:**

- `created_at` is true provider publication time or client receipt time.
- The v2.2 correction improved, harmed or validated B2 forecast performance.
- Sealed Phase 6/OOS results have been reconciled.

**Consequences:**

```text
B2_AVAILABILITY_SIDECAR=PASS_WITH_EXCLUSIONS
CORRECTED_PIT_PANEL_PREPARATION=PASS_MASK_READY_REQUIRES_NEW_TARGET_BLIND_PANEL_BUILD
SAFE_TO_RECONCILE_EXISTING_RESULTS=NO
SEALED_RESULT_RECONCILIATION=BLOCKED
OOS_PAYLOAD_READ=0
```

**Reversal condition:** a canonical input hash mismatch, a new raw/canonical
count mismatch, or independent evidence that invalidates the recorded Full Tape
timestamp interpretation.

## Decision 38 — v2.2 common predictor input panel

**Status:** accepted for target-blind engineering only; result reconciliation
and model evaluation remain prohibited.

**Evidence:**
`artifacts/target_blind_v22/target_blind_common_predictor_manifest_v22.json`,
`docs/target_blind_common_predictor_panel_v22.md`, and the D-resident Parquet
outputs named in that manifest.

**Decision:** build a new B0/B1Q/B2 predictor panel from immutable acquired
sources, apply the v2.2 primary availability mask before B2 completeness, and
omit all outcome-like fields from the output schema.

**Observed input result:** 77,328 origin rows were preserved. B0 is
predictor-complete for 70,668 rows, B1a for 70,556 and B2/common for 62,266.
All 451 primary delayed-trade sidecar exclusions remain separately represented,
including rows whose first overall exclusion is an earlier B0/B1 failure.

**Permitted claims:**

- A successor study has a deterministic, hash-bound, target-free common input
  panel.
- Delayed B2 source records cannot re-enter the B2 predictor subset as zeros.
- B1 nested features preserve the implication B1c => B1b => B1a.

**Forbidden claims:**

- Any result, positive edge, null result, predictive ranking or causal
  interpretation.
- That Massive SIP time proves client receipt time.
- That UW `created_at` proves publication or receipt time.
- Reconciliation of pre-v2.2 sealed output.

**Consequences:**

```text
TARGET_BLIND_COMMON_PREDICTOR_PANEL=PASS
SAFE_TO_RECONCILE_EXISTING_RESULTS=NO
SAFE_TO_OPEN_OR_EVALUATE_OOS=NO
MODEL_FIT_PERFORMED=NO
```

## Decision 39 — successor confirmation pre-method-freeze seal

**Status:** sealed, target-blind and not authorized for OOS.

**Evidence:**
`artifacts/target_blind_v22/next_confirmation_preregistration_v2.json` and
`specs/001-pit-options-rv30/contracts/target-blind-confirmation-preregistration-v22.schema.json`.

**Decision:** bind the corrected common-panel output hash, all source and
builder hashes, information-set fields and the fixed FMP/Massive/UW timing
claim boundary before a successor method freeze. The seal forbids model fitting,
tuning, metric computation, result reconciliation and OOS access.

**Consequence:** future work can freeze a method against this exact data-input
identity, but it cannot select a model or make any B1/B2 performance claim
until the separate method-freeze and OOS-access gates have passed.
