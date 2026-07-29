# Benchmark evaluation contract

## Phase 5 status

The owner approved this evaluation design on 2026-07-29. Model fitting and QLIKE remain
blocked until Spec Kit analysis has zero critical contradictions and the preregistration is
written and SHA-256 hashed. Holdout evaluation remains blocked until method freeze and its
single-read ledger transition.

The target MUST use the fully observed close at forecast origin t and the next thirty consecutive one-minute closes, producing exactly thirty one-minute log returns.

## Benchmark nesting

Each run must evaluate identical origin IDs, target hashes and eligible assets under:

- **B0**: underlying and market controls;
- **B1a**: B0 plus validated point-in-time ATM implied volatility;
- **B2**: B1a plus the frozen nine target-blind trade-derived activity features.

`B1b = B1a + skew` and `B1c = B1b + term structure` are enriched robustness benchmarks only.
The primary comparison is `Delta_B2 = QLIKE(B1a) - QLIKE(B2)`. The key secondary comparison is
`Delta_B1 = QLIKE(B0) - QLIKE(B1a)`. Positive values favor the expanded information set. If
ATM-IV PIT verification fails, B1a is `BLOCKED` and no incremental B2-over-B1a claim is
authorized; the research design is revised rather than silently substituted.

## Sample and folds

- Development: exactly 80 XNYS sessions, 2026-03-24 through 2026-07-17.
- Prospective holdout: exactly 10 XNYS sessions, 2026-07-20 through 2026-07-31.
- The holdout is read analytically once after method freeze.
- Four outer test intervals are 2026-05-20–2026-06-03, 2026-06-04–2026-06-17,
  2026-06-18–2026-07-02 and 2026-07-06–2026-07-17.
- Training expands through the session immediately before each test interval.
- Purge and embargo are each at least 30 minutes at every boundary.

## Evaluation record

Every model record contains `run_id`, `benchmark`, `model_role`, `asset_set`, `origin_start`,
`origin_end`, `training_cutoff`, `purge_minutes`, `embargo_minutes`,
`model_name`, `feature_schema_fingerprint`, `n_train`, `n_test`, `metric_name`,
`metric_value`, `metric_units`, `confidence_interval_method`, `seed`, and
`status`. `model_role` is `gamma_glm_confirmatory` or `lightgbm_robustness`.
`status` is `PASS`, `FAIL`, or `BLOCKED`; a blocked B1a prevents a
claim about incremental unusual activity. The target reference MUST identify the fully
observed origin close plus thirty future closes and exactly thirty log returns.

## Statistical safeguards

Splits are chronological and out of sample. Purging and embargo prevent overlap
between training labels and test origins. QLIKE is primary; MAE and RMSE are secondary
descriptive metrics. Gamma GLM is confirmatory and LightGBM with Gamma objective is a fixed
robustness challenger. Model selection, transformations and tuning are fit only on the
training side. Holm correction applies to the two confirmatory information-set comparisons.
Favorable-result selection is prohibited. The minimum detectable effect is estimated from
simulation, bootstrap, pilot or training data only, never from the holdout.

The uncertainty method is a paired whole-day cluster bootstrap with 10,000 draws and seed 650,
keeping all assets and origins on the same date together. The report includes pooled,
per-asset, session-tercile, development-defined volatility-regime, FMP +1/+2-minute and B2
60/120/300-second results, with an explicit statement separating predictive association from
causal information. Natural prevalence is preserved; training-only weighting, if any, is
documented and never changes validation or holdout distributions.

Every registered variant and every positive, negative or null result is retained. A supported
edge requires the preregistered development contrast to be positive with its interval above
zero, the one-time holdout effect to have the same sign, and no material systematic reversal
in prespecified stability strata.

## Reproducibility and safety

The execution manifest records repository revision, environment lock hash,
dataset hashes, preregistration hash, method-freeze hash, seed, provider audit identifiers,
holdout-read count, registered-variant ledger and test status. The pipeline is research-only:
no broker, order, payment, email,
publication, or deployment side effect is permitted.
