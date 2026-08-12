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

## Decision 40 — confirmation-readiness operational gate

**Status:** accepted as an offline target-blind readiness check; not an
acquisition, method-freeze or OOS authorization.

**Evidence:**
`artifacts/target_blind_v22/confirmation_readiness_v1.json`,
`specs/001-pit-options-rv30/contracts/confirmation-readiness-v1.schema.json`
and `docs/confirmation_readiness_v1.md`.

**Decision:** require a self-hashing gate to verify the full target-blind panel
hash, B2 availability-sidecar hash, preregistration self-hash, exact
common-complete subset, target-free coverage and all fixed FMP/Massive/UW
timing labels. For a newly requested acquisition, require a separate exact
session plan, provider/PIT preflight, conservative storage peak, secret-name
presence and an explicit non-secret cost-authorization reference.

**Reason:** the prior v2.2 prerequisite list described the intended controls
but did not emit one machine-readable state separating a sound target-blind
input identity from operational permission to acquire more data.

**Permitted claims:**

- The corrected target-blind input identity is ready to enter a separately
  authorised confirmation method freeze when the readiness hash passes.
- A future acquisition cannot silently proceed if its operational inputs are
  absent or the projected free-space floor falls below 80 GiB.
- Passing operational inputs alone remains insufficient: an exact session plan
  and date-level provider/PIT preflight are separately required.

**Forbidden claims:**

- The readiness gate demonstrates predictive value, an economic edge or a
  provider entitlement.
- A named environment variable proves a credential value is valid.
- An operational acquisition preflight authorises OOS access, model fit or
  reconciliation of sealed pre-v2.2 results.

**Consequences:**

```text
READY_FOR_CONFIRMATION=YES
SAFE_TO_ACQUIRE_NEW_SAMPLE=NO_UNTIL_EXACT_ACQUISITION_PREFLIGHT_PASSES
SAFE_TO_RECONCILE_EXISTING_RESULTS=NO
SAFE_TO_OPEN_OR_EVALUATE_OOS=NO
MODEL_FIT_PERFORMED=NO
```

## Decision 41 — claims-and-limitations ledger

**Status:** accepted as a target-blind presentation boundary; not an
evaluation, method-freeze or OOS authorization.

**Evidence:**
`artifacts/target_blind_v22/pit_v22_claim_ledger_v1.json`,
`specs/001-pit-options-rv30/contracts/pit-v22-claim-ledger-v1.schema.json`
and `docs/pit_v22_claims_and_limitations.md`.

**Decision:** bind exactly eight pre-registered PIT and input-readiness claims
to their source hashes, with fixed claim identifiers and a self-hash. The
ledger must label the B1-versus-B0, B2-versus-B1 and stability questions as
`NOT_EVALUATED_AFTER_PIT_CORRECTION` until a successor method freeze and a
separate OOS-access authorization are complete.

**Reason:** input coverage, operational readiness and conservative timing rules
are useful evidence, but none establishes predictive improvement. A fixed,
machine-readable presentation boundary prevents those categories from being
silently relabelled as a positive or negative research result.

**Permitted claims:**

- The corrected B0/B1Q/B2 input panel and its availability exclusions have
  target-blind evidence.
- UW `created_at` remains proxy-only, while FMP `+1/+2` minutes and Massive
  SIP selection remain explicitly conservative research rules.
- Existing pre-v2.2 results cannot be reconciled with the corrected panel.

**Forbidden claims:**

- That the project has established a predictive or economic edge.
- That a data-availability count proves an effect size, a QLIKE result or
  cross-asset stability.
- Any interpretation of sealed pre-v2.2 OOS material.

**Consequences:**

```text
PIT_V22_CLAIM_LEDGER_STATUS=PASS_TARGET_BLIND_CLAIMS_NO_EVALUATION
SAFE_TO_RECONCILE_EXISTING_RESULTS=NO
SAFE_TO_OPEN_OR_EVALUATE_OOS=NO
MODEL_FIT_PERFORMED=NO
```

## Decision 42 — official provider-documentation timing boundary

**Status:** accepted as target-blind documentation evidence; no timing-semantics
upgrade and no evaluation authorization.

**Evidence:**
`artifacts/provider_timing_v21/official_docs_audit_v1_20260812.json`,
`specs/001-pit-options-rv30/contracts/provider-timing-official-docs-audit-v1.schema.json`
and `docs/provider_timing_official_docs_audit_v1_20260812.md`.

**Decision:** record the positive scope of the official documentation without
filling omissions by inference. Massive documents SIP quote-event time and
nanosecond precision, but not historical customer delivery latency. FMP
documents a timestamp-formatted OHLCV field, but not its timezone, bar boundary
or availability. Unusual Whales labels Flow Alerts `created_at` as a general
UTC timestamp, but does not document it as historical publication or receipt.

**Historical-source clarification:** this is not a finding that FMP or Unusual
Whales lack history. The registered 90-session probes establish FMP session
availability and UW Full Tape file-metadata availability; row-level PIT timing
remains a separate question.

**Consequence:** retain the registered FMP `+1/+2` conservative rules, UW
`created_at` operational proxy, Massive technical as-of condition, and both
fail-closed gates. The audit adds a source-bound limitation record; it does not
authorize reconciliation, model fitting, QLIKE, or OOS access.

```text
PROVIDER_DOCUMENTATION_LIMITATIONS_AUDIT=PASS
SAFE_TO_RECONCILE_EXISTING_RESULTS=NO
SAFE_TO_OPEN_OR_EVALUATE_OOS=NO
MODEL_FIT_PERFORMED=NO
```

## Decision 43 — source-bound readiness v2 prepares method freeze only

**Status:** accepted target-blind operational readiness; no scientific outcome
or timing-semantics upgrade.

**Evidence:**
`artifacts/target_blind_v23_sourcebound_20260812/confirmation_readiness_v2.json`,
`docs/confirmation_readiness_v2_sourcebound_20260812.md` and
`specs/001-pit-options-rv30/contracts/confirmation-readiness-v2.schema.json`.

**Decision:** the v2.3 panel, complete subset, B2 availability sidecar and v3
preregistration are internally source-bound. This supports preparation of a
successor method freeze but does not reconcile any sealed legacy result.

**Consequence:** FMP and UW historical source availability is recognized
separately from the unresolved PIT timestamp semantics. Keep all three safety
gates closed until a future method freeze and the independently required timing
evidence are complete.

```text
READY_FOR_SUCCESSOR_METHOD_FREEZE=YES
SAFE_TO_RECONCILE_EXISTING_RESULTS=NO
SAFE_TO_OPEN_OR_EVALUATE_OOS=NO
SAFE_TO_ACQUIRE_NEW_SAMPLE=NO
MODEL_FIT_PERFORMED=NO
```

## Decision 44 — primary B0/B1a/B2 comparison contract

**Status:** accepted as an additive, target-blind method-freeze clarification;
it does not modify the immutable v4 preregistration or authorize evaluation.

**Evidence:**
`artifacts/target_blind_v25_comparison_contract_20260812/target_blind_comparison_contract_v1.json`
(file SHA-256 `82f455c3c5c7d72701d2525c1965aaa434d59bb24ded52002e0590d1cd5a91da`,
semantic SHA-256 `ed936c545292a3954405cf2c0d6545377320e930edd548b235a4c66d0f9dc050`),
`specs/001-pit-options-rv30/contracts/target-blind-comparison-contract-v1.schema.json`,
and `docs/target_blind_comparison_contract_v1.md`.

**Decision:** preserve the parent v4 feature contracts and make the nested
primary ladder explicit:

| Information set | Fixed composition | Role |
| --- | --- | --- |
| B0 | Parent v4 `B0` controls | Underlying/market benchmark |
| B1a | B0 plus parent v4 `B1a_addition` | Primary ordinary-options-state challenger |
| B2 | B1a plus the exact nine parent v4 `B2_addition` fields | Primary trade-activity challenger |

The two and only two primary estimands are the daily means of
`QLIKE(B0) - QLIKE(B1a)` and `QLIKE(B1a) - QLIKE(B2)`. Positive direction is
defined prospectively as favoring the challenger; no positive, negative or
null value has been inspected or asserted. B1b and B1c remain pre-specified
robustness analyses and cannot replace B1a after observing coverage, RV30,
QLIKE, a sign or a predictive outcome.

**Reason:** a list of additive feature families alone does not prevent a later
comparison switch. The separate self-hashing contract binds the exact ladder,
directional estimands, Gamma/LightGBM method context, daily-cluster bootstrap,
Holm adjustment and anti-selection controls before any target or metric access.

**Permitted claims:**

- The primary scientific questions have an exact, nested and source-bound
  future comparison definition.
- The declared comparison direction is a convention for interpreting a future
  lower QLIKE, not evidence of an edge.

**Forbidden claims:**

- That B1a improves B0, B2 improves B1a, or either effect is statistically
  significant or stable.
- That B1b or B1c may be promoted to primary after an observed result.
- That the comparison contract opens OOS, reconciliation, model fitting,
  metric evaluation, new acquisition or prospective capture.

**Consequences:**

```text
PRIMARY_COMPARISON_CONTRACT=SEALED_TARGET_BLIND
PRIMARY_B1_LEVEL=B1a
SAFE_TO_RECONCILE_EXISTING_RESULTS=NO
SAFE_TO_OPEN_OR_EVALUATE_OOS=NO
MODEL_FIT_PERFORMED=NO
```

## Decision 45 — executable fail-closed date-level PIT status

**Status:** accepted as a target-blind operational-status record. It confirms
that current compatibility planning is controlled, not that a provider call,
acquisition or scientific evaluation is authorized.

**Evidence:**
`artifacts/preflight/date_level_pit_preflight_status_v2_current.json`
(file SHA-256 `945908ba718bea18fe85f3cb4297495d08e7e2b3158619c1bc4ae5b543642683`,
semantic SHA-256
`sha256:f7089333dba0dd65d5a901f8fdfb64983fc5d976afd856594426b6918de5943d`),
`specs/001-pit-options-rv30/contracts/date-level-pit-preflight-status-v2.schema.json`,
and `docs/date_level_pit_preflight_status_v2.md`.

**Decision:** turn the already source-bound calendar plan, documentation-based
endpoint catalog and bounded request budget into a deterministic current-status
artifact. It preserves the distinction between historical source availability
and PIT validity:

- FMP historical sessions: `PASS_90_OF_90_SESSIONS`.
- UW Full Tape file metadata: `PASS_90_OF_90_FILE_METADATA`.
- PIT execution: `FAILED_CLOSED`, with `network_attempts_sent=0`.

The artifact binds 119 initial logical operations and an inclusive 343-attempt
future cap, while requiring the following unresolved evidence statuses before
any network transport: FMP exact session/PIT semantics, UW documented Full Tape
execution semantics, Massive contract-selection rule and Massive quote-as-of
parameter semantics.

**Reason:** historical files and date-bounded endpoints are necessary but not
sufficient to prove what was available at a forecast origin. An executable
zero-network record prevents that distinction from being relaxed by credentials,
storage capacity or a generic authorization flag.

**Permitted claims:**

- Current historical-source availability is documented separately from the
  unresolved PIT timing semantics.
- The next preflight state can be reproduced from exact source hashes without
  a provider call.

**Forbidden claims:**

- That FMP or UW history proves publication/receipt timing or opens B2.
- That a current `FAILED_CLOSED` record approves acquisition, reconciliation,
  OOS access, model fitting, QLIKE or an edge claim.

**Consequences:**

```text
DATE_LEVEL_PIT_PREFLIGHT_V2=FAILED_CLOSED
NETWORK_ATTEMPTS_SENT=0
SAFE_TO_RECONCILE_EXISTING_RESULTS=NO
SAFE_TO_OPEN_OR_EVALUATE_OOS=NO
READY_FOR_CONFIRMATION=YES_WITH_HARD_PIT_BLOCKS
```
