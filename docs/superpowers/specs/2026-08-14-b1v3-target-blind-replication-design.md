# B1v3 Target-Blind Ordinary-Options Replication Design

## Status and authority

**Design status:** `OWNER_APPROVED_IN_CHAT`

**Owner authorization date:** 2026-08-14

**Implementation status:** `NOT_STARTED`

**Outcome-access status:** `BLOCKED_UNTIL_SPEC_REVIEW_AND_METHOD_FREEZE`

The owner granted full methodological authorization after reviewing the proposed B1v3 direction.
That authorization permits this design to be frozen and then implemented through the project's
Spec Kit and test-driven workflow. It does not permit choosing features, dates, assets, models,
cutoffs, or claims because they produce a favourable RV30 or QLIKE result.

This design is additive. It does not overwrite, suppress, or reinterpret any legacy B1, Phase 5,
Phase 6, independent-replication, or corrected-forensic artifact. Every prior positive, negative,
and null result remains part of the evidence record.

## Research objective

Run one new, preregistered, source-bound replication that answers two nested questions on identical
forecast origins:

1. Does an economically coherent ordinary option-state benchmark, B1v3, improve RV30 forecasting
   relative to the underlying/market benchmark, B0?
2. Does the existing nine-feature trade-derived activity set, B2, add incremental forecasting
   value over B1v3?

The replication also tests whether any improvement is stable across assets, session thirds,
training-defined volatility regimes, and conservative provider-timing assumptions.

The scientific result may be positive, negative, or null. A valid null or adverse result is a
completed scientific result, not an implementation failure. No claim in this design concerns live
trading profitability, execution, transaction costs, or causal informed trading.

## Why B1v3 is necessary

The existing B1v2 builder is technically functional but does not consistently represent a fixed,
economically comparable option state:

- legacy ATM interpolation can combine option contracts without first requiring a same-expiry,
  same-strike call/put consensus;
- a small but material share of legacy ATM and skew selections can mix maturities;
- legacy term slopes subtract raw IV levels observed at varying maturities instead of deriving
  forward variance from total variance;
- a favourable or adverse model result cannot determine which of those constructions is retained.

The target-free Phase 6 option-attempt corpus contains 2,308,176 rows, 77,328 forecast origins,
six assets, 180 sessions, 10,950 contracts, and expiries spanning 7 to 179 DTE. Its observed
geometry supports a B1v3 feasibility check without reading RV30, forecasts, QLIKE, or model
results. Feasibility is not evidence of predictive improvement.

## Approaches considered

### Approach A — coherent deterministic B1v3 (selected)

Reuse the existing Massive contract-day caches, quote-reselection audit, point-in-time spot/rate/
dividend inputs, and evaluation pipeline. Reconstruct ATM level, skew, and term structure from
same-expiry contract sets with deterministic tie-breaks and total-variance arithmetic.

**Advantages:** minimum new code and acquisition; auditable; economically interpretable;
target-blind; compatible with current Gamma and LightGBM comparisons.

**Cost:** stricter geometry can reduce coverage. Missing states remain missing and may stop the
replication at the coverage gate.

### Approach B — patch only the legacy B1v2 aggregates (rejected)

Retain nearest-contract ATM and raw-IV term differences while repairing only obvious maturity
mixing.

**Reason rejected:** it would preserve the main economic ambiguity and could not support a strong
ordinary-option-state claim even if QLIKE improved.

### Approach C — fit a full implied-volatility surface or deep model (deferred)

Estimate a parametric surface, neural surface, or American-option model before forecasting RV30.

**Reason deferred:** it introduces additional calibration, tuning, and model-risk degrees of
freedom that the current number of independent daily clusters does not justify. It is not needed
to answer the approved incremental-information question.

## Canonical observation and RV30 target

One analytical row represents one frozen outcome asset at one valid five-minute forecast origin
inside an XNYS regular session:

```text
origin_id = asset | session_date | forecast_origin_utc
```

The official target remains non-annualised RV30:

```text
r(i,t+j) = ln(C(i,t+j) / C(i,t+j-1)), j = 1,...,30
RV30(i,t:t+30) = sum(r(i,t+j)^2), j = 1,...,30
```

Exactly 31 consecutive one-minute closes are required: the fully observed close at origin `t`
and the next 30 closes. Missing prices, a halt that breaks the sequence, an invalid calendar
minute, or a session-boundary violation excludes the origin with an explicit reason. Prices are
never silently interpolated. Overlapping RV30 windows require a 30-minute purge/embargo at every
training/evaluation boundary.

## Frozen outcome universe and information ladder

The outcome universe remains AAPL, AMZN, META, MSFT, NVDA, and TSLA. SPY and QQQ remain market
controls. No asset may be added or removed using RV30 association, QLIKE, feature importance, or
preliminary forecast performance.

The information sets are strictly nested:

| Set | Composition | Confirmatory role |
| --- | --- | --- |
| B0 | Existing point-in-time underlying and market controls | Parent benchmark |
| B1v3a | B0 plus 30-day ordinary option-state level and exact lags | Primary B1 challenger |
| B1v3b | B1v3a plus same-expiry symmetric skew and its lag | Enriched robustness benchmark |
| B1v3c | B1v3b plus forward-variance term structure and lags | Enriched robustness benchmark |
| B2 | B1v3a plus the nine frozen trade-derived B2 features | Primary activity challenger |

B1v3b and B1v3c cannot replace B1v3a because their result is more favourable. B2 uses B1v3a as
its parent so the primary B2 comparison remains available when enriched B1 components have lower
coverage.

## Point-in-time source boundary

### FMP underlying and market data

FMP one-minute bars use the registered conservative research convention:

```text
primary available_at = timestamp_raw + 1 minute
sensitivity available_at = timestamp_raw + 2 minutes
```

This is not described as provider-confirmed publication latency. All lagged B0 and spot inputs end
at or before the applicable forecast-origin cutoff. Exact-session filtering, XNYS daylight-saving
handling, early closes, duplicate rejection, and the 31-price target contract remain binding.

### Massive ordinary option state

The primary quote cutoff is the forecast origin. Source-time sensitivity cutoffs are origin minus
60 seconds and origin minus 300 seconds. For each cutoff, the quote is reselected from the raw
contract-day cache as the last observation ordered by `(sip_timestamp, sequence_number)` with:

```text
sip_timestamp <= applicable_cutoff
```

The later origin-selected quote is never reused for a shifted cutoff. The last eligible quote is
not replaced by an earlier quote merely because its bid/ask, spread, or IV inversion fails.
Quote age is measured relative to the applicable cutoff, not always relative to the unshifted
origin.

Primary quote-quality filters are:

- `bid > 0`;
- `ask > bid`;
- finite bid, ask, midpoint, and spread;
- quote age no greater than 60 seconds;
- relative spread no greater than 25%;
- the contract existed `as_of` the session date and expires after the origin;
- option type, strike scaling, underlying mapping, expiry, and OCC identity are valid;
- IV inversion succeeds within no-arbitrage bounds using inputs known at the origin.

The registered 300-second age and 50% spread filters are robustness diagnostics, not a way to
replace the primary sample after seeing outcomes. `sip_timestamp` supports source-time ordering;
it is not represented as Massive REST client-receipt time.

### Rates and dividends

Every IV attempt binds the exact rate and dividend record, its observation/effective date, its
availability rule, and its source-request hash. A value known after the origin is forbidden.
Missing provenance produces a missing B1 state rather than a carried-forward, future, or synthetic
value. A zero dividend yield is allowed only for an asset/date covered by the predeclared
zero-dividend policy and supporting source evidence; missing dividend data is not automatically
zero.

### Unusual Whales B2 inputs

The nine frozen B2 features and their definitions remain unchanged. Primary Full Tape eligibility
uses `created_at <= forecast_origin - 60 seconds`; 120- and 300-second cutoffs remain registered
timing sensitivities. `created_at` is an operational record-creation proxy, not publication or
client-receipt time. The B2 availability sidecar must mark delayed-source rows as unavailable;
they may not be encoded as genuine zero activity.

## B1v3 contract geometry

### Eligible contract state

At an origin and applicable cutoff, each contract contributes at most one reselected quote and one
IV inversion. Contract selection uses the existing deterministic DTE/moneyness rule and retains
the registered grid `0.95, 0.975, 1.00, 1.025, 1.05` for calls and puts. Duplicate contract/quote
identities, ambiguous source hashes, incomplete pagination, future quotes, and schema drift fail
closed.

### Same-expiry, same-strike ATM consensus

For each expiry:

1. Pair a valid call and put only when expiry and strike are identical.
2. Define pair IV as the arithmetic mean of call IV and put IV.
3. Prefer paired strikes immediately below and above spot and linearly interpolate pair IV in
   log-moneyness to `K/S = 1.00`.
4. If a bracketing pair is unavailable, use the nearest paired strike only when
   `abs(log(K/S)) <= abs(log(1.025))`; set `atm_interpolated = false`.
5. Otherwise the expiry-level ATM state is missing with an exact reason code.

The call/put IV dispersion, selected strikes, selected DTE, interpolation flag, source hashes,
and maximum SIP timestamp are diagnostics. They are not additional predictors unless explicitly
listed below.

### B1v3a — nearest-30-day log implied variance

Select the expiry whose DTE is closest to 30 within the fixed tolerance `30 +/- 10` days. Resolve
ties by smaller absolute DTE distance, earlier expiry, then lexical contract identity. Define:

```text
b1v3_log_atm_variance_30d = log(atm_iv_near_30d^2)
```

Within the same asset and XNYS session, compute exact five-minute and 30-minute changes from
states at `t-5m` and `t-30m`. Missing exact lags remain missing; there is no nearest-time or
overnight substitution.

B1v3a contains exactly:

- `b1v3_log_atm_variance_30d`;
- `b1v3_log_atm_variance_change_5m`;
- `b1v3_log_atm_variance_change_30m`.

### B1v3b — same-expiry symmetric skew

Use the selected near-30-day expiry. Estimate OTM put IV at moneyness 0.975 and OTM call IV at
moneyness 1.025 using only same-option-type strikes from that expiry. Linear interpolation in
log-moneyness is allowed only between bracketing strikes; otherwise the closest strike is allowed
within 1.25 percentage points of the target moneyness and is flagged as non-interpolated.

Define:

```text
b1v3_log_symmetric_skew_30d = log(put_iv_0.975 / call_iv_1.025)
```

B1v3b adds that level and its exact within-session 30-minute change. A put and call from different
expiries can never form skew.

### B1v3c — forward-variance term structure

Construct ATM consensus states at registered tenor targets and tolerances:

- short: `7 +/- 7` days, with DTE at least 7;
- medium: `30 +/- 10` days;
- long: `90 +/- 30` days.

For each selected tenor use its actual positive time to expiry `T` in years and define total
variance:

```text
w(T) = ATM_IV(T)^2 * T
```

Require `T_short < T_medium < T_long` and nondecreasing total variance. Do not clip or repair a
calendar-arbitrage violation. Define:

```text
forward_variance_short_medium = (w_medium - w_short) / (T_medium - T_short)
forward_variance_medium_long  = (w_long - w_medium) / (T_long - T_medium)
```

B1v3c adds the logarithm of both strictly positive forward variances and each feature's exact
within-session 30-minute change. Zero, negative, non-finite, reversed-tenor, or missing values
receive explicit reason codes and remain missing.

## Nested completeness and coverage gates

The predicates are immutable:

```text
b1v3a_complete = all three B1v3a features finite
b1v3b_complete = b1v3a_complete AND both B1v3b features finite
b1v3c_complete = b1v3b_complete AND all four B1v3c features finite
```

The run fails if any global or subgroup result violates:

```text
coverage(B1v3c) <= coverage(B1v3b) <= coverage(B1v3a)
```

B1v3a is eligible as the primary ordinary-options benchmark only when:

- global coverage is at least 80%;
- every asset has at least 65% coverage;
- every session third has at least 60% coverage;
- no future quote or exogenous input is present;
- coverage is not concentrated exclusively near the close.

B1v3b and B1v3c may be reported as robustness levels only when each has at least 70% global,
50% per-asset, and 40% per-session-third coverage. No imputation is used to force a gate. Failure
of B1v3a returns `REVISE_B1V3`; it does not authorize B2-versus-B0 as a substitute primary claim.

## Target-blind build stage

The first implementation stage reads only forecast origins, option-state attempts, source-bound
quotes, point-in-time exogenous inputs, calendar metadata, and predictor contracts. The builder
must reject any input containing RV30, target, QLIKE, prediction, residual, model-result, or OOS
fields. It produces a predictor-only B1v3 matrix, diagnostics, coverage tables, and immutable
hashes.

The existing 2,308,176-row attempt corpus is used first. No provider call or new download occurs
until its source hashes, cache identities, and date coverage are validated and the target-blind
coverage gates are computed.

## Independent confirmation sample

The new confirmation dates are selected without reading a target or metric:

1. Build and hash a session-exposure ledger containing every date previously used in any model
   development, prediction, OOS read, robustness block, corrected reevaluation, or reported
   scientific result.
2. Enumerate XNYS sessions inside authenticated common provider history.
3. Exclude every exposed date, every date with a known corrupt unique payload, and every date that
   fails the date-level provider/PIT preflight.
4. Require at least 60 preceding eligible sessions for model fitting and B2 trailing-history
   construction. Those preceding sessions are not part of the confirmation estimand.
5. From the remaining dates, select the chronologically earliest contiguous block of 30 sessions.
   This deterministic rule is fixed before downloading analytical payloads.
6. Freeze the exact 60-training/30-confirmation calendar, source expectations, hashes, and access
   guard before constructing any RV30 target for the confirmation block.

If no such block exists, stop with `NO_PRISTINE_30_SESSION_BLOCK`. Dates are not shifted,
substituted, or shortened after outcomes are observed. A study-window change required by the
deterministic block must be recorded explicitly before acquisition; the existing default window
is never silently widened.

Existing raw ZIP, Parquet, FMP, and Massive caches may be reused only when hashes, manifests,
licenses, and source identities match. Reuse reduces acquisition cost but cannot alter the date
selection rule.

## Models, temporal fitting, and primary estimands

The model roles remain fixed:

- confirmatory: Gamma GLM with log link and the existing preregistered alpha grid;
- nonlinear robustness: LightGBM with Gamma objective and the existing preregistered grid;
- persistence, rolling mean, and HAR-RV: diagnostics only.

All scaling, regularisation, transformations with fitted parameters, B2 trailing normalization,
and hyperparameter selection use chronological training data only. The final 30-session block is
read analytically once after the method freeze. No intermediate confirmation result is exposed.

The two global confirmatory estimands are paired daily means of:

```text
delta_B1v3 = QLIKE(B0) - QLIKE(B1v3a)
delta_B2   = QLIKE(B1v3a) - QLIKE(B2)
```

Positive values favour the expanded information set. QLIKE is primary; MAE and RMSE are
descriptive. Uncertainty uses 10,000 paired whole-day bootstrap draws, retaining all assets and
origins for a selected date together. Holm correction applies to the two global confirmatory
p-values. The minimum detectable effect is estimated from training-only daily clusters and frozen
before confirmation access.

## Stability and claim taxonomy

Registered stability reports cover:

- each of the six outcome assets;
- first, middle, and final session thirds;
- volatility regimes defined from training-history B0 only;
- FMP `+1` and `+2` minute timing assumptions;
- Massive origin, origin-minus-60-second, and origin-minus-300-second reselection;
- UW 60-, 120-, and 300-second B2 cutoffs;
- B1v3b and B1v3c robustness levels when their coverage gates pass.

`GLOBAL_B1V3_EDGE_CONFIRMED` requires all of:

1. Gamma `delta_B1v3 > 0`;
2. its 95% paired-day bootstrap lower bound is above zero;
3. its Holm-adjusted p-value is below 0.05;
4. its magnitude is at least the frozen training-only MDE;
5. LightGBM has the same positive sign;
6. at least four of six asset point estimates are positive;
7. no more than one asset has an interval wholly below zero;
8. no registered FMP or Massive timing sensitivity has an interval wholly below zero.

`GLOBAL_B2_EDGE_CONFIRMED` applies the same rules to `delta_B2` and additionally requires that no
registered UW timing sensitivity has an interval wholly below zero.

A positive result that fails a global rule is reported as `POSITIVE_BUT_NOT_GLOBALLY_CONFIRMED`,
with the exact failed conditions. A negative or null result is `GLOBAL_EDGE_NOT_CONFIRMED`.
Subgroup findings remain secondary and multiplicity-labelled; they never replace a failed global
claim. No test establishes causal informed trading or live profitability.

## Error handling and stop conditions

The run stops before confirmation modeling on any of:

- critical Spec Kit contradiction;
- missing or conflicting source hash;
- duplicate origin, contract/quote identity, or session-exposure record;
- schema or pagination drift;
- quote, bar, rate, dividend, or B2 record later than its applicable cutoff;
- ambiguous rate/dividend provenance;
- invalid B1v3 nested coverage;
- B1v3a coverage-gate failure;
- fewer than six frozen outcome assets in the common primary panel;
- no pristine 30-session confirmation block;
- any overlap between training and confirmation targets after purge/embargo;
- target or QLIKE access before the method freeze;
- second analytical access to the confirmation block;
- secret or personal path in a sanitized artifact;
- projected minimum free space below 80 GiB during any acquisition batch.

An implementation failure produces a reason-coded invalid run. It cannot be converted into a
scientific null, and a scientific null cannot be relabelled as an implementation failure.

## Minimal implementation architecture

Ponytail's minimality rule applies: reuse the existing provider clients, cache envelopes,
quote-reselection logic, exogenous-provenance package, Phase 6 model/evaluation code, metrics,
bootstrap, Holm, manifests, and access guards.

Only the following new logical units are justified:

1. a focused pure B1v3 feature module for contract pairing, tenor selection, total variance,
   exact lags, coverage, and reason codes;
2. a thin target-blind builder that binds existing inputs and emits predictor-only artifacts;
3. an additive B1v3 contract/schema and preregistration package;
4. focused unit/contract tests and a session-exposure ledger;
5. an adapter that supplies B1v3 information sets to the existing evaluation pipeline.

No new ML framework, database, cloud service, notebook implementation, general surface engine,
or provider connector is introduced. Heavy raw data and caches remain under `D:\MDS650`; code,
schemas, manifests, hashes, and compact reports remain in Git.

## Verification contract

Before any confirmation outcome access, tests must prove:

- same-expiry/same-strike ATM pairing and deterministic tie-breaks;
- no cross-expiry skew;
- total-variance and forward-variance arithmetic using actual DTE;
- rejection of negative/non-finite forward variance without clipping;
- exact within-session 5- and 30-minute lags with no overnight carry;
- last-quote reselection at every shifted cutoff and no future quote;
- no fallback from an invalid last quote to an earlier valid quote;
- point-in-time rate/dividend provenance and controlled zero-dividend policy;
- B1v3 nested monotonicity globally and by asset/date/session third/timing route;
- deterministic coverage and reason-code reconciliation;
- rejection of forbidden outcome fields during predictor construction;
- exposure-ledger exclusion of all previously analysed dates;
- 30-minute purge/embargo and training-only fitting;
- common `origin_id` and target hashes for B0, B1v3a, and B2;
- immutable manifests, deterministic hashes, idempotent reruns, and one-read access;
- absence of secrets and personal paths from sanitized evidence.

The quality gate requires focused and full pytest, Ruff, Mypy, coverage, JSON Schema validation,
secret/path scanning, deterministic replay, clean-install verification, and Spec Kit analyze with
no critical contradiction.

## Ordered execution gates

1. Owner reviews and approves this written design.
2. Update Spec Kit specification, plan, requirements checklist, task graph, contracts, and
   methodology decision; run clarify, plan, checklist, tasks, and analyze.
3. Write failing B1v3 tests and implement the target-blind feature builder only.
4. Recompute target-blind B1v3 coverage on existing source-bound attempts; do not read RV30 or
   QLIKE.
5. Build and freeze the session-exposure ledger and deterministic 60/30 calendar.
6. Run authenticated date-level provider preflight and storage gate; acquire only missing,
   allow-listed evidence resumably.
7. Build a source-bound predictor-only B0/B1v3/B2 panel and pass all leakage/quality gates.
8. Freeze features, dates, models, folds, MDE, timing variants, hashes, and the one-read guard.
9. Execute the complete confirmation once, without intermediate adaptation.
10. Report every registered result and publish the institutional evidence index locally.

## Explicit exclusions

- no objective to force a positive sign;
- no feature, asset, date, cutoff, model, or threshold selection from RV30 or QLIKE;
- no repeated confirmation runs until a preferred result appears;
- no B2-versus-B0 substitution when B1v3 fails;
- no imputation to force B1 coverage;
- no reinterpretation of `created_at` as publication time or `sip_timestamp` as REST receipt;
- no full OPRA quote-market backfill;
- no RL, DL, new model family, or option-pricing model escalation in this phase;
- no trading, broker action, email, external publication, or Word/PowerPoint modification;
- no deletion or overwrite of prior evidence;
- no guarantee of global, positive, or commercially actionable edge.

## Acceptance of the design

Implementation remains blocked until the owner reviews this exact file and confirms that it is the
intended written specification. After that confirmation, the next permitted action is the detailed
implementation plan and Spec Kit coherence update; model training and QLIKE remain later gates.
