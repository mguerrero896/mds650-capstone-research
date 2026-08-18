# Block 2 — Gate 1: operational point-in-time truth

**Status:** `EXECUTED — 2026-08-18` · label `EXPLORATORY_MECHANISM_DISCOVERY`
**Program:** `docs/research_program_v2.md`, Block 2
**Artifacts:** `artifacts/rp2_block2_pit/{ledger.json, per_session.json, admissibility.json}`
**Ledger SHA-256:** `49df37ead2a494b55cff5dbab3b3e9095b4930e548d2f79b6856a78dbeb0e776`
**Admissibility SHA-256:** `1c72835959bdbd6fe9147ac5c41a9ac44811a709adc56c02fe1bc62172384b76`
**Code:** `src/mds650/rp2/pit_ledger.py`, `scripts/rp2_block2_pit_ledger.py`,
`scripts/rp2_block2_admissibility.py` · **Tests:** `tests/unit/test_rp2_pit_ledger.py`

---

## 1. What was measured, and on what

Every partition of the frozen D and V universes was streamed: **1,461,521,313 option-trade
rows across 469 sessions and 3,717 partitions**. This is the whole locally held tape, not a
sample.

The tape carries two of the seven timestamps the program asks for:

| Program field | Available on the historical tape | Field used |
|---|---|---|
| `exchange_timestamp` | yes | `executed_at` |
| `provider_created_at` | yes | `created_at` |
| `provider_received_at` | no | — |
| `local_received_at` | **only prospectively** | live campaign `receipt_utc` |
| `ingested_at` | no (equal to file write time) | — |
| `reconciled_at` | no | — |
| `revision_version` | no explicit field | duplicate `id` used as proxy |

So the measurement is decomposed into two legs, and the missing legs are named rather than
assumed away.

### Leg 1 — provider ingestion latency, `created_at − executed_at` (whole tape)

| Statistic | Value |
|---|---|
| P50 | **0.073 s** |
| P90 | 0.216 s |
| P95 | **0.979 s** |
| P99 | 4.756 s |
| P99.9 | 13,874 s (3.85 h) |
| max | 23,995 s (6.67 h) |
| mean | 25.3 s |
| share > 60 s (backfill) | **0.352 %** (5,139,635 rows) |
| non-positive latencies | **0** |
| duplicate `id` rows (revision proxy) | **0** |
| rows executed on another session's date | **0** |

### Leg 2 — local receipt latency, `receipt_utc − created_at` (live campaign)

Sessions 2026-08-17 and 2026-08-18, 486 steady-state records after excluding the 1,200
initial-window backlog records per session (those were already in the endpoint's rolling
window when the collector started and would otherwise masquerade as latency).

| Statistic | Value |
|---|---|
| P50 | 31.1 s |
| P95 | **57.5 s** |
| P99 | 60.2 s |
| max | 61.3 s |
| min | **−0.79 s** |

The shape — near-uniform on `[0, 60]` with a hard ceiling at ~61 s — shows this leg is
**our own 60-second polling cadence**, not a provider delay. It is an operational property
of this pipeline and is reducible by polling faster or subscribing to a stream. The seven
negative values bound the **clock skew** between the provider's clock and the local machine
at **under 0.8 s**, which is the closest thing to a clock-synchronisation check the
available evidence permits.

---

## 2. The cutoff rule

$$c_{B2} \ge Q_{0.95}(\ell) + \text{safety margin}$$

with `Q_0.95(ℓ)` taken end to end:

```
end-to-end P95 = 0.979 s (provider) + 57.548 s (local receipt) = 58.527 s
c_B2           = ceil(2 × 58.527) = 118 s   →   registered as 120 s
```

**Finding — the incumbent 60-second cutoff is not point-in-time valid.** The end-to-end P95
is 58.5 s, so a 60-second cutoff leaves a margin of 1.5 seconds, i.e. essentially none, and
5 % of records are not yet locally visible at that boundary. This is precisely the failure
mode the program anticipated ("if the observed P95 is 83 seconds, 60 seconds cannot continue
to be used as if it were PIT") — the number here is 58.5 s rather than 83 s, but the
conclusion is the same.

**Consequence for the existing record.** The registered 120 s availability sensitivity
(R-023, already executed on C4/C5/C6) is not a sensitivity: **it is the correct primary
convention**, and 60 s is the optimistic bound. The measured effect of that switch is
already on file and is small — Gamma Δ(B2) on the 2024 blocks moves +0.0784 → +0.0766 (block
A) and +0.0348 → +0.0329 (block B), with LightGBM adverse throughout. Reclassifying the
convention therefore changes the interpretation's status, not its sign.

---

## 3. Gate approval — the sub-gates, honestly

| Sub-gate | Requirement | Measured | Verdict |
|---|---|---|---|
| Stable P95 | P95 comparable across sessions | session P95 median 0.297 s, max **22,587 s** | **FAIL** |
| Backfill below threshold | share > 60 s small | pooled 0.352 %, but 17 sessions above 1 % | **CONDITIONAL** |
| Revision rate below threshold | few revisions | 0 duplicate ids in 1.46 B rows | **PASS** |
| Clocks synchronised | no inversions | 0 negative on the tape; ≤ 0.79 s skew live | **PASS** |
| No observation used before receipt | cutoff ≥ P95 + margin | 120 s adopted | **PASS at 120 s, FAIL at 60 s** |

The P95-stability sub-gate fails because latency is **not homogeneous across sessions**:

| Threshold | Sessions with P95 above it |
|---|---|
| 1 s | 120 / 469 (25.6 %) |
| 10 s | 10 / 469 (2.1 %) |
| 60 s | 8 / 469 (1.7 %) |
| 300 s | 2 / 469 (0.4 %) |
| 3600 s | 1 / 469 (0.2 %) |

Worst sessions: **2025-10-20** (P95 22,587 s, backfill share **100 %** — the entire session
arrived late; this is the incident already documented at ~24,000 s in the v2.1 academic
appendix, now measured on the full tape), then 2025-03-07 (708 s), 2026-06-01 (196 s),
2025-03-04 (179 s), 2025-08-21 (141 s), 2025-05-15 (124 s).

**Resolution adopted.** A single global cutoff cannot repair a session whose own P95 exceeds
it. The cutoff is therefore paired with a **per-session admissibility rule**: a session is
PIT-admissible when its own P95 ≤ 120 s *and* its backfill share ≤ 1 %.

```
sessions evaluated   469
admissible           452  (96.4 %)
inadmissible          17  (3.6 %)
```

Inadmissible: 2025-03-04, 03-07, 03-11, 04-07, 04-09, 05-15, 06-25, 08-21, 09-18, 10-20,
11-20, 2026-01-29, 02-05, 04-28, 05-08, 06-01, 06-03.

All 17 fall in the **D** universe or the V universe; they are excluded from every downstream
block of this program by list, not by re-derivation.

---

## 4. What this block cannot establish

- `provider_received_at`, `ingested_at`, `reconciled_at` and an explicit `revision_version`
  do not exist in the historical tape. Zero duplicate ids is evidence that the provider does
  not *re-emit* revised rows under the same id; it is **not** evidence that no row was ever
  silently corrected before we fetched it.
- The local-receipt leg rests on two sessions and 486 steady-state records. It measures our
  polling cadence well and the provider's push behaviour barely at all. It is a floor on
  what a faster collector could achieve, not a characterisation of the provider.
- "Rows appearing only in the historical tape" cannot be computed: there is no live stream
  capture of the same trades to difference against. Recorded as an open item, not estimated.

## 5. Advance rule

"Empirical cutoff approved": **PASS with a documented amendment** — `c_B2 = 120 s` replaces
60 s as the point-in-time convention, and it is admissible only in combination with the
452-session admissibility list. The stability sub-gate fails on its own terms and is
resolved by exclusion rather than by relaxing the threshold.
