# The study window: two statements, and which one the evidence was built on

The repository contains two different answers to the question *what period does this study
cover*, and they have never been reconciled in writing. This document states both, says
which one every existing artifact was produced under, and marks the reconciliation as an
open decision rather than settling it.

## What each source says

**`AGENTS.md`, "Study window rule (binding)"**

> A recorded configuration change for this run freezes `2025-07-21` through `2026-07-21`
> (end exclusive) […] Future widening or shortening requires another recorded
> configuration change.

Twelve months. The paragraph beneath it records the probe that motivated it: Unusual
Whales flow alerts entitled back to 2023-08-18 with the oldest non-empty events around
2024-08-02, FMP one-minute bars verified to at least 730 days, and Massive options history
deep. Its conclusion is that "a 12-month study window is therefore feasible".

**`artifacts/rp2_block1_partition/partition.json`**, written by Block 1 on 2026-08-18:

```text
D   389 sessions   2024-08-02 -> 2026-03-23   8 assets
V    80 sessions   2026-03-24 -> 2026-07-17   9 assets
sealed confirmation  2026-07-20 -> 2026-08-28  (never read)
```

Twenty-four months, starting at the oldest non-empty option events the probe found rather
than at the frozen start.

Neither `RP2_V3_MASTER_PLAN.md` nor `RESEARCH_CONTRACT.md` states a window.

## Which one produced the evidence

Every RP2 and RP2-v3 artifact — the panels, the ladders, the DML diagnostics, the
incremental inference, and every delta reported so far — was built on the partition:
389 development sessions and 80 validation sessions. Not on the twelve-month window.

The pipeline runner enforces the partition and records it. `assert_partition_matches`
compares the rebuilt B0 panel against `partition.json` per role, by session count and by
first and last session, and stops the run on a mismatch; `input_manifest.json` carries
`study_window_enforced` and `study_window_source` so the window a run used is written down
rather than inferred from whatever the bar store happened to hold that day.

## Why this is not resolved here

Adopting the twelve-month window would discard roughly 309 of the 389 development
sessions. That is not a correction; it is a different study, and it would invalidate every
frozen result the repository currently cites. Adopting the partition as the binding window
would amend a rule `AGENTS.md` calls binding, which the rule itself says requires a
recorded configuration change.

Both are decisions for the owner of the research programme, and neither is defensible as a
side effect of a code change. What is defensible, and what is done here, is that the
discrepancy is written down, the enforced window is recorded in every run, and no artifact
silently depends on which answer a reader assumes.

## The decision that is owed

One of these, recorded with its reason:

1. **The partition is the study window.** `AGENTS.md` is amended by a recorded
   configuration change to state 2024-08-02 through 2026-07-17 for RP2, with the twelve
   month rule retained for whatever programme it was written for. Nothing is rebuilt.
2. **The twelve-month window binds RP2 as well.** Block 1 is re-run against
   2025-07-21..2026-07-21, and every downstream artifact is rebuilt and superseded. The
   development sample falls to roughly 80 sessions, and the power of every contrast falls
   with it.

## What is recorded now

`configs/rp2_v3_study_window.json` records `adopted: "twelve_month"`. That is not a choice
made here: `AGENTS.md` states that a recorded configuration change already froze
`2025-07-21` through `2026-07-21` (end exclusive), and recording anything else would be a
new decision while recording nothing claimed no decision existed, which the rule
contradicts.

The consequence is stated with it, because it is severe. No existing RP2 or RP2-v3 artifact
may be published under that window — every one of them was built on the partition. Publishing
requires re-running Block 1 against the frozen window and rebuilding downstream, which
reduces the development sample from 389 sessions to roughly 80 and the power of every
contrast with it. Adopting `partition` instead amends a rule the repository calls binding and
needs its own recorded configuration change, with a reason written here.

The endpoint is recorded: `last_session` is `2026-07-17`, the final session eligible for D or
V inside the frozen window. It is not the calendar day before the exclusive end — 2026-07-20
is a market session, and Block 1 assigns it to the sealed Phase 8 cohort, so a rebuild
reaching it would either be impossible or would read a sealed cohort.

What publication refuses today is therefore the mismatch, not the absence. The completed
rebuild `rp2-v3-20260820-1710` runs 2024-08-02 through 2026-07-17, and the frozen window
begins 2025-07-21:

```text
RP2_PUBLISH_STUDY_WINDOW_MISMATCH:twelve_month:2024-08-02..2026-07-17!=2025-07-21..2026-07-17
```

Publishing under the frozen window means re-running Block 1 against it and rebuilding
downstream. Measured against `artifacts/rp2_block1_partition/inventory.jsonl`: 170 of the 389
development sessions fall inside it, and all 80 validation sessions do.

## What Block 1 cannot do yet

Re-running Block 1 as it stands does not produce that window. `discover_sessions` enumerates
every session the tape holds and `role_for` labels everything before `VALIDATION_FIRST_SESSION`
as `D`, so a rebuild starts at 2024-08-02 whatever window has been adopted, and the publisher
rejects it. The adopted window is therefore not merely unbuilt: it is unreachable by the
documented process until `role_for` takes a lower bound and Block 1 is regenerated against it.

That change alters which sessions are `D`, so it alters the frozen partition and every
artifact built on it. It belongs to the rebuild gate rather than to the publication gate,
and it is recorded here as the first thing that gate must do — not left to be discovered
when the rebuild is rejected.

The reconciliation is this page: the artifacts say what they were built on, the
configuration says what may be published, and neither is inferred from the other.
