# Block 13 — cascade execution map, filled in

**Status:** `EXECUTED — 2026-08-19`
Every row records what the block actually returned, not what it was hoped to return.

| # | Block | Deliverable | Advance rule | Result |
|---|---|---|---|---|
| 1 | Freeze | `DISCOVERY_VALIDATION_CONFIRMATION_PROTOCOL.md` | three temporally separated samples | **PASS** — D 389 sessions, V 80, C sealed and untouched |
| 2 | PIT | receipt-latency / backfill / revisions ledger | empirical cutoff approved | **PASS with amendment** — `c_B2 = 120 s` replaces 60 s; P95 stability sub-gate FAILS, resolved by a 452/469 admissibility list |
| 3 | Target | RV / jump / semivariance / horizon comparison | one primary target frozen | **PASS** — RV30 stays primary on the owner's standing decision; the empirical case for RV60 is escalated |
| 4 | B0 | HARQ + market + liquidity | well-calibrated baseline | **PASS with condition** — beats all five challengers in both universes; calibration is era-dependent |
| 5 | B1 | constant-maturity surface + VRP | improvement in D/V **or** a clear mechanism | **PASS on the second clause only** — the stated two-family improvement rule FAILS |
| 6 | B2 | Greeks flow + intensity + sequence | target-blind features frozen | **PASS** — 52 features, 125,136 origins, zero failures |
| 7 | Orthogonalization | DML of B2 on B0+B1 | preliminary incremental evidence | **PASS in D only** — joint Wald 501.9 (full) / 206.8 (core), p = 6 × 10⁻³⁹ in D; core test p = 0.059 in V |
| 8 | Model ladder | smooth + tree + hierarchical | selection only in D/V | **PASS procedurally, NULL substantively** |
| 9 | Generalization | LOAO / LOEO / event / regime | no concentrated dependence | **PASS in D, FAIL in V** |
| 10 | Inference | CW / GW / SPA / block-MCS | survives multiplicity | **FAIL** — best SPA p = 0.0070 against a budget of 0.00417 |
| 11 | Economics | P&L / utility after costs | positive net value | **FAIL** — deflated Sharpe ≤ 0.19 everywhere, 0.000 when selective |
| 12 | Prospective | one-read future holdout | binding result | **NOT_RUN by design** — 537 sessions needed, 60–120 proposed; protocol frozen and `READY_TO_RUN` |
| 13 | Replication | second window / implementation | external confirmation | **NOT_REACHED** — there is no positive first window to replicate |

## Level-4 and tensor work: gated, not skipped

| Item | Status | Gate that was not met |
|---|---|---|
| Moneyness × DTE tensor (§6.5) | NOT_BUILT | "only after demonstrating that the tabular baseline does not capture the signal" — the tabular baseline captures no signal to begin with |
| DeepSets / TCN / transformer / neural Hawkes (§8 level 4) | NOT_RUN | same gate, plus no deep-learning stack installed |
| Bridge A, delta-hedged options (§11) | NOT_IMPLEMENTED | needs a full quote book through the holding period; the tape carries NBBO only at trade instants |

Each is recorded as an unmet prerequisite rather than as an approximation, because an
approximated number here would read as a result.

## The cascade in one sentence

A full arbitrage-aware option surface and a full microstructure representation of option
flow were built at zero acquisition cost; **B2 demonstrably contains information that B0 and
B1 cannot reconstruct** (Block 7); **that information is smaller than the cost of estimating
the parameters needed to use it** (Blocks 8 and 10); and it is therefore worth nothing
economically (Block 11) and cannot be confirmed by any feasible prospective test (Block 12).
