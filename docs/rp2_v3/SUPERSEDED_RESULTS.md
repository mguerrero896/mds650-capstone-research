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

| `artifacts/rp2_ext12_level4/level4_and_tensor.json` -> `D.extension_1_level4`, every estimate and interval (deepsets QLIKE 0.22154, delta vs control -0.05747, delta vs lightgbm -0.08691, log-scale RMSE 1.10246) | the same artifact rebuilt on `feat/rp2-v3-level4-sequence` (deepsets QLIKE 0.17017, delta vs control -0.00469 [-0.01967,+0.00729] p 0.6017, delta vs lightgbm -0.03553 [-0.07755,-0.01184] p 0.0010, log-scale RMSE 0.58241) | the masked max-pool filled padded positions with -1e9 and the repair tested for -inf, so 448 of 2,975,222 forward passes carried a feature of magnitude 1e9 into the head; the first epoch recorded MSE 1.7e14 against the control's 43.5. The preregistered conclusion is unchanged - the sequence fails both references - but 92 % of the reported effect was the sentinel | 2026-08-21 |

| `artifacts/rp2_v3/rp2-v3-20260821-134741/rp2_block8_ladder/ladder.json` and `rp2_block10_inference/inference.json` -> every role-D figure, and the six role-D rows of the twelve-contrast table in `docs/rp2_v3/VERDICT.md` | the same producers run against a B0 built from re-acquired bars (`data/fmp/rp2_ohlcv_repair/underlying_1min_repair.parquet`) | two development-only bar stores carried no high, low or volume and the session grid invented them as high == low == close and volume == 0, making three B0 features exactly zero on 22,967 of 152,954 development origins and none of the 31,678 validation ones. B0 improves and the development B1 increment falls by about two fifths - ridge_log +0.00424 to +0.00250, gamma_glm +0.00408 to +0.00234, lightgbm_qlike +0.00381 to +0.00314 - while validation is unchanged to the digit. Decision 86 | 2026-08-21 |
| `docs/rp2_v3/VERDICT.md` -> the claim that `ridge_log` refutes | decision 86 | the corrected development effect +0.00250 is below validation's own minimum detectable effect of 0.00268, so validation was not powered to see it: about 37 sessions would be needed against 32 available. All three families are underpowered rather than one refuting | 2026-08-21 |
| `artifacts/rp2_v3/*/scorecard.json` -> `b1.b1_p95_quote_age_s` (1723.92 s), `b1.b1_median_quote_age_s` (579 s) and `b2.b2_multileg_share` (0.231077) | the same fields read off summed histogram bins and pooled by premium | the first two were a median across origins of each origin's own quantile, which is not a quantile of any population; the third was an unweighted mean of ratios whose denominators span a factor of fourteen, against a pooled share of 0.236861. Decision 87 | 2026-08-21 |

Later rows are added by the rebuild gate (`results/rp2-v3-rebuild`) once the RP2-v3 run
exists and its `run_id` is known. A gate that supersedes a number before that point records
it here against its own branch, because a reader of the frozen artifact would otherwise
find the old value with nothing saying it has been replaced.

## Rule

- No frozen artifact under `artifacts/` is overwritten, moved or removed by an RP2-v3 gate.
- A superseding run writes under `artifacts/rp2_v3/<run_id>/` only.
- A claim withdrawn rather than replaced is recorded in `docs/methodology_decisions.md`
  with its withdrawal reason, and is also listed here.
