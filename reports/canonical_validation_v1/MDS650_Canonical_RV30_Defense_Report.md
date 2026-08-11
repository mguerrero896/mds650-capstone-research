# MDS650 Canonical RV30 Validation — Defense Report

## Executive answer

**Primary research question.** At each five-minute forecast origin, does the ordinary
state of the options market improve a 30-minute realised-variance (RV30) forecast beyond
underlying and market controls, and does trade-derived option activity add further
incremental information?

**Canonical answer.** `MODEL_FAMILY_DEPENDENT` for both comparisons. The study preserves
positive and negative outcomes: the confirmatory Gamma generalized linear model (Gamma GLM)
shows a targeted positive B2 result in the independent block, while the registered LightGBM
robustness model has the opposite B2 sign in that same block. The evidence therefore does not
support an all-model conclusion.

## What one row means

One row is one eligible outcome asset at one five-minute New York Stock Exchange forecast
origin. RV30 uses the fully observed close at the origin and the next thirty consecutive
one-minute closes, producing exactly thirty one-minute log returns. Predictors are available
at or before the origin; missing observations are not interpolated or replaced.

## Information sets and data provenance

- **B0:** point-in-time underlying and market controls.
- **B1a:** B0 plus at-the-money implied volatility from qualifying historical option quotes
  in the 30–60 days-to-expiry bucket. It is an ordinary-option-state benchmark, not a claimed
  full skew or term-structure surface.
- **B2:** B1a plus nine frozen, target-blind option-trade activity features. The conservative
  availability rule is `created_at <= origin - 60 seconds`; this is an operational proxy, not
  a statement about publication time, trader intention, or informed trading.

The data are licensed commercial data rather than a public classroom download. Reproducibility
is addressed through code, fixed study contracts, source hashes, sanitized manifests, exact
origin pairing, and a portable evidence index; licensed raw payloads remain outside Git. A
future date qualifies only after its historical Full Tape availability, hash, market-calendar,
and point-in-time checks pass.

## Why these models were used

Gamma GLM is the registered confirmatory estimator. LightGBM is the pre-registered nonlinear
robustness estimator. HAR-RV, Ridge, and Elastic Net are retained only as post-read fixed
extensions and do not upgrade the registered evidence. A deep neural network is not introduced
because the independent unit is trading day rather than the raw number of overlapping rows;
it would add material model-selection risk without resolving the current disagreement.
Reinforcement learning is not appropriate for this question because it would change RV30
forecasting into a sequential trading-policy problem requiring action, reward, execution-cost,
and risk contracts that are not part of this study.

## Registered out-of-sample results

`QLIKE delta = QLIKE(baseline) - QLIKE(expanded information set)`. A positive value favours
the expanded information set. Confidence intervals use a paired bootstrap clustered by trading
day, with all assets from a day retained together. Holm adjustment applies to the two declared
nested contrasts in each model/block. The minimum detectable effects (MDEs) were frozen before
the relevant out-of-sample outcomes were read.

| Evidence block | Model | Comparison | QLIKE delta | 95% interval | Holm p | Frozen MDE met? |
| --- | --- | --- | ---: | --- | ---: | --- |
| Phase 6 historical OOS block | Gamma generalized linear model (confirmatory) | B1a ordinary option state versus B0 underlying/market | +0.01180281 | [+0.00487252, +0.01881563] | 0.00059994 | no |
| Phase 6 historical OOS block | Gamma generalized linear model (confirmatory) | B2 trade activity versus B1a ordinary option state | +0.00443912 | [+0.00240959, +0.00674248] | 0.00039996 | no |
| Phase 6 historical OOS block | LightGBM nonlinear tree model (robustness) | B1a ordinary option state versus B0 underlying/market | +0.00597230 | [+0.00354998, +0.00858633] | 0.00039996 | no |
| Phase 6 historical OOS block | LightGBM nonlinear tree model (robustness) | B2 trade activity versus B1a ordinary option state | +0.00170046 | [+0.00069438, +0.00273442] | 0.00079992 | no |
| Independent historical replication block | Gamma generalized linear model (confirmatory) | B1a ordinary option state versus B0 underlying/market | -0.08698073 | [-0.14520251, -0.02706899] | 0.00399960 | no |
| Independent historical replication block | Gamma generalized linear model (confirmatory) | B2 trade activity versus B1a ordinary option state | +0.03291534 | [+0.02444358, +0.04162629] | 0.00039996 | yes |
| Independent historical replication block | LightGBM nonlinear tree model (robustness) | B1a ordinary option state versus B0 underlying/market | +0.00553712 | [-0.00018858, +0.01076412] | 0.05719428 | no |
| Independent historical replication block | LightGBM nonlinear tree model (robustness) | B2 trade activity versus B1a ordinary option state | -0.00180221 | [-0.00240038, -0.00119407] | 0.00039996 | no |

## What can be said, precisely

- **B1a over B0:** not established as a general improvement. Gamma changes from positive in
  Phase 6 to negative in independent replication. LightGBM is positive in both blocks, but its
  independent interval crosses zero and its gain is below the frozen MDE.
- **B2 over B1a:** a targeted Gamma result exists in the independent block: `+0.03291534`,
  95% interval `[+0.02444358, +0.04162629]`, above the frozen B2 MDE `0.00503510`.
  It is bounded by the adverse independent LightGBM B2 result `-0.00180221`.
- **Scientific status:** the disagreement is informative. It prevents selective reporting and
  identifies the precise condition that a future, newly sealed replication must resolve.

## Quality controls already passed

- Identical B0/B1a/B2 origins within every comparison; canonical unpaired rows: zero.
- Temporal train-before-test audit; minimum retained separation: 1,115 minutes.
- Six outcome assets: AAPL, AMZN, META, MSFT, NVDA, and TSLA. SPY and QQQ are market-control
  inputs, so their absence from outcome rows is a data-role rule rather than performance-based
  asset removal.
- All registered signs, intervals, MDE decisions, and negative robustness findings are retained.

## Supervisor-feedback checklist

| Supervisor concern | Direct response in this package |
| --- | --- |
| Goals and objectives were unclear | The single primary question and row-level target are stated above before any acronym-heavy result. |
| Dataset is not standard/public | The commercial-data boundary, audit trail, and reproducibility mechanism are stated explicitly. |
| Literature feasibility was missing | The verified study matrix and evidence ledger are retained at `docs/literature_matrix.csv` and `docs/literature_evidence_ledger.csv`; they provide recent empirical motivation, not a substitute for this dataset's PIT validation. |
| No baseline was selected | B0, B1a, and B2 are explicit nested information sets, with Gamma GLM and LightGBM registered roles shown above. |

## Limits and next scientific step

This is an RV30 forecast-loss study, not proof of a deployable strategy, causal mechanism, or
trader intent. The next valid strengthening step is a newly sealed replication with the method
frozen before its outcomes are read; it must retain both registered model families and all
outcomes. No new model family, feature redesign, or result-selection rule should be introduced
to manufacture agreement.

## Evidence index

- Canonical result source: `artifacts/canonical_validation_v1/contrasts.json`.
- Source validation: `artifacts/canonical_validation_v1/report_manifest.json`.
- Claims and limitations ledger: `docs/canonical_claims_and_limitations.md`.
- Causal audit: `artifacts/canonical_validation_v1/phase6/causal_audit.parquet` and
  `artifacts/canonical_validation_v1/independent_replication/causal_audit.parquet`.
