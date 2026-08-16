# B2 calibration contract (Phase 3F)

Status: `AUTHORIZED_CALIBRATION_ONLY`

Cache boundary: `LEGACY_CACHE_READ_ONLY`; `ACTIVE_CALIBRATION_CACHE_V2_ONLY`.

Full Tape deduplication is keyed by the provider event `id` and uses a
disk-backed SQLite primary-key table while streaming. The downloader therefore does not
retain an unbounded in-memory set of event identifiers; the per-day checkpoint records
`dedup_storage=disk_backed_sqlite_primary_key` and `dedup_memory_bound=true`.

The twenty-session calibration window is exactly 2026-06-11 through 2026-07-10. The five
Pilot V2 sessions (2026-07-13 through 2026-07-17) are application data, never fitting data.

## Point-in-time rule

For each five-minute forecast origin `t`, the primary B2 panel includes only Full Tape rows
with `created_at <= t - 60 seconds`. `created_at` is retained as an
`operational_availability_proxy`; it is not called publication time. Cutoffs of 15 seconds and
0 seconds are sensitivities. Provider cumulative fields (`volume`, `ask_vol`, `bid_vol`,
`mid_vol`, `no_side_vol`) are not used as predictors because their historical PIT semantics are
not established. Open interest is treated as prior-session information.

## Continuous features

The panel retains all valid origins and natural prevalence. It computes trade counts, unique
contracts, premium/size totals and maxima, call/put premium imbalance, side/midpoint shares,
multileg/sweep shares, strike/expiry concentration, DTE/moneyness medians, repeated-contract
measures, IV median/change, valid-trade share and missing-IV share. A trade's call/put, ask-side
or sweep fields are descriptive proxies only; they do not imply direction, informed intent or
opening activity.

## Calibration and application

For each asset and 30-minute New York session band, fit feature medians and robust scales from
the twenty calibration sessions only. Use `1.4826 * MAD`, then IQR/1.349, then the asset-level
distribution; a constant feature is recorded as `asset_constant_fallback` and has zero score
variation. Core intensity inputs are `log1p(total_premium_5m)`, `log1p(option_trade_count_5m)`,
`log1p(unique_contract_count_5m)`, `log1p(max_trade_premium_5m)` and
`log1p(repeated_contract_premium)`.

`unusual_intensity_score` is the median of the three largest positive robust z-scores (or all
positive scores when fewer than three exist; zero when none exist). The secondary
`unusual_event` label is `score >= historical p95` for the same asset/band. No threshold is
selected from RV30, QLIKE or predictive performance. Frozen parameters are applied unchanged to
Pilot V2, with calibration bounds, sample size, fallback, cutoff and source hashes retained. The
Pilot V2 application artifact labels the binary output
`CALIBRATED_SECONDARY_EXPLORATORY`; this does not promote it to the primary B2 input or change
the natural-prevalence continuous-feature design. Calibration rows remain descriptive fitting
data and are not treated as a final evaluation. Each Pilot V2 application row carries the
deterministic bundle hash of the twenty raw ZIP SHA-256 values and the relative source-manifest
path, so the calibration history cannot be silently substituted.

Sensitivity definitions are asset-only, exact-five-minute and 60-minute bands; p90/p95/p97.5;
and 60/15/0-second availability cutoffs. Percentile thresholds use deterministic linear
interpolation over the requested empirical quantile; sensitivity results cannot replace the primary
30-minute/p95/60-second definition.

The download telemetry distinguishes the measured streaming stage from later aggregation:
`zipfile` inflate and CSV filtering are measured together because separating them would require
a second full read of each multi-gigabyte archive. Calibration aggregation time is emitted by
the bounded Polars runner in `b2_calibration_telemetry.json`.

Derived Parquet partitions are written through one explicitly reused writer per asset. A prior
recovery run exposed that constructing a `ParquetWriter` inside `dict.setdefault` could truncate
an existing partition on every flush; the writer-reuse regression test and footer/page-read
validation are now mandatory before the calibration panel is accepted.

## Explicit exclusions

This contract does not authorize model training, tuning, QLIKE, final testing, a larger
backfill, definitive asset freezing, Word/PowerPoint changes or publication.
