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
