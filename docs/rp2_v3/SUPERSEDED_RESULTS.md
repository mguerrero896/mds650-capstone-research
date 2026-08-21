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
| `artifacts/rp2_block6_flow/flow_coverage.json` (`d7320a54…`, 60 features) and the B2 panel | `artifacts/rp2_v3/gate5-exact-clock-b2/flow_coverage.json` (`773c3d3d…`, 70 features) | economics measured on the availability clock, a one-day floor on time to expiry, and no 0DTE features | 2026-08-20 |
| `artifacts/rp2_block10_inference/inference.json` → `{D,V}.superior_predictive_ability` (D: `lightgbm|B0+B1+B2`, ΔQLIKE +0.01195, SPA p 0.0010) | `artifacts/rp2_v3/gate9-session-inference/inference.json` (D: `gamma_glm|B0+B1`, ΔQLIKE +0.00408, SPA p 0.0010; V: nothing beats its own B0) | one cross-family race over per-origin rows: it confounded the estimator with the information set and used a sample it did not have | 2026-08-20 |
| `artifacts/rp2_block8_ladder/ladder.json` and `artifacts/rp2_block10_inference/inference.json` → every contrast estimate and p-value | `fix/rp2-v3-session-inference` | the estimate averaged over origins, so a busy session weighed more than a quiet one and an early close weighed less than a full day; the interval resampled single days rather than blocks of five sessions | 2026-08-20 |

| `artifacts/rp2_block6_flow/flow_coverage.json` -> `b2_p95_provider_latency_s` (0.122 s) | `results/rp2-v3-rebuild` (0.280 s) | the reported tail was a median across windows of each window's own 95th percentile, which is not a quantile of any population: a window holding one trade weighed as much as one holding ninety-nine, and quantiles do not merge by averaging. It is now read off a histogram of all 580,549,989 trades. The value falling below the reported mean is not the defect and never was: the distribution is heavy-tailed, with 94.3 % of trades at or under 0.28 s and 0.23 % above 100 s, which is what carries the mean to 1.221 s | 2026-08-21 |

| `artifacts/rp2_block10_inference/inference.json` and the RP2-v2 ladder, every contrast estimate and interval | `rp2-v3-20260821-134741` (published, scientific hash `fdce125264082af5`) | rebuilt end to end under the frozen partition with contemporaneous B1, corrected B2 clocks, fold-local preprocessing, one common evaluation mask, LightGBM aligned to QLIKE, and session-level family-matched inference | 2026-08-21 |
| README "Findings at a glance (2026-08-19)", item 2: B2-over-B1 under the Gamma GLM "positive and statistically supported... up to +0.053" | `rp2-v3-20260821-134741` | the rebuilt contrast is ΔB2\|B1 = −0.02549 in development and −0.00222 in validation, the latter with a 95 % interval excluding zero. The sign is reversed, not the magnitude reduced | 2026-08-21 |

Later rows are added by the rebuild gate (`results/rp2-v3-rebuild`) once the RP2-v3 run
exists and its `run_id` is known. A gate that supersedes a number before that point records
it here against its own branch, because a reader of the frozen artifact would otherwise
find the old value with nothing saying it has been replaced.

## Rule

- No frozen artifact under `artifacts/` is overwritten, moved or removed by an RP2-v3 gate.
- A superseding run writes under `artifacts/rp2_v3/<run_id>/` only.
- A claim withdrawn rather than replaced is recorded in `docs/methodology_decisions.md`
  with its withdrawal reason, and is also listed here.
