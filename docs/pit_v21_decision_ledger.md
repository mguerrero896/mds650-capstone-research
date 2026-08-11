# Provider Timing PIT v2.1 — Decision Ledger

**Scope:** target-blind, offline audit of acquired provider inputs only.
No RV30, prediction, QLIKE, model output, holdout outcome, provider-data request,
or new download was read or produced by this amendment.

## Final v2.1 gate state

| Gate | Status | Evidence | Consequence |
|---|---|---|---|
| Forecast-origin session bounds | `PASS` | 77,328 origins; zero before open, zero after close; 432 early-close origins across 12 asset-date groups | The target-free origin sidecar respects the XNYS calendar under the audited contract. |
| Massive B1Q quote re-selection | `PASS` | 2,308,176 attempts, 32,238 cache identities, zero identity failures, zero future quotes and non-increasing quote existence across 0/60/300-second cutoffs | Cached B1Q source-time sensitivity is technically traceable; this does not itself establish historical REST delivery latency. |
| B2 operational availability | `FAIL_ZERO_ACTIVITY_NOT_DISAMBIGUATED` | 61 of 5,400 canonical variant/session/asset traceability rows are zero-coded while the source incident sidecar reports record-creation delay | A B2 zero cannot yet be interpreted as confirmed absence of eligible activity. |
| Existing-result reconciliation | `NO` | `B2_ACTIVITY_AVAILABILITY_GATE_NOT_CLOSED` | Do not reopen, re-read, reconcile or report sealed predictive results as a v2.1 conclusion. |

## Specific Massive handling

For early-close cache requests that extended to nominal 16:00 New York, the
audit recorded 329 overextended-but-in-session cache envelopes and 31 envelopes
containing post-close SIP rows. The latter rows were excluded before each as-of
join and were never eligible for quote selection. This is an explicit audit
state, not a change to the original cache or a silent repair.

## B2 limitation and next permissible work

The evidence supports only `FULL_TAPE_CREATED_AT_DELAY_OBSERVED`. It does not
identify a provider root cause, publication time, customer receipt time, or
actual trading intent. A permitted next step must either apply a pre-specified
availability/incident sidecar before use of B2 rows, obtain written historical
field-semantics evidence, or validate a separately licensed prospective
receipt-logger. It must then repeat the target-blind gate before any model or
QLIKE action.

## Decision

`PIT_V21=CONDITIONAL_NOT_CLOSED`
`SAFE_TO_RECONCILE_EXISTING_RESULTS=NO`

The v2.1 amendment improves B1Q cache validation and confirms origin session
bounds, but it does not authorize a predictive claim for B2.
