# PIT Contract v2 Design

**Goal:** Close an evidence-scoped point-in-time contract for FMP, Unusual Whales, and Massive without acquiring data or reading research outcomes.

## Scope and non-negotiable boundaries

- Inputs are official provider documentation and already-acquired sanitized or commercial caches only.
- The work must not read RV30, QLIKE, predictions, model outputs, or outcome columns.
- The work must not train models, invoke a provider-data endpoint, wait for a market session, or alter canonical research artifacts.
- Each statement is labelled `PROVIDER_DOCUMENTED`, `PAYLOAD_OBSERVED`, `STUDY_ASSUMPTION`, or `UNVERIFIED`.
- A historical source timestamp is never relabelled as provider publication time or client receipt time unless the official provider document says so.

## Approaches considered

1. **Document-only amendment.** Smallest diff, but cannot verify Massive cache ordering, sequence fields, quote-age sensitivity, or future-quote absence.
2. **Offline contract audit over cached evidence.** Read official docs plus existing FMP/UW/Massive inputs, emit a claim matrix and deterministic audits. This verifies data facts while preserving strict provider-claim boundaries. **Selected.**
3. **New provider probes or prospective capture.** Could measure receipt behavior but violates the current no-acquisition/no-market-wait constraint. Deferred and retained as a separately gated future action.

## Architecture

`src/mds650/provider_timing.py` remains the pure, testable domain module. A new offline v2 audit consumes only logical cache roots and compact fixtures. It produces sanitized summary artifacts; raw payloads remain on `D:`. A renderer creates human-readable contract, academic appendix, claim matrix, and single handoff from those artifacts.

FMP has three independent facts: documented one-minute endpoint scope, observed timestamp labels, and a conservative availability rule of `timestamp + 60 seconds` with `+120 seconds` sensitivity. Unusual Whales has three independent timestamps: execution, record creation, and future client receipt. `created_at - executed_at` is named `record_creation_lag_seconds` and is never publication latency. Massive uses the documented SIP source time and sequence number; `sip_timestamp <= cutoff` and quote-age filters are study selection rules, not proof of API delivery latency.

## Acceptance criteria

1. Official source records contain URL, retrieval date, content fingerprint, concise quoted claim, and the exact non-claim boundary.
2. UW retention at 60, 120, and 300 seconds is calculated from already acquired Full Tape and is monotonic.
3. The UW extreme tail is counted and summarized separately from percentiles.
4. Massive v4 cache audit verifies required fields, timestamp unit, duplicate `(contract, sip_timestamp, sequence_number)` keys, ordering facts, query-bound violations, future quote selection invariant, and 60/300-second quote-age sensitivity on a generic intraday cutoff grid.
5. All historical claims and all study rules are visibly distinct in a machine-readable claims matrix.
6. Gates separately address existing evidence, a new historical sample, and prospective capture.
7. Canonical artifact hashes are unchanged; quality gates and deterministic rerun pass.

## Risks and deliberate limits

- FMP documentation calls the one-minute endpoint real-time but does not quantify completed-bar publication latency, label semantics, or response timezone. No stronger provider claim is allowed.
- UW documents record creation, not delivery to the client. The historical metric can demonstrate record-field lag but never client receipt.
- Massive documents SIP receipt from exchange, not when a REST response became accessible to this client. The SIP cutoff protects event-time ordering but cannot establish customer-availability latency.
- Cached Massive data can verify source timestamps and retrieval-bound compliance. It cannot recreate a past customer-side REST receipt timestamp.
