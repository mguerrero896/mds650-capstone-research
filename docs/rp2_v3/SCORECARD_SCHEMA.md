# RP2-v3 scorecard schema

Every rebuild writes `artifacts/rp2_v3/<run_id>/scorecard.json` and its rendered
`scorecard.md`. The JSON is the contract; the Markdown is a view of it. A rebuild that
cannot fill a required field fails rather than omitting it, because a missing metric reads
as an unmeasured one.

## Top level

```json
{
  "schema_version": "rp2-v3-scorecard-v1.0",
  "run_id": "rp2-v3-YYYYmmdd-HHMMSS",
  "data": {...},
  "b1": {...},
  "b2": {...},
  "forecast": {...},
  "engineering": {...}
}
```

## Data

| Field | Type | Meaning |
| --- | --- | --- |
| `b0_rows` | int | rows in the causal baseline panel |
| `b1_rows` | int | rows in the contemporaneous option-state panel |
| `b2_rows` | int | rows in the point-in-time flow panel |
| `common_evaluation_rows` | object | `{"D": int, "V": int}` — held-out rows every nested model in a contrast is scored on |
| `masked_rows_by_role` | object | `{"D": int, "V": int}` — rows surviving the common mask, of which only the held-out segment is evaluated |
| `sessions_by_role` | object | `{"D": int, "V": int}` |
| `assets` | int | distinct assets in the evaluation mask |
| `duplicate_keys` | int | must be 0 |
| `provider_failures` | int | session-assets with no tape to read at all, summed over B1 and B2; distinct from empty windows and from sparse sessions |
| `sparse_session_assets` | int | session-assets whose tape opened and held too little to build a surface from — a thin day, not an outage |

## B1

| Field | Type | Target |
| --- | --- | ---: |
| `b1_core_coverage` | float | > 0.90 |
| `b1_median_quote_age_s` | float | < 900 |
| `b1_p95_quote_age_s` | float | <= 1800 |

`b1_p95_quote_age_s` is the median across origins of *each origin's* 95th-percentile quote
age. The producer computes the tail over that origin's own quotes: an origin of mostly
fresh quotes with a stale tail has a fresh median, so a quantile taken over per-origin
medians afterwards would describe typical origins rather than stale quotes.

| `b1_surface_contracts_per_origin` | float | reported |
| `b1_surface_expiry_coverage` | float | reported |
| `b1_rows_dropped_for_rate_or_dividend` | int | 0 |
| `b1_post_cutoff_observations` | int | 0 |
| `b1_duplicate_contracts_per_snapshot` | int | 0 |
| `b1_missing_rate_share` | float | reported |

## B2

| Field | Type | Target |
| --- | --- | ---: |
| `b2_pit_violation_count` | int | 0 |
| `b2_zero_dte_count` | int | reported |
| `b2_mean_provider_latency_s` | float | reported |
| `b2_p95_provider_latency_s` | float | reported |
| `b2_multileg_share` | float | reported |
| `b2_empty_window_share` | float | reported |
| `b2_provider_failure_share` | float | reported |

`b2_p95_provider_latency_s` is the 95th percentile of the run's record lags, read off a
histogram the producer emits per counting window and the scorecard adds. Per-window
quantiles cannot be merged: a median across windows of their own 95th percentiles lets a
window holding one trade weigh as much as a window holding ninety-nine, and the result is not
the 95th percentile of any population.

A tail below the mean beside it is not a symptom of that, and was mistaken for one when this
was first investigated. The measured distribution over 580,549,989 trades is
`p50 0.067 s, p90 0.137 s, p95 0.280 s, p99 4.877 s, p999 279.102 s`: 94.3 % of records
arrive within 0.28 s and 0.23 % take more than 100 s, and that fraction alone carries the
mean to 1.221 s. A heavy tail puts the mean above the 95th percentile as a matter of
arithmetic, so the ordering of these two fields says nothing about whether either is
correct. Counts in fixed bins do merge, by adding. The bins are
log-spaced from 0.01 s to about 3.5 hours, and the reported value is the lower edge of the
bin the quantile falls in, so it understates rather than overstates a number reported as a
worst case.

## Forecast

| Field | Type | Meaning |
| --- | --- | --- |
| `qlike_b0` | object | QLIKE by role and model family for B0 |
| `qlike_b0_b1` | object | ditto for B0+B1 |
| `qlike_b0_b1_b2` | object | ditto for B0+B1+B2 |
| `delta_b1` | object | `L(B0) - L(B0+B1)`, by role and family |
| `delta_b2_given_b1` | object | `L(B0+B1) - L(B0+B1+B2)`, by role and family |
| `delta_total` | object | `L(B0) - L(B0+B1+B2)`, by role and family |
| `ci_by_session` | object | session-level confidence interval per contrast |
| `mde` | object | minimum detectable effect at the realised session count |
| `calibration_slope` | object | Mincer–Zarnowitz slope per model |
| `calibration_intercept` | object | Mincer–Zarnowitz intercept per model |
| `common_mask_sha256` | object | hash of the evaluated row mask, **per contrast** |

## Engineering

| Field | Type | Meaning |
| --- | --- | --- |
| `runtime_seconds` | float | wall clock from the start of the run to the moment the scorecard was assembled; the steps after it are recorded in `run_manifest.json` |
| `peak_memory_bytes` | int | peak resident memory |
| `input_manifest_sha256` | str | hash of the resolved input manifest |
| `feature_registry_sha256` | str | hash of the frozen feature registry |
| `model_config_sha256` | str | hash of the model configuration |
| `code_commit` | str | commit the run was produced from |
| `artifact_sha256` | object | content hash per emitted artifact |

A contrast is keyed by role, model family, base information set and expanded information
set. `common_mask_sha256` is recorded per contrast, not once per run: two contrasts can
score the same number of rows without scoring the same rows, so an equal
`common_evaluation_rows` count is not evidence that a nested pair saw identical data.
Only the hash is.

## Field list

The authoritative list of required fields is [`configs/rp2_v3_scorecard_fields.json`](../../configs/rp2_v3_scorecard_fields.json). This document and the pipeline runner both
read it, so a field cannot be dropped from one and survive in the other.

## Reproducibility

Two runs from the same inputs, commit, configuration and seeds must produce identical
values for every field above except `runtime_seconds` and `peak_memory_bytes`. Execution
timestamps never enter a scientific content hash.
