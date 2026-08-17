# Results reconciliation across all evaluation campaigns (v2)

Compiled 2026-08-17 from the frozen artifacts named in each row. This is the single
cross-campaign view required by decision 53. Positive `ΔQLIKE = QLIKE(base) − QLIKE(expanded)`
favors the expanded information set. "Null known" marks whether the prospective Phase 5
holdout null (read 2026-08-01) was already known when the campaign's protocol was frozen.

## Campaign register

| # | Campaign | Evaluation window | Sessions | Protocol frozen | Null known at freeze? | Nature |
|---|---|---|---|---|---|---|
| C1 | Phase 5 development | 2026-03-24..2026-07-17 | 80 | 2026-07-29 (pre-holdout) | No | Development (in-sample selection) |
| C2 | Phase 5 holdout | 2026-07-20..2026-07-31 | 10 | 2026-07-29; read once 2026-08-01 | — (this IS the prospective test) | **Prospective, preregistered, one-read** |
| C3 | Phase 6 mechanism-aware | 2025-07-07..2026-03-23 | 100 OOS | 2026-08-01 | Yes (same day) | Retrospective |
| C4 | Independent 30-session replication | 2025-05-21..2025-07-03 | 30 | 2026-08-10 | Yes | Retrospective |
| C5 | B2 confirmation, two 2024 blocks | 2024-08-02..09-13; 2024-10-01..11-11 | 30+30 | 2026-08-11 | Yes | Retrospective, **out of frozen study window** (decision 51: EXPLORATORY_RETROSPECTIVE) |
| C6 | B1v3 one-read confirmation | 60 dev + 30 confirmation sessions | 90 | 2026-08-14 (sealed before read) | Yes | Retrospective, exposure-ledger pristine block |

Also: corrected independent reevaluation (PIT v2) of C4 recorded in
`artifacts/independent_replication_pit_v2/results.json` (same 30 sessions, corrected B1).
Mechanism search (25 variants, 2026-08-11): `NO_VARIANT_RETAINED` — retained as a null.

## Contrast table

| Campaign | Contrast | Gamma GLM (confirmatory) | LightGBM (fixed challenger) | Verdict recorded in artifact |
|---|---|---|---|---|
| C1 development | B1 vs B0 | ≈0 / negative (p≈0.95) | — | No B1 edge in development |
| C1 development | B2 vs B1 | +0.0131 (Holm 0.012) | null (p 0.321) | Development lead, linear models only |
| **C2 holdout (prospective)** | B1 vs B0 | −0.00705 (Holm 0.763) | −0.01144 (p 0.0116, adverse) | **NULL / adverse — confirmatory finding** |
| **C2 holdout (prospective)** | B2 vs B1 | +0.00061 (p 0.870) | −0.00053 (p 0.517) | **NULL — confirmatory finding** |
| C3 Phase 6 | B1v2a vs B0v2 | +0.0118 < MDE 0.0217 | +0.00597 < MDE | Below frozen MDE; `confirmed_contrasts=[]` |
| C3 Phase 6 | B2v2 vs B1v2a | +0.00444 < MDE 0.005035 | +0.00170 < MDE | Below frozen MDE; targeted family only |
| C4 replication | B1v2a vs B0v2 | −0.0870 (p 0.004, severely adverse) | +0.0052 (CI incl. 0) | B1 baseline broken under Gamma |
| C4 replication | B2v2 vs B1v2a | +0.0329 (Holm 0.0004, > MDE) | −0.0018 (p 0.0002, adverse) | Model-dependent; B2v2 QLIKE 0.3436 still worse than B0v2 0.2896 (total B0→B2 negative) |
| C4 corrected (PIT v2) | B1v2a vs B0v2 | −0.0908 | +0.0052 | MODEL_FAMILY_DEPENDENT |
| C4 corrected (PIT v2) | B2v2 vs B1v2a | +0.0340 [0.0254, 0.0427] > MDE 0.00504 | +0.00028 (ns, < MDE) | MODEL_FAMILY_DEPENDENT |
| C5 block A (2024) | B2 vs B1 | +0.0784 (Holm 0.002) | −0.0245 (Holm 0.002, adverse) | Gamma B0 baseline exploded (MAE ~2.1e5 vs ~1e-5 target) — see R-020 |
| C5 block B (2024) | B2 vs B1 | +0.0348 (Holm 0.002) | −0.0086 (Holm 0.002, adverse) | Same caveat; Elastic Net ns in both blocks |
| C6 B1v3 confirmation | B1v3a vs B0 | −0.0503 [−0.0653, −0.0359] (adverse) | reversed | B1v3a does not beat B0 |
| C6 B1v3 confirmation | B2 vs B1v3a | +0.0534 [0.0386, 0.0682], Holm 0.0004, > MDE 0.0130; positive in all 6 assets; survives all 5 registered timing sensitivities | −0.00745 [−0.0122, −0.0036] (adverse) | `POSITIVE_BUT_NOT_GLOBALLY_CONFIRMED` (decision 48) |

## Multiplicity accounting (decision 52 / R-019)

Registered outcome-bearing contrasts evaluated since 2026-07-29, by campaign:
C1: 2 primary + robustness families; C2: 2; C3: 2 global + 3 targeted (×2 models);
C4: 2 (×2 models) + corrected reevaluation 2 (×2 models); C5: 2 blocks × 5 models;
C6: 2 (×2 models) + 5 timing sensitivities; mechanism search: 25 variants (all discarded).
Per-campaign Holm families never exceeded 3 members; nothing corrects across the
sequence of campaigns, all of which sought the same Δ(B2)-type effect after C2 nulled.
Any headline p-value must be presented next to this count.

## Honest headline (decision 53)

1. The only prospective, preregistered test (C2) returned **null** for both nested contrasts.
2. Retrospective campaigns show a **recurring, Gamma-specific positive B2 increment**
   (+0.033..+0.078 across C4/C5/C6) that is **reversed or null under the fixed LightGBM
   challenger in every one of those samples**, and the total B0→B2 contrast is negative for
   the confirmatory model wherever it was measured (C3, C4).
3. The Gamma-specific effect shrinks toward the present: +0.078 (2024-A) → +0.035 (2024-B)
   → +0.033..0.034 (mid-2025) → +0.0044 (Phase 6, below MDE) → +0.0006 (2026 holdout).
4. Both PIT timing conventions remain assumptions (R-023). C6 ran its five registered
   sensitivities and stayed positive; C4/C5 were never re-evaluated under delayed
   availability.
5. No campaign may be described with the bare word "confirmed" while its
   `confirmed_contrasts` array is empty (C3, C4).

## Studentized inference addendum (2026-08-17, Gate 1)

The sign-bootstrap p-values above saturate at 2/(N+1). Studentized statistics
(cluster t, Newey-West/DM, wild cluster bootstrap-t), the formal Gamma-minus-LightGBM
interaction test, per-campaign Model Confidence Sets, serial-dependence diagnostics and
Gelman-Carlin design analysis now live in `docs/gate1_inference_hardening_v1.md` with
the machine-readable artifact `artifacts/gate1_inference/results.json`. Headlines:
every retrospectively significant Gamma B2 contrast survives HAC and wild-bootstrap
correction; the interaction is significant in every retrospective sample and null in
the prospective C2 holdout; the Gamma family never enters any Model Confidence Set
(C6's sole survivor is LightGBM|B0). Any headline p-value quoted from this file should
be accompanied by its studentized counterpart.

Artifacts: `artifacts/phase5/{development,holdout}_results.json`,
`artifacts/phase6/results.json` (evidence root), `artifacts/independent_replication/independent_results.json`,
`artifacts/independent_replication_pit_v2/results.json`,
`artifacts/b2_confirmation/frozen_evaluation_results.json`,
`artifacts/methodology/b2_mechanism_*.json`, decision 48 (B1v3), and
`docs/canonical_validation_conclusion.md`.
