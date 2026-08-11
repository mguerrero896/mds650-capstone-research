# Model card — Ridge RV30

## Identity

- **Role:** `ridge_fixed_extension`
- **Evidence status:** post-read fixed extension
- **Target:** positive RV30 at each five-minute origin
- **Fixed parameter:** `alpha = 1.0`

## Intended estimand

Ridge tests whether a fixed L2-regularized linear mapping produces the same
direction of nested B0v2/B1v2a/B2v2 forecast differences on canonical origins.
It does not select features or tune regularization on evaluated outcomes.

## Training and evaluation contract

The model is refit independently inside every causal training fold and forecasts
only the later test rows. The fixed alpha and post-read status are recorded for
every block and information set.

Evidence: `src/mds650/canonical_validation.py` and
`artifacts/canonical_validation_v1/independent_replication/model_variant_ledger.json`.

## Interpretation boundary

Ridge is descriptive post-read fixed extension evidence. It may guide a future
sealed design but cannot increase the strength of the registered conclusion.

## Principal limitations

- Linear shrinkage may mask nonlinear interactions in B2.
- A favorable Ridge result does not settle Gamma/LightGBM disagreement.
- No target-driven alpha tuning was allowed.
