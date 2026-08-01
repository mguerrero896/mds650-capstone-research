# RV30 Mechanism-Aware Global Replication Design

## Status and authority

**Status:** OWNER-APPROVED DESIGN

**Owner approval:** 2026-08-01

**Previous study:** Phase 5 is immutable and remains `PASS_HOLDOUT_READ_ONCE`.

**Implementation authority:** specification and planning only until the Spec Kit coherence gates pass.

This design supersedes any proposal to obtain a favourable result merely by adding more days to
the unchanged Phase 5 feature set. It does not alter, rerun or reinterpret the Phase 5 holdout.
Every positive, negative and null Phase 5 result remains part of the final evidence.

## Objective

Run a new, preregistered and outcome-blind historical replication that determines:

1. whether a strengthened ordinary option-state benchmark, B1v2, improves a strengthened
   underlying/market benchmark, B0v2, for five-minute-origin RV30 forecasts;
2. whether historically abnormal option-trade activity, B2v2, improves B1v2;
3. whether either improvement is stable across assets, session terciles, volatility regimes and
   conservative availability delays.

The primary claim remains global across the same six outcome assets. META, MSFT and the last
session tercile form a separately corrected secondary replication family and cannot substitute
for a failed global comparison.

## Phase 5 evidence motivating the redesign

The sealed ten-day holdout produced:

- Gamma B1a versus B0: delta QLIKE `-0.0070486556`, Holm `0.7631`;
- Gamma B2 versus B1a: delta QLIKE `+0.0006130677`, Holm `0.8703`;
- LightGBM B1a versus B0: delta QLIKE `-0.0114367802`;
- LightGBM B2 versus B1a: delta QLIKE `-0.0005273483`.

The Gamma B2 daily-cluster effect was approximately `0.00062349` with daily standard deviation
`0.02616533`. A normal approximation gives about 13,823 sessions for 80% power at two-sided
five-percent size if the unchanged effect and dispersion persisted. Therefore, unchanged data
extension is rejected as scientifically and operationally inefficient.

The secondary Gamma B2 estimates were positive for META (`+0.02315431`), MSFT (`+0.02563099`)
and the last session tercile (`+0.02474496`). With a 50% effect haircut and a three-hypothesis
Holm planning size, approximate 80%-power requirements are 94, 25 and 66 daily clusters,
respectively. These calculations are planning evidence from only ten days, not confirmatory
claims or frozen minimum-effect thresholds.

## Data partition and calendar

The calendar is XNYS. The acquisition allow-list contains exactly 180 sessions:

| Role | Sessions | Start | End | Analytical use |
|---|---:|---|---|---|
| Causal feature warm-up | 20 | 2025-07-07 | 2025-08-01 | Prior-history normalization only; never model fitting or evaluation |
| Initial training | 60 | 2025-08-04 | 2025-10-27 | Model fitting and inner chronological selection |
| OOS fold 1 | 20 | 2025-10-28 | 2025-11-24 | Locked out-of-sample predictions |
| OOS fold 2 | 20 | 2025-11-25 | 2025-12-23 | Locked out-of-sample predictions |
| OOS fold 3 | 20 | 2025-12-24 | 2026-01-23 | Locked out-of-sample predictions |
| OOS fold 4 | 20 | 2026-01-26 | 2026-02-23 | Locked out-of-sample predictions |
| OOS fold 5 | 20 | 2026-02-24 | 2026-03-23 | Locked out-of-sample predictions |

Fold training sets expand from 60 to 140 sessions. A single locked execution creates all five
folds without human or programmatic adaptation to intermediate OOS results. The combined
primary evaluation contains 100 whole-day clusters.

The ten warm-up sessions before the previously recorded 2025-07-21 study boundary require an
authenticated common-provider metadata probe and an explicit recorded configuration change.
They may supply only pre-origin normalization history. If any of the twenty warm-up sessions
or any evaluation session fails the provider-continuity contract, the run stops with
`REPLICATION_SESSION_ALLOWLIST_INCOMPLETE`; dates are not shifted or substituted.

The new evaluation dates end before Phase 5 development begins on 2026-03-24, so they do not
overlap any Phase 5 model-development or holdout date. Earlier metadata-only provider probes do
not constitute analytical outcome reads, but every existing local payload hash must be recorded.

## Assets and source roles

Outcome assets remain frozen as AAPL, AMZN, META, MSFT, NVDA and TSLA. They are not reselected
using Phase 5 performance. SPY and QQQ are market-control sources only and are never added to the
outcome universe in this replication.

- FMP: underlying and SPY/QQQ one-minute OHLCV; conservative
  `available_at = timestamp_raw + 1 minute` with `+2 minutes` sensitivity.
- Massive: historical contract resolution and NBBO quotes, with
  `sip_timestamp <= forecast_origin`, positive non-crossed bid/ask, quote-age and spread gates.
- Unusual Whales: Full Tape individual operations, with primary
  `created_at <= forecast_origin - 60 seconds`; `created_at` remains an operational-availability
  proxy and is not publication time. Delays of 120 and 300 seconds are sensitivities.

No provider cumulative field with unverified reset semantics is a predictor. No call, put,
ask-side, bid-side, sweep or multileg field is interpreted as trader intention or informed flow.

## Canonical row and target

One row is one selected asset at one valid five-minute forecast origin during the XNYS regular
session. Every accepted predictor must be available no later than the origin under its source
contract. The target remains:

`r(i,t+j) = ln[C(i,t+j) / C(i,t+j-1)]`, for `j = 1,...,30`

`RV30(i,t:t+30) = sum(r(i,t+j)^2, j=1,...,30)`

The target requires the fully observed close at origin and the next thirty consecutive
one-minute closes. Missing prices, halts that break the sequence or session-boundary violations
drop the origin with an explicit reason. Prices are never silently interpolated.

## B0v2 — strengthened underlying and market benchmark

B0v2 contains only point-in-time variables:

1. log spot;
2. underlying five-minute log return;
3. underlying lagged realised variance over 5 and 30 minutes;
4. log underlying five-minute dollar volume;
5. SPY five-minute return and lagged 30-minute realised variance;
6. QQQ five-minute return and lagged 30-minute realised variance;
7. session-minute sine and cosine;
8. frozen asset identity indicators.

All lag windows end at or before the origin after the FMP availability delay. Earnings, actual
EPS/revenue and news remain excluded from the primary benchmark.

## B1v2 — ordinary option state

The benchmarks are nested:

- **B1v2a:** B0v2 plus 30–60 DTE ATM IV level, five-minute change and thirty-minute change;
- **B1v2b:** B1v2a plus same-expiry symmetric-moneyness skew level and thirty-minute change;
- **B1v2c:** B1v2b plus ATM short-to-medium and medium-to-long term slopes and their
  thirty-minute changes.

Every state is constructed through a local as-of join using the last qualifying Massive quote.
Changes use only earlier point-in-time states. Rates and dividend inputs must have been known at
the origin. No future quote, snapshot substitution or silent imputation is permitted.

B1v2a is the primary conventional-options benchmark only if coverage is at least 80% globally,
65% for every asset and 60% in every session tercile. B1v2b and B1v2c are robustness benchmarks
only if they meet the prior 70% global, 50% per-asset and 40% per-tercile gates. Failure of B1v2a
returns `REVISE_B1V2`; it does not trigger an automatic B2-versus-B0 substitution.

## B2v2 — target-blind abnormal trade activity

B2v2 adds exactly nine target-blind features to B1v2a:

1. robust z-score of log trade count;
2. robust z-score of unique-contract share;
3. robust z-score of log mean trade premium;
4. robust z-score of log maximum trade premium;
5. robust deviation of scaled call/put premium imbalance;
6. robust deviation of execution-side premium imbalance;
7. robust z-score of repeated-contract premium share;
8. robust z-score of strike concentration;
9. robust z-score of expiry concentration.

For every origin, normalization uses only prior sessions for the same asset and 30-minute New
York time band. The primary history is the most recent 60 eligible sessions, with a minimum of
20. Scale is `1.4826 × MAD`, then `IQR / 1.349`, then the prior asset-level scale; a constant
feature receives zero deviation and an explicit fallback code. The twenty warm-up sessions make
the first training day causal. No RV30, QLIKE, model residual or OOS result enters this process.

The five-minute aggregation window is primary. Fifteen- and thirty-minute aggregations are
registered robustness variants and cannot replace the primary result. The natural activity
distribution is retained; there is no event/no-event balancing.

## Models and fitting

The confirmatory estimator remains `GammaRegressor` with log link, `max_iter=2000`,
`tol=1e-8` and the frozen alpha grid `[0.0, 0.01, 0.1, 1.0]`. Training-only standardization and
regularized, predeclared asset/session interactions allow a pooled global effect with bounded
heterogeneity. Interactions are limited to the nine B2v2 features crossed with asset identity
and session tercile; no interaction is selected from predictive results.

LightGBM remains the robustness challenger with gamma objective and the frozen grid:

- learning rate: `[0.03, 0.05]`;
- maximum depth: `[3, 5]`;
- minimum child samples: `[50]`;
- estimators: `[200, 500]`;
- leaves: `[7, 15]`;
- L2 regularization: `[1.0]`.

Each fold performs chronological inner selection using only its training dates. A 30-minute
purge/embargo applies wherever adjacent origins could leak target information. Deep learning and
reinforcement learning are excluded: the available daily-cluster count does not justify their
additional model-selection risk.

## Estimands, uncertainty and multiplicity

The global confirmatory family contains exactly:

- `delta_b1v2 = QLIKE(B0v2) - QLIKE(B1v2a)`;
- `delta_b2v2 = QLIKE(B1v2a) - QLIKE(B2v2)`.

Positive values favour the expanded information set. QLIKE is primary; MAE and RMSE are
descriptive. Uncertainty uses 10,000 paired whole-day bootstrap draws, keeping all assets and
origins for a date together. Holm controls the two global p-values.

The secondary replication family contains exactly three Gamma B2v2 contrasts: META, MSFT and
the last session tercile. It receives its own Holm correction across three p-values and cannot
establish a global claim. All other asset, tercile, volatility-regime, B1v2b/B1v2c, timing and
window results are robustness analyses with explicit labels.

The minimum detectable effect is computed before OOS access using simulation and daily-cluster
dispersion from training predictions only. The planning range `0.008–0.010` is not a frozen
success threshold. The final threshold is the pre-OOS training MDE recorded in the method
freeze; the OOS data never set it.

## Success rules

`GLOBAL_B1V2_EDGE_CONFIRMED` requires all of:

1. Gamma `delta_b1v2 > 0`;
2. its 95% paired-day bootstrap lower bound is above zero;
3. its Holm-adjusted p-value is below 0.05;
4. its magnitude is at least the training-only MDE;
5. LightGBM has the same positive sign;
6. at least four of six asset point estimates are positive;
7. no more than one asset has a 95% interval wholly below zero;
8. no registered FMP delay produces a 95% interval wholly below zero.

`GLOBAL_B2V2_EDGE_CONFIRMED` applies the same eight rules to `delta_b2v2`, with the additional
requirement that no registered UW delay produces an interval wholly below zero.

Stability fails systematically when two or more preregistered strata have intervals wholly below
zero and together contain at least 50% of evaluated origins. A positive secondary replication is
reported as `TARGETED_B2V2_REPLICATION_CONFIRMED`, never as a global edge.

If no global rule passes, the scientifically valid conclusion is `GLOBAL_EDGE_NOT_CONFIRMED`.
No asset, feature, window, model or threshold is changed to obtain a preferred sign.

## Acquisition, storage and reproducibility

The acquisition is re-entrant by provider, session, asset and contract-day. Existing files are
reused only after SHA-256, manifest and schema validation. Raw ZIPs are immutable. Derived
Parquet, FMP and Massive caches remain on `D:`; code, contracts, reports and manifests remain in
the repository.

Using the observed ten-day Phase 5 rates, 180 Full Tape sessions imply approximately 252 GiB raw
and 37 GiB filtered Parquet before safety margin. A fresh storage audit must pass before the first
batch, and no batch starts if projected minimum free space during the peak is below 80 GiB.

Every run records code, lockfile, contract, raw-source, transformation, panel, prediction and
result hashes. Provider secrets are presence-checked without printing values. Sanitized artifacts
must contain neither secret values nor personal paths.

## Execution gates

The order is binding:

1. update Spec Kit specification, plan, checklist and tasks;
2. run clarify, plan, checklist, tasks and analyze with no critical contradiction;
3. authenticate a metadata-only continuity probe for all 180 dates and all source roles;
4. verify storage, secrets and restartability;
5. acquire raw evidence without reading analytical outcomes;
6. build and validate causal B0v2/B1v2/B2v2 predictors;
7. freeze dates, code, features, models, MDE, folds and hashes;
8. execute the complete five-fold OOS run once without intermediate adaptation;
9. report every registered result and retain the prior Phase 5 evidence unchanged.

Implementation stops on a provider-continuity failure, B1v2a coverage failure, PIT violation,
schema drift, secret leak, hash mismatch, storage-floor breach or critical Spec Kit contradiction.

## Explicit exclusions

- no reuse of Phase 5 holdout outcomes as evaluation evidence;
- no post-OOS feature engineering, retuning, asset selection or threshold changes;
- no claim that a favourable META/MSFT/session result is global;
- no B2-versus-B0 fallback when B1v2 fails;
- no synthetic provider data, silent zero fill or price interpolation;
- no trading, broker connection, deployment, email or external publication;
- no deletion or overwrite of Phase 5 evidence;
- no guarantee that the replication will be positive.
