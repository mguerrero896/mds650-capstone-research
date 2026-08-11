# Provider-Timing PIT Contract v2.2

## Scope and boundary

Version 2.2 is an offline, target-blind correction to the interpretation of
canonical B2 numeric zeroes. It reads only already acquired Full Tape
timestamps, canonical B2 raw-activity matrices, forecast-origin identifiers,
and v2.1 traceability hashes. It does not read RV30, forecasts, predictions,
QLIKE, model artefacts, or sealed OOS payloads; it makes no provider request.

The v2.2 output is an eligibility sidecar, not a rewritten B2 matrix. The
canonical matrices, their hashes, and all historical result artefacts remain
immutable.

## Root cause and correction

The prior B2 builder joined eligible trade aggregates to the full origin grid
and filled absent aggregate values with numeric zero. That is valid only when
the raw source and its availability predicate have been independently
established. In delayed-source groups, a canonical zero can instead mean that
raw trades occurred in the execution window but their `created_at` exceeded the
registered cutoff.

For a variant with execution window `W` and operational delay `L`, a Full Tape
trade is eligible at forecast origin `t` only when:

```text
executed_at in [t - L - W, t - L)
and created_at <= t - L
```

`created_at` remains an operational availability proxy, not a provider-proven
publication or client-receipt timestamp. Therefore v2.2 permits only the claim
that a row is usable *under the registered proxy*; it does not claim live or
provider-confirmed availability.

## Row-level sidecar contract

The D-resident Parquet sidecar has one row per
`(canonical_variant, origin_id)`, sorted deterministically. It contains only
target-free fields:

- canonical variant, execution-window and delay;
- origin identifier, asset, session date and UTC forecast origin;
- canonical numeric state (`ZERO`, `NONZERO` or `INVALID`);
- raw-window, eligible, delayed and missing-`created_at` event counts when
  recomputation is required;
- source temporal state, row status and boolean eligibility.

The builder verifies every input matrix against the exact v2.1 SHA-256 trace
for its variant/date/asset group. It fails if an origin identity changes, a
trace row is absent or duplicate, a matrix hash drifts, a required schema is
absent, a sidecar key repeats, or a delayed raw candidate remains eligible as a
canonical zero.

## Status semantics

| Row status | Eligibility | Meaning |
|---|---:|---|
| `PIT_USABLE_ELIGIBLE_ACTIVITY` | yes | Nonzero canonical activity in a group without a v2.1 delay incident. |
| `PIT_USABLE_ZERO_NO_DELAY_INCIDENT` | yes | Numeric zero in a group without a v2.1 delay incident. It is not a claim of provider publication time. |
| `PIT_USABLE_ELIGIBLE_ACTIVITY_DELAY_CONTEXT` | yes | Raw eligible count exactly matches canonical trade count despite a group-level delay incident. |
| `PIT_EXCLUDED_DELAYED_RAW_WINDOW_TRADES` | no | Canonical numeric zero while one or more raw execution-window trades have `created_at` after cutoff. |
| `PIT_EXCLUDED_SOURCE_DELAY_CONTEXT_ZERO` | no | Numeric zero within a group affected by record-creation delay but with no raw candidate for that row; kept conservative rather than promoted to an absence claim. |
| `PIT_EXCLUDED_CANONICAL_RAW_COUNT_MISMATCH` | no | Canonical count and recomputed eligible raw count disagree. |
| `PIT_EXCLUDED_MISSING_CREATED_AT` | no | A candidate has no usable availability-proxy timestamp. |
| `PIT_EXCLUDED_SOURCE_UNAVAILABLE_OR_SCHEMA_INVALID` | no | Raw evidence needed for a confounded group cannot be safely recomputed. |

## Observed v2.2 result

The v2.2 builder produced 386,640 rows: five variants times 77,328 canonical
forecast origins. Under the primary `primary_5m_60s` proxy, 76,877 rows are
eligible and 451 are excluded. The excluded primary rows occur only on
2025-08-21 (8), 2025-09-18 (11), and 2025-10-20 (432). The known 2025-10-20
incident is therefore isolated as delayed raw activity, not accepted as a true
zero-activity session.

Across all five variants, 384,392 rows are eligible and 2,248 rows are
explicitly excluded. No canonical/raw-count mismatches were observed. These
counts are availability diagnostics; they are not predictive results.

## Decision boundary

`B2_AVAILABILITY_SIDECAR = PASS_WITH_EXCLUSIONS` and
`CORRECTED_PIT_PANEL_PREPARATION = PASS_MASK_READY_REQUIRES_NEW_TARGET_BLIND_PANEL_BUILD`.
The result does **not** authorize reconciliation of sealed result artefacts:
`SAFE_TO_RECONCILE_EXISTING_RESULTS = NO`.

Before any future evaluation, a new target-blind common B0/B1/B2 panel must
apply the immutable sidecar mask, receive its own hash and pass the registered
no-leakage and provenance gates. Any claim that `created_at` represents true
publication/receipt remains prohibited unless independent provider evidence or
a prospective receipt logger establishes it.

## Evidence

- `artifacts/provider_timing_v22/b2_availability_manifest_v22.json`
- `artifacts/provider_timing_v22/b2_availability_summary_v22.json`
- `artifacts/provider_timing_v22/b2_availability_by_variant_v22.csv`
- `artifacts/provider_timing_v22/b2_availability_by_incident_v22.csv`
- `D:\MDS650\phase6\derived\provider_timing_v22\b2_row_availability_v22.parquet`
- `docs/provider_timing_pit_contract_v21.md`
