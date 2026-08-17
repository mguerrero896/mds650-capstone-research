# Sealed-cohort disposition record (D006)

Status: `RESOLVED_20260817` (decision 55). Created 2026-08-17 under decision 52.

## Inventory of sealed, unread cohorts

| Cohort | Window | Acquired | Scientific reads | Frozen gate |
|---|---|---|---|---|
| Validation A | 2026-01-26..2026-03-09 | 14 of 30 | 0 | Candidate freeze `22f5454d…`, internal freeze `0e8b5a6e…`; one-shot authorization required |
| Validation B | 2026-03-10..2026-04-21 | 0 of 30 | 0 | Role registry `79cffdd8…`; sequential after A |
| Phase 8 prospective holdout | 2026-07-20..2026-08-28 | 10 of 30 | 0 | Method freeze `87c818…`; collector currently disabled; may not be read before 30/30 |

These are the study's own planned confirmation pathways. Since 2026-08-02 they have been
bypassed in favor of newly designed historical blocks (C3–C6 in
`docs/results_reconciliation_v2.md`), which creates the selective-completion exposure
recorded as R-022.

## Options for the owner (choose one per cohort)

1. **Complete and read under the existing frozen gates.** Requires: finishing acquisition
   (16 A sessions / 30 B sessions / 20 Phase 8 sessions), hash verification, an explicit
   one-shot authorization record, and a single read evaluated under the already-frozen
   candidate and success rules. No redesign of features, models, thresholds or windows is
   permitted after this choice.
2. **Close formally without reading.** Record the closure here with a reason (e.g.
   superseded by the B1v3 exposure-ledger design), mark the cohort
   `CLOSED_UNREAD_<date>`, and never evaluate it later. A closed cohort may still be cited
   as an unopened seal (evidence of restraint), never as a result.

Splitting the decision is legitimate (e.g. close Validation A/B, complete Phase 8).

## Recommendation (non-binding)

Phase 8 is the only cohort whose completion yields a genuinely **prospective** test — the
single design immune to the retrospective-availability objection (R-023). If any positive
claim is to be defended, the highest-value path is: re-enable the Phase 8 collector (or
freeze a successor prospective protocol per decision 47's exposure-ledger rules with a
stabilized confirmatory model per R-020), complete 30/30, and evaluate once. Validation A/B
predate the B1v3 redesign and can be closed unread with the supersession documented.

## Decision record

| Date | Cohort | Decision (1/2) | Authorized by | Evidence |
|---|---|---|---|---|
| 2026-08-17 | Phase 8 | 1 — complete under frozen gates | Owner (session message 2026-08-17) | Store junction to `D:\MDS650\phase8_holdout`; `phase8_repro_gate.py` PASS; catch-up launched; `MDS650_Phase8A_BlindCollector` re-enabled (daily 18:00); 30/30 lands 2026-08-29; reads remain 0 pending one-shot authorization |
| 2026-08-17 | Validation A | 2 — `CLOSED_UNREAD_20260817` | Owner (session message 2026-08-17) | Superseded by decision 47 exposure-ledger design; 14 acquired sessions stay sealed as an unopened archive |
| 2026-08-17 | Validation B | 2 — `CLOSED_UNREAD_20260817` | Owner (session message 2026-08-17) | Never acquired; role registry retained as design evidence only |

The decision-52 moratorium on **new** retrospective campaigns remains in force; completing
Phase 8 under its already-frozen gate is not a new campaign.
