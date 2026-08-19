# Discovery / Validation / Confirmation protocol (Research Program v2, Block 1)

**Status:** `FROZEN — 2026-08-18`
**Program:** `docs/research_program_v2.md`, Block 1 (Gate 0)
**Label of every retrospective analysis performed under it:** `EXPLORATORY_MECHANISM_DISCOVERY`
**Frozen artifact:** `artifacts/rp2_block1_partition/partition.json`
**Partition SHA-256:** `93566e5771cb4eb7f4badf1bfc2c2cc9a491b45a4324fa141bd240f469b2a168`
**Inventory SHA-256:** `ded4bc9b5d0e4c748e11e259d7b44660d3000e5b78fee6951376e76dd7a50abd` (3717 rows)
**Code:** `src/mds650/rp2/partition.py`, `scripts/rp2_block1_freeze_partition.py`
**Tests:** `tests/unit/test_rp2_partition.py`

---

## 1. The three universes

The separation is temporal, never a random partition: `D < V < C`.

| Universe | Window | Sessions | Assets | Tape bytes | Permitted use |
|---|---|---|---|---|---|
| **D — Discovery** | 2024-08-02 .. 2026-03-23 | 389 | AAPL, AMZN, META, MSFT, NVDA, SPY, QQQ, TSLA | 65.8 GB | Feature engineering, horizon exploration, mechanism identification, model-family selection, error diagnosis. **Produces no confirmation.** |
| **V — Validation** | 2026-03-24 .. 2026-07-17 | 80 | same eight | 18.8 GB | Specification choice, calibration, MDE estimation, preliminary stability. **Used for selection, therefore exploratory — see §2b. Produces no confirmation of any kind.** |
| **C — Confirmation** | 2026-07-20 .. 2026-08-28 | 30 | frozen by its own protocol | *not enumerated* | Sealed, one read, no changes once started. **Not touched by this program.** |

`temporal_ordering_D_lt_V_lt_C = true` is asserted by
`mds650.rp2.partition.temporal_ordering_holds` and re-checked by the runner: the last
Discovery session (2026-03-23) precedes the first Validation session (2026-03-24), which
precedes the first sealed Confirmation session (2026-07-20).

### Source stores composing D and V

| Store | Sessions | Role |
|---|---|---|
| `b1v3_confirmation/data/option_events` | 2024-08-02 .. 2024-12-09 | D |
| `b1_diagnostic_replication/data/option_events` | 2024-12-10 .. 2025-01-24 | D |
| `independent_replication_30/data/option_events` | 2025-02-25 .. 2025-07-03 | D |
| `phase6/data/option_events` | 2025-07-07 .. 2026-03-23 | D |
| `data/option_events` | 2026-03-24 .. 2026-07-17 | V |

Five Validation sessions (2026-07-13..07-17) are stored un-partitioned as a single
multi-asset `events.parquet`; they carry the asset label `__ALL__` in the inventory and are
split at read time. This is a storage-layout fact, not a coverage gap.

---

## 2. Why the confirmation universe is the sealed Phase 8 cohort

Every retrospective window in this project has already been observed — C1 through C6 all
read their samples, and the Phase 5 prospective holdout was read once on 2026-08-01. There
is therefore **no unburned retrospective sample that could serve as C**. Manufacturing one
by carving a "fresh" slice out of an already-examined era would be a confirmation in name
only.

The only genuinely unobserved evidence in the project is the sealed Phase 8 one-shot cohort
(`docs/phase8_one_shot_protocol_v1.md`): collected blind, sealed at capture time,
`holdout_reads=0`, one read authorized by the owner.

**Recorded honestly:** the first ten sessions of the Phase 8 window (2026-07-20..07-31)
coincide with the already-read Phase 5 prospective holdout C2. Only 2026-08-03..08-28 is
strictly unobserved. This is a property of how the cohorts were laid out, it is disclosed
here rather than hidden, and it caps what a Phase 8 read can claim.

**Binding rule for this program:** no block reads any sealed cohort. Block 12 designs a
*future* prospective protocol; it does not modify Phase 8 or Phase 9.

---

## 2b. Reclassification: D **and** V are exploratory (2026-08-19)

The original framing gave V a quasi-confirmatory role — "choosing among a limited number of
specifications". In practice V has been used to select: the specification comparisons of
Blocks 3 and 8, the family choice, the recalibration decision and the target battery of
Extension 1 all read V and all fed back into what was reported.

That is selection, and a sample used for selection cannot also confirm. **Both D and V are
therefore reclassified as exploratory**, and every result computed on either carries
`EXPLORATORY_MECHANISM_DISCOVERY` regardless of which universe produced it. A replication
across D and V is evidence that a finding is not a single-era accident; it is **not**
confirmation, and this document no longer implies otherwise.

The only confirmatory evidence this project can produce is a cohort collected after a frozen
protocol and read once. None has been read.

## 3. Approval rule

No new retrospective *confirmatory* campaign is started. Every retrospective analysis
produced by Blocks 2–11 of Research Program v2 is labelled

```
EXPLORATORY_MECHANISM_DISCOVERY
```

and is reported under decision 53's hierarchy: the prospective C2 null first, exploratory
mechanism findings second, always with their multiplicity count attached. This label is what
makes Blocks 3–10 compatible with the decision-52 moratorium on new retrospective campaigns.

## 4. Selection discipline

Model families, targets, horizons and features are selected **only in D and V**. Nothing is
selected in C. Any specification that reaches C is frozen, hashed and registered before the
seal is opened.

## 5. Advance rule — met

Three temporally separated samples exist and are hash-frozen:
`partition_sha256 = 93566e57…b2a168` over an inventory of 3717 `(session, asset, file, size)`
rows, with the confirmation universe recorded by protocol reference rather than by
enumeration. **Block 1 advance rule: PASS.**
