# Results superseded by RP2-v3

A result that RP2-v3 replaces is marked `SUPERSEDED_BY_RP2_V3` and is **never deleted**.
The frozen artifact, its hash and its provenance stay exactly where they were: a reader
who followed a citation to an RP2-v2 number must still find that number, and must also
find the record that a later run replaced it and why.

## Marker

```text
SUPERSEDED_BY_RP2_V3
```

Carried in three places, so that no single omission hides the supersession:

1. the superseding run's `scorecard.json`, under the artifact it replaces;
2. `public.rp2_block_results.supersedes_run_id`, with `is_current` moved to the new row;
3. the table below.

## Register

| Superseded artifact | Superseded by | Reason | Recorded |
| --- | --- | --- | --- |
| _(none yet)_ | | | |

Rows are added by the rebuild gate (`results/rp2-v3-rebuild`) once the RP2-v3 run exists
and its `run_id` is known. An empty register before that gate is the correct state, not an
omission.

## Rule

- No frozen artifact under `artifacts/` is overwritten, moved or removed by an RP2-v3 gate.
- A superseding run writes under `artifacts/rp2_v3/<run_id>/` only.
- A claim withdrawn rather than replaced is recorded in `docs/methodology_decisions.md`
  with its withdrawal reason, and is also listed here.
