# Phase 8 one-read evaluation protocol (v1)

Created 2026-08-17 under decision 55. Everything below is prepared; the ONLY missing
input is the owner's one-shot authorization, which cannot be pre-granted.

## Current automation (running unattended)

| Piece | State |
|---|---|
| Blind collector `MDS650_Phase8A_BlindCollector` | Enabled, daily 18:00, one session per run |
| Watchdog `MDS650_Phase8A_CollectionWatch` | Enabled, daily 20:00; alerts (screen popup + `D:\MDS650\logs\PHASE8_ALERT.txt`) if collection falls behind, if the seal breaks, and when 30/30 completes |
| Store | `D:\MDS650\phase8_holdout` (junction from the phase8a worktree); repro gate PASS after relocation |
| Progress | 20/30 as of 2026-08-17; sessions 2026-08-17..28 arrive daily; 30/30 expected 2026-08-29 ~18:05 |
| Seal | `holdout_reads = 0`; method freeze `87c818be…`; calendar hash `82139e72…` |

The machine must simply be powered on once per evening (both tasks have
StartWhenAvailable, so a late boot still runs them).

## On 2026-08-29 (or when the COMPLETE alert fires)

Run everything from `C:\Users\mguer\Dev\MDS650-Capstone-phase8a-recovery`:

1. **Verify completion and seal** (read-only):
   ```bash
   uv run python scripts/phase8_collect.py --status
   uv run python scripts/phase8_repro_gate.py
   ```
   Require: `completed_sessions=30`, `holdout_reads=0`, gate `status=PASS`.
2. **Owner one-shot authorization** — a written record (this file's Decision record
   below, or a signed note in `docs/`) stating: date, the frozen method hash
   `87c818be…`, and the sentence "I authorize exactly one scientific read of the
   Phase 8 holdout under the frozen method." Without this record, STOP.
3. **Single read** — run the frozen evaluator exactly once:
   ```bash
   uv run python scripts/phase8_one_shot_evaluator.py
   ```
   (Its dry-run path is already exercised daily by the repro gate:
   `evaluator_dry_run_status=PASS`.) Do not re-run on error without recording the
   incident first; the access ledger counts every read.
4. **Report under decision 53**: prospective-null-first hierarchy, both nested
   contrasts for both model families, total `B0→B2` beside the increment, no bare
   "confirmed". Append the outcome to `docs/results_reconciliation_v2.md` as campaign
   C7 (the second genuinely prospective test after C2).
5. **Publish**: commit results + updated reconciliation, run
   `bash scripts/publish_mirror.sh`, refresh the release bundle.

## Interpretation guardrails (pre-stated, before any outcome is seen)

- Phase 8 sessions (2026-07-20..08-28) postdate every protocol freeze involved, and
  collection occurred within days of each session close — this is the only campaign
  besides C2 immune to the retrospective-availability objection (R-023).
- n = 30 session clusters: report the achieved MDE next to any null.
- If the Gamma-specific B2 effect fails to appear here, the decaying-effect pattern in
  `docs/results_reconciliation_v2.md` §"Honest headline" point 3 is confirmed on
  prospective data and the thesis leads with the null. If it appears under both model
  families above MDE, that — and only that — supports a global claim.

## Pre-read interpretation amendment (recorded 2026-08-17, before any read)

Interpretation-layer addition under Gate 4 (`docs/gate4_prospective_design_v1.md`,
`artifacts/gate4_decay_power/results.json`). The frozen method hash `87c818be…` and its
decision rules are untouched; the following is ADDITIONAL reporting, fixed before the
30/30 read:

1. **Equivalence (TOST) bound:** δ_eq = 0.005035 (the lineage's frozen targeted B2 MDE).
   If the 90% CI of the primary Δ_QLIKE lies entirely within (−δ_eq, +δ_eq), the result
   is reported as *affirmative evidence that any B2 effect is smaller than the smallest
   registered meaningful size* — not as "inconclusive".
2. **Ex-ante predictions (stated now):** decay-trend extrapolation at the window
   midpoint gives +0.0053 [−0.0091, +0.0197] for the Gamma-family effect and
   +0.0051 [−0.0009, +0.0111] for the tree-family effect (Gate 4 artifact). The
   tree-family proxy for the frozen primary (hist-gradient-boosting) has achieved
   MDE ≈ 0.0048 at n = 30 — the equivalence test at δ_eq is adequately powered for the
   primary model. For Gamma-sized effects the achieved MDE is ≈ 0.0179, so:
3. **Precommitment:** a null/equivalent outcome is interpreted as prospective
   confirmation of the registered decay pattern (reconciliation §"Honest headline"
   point 3), not as an invitation to further retrospective campaigns.

## Contingencies (pre-stated, 2026-08-18 — before the read)

1. **Missed collection evening:** the calendar is frozen but completion slips
   day-for-day; the read waits for a verified `completed_sessions=30` +
   `phase8_repro_gate.py` PASS. Slippage is logged, never compressed.
2. **Repro gate FAIL on read day:** do not read. Record the failure verbatim as an
   incident, fix the environment (never the frozen method), re-run the gate; the read
   happens only on PASS. If the failure implicates the store's integrity, the incident
   report decides between repair-with-evidence and declaring the cohort compromised —
   a compromised cohort is reported as such, not read.
3. **Evaluator error mid-read:** stop; the access ledger already counts the attempt.
   Record the incident with the exact error before any second invocation; a second
   invocation is only allowed if the first demonstrably produced no scientific output
   (ledger + absence of the result artifact), and both attempts are reported.
4. **Read-day session overlap:** the 30th session completes at 2026-08-29 ≈ 18:05
   local; the read is scheduled AFTER the post-collection verification, never the same
   process. If the final session is deficient, rule 1 applies.
5. **Owner unavailable on 2026-08-29:** nothing fires automatically — the read requires
   the written one-shot authorization below. The seal keeps; a late read is a
   non-event scientifically (sessions are already sealed at capture time).
6. **Machine loss before the read:** the holdout store is on a single disk by owner
   decision (backup declined 2026-08-18); this is a stated accepted risk.

## Decision record (one-shot authorization)

| Date | Authorized by | Method hash confirmed | Read executed | Result artifact |
|---|---|---|---|---|
| — | — | — | — | — |
