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
| `artifacts/rp2_block4_b0/ladder.json` → `results.{D,V}.ewma` | `fix/rp2-v3-causal-b0` | the EWMA challenger was built from the square root of the RV30 target rather than from observed one-minute returns | 2026-08-20 |
| `artifacts/rp2_block5_surface/surface_coverage.json` and the B1 panel | `feat/rp2-v3-contemporaneous-b1` | the snapshot ended 1 920 s before the origin, and the primary set carried two 60 %-coverage diagnostics | 2026-08-20 |
| `artifacts/rp2_block6_flow/flow_coverage.json` (`d7320a54…`, 60 features) and the B2 panel | `artifacts/rp2_v3/gate5-exact-clock-b2/flow_coverage.json` (`32127e12…`, 70 features) | economics measured on the availability clock, a one-day floor on time to expiry, and no 0DTE features | 2026-08-20 |

Later rows are added by the rebuild gate (`results/rp2-v3-rebuild`) once the RP2-v3 run
exists and its `run_id` is known. A gate that supersedes a number before that point records
it here against its own branch, because a reader of the frozen artifact would otherwise
find the old value with nothing saying it has been replaced.

## Rule

- No frozen artifact under `artifacts/` is overwritten, moved or removed by an RP2-v3 gate.
- A superseding run writes under `artifacts/rp2_v3/<run_id>/` only.
- A claim withdrawn rather than replaced is recorded in `docs/methodology_decisions.md`
  with its withdrawal reason, and is also listed here.
