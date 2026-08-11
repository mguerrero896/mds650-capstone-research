# PIT Contract v2.1 Amendment Design

**Goal:** Resolve only the known provider-timing evidence gaps in the RV30
research pipeline without reading outcomes or altering any canonical research
artifact.

## Scope and hard boundaries

- Inspect only official public documentation, acquired Full Tape partitions,
  canonical B2 feature matrices, target-free B1 provenance, and Massive cache
  files already stored under `D:\MDS650\phase6`.
- Never read RV30, QLIKE, predictions, model-output, or outcome columns.
- Never train a model, download data, call a provider-data endpoint, wait for
  a session, or mutate a canonical artifact.
- Official documentation retrieval is restricted to a fixed HTTPS allow-list;
  it has no credentials and persists only a compact source record plus a body
  SHA-256, not the document body.
- Do not call a Full Tape record delay a provider outage, publication time, or
  client receipt time unless the provider explicitly establishes that fact.

## Problem decomposition

1. **FMP:** an official FAQ documents intraday time zones at the exchange-region
   level. It does not resolve exact IANA/DST implementation, bar start/close
   labels, or completed-bar latency.
2. **Unusual Whales:** Kafka documentation defines `executed_at` and
   `created_at`; Full Tape REST/OpenAPI documents the ZIP endpoint but does not
   attach those timestamp semantics to persisted ZIP fields. Field-name and UTC
   concordance can be observed locally but must remain separate from the Kafka
   statement.
3. **B2:** provider-record delay can turn a data-availability incident into an
   all-zero canonical feature row. A zero must not be relabelled as confirmed
   absence of activity when no independent availability indicator exists.
4. **Massive:** an origin-minus-delay sensitivity must reselect from the raw
   quote sequence, not filter a quote selected at the original origin.

## Selected architecture

`src/mds650/provider_timing_v21.py` is an offline, pure audit module. It has
four independent functions:

- timestamp-unit-safe Arrow conversion;
- session-asset Full Tape delay and source-availability diagnostics;
- canonical B2 coding traceability (zero, missing, excluded, or absent
  indicator);
- memory-bounded Massive raw-cache re-selection and BSM IV recalculation.

`scripts/archive_provider_timing_v21_sources.py` accesses only a fixed official
documentation allow-list and writes source records. `scripts/audit_provider_timing_v21.py`
creates compact target-free CSV/JSON sidecars. `scripts/render_provider_timing_v21_docs.py`
renders the amendment, claim matrix, appendix, and handoff from those sidecars.

## Fixed target-blind decision rules

- Regular-session diagnostics use the local `America/New_York` interval
  `[09:30, 16:00]`; they are diagnostic only and do not claim provider calendar
  semantics.
- A record-creation delay is reported at `>300` seconds; an extreme delay is
  reported at `>3,600` seconds. These thresholds classify data quality, not
  trading behaviour.
- A B2 canonical all-zero row paired with an observed source delay state is
  `ZERO_CODING_POTENTIALLY_CONFOUNDED`, never `TRUE_NO_ACTIVITY`.
- B2 availability is **not closed** until a future consumer applies the
  generated sidecar exclusion/availability state before any scientific use.
- Massive cutoffs are exactly `origin`, `origin - 60 seconds`, and
  `origin - 300 seconds`; selected quote must satisfy `sip_timestamp <= cutoff`.
  IV inputs are recalculated from the target-free attempt row and new midpoint.

## Acceptance criteria

1. FMP, UW Full Tape, UW OpenAPI, and UW Kafka source records each have the
   exact URL, retrieval outcome, SHA-256, content class, claim boundary, and no
   stored raw document body.
2. Every source Full Tape session-asset in scope receives an explicit source
   state. The four named dates are shown with temporal diagnosis and no invented
   provider-cause assertion.
3. Every canonical B2 matrix/session-asset has a sidecar coding state. The
   sidecar differentiates zero, missing values, exclusion, and absent
   availability indicator.
4. Massive sensitivity proves raw quote reselection per cutoff, validates cache
   identity, rejects future quotes, and reports coverage, age, and IV results.
5. Tests prove Arrow timestamp unit handling, zero-confounding treatment, cache
   selection semantics, official-source hashing, deterministic rendering, and
   path/secret hygiene.
6. Canonical hashes are unchanged. The amendment remains explicitly
   conditional if provider data availability can still be confused with zero
   activity.

## Risks deliberately retained

- The data can reveal record-creation delay but cannot isolate an upstream
  queue, API export, or other provider-internal root cause.
- FMP's regional-timezone FAQ is not proof of an exact IANA implementation.
- Massive SIP time proves source ordering, not historical REST delivery time.
- No result in this amendment supports an economic or predictive claim.
