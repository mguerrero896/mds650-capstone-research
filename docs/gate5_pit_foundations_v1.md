# Gate 5 — Foundational PIT assumptions, end to end (v1)

Started 2026-08-17. Code: `scripts/run_gate5_bar_reconciliation.py` (5.1),
`scripts/uw_latency_{collector,verify,reconcile}.py` + `scripts/register_uw_latency_tasks.ps1`
(5.2/5.3). Artifacts: `artifacts/gate5_pit/` and `MDS650_EXTERNAL_ROOT/uw_latency/`.
Zero model reads; zero sealed-cohort access; decision-52 compliant.

## 5.1 — FMP bar semantics (A001): MEASURED, resolved

Cross-provider reconciliation of the same one-minute bars from FMP and the
Polygon-compatible Massive aggregates endpoint (new bounded method
`MassiveProvider.stock_minute_aggregates`), over ten stratified sessions spanning the
C5 (2024), C4 (mid-2025), C6 and 2026 development windows, six outcome assets:

| Alignment | Median of per-cell median relative close differences |
|---|---|
| **Identical labels (same_label)** | **0.0 (exact equality)** |
| FMP shifted +1 minute | 3.42e−04 |

Both providers label one-minute bars identically and agree on closes exactly.
Combined with Gate 3 (reconstructed 30-minute RV matches the frozen `b0_rv_30m_lag`
with log-correlation 1.0000 under shift 0), registered assumption A001 is now an
empirically pinned fact: the pipeline's convention is correct, with an independent
second source across all evaluation eras. A standing tripwire
(`tests/test_gate5_bar_reconciliation_contract.py`) fails the suite if a future
re-acquisition breaks this agreement.

## 5.2/5.3 — UW `created_at` latency campaign: RUNNING (unattended)

Live measurement infrastructure, all verified this session:

| Piece | State |
|---|---|
| Collector `MDS650_UW_LatencyCollector` (daily 23:20 local ≙ pre-open NY) | Ready; XNYS-calendar aware; 60 s flow-alert polling for 6 assets; crash-safe JSONL appends; heartbeat per cycle |
| Watchdog `MDS650_UW_LatencyWatchdog` (every 30 min through the session) | Ready; restarts the collector when the heartbeat is > 5 min stale |
| Post-check `MDS650_UW_LatencyPostCheck` (daily 06:20) | Ready; per-asset capture report; **alert path proven** (popup + `logs/UW_LATENCY_ALERT.txt`) |
| Re-download `MDS650_UW_LatencyReconcile` (daily 07:00) | Ready; processes sessions ≥ 7 days old exactly once; historical full-tape download + fingerprint join |
| Dry run | Executed end-to-end 2026-08-17: 1,200 real records captured over 3 cycles, storage/heartbeat/verify all green; dry-run data quarantined to `uw_latency/dryrun_20260817` |
| Credential check | Fails loudly to the alert file when `UNUSUAL_WHALES_API_KEY` is absent |

Outputs per session, ~7 days later: receipt−`created_at` latency distribution per
asset × NY hour, backfill **upper bound** (tape rows never observed live — the
flow-alerts channel is a filtered subset, so unmatched rows bound backfill from above;
stated in the artifact), and the revision rate among matched rows.

**Gate-close condition:** evidence of the first real captured session
(expected from the 2026-08-17 NY session; capture report lands 06:20 local
2026-08-18). First reconciliation report expected on or after 2026-08-24. Gates 6–9
proceed in parallel per the backlog.

## What this retires (and what it does not)

- A001 (bar semantics): retired — measured, two providers, three eras.
- A002 (`created_at` as availability): the five registered timing sensitivities only
  delay the cutoff; this campaign measures the latency distribution and bounds
  backfill/revision — after ≥5 sessions reconcile, `VALID_UNDER_REGISTERED_TIMING_
  ASSUMPTIONS` can be upgraded to a measured statement for the live era. Historical
  tapes (2024/2025) remain assumption-based; that residual is permanent and will be
  stated in the threats-to-validity matrix.
