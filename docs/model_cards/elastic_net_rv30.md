# Model card — Elastic Net RV30

## Identity

- **Role:** `elastic_net_fixed_extension`
- **Evidence status:** post-read fixed extension
- **Target:** positive RV30 at each five-minute origin
- **Fixed parameters:** `alpha = 0.01`, `l1_ratio = 0.5`

## Intended estimand

Elastic Net provides a fixed sparse-plus-shrinkage linear sensitivity analysis
for the same nested information sets. It forecasts RV30; it does not estimate
trader direction, causality or economic profit.

## Training and evaluation contract

The fixed parameters are defined in the canonical model contract. The model
uses only prior rows in each fold, never selects a parameter from test loss and
keeps the post-read fixed extension label in the evidence ledger.

Evidence: `src/mds650/canonical_validation.py` and
`artifacts/canonical_validation_v1/phase6/model_variant_ledger.json`.

## Interpretation boundary

Elastic Net's positive B2 estimates are descriptive. They do not convert the
registered model-family-dependent evidence into universal support.

## Principal limitations

- Fixed sparsity can be sensitive to correlated B2 predictors.
- The B2 redundancy diagnostic is descriptive, not a basis for post hoc feature removal.
- The analysis is post-read fixed extension evidence.
