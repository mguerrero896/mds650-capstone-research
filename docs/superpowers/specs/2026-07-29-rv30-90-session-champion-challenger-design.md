# RV30 90-Session Champion–Challenger Design

## Status and approvals

This design records the owner's approvals on 2026-07-29:

- 90 XNYS trading sessions: 80 development sessions and 10 prospective
  holdout sessions.
- Gamma GLM with a log link as the confirmatory model.
- LightGBM as a nonlinear robustness challenger.
- QLIKE as the primary loss.
- Paired whole-day cluster bootstrap with all assets from a day kept together.
- Holm correction across the two confirmatory information-set comparisons.
- One read of the prospective holdout after the preregistration and method
  freeze.
- The compact, target-blind nine-feature B2 specification defined below.

No RV30 outcome, QLIKE result, or holdout observation was used to select the
nine B2 features.

## Existing data versus the final research dataset

The repository already contains a reusable 25-session engineering dataset:

- 20 calibration sessions and 5 Pilot V2 sessions;
- 14,200 nominal forecast origins across eight assets;
- 13,240 B0/RV30 availability-aware rows;
- 11,993 rows in the current B0/B1Q/B2 Phase 4B common intersection;
- 25 retained Full Tape ZIP files.

This is not the final 90-session research dataset. The approved design reuses
those 25 sessions in development, requires 55 additional historical development
sessions, and reserves 10 separate prospective sessions as the holdout. The
holdout remains sealed and must not be inspected before the method freeze.

## Research questions and estimands

The project tests two nested predictive claims on identical eligible origins:

1. Does ordinary options-state information improve RV30 forecasting relative
   to an underlying-market benchmark?
2. Does trade-derived options activity add incremental forecasting value over
   that ordinary options-state benchmark?

The paired loss improvements are:

```text
Delta_B1 = QLIKE(B0) - QLIKE(B1a)
Delta_B2 = QLIKE(B1a) - QLIKE(B2)
```

Positive values indicate lower loss for the expanded information set.
`Delta_B2` is the primary confirmatory estimand; `Delta_B1` is the key secondary
confirmatory estimand. Holm correction applies to these two claims. Negative,
zero, and positive results must all be retained and reported.

## Canonical observation and target

One row represents one asset `i` at one five-minute forecast origin `t` during
an XNYS regular session:

```text
origin_id = asset | session_date | forecast_origin_utc
```

The target is non-annualised RV30:

```text
r(i,t+j) = ln(C(i,t+j) / C(i,t+j-1)), j = 1,...,30
RV30(i,t:t+30) = sum(r(i,t+j)^2), j = 1,...,30
```

Exactly 31 consecutive one-minute closes are required: the fully observed
origin close and 30 future closes. A row with any missing required close is
invalid; prices are never silently interpolated. Adjacent targets overlap, so
temporal validation purges and embargoes at least 30 minutes at fold
boundaries.

## Point-in-time information sets

### B0 — underlying and market state

B0 contains the existing point-in-time underlying features:

- spot;
- lagged five-minute realised variance;
- lagged 30-minute realised variance;
- lagged five-minute return;
- lagged five-minute volume;
- session-minute control;
- asset identity controls shared by all information sets.

FMP bars use the approved conservative availability convention
`available_at = timestamp_raw + 1 minute`; `+2 minutes` is a sensitivity. This
is a research assumption, not a provider-confirmed statement about bar
semantics.

### B1a — ordinary options state

B1a is B0 plus Massive-reconstructed ATM implied volatility using historical
contracts and the last valid quote satisfying:

```text
sip_timestamp <= forecast_origin
bid > 0
ask > bid
quote_age <= 60 seconds
relative_spread <= 25%
```

B1b (B1a plus skew) and B1c (B1b plus term structure) are enriched robustness
benchmarks only. Their missing components are not imputed to force coverage.

### B2 — compact trade-derived activity

B2 is B1a plus these nine features, computed solely from eligible Full Tape
rows:

1. `b2_log_trade_count = log1p(option_trade_count_5m)`
2. `b2_unique_contract_share = unique_contract_count_5m / option_trade_count_5m`
3. `b2_log_mean_trade_premium = log1p(total_premium_5m / option_trade_count_5m)`
4. `b2_log_max_trade_premium = log1p(max_trade_premium_5m)`
5. `b2_call_put_premium_imbalance_scaled =
   (call_premium_5m - put_premium_5m) /
   (call_premium_5m + put_premium_5m)`
6. `b2_execution_side_premium_imbalance =
   ask_side_premium_share - bid_side_premium_share`
7. `b2_repeated_contract_premium_share =
   repeated_contract_premium / total_premium_5m`
8. `b2_strike_concentration = max trades at one strike / eligible trades`
9. `b2_expiry_concentration = max trades at one expiry / eligible trades`

A zero denominator produces a documented zero because it represents no
eligible activity for that ratio, not missing provider data. All raw counts and
sums are reconstructed locally; provider cumulative fields are excluded.

The primary eligibility rule is:

```text
window_end = forecast_origin - 60 seconds
window_start = window_end - 5 minutes
executed_at in [window_start, window_end)
max(executed_at, created_at) <= window_end
```

Cutoffs of 120 and 300 seconds are prespecified sensitivities. `created_at` is
an operational availability proxy, not publication time. Call/put, execution
side, sweep, multileg, and volume/open-interest relationships are not treated
as proof of intention or informed trading. `unusual_event` is excluded from the
primary B2 information set.

## Sample construction and missingness

All benchmark comparisons use the same forecast origins and target values.
The primary complete-case intersection requires valid B0, B1a, B2, and RV30.
Missing B1a or B2 data receives an explicit reason code; there is no silent
zero substitution, interpolation, nearest-neighbour repair, or artificial
event balancing.

Asset eligibility is determined before outcome evaluation using only PIT
validity, provider coverage, temporal coverage, missingness, and session-segment
stability. Predictive performance, RV30 correlations, and QLIKE cannot select
assets. The study may retain four to six of the eight candidates if they pass
the predeclared quality thresholds.

## Models and temporal validation

The confirmatory model is a Gamma GLM with log link, producing strictly positive
RV30 forecasts. Persistence, rolling historical mean, and HAR-RV are benchmark
diagnostics. LightGBM is a nonlinear robustness challenger and cannot replace
the confirmatory model based on a favorable result.

Development uses expanding walk-forward validation over 80 sessions. Scaling,
regularisation, transformations requiring fitted parameters, unusualness
calibration, and any hyperparameter choice are fit within each training history
only. The preregistration must freeze the exact fold dates, model grids, seeds,
forecast floor, and missingness policy before any model or QLIKE computation.

The ten-session prospective holdout is read once after:

1. Spec Kit consistency gates pass;
2. the preregistration is written and SHA-256 hashed;
3. the development pipeline and model choices are frozen;
4. leakage and reproducibility tests pass;
5. the holdout access guard is explicitly released.

No development decision may be revised after viewing holdout results.

## Inference and stability

QLIKE is primary; MAE and RMSE are secondary descriptive metrics. Uncertainty
uses a paired bootstrap that resamples complete trading days and keeps all
assets observed on the selected day together. Stability reporting covers:

- asset;
- first, middle, and final session thirds;
- volatility regimes defined from development-history B0 information only;
- FMP `+1` versus `+2` minute availability;
- B2 cutoffs of 60, 120, and 300 seconds.

An edge is described as supported only when the prespecified development
comparison is positive with uncertainty excluding zero, the one-time holdout
effect has the same sign, and stability analysis shows no material systematic
reversal. This criterion does not guarantee a positive result and cannot be
relaxed after observing outcomes.

## Engineering sequence

1. Update Spec Kit artifacts for this approved phase.
2. Write and hash the preregistration without computing QLIKE.
3. Verify secure provider-key presence without displaying values.
4. Reuse the 25 retained sessions when their hashes match.
5. Acquire and process 55 additional development sessions resumably by day.
6. Acquire the sealed 10 holdout sessions without reading analytical outcomes.
7. Build the canonical 90-session PIT panel and freeze its manifest.
8. Run development walk-forward evaluation.
9. Freeze the final method and release the one-time holdout read.
10. Report every attempted registered variant and every positive, negative, or
    null result.

Large raw data, Parquet files, and provider caches belong under the configured
Samsung `D:\MDS650` roots. Code, specifications, manifests, hashes, and compact
reports remain in the repository. No raw evidence is deleted until hashes,
manifests, and reproducibility have been independently verified.

## Fail-closed conditions

The run stops before modeling when any of these occurs:

- a predictor timestamp is later than its forecast origin;
- the holdout guard is breached;
- benchmark row sets or RV30 target hashes differ;
- fewer than four assets satisfy the predeclared data-quality rules;
- the common provider interval is not continuous for the selected sessions;
- secrets or personal paths appear in sanitized artifacts;
- Spec Kit analysis reports a critical contradiction;
- the minimum free-space-at-peak rule is violated.

## Verification contract

Tests must prove deterministic ordering and hashes, unique origin IDs, exact
31-price RV30 targets, PIT-safe B0/B1a/B2 joins, no future quotes or trades,
training-only fitting, 30-minute purge/embargo, sealed holdout access, paired
common-origin comparisons, bootstrap day clustering, Holm adjustment, and
complete reporting of registered variants. Pytest, Ruff, Mypy, coverage, JSON
Schema validation, and Spec Kit analysis must pass before analytical claims are
released.
