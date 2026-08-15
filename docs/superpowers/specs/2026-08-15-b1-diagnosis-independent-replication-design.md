# B1 Diagnosis and Sign-Agnostic Temporal Replication

## Authority and objective

**Status:** `OWNER_APPROVED_IN_CHAT`

**Approval date:** 2026-08-15

Diagnose why the ordinary option-state benchmark B1v3a did not improve B0, then execute one
independent, preregistered temporal replication that determines whether the B2 improvement
reproduces. Positive, null and negative outcomes are equally valid. No choice may be optimized for
the result sign.

## Evidence boundary

- The sealed B1v3 result and its one-read ledger remain immutable.
- B1 diagnosis may use previously exposed development outcomes and already-opened aggregate
  results only.
- The new 30-session replication block is target-blind until all predictor, method and access
  gates are frozen.
- No row-level target, prediction, QLIKE or residual from the replication block may enter
  diagnosis, acquisition, feature construction or method selection.

## Frozen calendar

The rolling training set is the 60 XNYS sessions from 2024-09-16 through 2024-12-09. The
replication set is the next 30 XNYS sessions, 2024-12-10 through 2025-01-24. The lists are
generated from the local XNYS calendar and will be bound by ordered SHA-256 identities. Training
data may be reused only from previously exposed evidence. Replication dates must be absent from
every prior result ledger.

This exact block is a recorded replication-only amendment to the default study window. Every
candidate date in the previous window already appears in Phase 5/6 exposure ledgers; using it
would not be an independent replication. The amended block is the earliest unexposed block after
the sealed B1v3 evidence cutoff. It remains provisional until authenticated FMP/UW/Massive
preflight passes, and no failed date may be silently replaced.

## Frozen information sets and inference

- B0: existing point-in-time underlying and market controls.
- B1v3a: B0 plus the three frozen near-30-day ordinary option-state predictors.
- B2: B1v3a plus the nine frozen trade-derived activity predictors.
- Confirmatory model: Gamma GLM under the existing chronological training protocol.
- Robustness challenger: the existing fixed LightGBM configuration.
- Primary loss: QLIKE; MAE and RMSE are descriptive.
- Inference: 10,000 paired whole-XNYS-session bootstrap draws with all assets retained together.
- Multiplicity: Holm correction across the two global contrasts.
- Materiality: training-only MDE, frozen before replication access.

The primary contrasts retain the definitions `QLIKE(B0)-QLIKE(B1v3a)` and
`QLIKE(B1v3a)-QLIKE(B2)`. A positive value favours the expanded information set.

## B1 diagnostic families

The diagnostic must report all predeclared families rather than selecting a narrative:

1. source/coverage and missingness;
2. quote freshness, spreads and IV inversion failures;
3. ATM interpolation/fallback and exact-lag availability;
4. feature scale, dispersion, outliers and temporal drift;
5. feature correlation and numerical conditioning;
6. pooled-versus-asset heterogeneity in development-only coefficients and loss deltas;
7. model-specification sensitivity already registered before replication.

These analyses diagnose mechanisms; they do not prove causality and cannot rewrite the primary
information sets.

## Acquisition and storage

Heavy evidence remains under `D:/MDS650`. Existing hashes are reused when identical. New provider
requests are exact-date and resumable. Every batch requires present secrets without value output,
licensed provider access, a source-bound request ledger and projected minimum free space of at
least 80 GiB. No full-market OPRA backfill is permitted.

## Stop conditions

Stop without opening replication targets if any date was previously exposed, a provider/PIT
contract fails, B1v3a coverage fails, common origins drift, a future predictor appears, a hash or
schema changes, deterministic replay fails, storage breaches the 80-GiB floor, or preregistration
is incomplete. After the one-read token is consumed, no refit, retry or replacement block is
allowed.

## Claim boundary

The final result may support model-independent replication, Gamma-only replication, no
replication or an invalid run. It cannot establish causal informed trading, live profitability,
transaction-cost-adjusted edge or production readiness.
