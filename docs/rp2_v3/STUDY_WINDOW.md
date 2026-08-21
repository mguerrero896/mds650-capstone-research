# The study window: what the repository said twice, and what it says now

The repository contained two different answers to the question *what period does this study
cover*. They are reconciled by a recorded configuration change, and this page states what
each source said, which one produced the evidence, and what was decided.

## What each source said

**`AGENTS.md`, "Study window rule (binding)"** froze `2025-07-21` through `2026-07-21`
(end exclusive), on the strength of a probe that found Unusual Whales flow alerts entitled
back to 2023-08-18 with the oldest non-empty events around 2024-08-02, FMP one-minute bars
verified to at least 730 days, and Massive options history deep. Its conclusion was that a
twelve-month window is feasible.

**`artifacts/rp2_block1_partition/partition.json`**, written by Block 1 on 2026-08-18:

```text
D   389 sessions   2024-08-02 -> 2026-03-23   8 assets
V    80 sessions   2026-03-24 -> 2026-07-17   9 assets
sealed confirmation  2026-07-20 -> 2026-08-28  (never read)
```

Twenty-four months, starting at the oldest non-empty option events rather than at the frozen
start. Every RP2 and RP2-v3 artifact was built on it — the panels, the ladders, the DML
diagnostics, the incremental inference and every delta reported.

## The decision, recorded

`configs/rp2_v3_study_window.json` records `adopted: "partition"`. This is the recorded
configuration change the binding rule itself calls for — methodology decision 84, dated
2026-08-21, made by the owner of the research programme — and `AGENTS.md` carries the
amendment where the rule is stated. The twelve-month freeze is retained for the acquisition
programme it was written for.

The study window for RP2 and RP2-v3 is therefore:

```text
D   389 sessions   2024-08-02 -> 2026-03-23
V    80 sessions   2026-03-24 -> 2026-07-17
```

Measured before deciding, against `artifacts/rp2_block1_partition/inventory.jsonl`: 170 of
the 389 development sessions fall inside the twelve-month window and all 80 validation
sessions do, so adopting it would have discarded 219 development sessions, required Block 1
to be re-run with a lower bound it does not have, and superseded every frozen result the
repository cites.

Nothing was rebuilt and no number changed. The completed rebuild
`rp2-v3-20260820-1710` builds a publishable payload under this window — 7 blocks, 24
contrasts, scientific hash `bae01ab50013077e` — which is the same run, the same artifacts and
the same digests that existed before the decision. What changed is that the repository now
says once, in a place publication reads, which of its two statements governs.

Publication still refuses a run whose enforced window is not this one, so the decision cannot
be recorded and then quietly departed from.

The reconciliation is this page: the artifacts say what they were built on, the
configuration says what may be published, and neither is inferred from the other.
