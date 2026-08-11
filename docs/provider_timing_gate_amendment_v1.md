# Provider Timing Gate Amendment v1

## Decision

This amendment replaces a single absolute timing NO-GO with evidence-scoped decisions. `UNVERIFIED` means an evidence boundary, not automatically false and not automatically a hard blocker for work already frozen under explicit timing assumptions.

| Gate | Status | Consequence |
|---|---|---|
| `EXISTING_CANONICAL_EVIDENCE` | `VALID_UNDER_REGISTERED_TIMING_ASSUMPTIONS` | Existing registered evidence remains interpretable. |
| `EXISTING_SCIENTIFIC_RECONCILIATION` | `CONDITIONAL_GO_NOW` | Reconcile existing results now; do not rerun them. |
| `NEW_HISTORICAL_SAMPLE` | `GO_AFTER_DATE_LEVEL_PIT_PREFLIGHT` | Run a date-level PIT preflight before acquisition. |
| `NEW_PROSPECTIVE_SAMPLE` | `GO_AFTER_RECEIPT_LOGGER_VALIDATED` | Validate the receipt logger before a live capture. |
| `UNIVERSAL_PROVIDER_LATENCY_CLAIM` | `NOT_SUPPORTED` | Do not make a universal latency assertion. |

## Scope protection

This amendment does not alter, re-read or recompute canonical RV30/QLIKE results, features, model fits, evidence hashes or conclusions. It authorizes only the scientific reconciliation of existing canonical evidence under its registered timing assumptions. A future historical sample still needs a date-level PIT preflight; a future prospective sample still needs a validated receipt logger.

The pending prospective probe must not block reconciliation of existing QLIKE, MAE, RMSE, calibration, MDE or already-frozen results.
