# Phase 4B feature contract

This contract describes the local-only correction over the retained calibration and Pilot V2
Parquet files. It does not authorize provider requests or a new backfill.

## Forecast origin and B0

Existing canonical `origin_id` values and RV30 targets are immutable. For delay `d`, the B0
predictor snapshot is the latest raw bar satisfying:

```text
raw_timestamp + d minutes <= forecast_origin
```

The primary view uses `d=1`; the sensitivity view uses `d=2`. Each view retains the raw source
timestamp, available-at timestamp and feature age. The target continues to use the existing 31
prices and 30 one-minute returns; the predictor snapshot never shifts the target origin.

## B2 windows

For `delay ∈ {60, 120, 300}` seconds:

```text
window_end   = forecast_origin - delay
window_start = window_end - 5 minutes
executed_at ∈ [window_start, window_end)
max(executed_at, created_at) <= window_end
```

The half-open boundary assigns an event at an exact five-minute boundary to one window only.
`created_at` is an `operational_availability_proxy`, not publication time and not evidence of
trader intention.

## Canonical B2 identities

`b2_within_bin_iv_change` is the only canonical name for the within-window IV range. The aliases
`median_implied_volatility` and `implied_volatility_change_within_bin` are prohibited in derived
matrices. IV median and IV-change retain nulls, valid-observation counts and availability reasons;
neither field is required for B2-core completeness.

`b2_call_put_premium_imbalance` is retained as an audit-derived field rather than a primary
predictor because it is algebraically determined by call and put premium. `option_activity_present`
is metadata, not an unusual-event label. High correlation without an exact identity is diagnostic
only and does not trigger target-based feature deletion.

## Comparable matrices

The runner emits B0-complete, B0+B1Q-complete, B0+B1Q+B2-core-complete and the exact common
intersection. The row-set contract is `B2 ⊆ B1Q ⊆ B0`, with deterministic ordering, one target per
origin, identical RV30 target hashes on the intersection, no imputation and no artificial balancing.
