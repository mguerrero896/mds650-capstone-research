# Benchmark evaluation contract

## Recovery status

This contract specifies future evaluation only. No model fitting or benchmark execution is
authorized in the recovery iteration.

The target MUST use the fully observed close at forecast origin t and the next thirty consecutive one-minute closes, producing exactly thirty one-minute log returns.

## Benchmark nesting

Each run must evaluate the same origins and frozen assets under:

- **B0**: underlying and market controls;
- **B1**: B0 plus validated point-in-time implied volatility, skew, and term
  structure;
- **B2**: B1 plus unusual-options activity variables.

The primary comparison is exactly `Delta_Q = QLIKE(B1) - QLIKE(B2)`. B0 is retained as the
control baseline. If ordinary option-state PIT verification fails, B1 is `BLOCKED` and no
incremental B2 claim is authorized; B2-versus-B0 is only a declared fallback.

## Evaluation record

Every model record contains `run_id`, `benchmark`, `asset_set`, `origin_start`,
`origin_end`, `training_cutoff`, `purge_minutes`, `embargo_minutes`,
`model_name`, `feature_schema_fingerprint`, `n_train`, `n_test`, `metric_name`,
`metric_value`, `metric_units`, `confidence_interval_method`, `seed`, and
`status`. `status` is `PASS`, `FAIL`, or `BLOCKED`; a blocked B1 prevents a
claim about incremental unusual activity. The target reference MUST identify the fully
observed origin close plus thirty future closes and exactly thirty log returns.

## Statistical safeguards

Splits are chronological and out of sample. Purging and embargo prevent overlap
between training labels and test origins. Metrics must include QLIKE and a
secondary scale-dependent error selected in the frozen configuration. Model
selection, transformations, and imputation are fit only on the training side.
The single primary contrast is frozen before the final test. Secondary and robustness analyses
are labelled before inspection; Holm or Benjamini-Hochberg is used where applicable, and
favorable-result selection is prohibited. The minimum detectable effect is estimated from
simulation, bootstrap, pilot or training data only, never from the final test.

The uncertainty method is a bootstrap by trading day, keeping all observed assets on the same
day together. The report includes per-asset and pooled results and predeclared volatility,
earnings, session-segment, asset/ETF and normal/stressed regimes, with an explicit statement
separating predictive association from causal information. Event/no-event origins preserve
natural prevalence; training-only weighting, if any, is documented and never changes
validation or final-test distributions.

## Reproducibility and safety

The execution manifest records repository revision, environment lock hash,
dataset hashes, configuration hash, seed, provider audit identifiers, and test
status. The pipeline is research-only: no broker, order, payment, email,
publication, or deployment side effect is permitted.
