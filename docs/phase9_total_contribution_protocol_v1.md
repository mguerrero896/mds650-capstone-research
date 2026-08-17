# Phase 9 — prospective total-contribution protocol (v1, FROZEN 2026-08-18)

Authorized by decision 58. Frozen before any Phase 9 data exist; the SHA-256 of this
file at freeze is recorded in `artifacts/phase9/protocol_freeze.json` and any change
after that hash invalidates the protocol.

## Question and estimand

Does option-market information, **in total**, improve out-of-sample RV30 forecasts on
sessions that postdate this freeze? Primary estimand: daily-equal-weight
Δ_QLIKE(TOTAL) = mean_t[ QLIKE(B0HAR) − QLIKE(B2) ] on identical origins, where the
ladder is the Gate-12 design: B0HAR (B0 + target-blind daily/weekly HAR components) →
+B1 (option state) → +B2 (+trade activity). Secondary: the B0HAR→B1 and B1→B2 stages.

## Design (fixed)

- Universe, target, origins, PIT rules: identical to the frozen Phase 8 method
  (six outcome assets; RV30 from 31 closes; five-minute origins; FMP label+same
  convention as measured in Gate 5.1; UW `created_at` ≤ origin − 60 s with the
  decision-57 measured-latency caveats; Massive quotes `sip_timestamp` ≤ origin).
- Sessions: the first **60 XNYS sessions strictly after 2026-08-18** for which the
  collector captures a complete session (gaps roll the window forward; no session may
  be added retroactively).
- Families (both required, genuinely independent): (a) log-OLS on the B0HAR ladder
  (smooth-linear); (b) LightGBM with the fixed hyperparameters of Gate 11/12 (tree).
  No tuning, no model selection, fold-local median imputation, lognormal smearing.
- Evaluation: expanding walk-forward with 24-session warm-up and 12-session test
  blocks; studentized inference (cluster t, Newey-West, wild cluster bootstrap, 9,999
  reps, seed 650); one read, access-ledger controlled, after session 60 completes.

## Decision rules (fixed before any data)

- **GLOBAL_POSITIVE** iff the primary Δ_QLIKE(TOTAL) is positive with wild p < 0.05 in
  **both** families and both point estimates exceed the frozen MDE **0.005**.
- **EQUIVALENT_NULL** iff the 90% CI of the primary lies within (−0.005, +0.005) in
  both families (TOST at δ = 0.005).
- Anything else: **MIXED**, reported as such. No subgroup selection; all signs retained.

## Power, stated honestly (from the Gate-11 daily SDs)

| SD scenario | log-OLS 80%-power MDE at n=60 | LightGBM |
|---|---|---|
| Recent (2026 dev era) | ≈ 0.015 | ≈ 0.013 |
| P6 era (2025H2–2026Q1) | ≈ 0.007 | ≈ 0.011 |

The observed 2025H2 totals (+0.010/+0.021) are detectable under the P6-era SDs and
borderline under recent-era SDs. **Precommitment:** if the read lands underpowered-null
(neither GLOBAL_POSITIVE nor EQUIVALENT_NULL), it is reported as consistent with the
measured decay and no retrospective salvage analysis is run.

## Collection (activation required)

Nightly post-close pulls per session: FMP 1-minute bars (6 assets), UW full-tape day
archive, Massive ATM quote sweep at the five-minute origins (rate-limited ≈ 94 min at
5 req/min). Implementation clones the UW-latency collector pattern (heartbeat, watchdog,
post-session verification, crash-safe storage under `MDS650_EXTERNAL_ROOT/phase9/`,
access counter starting at zero). **Collection is inert until the owner activates the
scheduled task; the 60-session clock starts at the first captured session.** Disk note:
≈ 1–2 GB/session of raw tape; ≥ 120 GB free required at activation.

## Reporting

Under decision 53: after the prospective C2 and Phase 8 results, never before them;
one read; outcome appended to `docs/results_reconciliation_v2.md` as campaign C8.
