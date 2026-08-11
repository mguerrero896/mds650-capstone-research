# B2 Availability Remediation — Design

## Objective

Preserve the immutable canonical B2 matrices while producing a target-blind,
row-level availability sidecar. The sidecar must prevent a zero produced by
late Full Tape records from being treated as no option activity.

## Root cause

`aggregate_b2_activity` constructs the full forecast-origin grid and fills
unmatched aggregates with numeric zero. That is mechanically appropriate only
after source availability is known. The canonical matrices contain no such
availability indicator. On 2025-10-20, all 432 primary B2 origins have zero
features even though each has raw trades in its execution window; those trades
were created after the origin-minus-60-second cutoff.

## Scope and hard boundaries

- Read only acquired Full Tape partitions, target-free origin metadata,
  canonical B2 raw-activity matrices, and the v2.1 incident sidecar.
- Do not change a canonical matrix, its hash, any outcome, prediction, QLIKE
  result, model, feature definition, asset universe, or sealed OOS artifact.
- Do not issue a provider-data request or download a new file.
- Keep the row-level Parquet sidecar on `D:`; commit only compact sanitized
  summaries and manifest hashes.

## Data contract

One row per `(canonical_variant, session_date, asset, origin_id)` has:

- canonical numeric coding and immutable canonical-file SHA-256;
- source temporal state and exact availability status;
- optional target-free raw-window counts for a confounded group;
- `eligible_for_corrected_pit_panel` and an explicit exclusion reason;
- provenance that distinguishes the study's `created_at` operational proxy
  from provider-confirmed publication or client-receipt time.

Statuses are mutually exclusive. A numeric zero with raw execution-window
trades whose `created_at` is after the cutoff is
`PIT_EXCLUDED_DELAYED_RAW_WINDOW_TRADES`, never no activity.

## Decision rules

1. Non-confounded source groups preserve canonical nonzero rows and clean zeros
   under the registered operational proxy.
2. For a confounded group, raw-window diagnostics are recomputed per origin and
   variant without opening targets.
3. A zero with any delayed raw-window trade is excluded.
4. A zero in a delayed-source context without a raw-window trade is also
   excluded conservatively; the sidecar must not manufacture completeness.
5. A nonzero canonical count must match the eligible raw trade count whenever
   a raw diagnostic is run; mismatch fails closed.
6. The sidecar may permit construction of a *new corrected* target-blind panel
   under the registered proxy. It cannot make
   `SAFE_TO_RECONCILE_EXISTING_RESULTS=YES`, because sealed results did not
   consume the mask and cannot be reopened in this objective.

## Outputs

- `D:\MDS650\phase6\derived\provider_timing_v22\b2_row_availability_v22.parquet`
  (licensed-data-derived, not committed);
- `artifacts/provider_timing_v22/b2_availability_manifest_v22.json`;
- `artifacts/provider_timing_v22/b2_availability_summary_v22.json`;
- `artifacts/provider_timing_v22/b2_availability_by_variant_v22.csv`;
- `artifacts/provider_timing_v22/b2_availability_by_incident_v22.csv`;
- updated PIT decision ledger and confirmation-readiness protocol.

## Acceptance criteria

1. Every canonical B2 origin gets exactly one deterministic row-level status.
2. 2025-10-20 primary has 432 delayed-raw-trade exclusions and zero usable
   primary rows for its six canonical assets.
3. Canonical B2 hashes remain unchanged; output carries their source hashes.
4. No usable row has a canonical zero and delayed raw-window trade count above
   zero.
5. All primary cutoffs, session counts, early closes, and status totals are
   deterministic and target-free.
6. Unit tests cover delayed zero, clean zero, mismatch, missing source,
   deterministic ordering, schema, path hygiene, and source-hash integrity.
7. Existing-result reconciliation remains explicitly blocked until a separate,
   authorized corrected evaluation can consume this sidecar.
