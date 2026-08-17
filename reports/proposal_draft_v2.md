# Assessment 1 proposal — DRAFT v2 (2026-08-18)

> Status: `DRAFT_PENDING_HUMAN_DECISIONS`. Supersedes v1 (2026-08-17) by integrating the
> 2026-08-17 gate-cascade evidence (`reports/gate_cascade_report_20260817.md`). Blocking
> items before any submission freeze: D003 (institutional title page, ethics wording,
> calendar mapping), D004 (feedback provenance), Corsi (2009) retrieval (Patton (2011) is
> now retained, LIT-012). Word targets per the master status Section 18 pack (≈990
> narrative words). Every claim is bounded by decision 53.

## Title (D003 pending institutional metadata)

Point-in-time options information for forecasting next-30-minute realised variance.

## Abstract (~120 words)

This project asks whether option-market information improves out-of-sample prediction of
the realised variance of large US equities over the next 30 minutes (RV30). At five-minute
forecast origins during the regular New York session, three nested information sets are
compared on identical origins: underlying and market state (B0); B0 plus conventional
option-state variables such as at-the-money implied volatility (B1); and B1 plus
point-in-time option-trade activity (B2). Six liquid equities form the outcome universe
with SPY and QQQ as market controls. Forecasts from prespecified benchmark and regularised
models are evaluated chronologically with the QLIKE loss and studentized day-clustered
inference. Commercial data cannot be redistributed, but code, schemas, hashes, fixtures and
aggregate outputs provide controlled auditability. A correctly preregistered null is a
valid outcome; no profitability or causal claim is made.

## Introduction (~140 words)

Short-horizon realised-variance forecasting is an active research area: recent work spans
intraday decompositions and forecast reconciliation (Caporin et al., 2024), coherent
loss-aligned HAR evaluation (Puke & Schweikert, 2026), and options-driven volatility
forecasting in which option-surface information and machine-learning models improve on
econometric baselines (Michael et al., 2025). Within this literature a specific gap
remains: whether point-in-time option-trade *activity* — what was just traded, beyond what
option *prices* already state — adds incremental predictive information at intraday
horizons. Existing studies largely target daily or longer horizons, and activity-based
predictors are rarely tested under strict operational-availability rules. This project
addresses that gap at the 30-minute horizon with commercial point-in-time data from three
audited providers, an explicitly nested information-set design, preregistered evaluation
gates, and Patton's (2011) proxy-robustness conditions respected by a registered
noise-robust target sensitivity. [Corsi (2009) is being obtained before the literature
section freezes.]

## Problem and objectives (~130 words)

Primary question: does conventional options information and, additionally, point-in-time
options-trade activity improve out-of-sample prediction of the underlying asset's
next-30-minute realised variance relative to nested underlying-market benchmarks? The
dependent variable is unannualised RV30: the sum of 30 squared one-minute log returns from
31 consecutive closes. The primary estimand is the incremental out-of-sample QLIKE
improvement of B2 over B1 on identical origins; secondary objectives are (1) the analogous
B1-over-B0 increment, (2) stability of any effect across assets, session periods,
volatility regimes and event composition, (3) model-family robustness — a confirmatory
regularised Gamma model against a fixed nonlinear challenger, with the family *difference*
itself formally tested — and (4) controlled auditability of a commercial-data pipeline.
The interpretation is strictly predictive-informational: no causality, trader intent,
direction, or profitability claim is in scope.

## Scope (~110 words)

The ten-week core comprises six outcome equities (AAPL, AMZN, META, MSFT, NVDA, TSLA) with
SPY/QQQ as controls, not outcomes; three nested information sets on identical five-minute
origins; prespecified model roles now anchored by field-standard baselines (intraday
HAR-RV and HARQ, implemented and validated on development data; regularised Gamma
confirmatory; LightGBM challenger); one chronological evaluation design with a 30-minute
purge/embargo; and QLIKE as primary loss. Feasibility is demonstrated: full preregistered
development-plus-holdout cycles have been executed, bar-label semantics are cross-provider
validated (FMP vs Massive, exact agreement), and a live latency-measurement campaign for
the trade-tape availability assumption is running unattended. Out of scope: live trading,
profitability backtests, deep or reinforcement learning, and any raw-data redistribution.

## Proposed methodology (~230 words; researcher process)

The researcher first completes a structured literature review, recording each study's
dataset, horizon, models, validation design and evidential strength. Second, the three
commercial providers (FMP for underlying bars and RV30; Massive for historical option
quotes; Unusual Whales for the option-trade tape) are audited for entitlement, timestamp
semantics, schema stability and licence constraints; operational-availability assumptions
are registered explicitly and, where possible, *measured*: bar-label semantics via
cross-provider reconciliation, and trade-record availability via a live collector that
records receipt timestamps intraday and reconciles them against the historical tape seven
days later, bounding latency, backfill and revision rates. Third, the research design is
frozen before outcomes are read: question, estimands, universe, session lists, losses,
models, coverage gates and stop rules are hash-sealed in preregistration manifests, with
an equivalence (TOST) bound recorded pre-read so a null is reportable as affirmative
evidence of absence. Fourth, the point-in-time panel is constructed without interpolation
and with target-blind normalisation. Fifth, prespecified models are fitted with
training-only transforms in expanding chronological folds. Sixth, evaluation uses QLIKE on
identical origins with studentized inference — cluster t, Newey-West (Diebold-Mariano)
statistics, wild cluster bootstrap, moving-block sensitivity, and a Model Confidence Set —
plus Holm adjustment within declared families; sealed holdouts are read exactly once under
access-ledger control. Seventh, results are interpreted against a binding claims hierarchy
separating confirmatory, exploratory and null evidence, with controlled auditability.

## Expected outcomes (~130 words)

A methodologically valid estimate may be positive, null or negative, and each is a
reportable contribution. Prior evidence is stated honestly: the prospective preregistered
holdout returned null for both nested contrasts, while retrospective evaluations show a
recurring positive B2 increment that is specific to the confirmatory Gamma family,
reversed or null under the fixed challenger, absent against HAR/HARQ baselines, outside
every Model Confidence Set, and shrinking toward the present at a formally measured rate.
Seven independent robustness probes (calibration, event composition, microstructure,
selection, feature ablation, earnings conditioning, horizon structure) already
characterise this effect. The study therefore expects one of two defensible endpoints: a
model-robust prospective confirmation, or an equivalence-bounded null that quantifies how
little option-trade activity adds once conventional option state and underlying dynamics
are controlled. Deliverables include comparative evidence tables and a reproducible audit
pack.

## Timeline (ten weeks; calendar mapping pending D003/A003)

Week 1 scope/ethics freeze → Week 2 literature closure → Week 3 contract freeze →
Week 4 panel/coverage gates → Week 5 benchmark repair decision → Week 6 model freeze →
Week 7 one-read chronological evaluation → Week 8 inference and robustness →
Week 9 interpretation and audit pack → Week 10 final document and presentation.
Weekly evidence is a supervisor-readable artifact or gate, not a commit log.

## Resources and ethics (~130 words combined)

Python 3.12 with a locked environment (`uv.lock`); licensed API access to FMP, Unusual
Whales and Massive; a two-SSD Windows workstation with heavy licensed data outside Git;
Git with preregistration manifests, hash gates and a 1,000-test suite. No human
participants are involved. Licensed raw data and credentials are never redistributed or
committed; reproducibility for unlicensed examiners is provided through code, schemas,
sanitised fixtures, hashes, missingness summaries and aggregate outputs. The study makes
no informed-trading, causal or profitability claims, and vendor labels are treated as
observed events, never as trader intent. [Ethics wording and institutional template:
pending D003.]

## References

Use only ledger-verified sources (`docs/literature_evidence_ledger_v2.csv`); the current
candidate list is master status Section 21.1. Patton (2011) is retained (LIT-012);
Corsi (2009) and the three ScienceDirect full texts must be obtained before the reference
list freezes; limited sources may not support strong claims.
