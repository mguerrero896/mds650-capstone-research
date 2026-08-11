# Model card — LightGBM RV30

## Identity

- **Role:** `lightgbm_robustness`
- **Evidence status:** registered out-of-sample robustness model
- **Target:** positive RV30 at each five-minute origin
- **Information sets:** B0v2, B1v2a and B2v2 on identical origin keys

## Intended estimand

LightGBM assesses whether registered nested information gains survive a
nonlinear tree-based forecast mapping under the same temporal and common-origin
contract as Gamma GLM. It is a robustness model, not a mechanism or causal model.

## Training and evaluation contract

The selected parameter record is preserved for each historical fold and
information set. It uses only causal training rows and produces positive
forecasts for later test origins. Its observations are checked against the same
whole-day bootstrap, frozen MDE and Holm family as Gamma.

Evidence: `artifacts/canonical_validation_v1/phase6/model_variant_ledger.json`,
`artifacts/canonical_validation_v1/independent_replication/model_variant_ledger.json` and
`artifacts/canonical_validation_v1/contrasts.json`.

## Registered result boundary

LightGBM supports positive B1 in both blocks, although the independent interval
includes zero and is below MDE. It supports B2 in Phase 6 but is negative for
B2 in independent replication. Therefore it does not validate a global B2 claim.

## Principal limitations

- Tree models can respond differently to correlated or regime-dependent B2 patterns.
- Hyperparameters are historical and frozen within the registered workflow; they
  are not re-optimized to resolve disagreement.
- Forecast accuracy does not demonstrate a tradable or causal edge.
