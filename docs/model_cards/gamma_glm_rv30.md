# Model card — Gamma GLM RV30

## Identity

- **Role:** `gamma_glm_confirmatory`
- **Evidence status:** registered out-of-sample model
- **Target:** positive RV30 at each five-minute origin
- **Information sets:** B0v2, B1v2a and B2v2 on identical origin keys

## Intended estimand

The model estimates whether adding the fixed nested information set changes
out-of-sample RV30 forecast loss, measured primarily by paired QLIKE. It is not
a trading-policy, causal-effect or trader-intent estimator.

## Training and evaluation contract

Each fold retains only rows before the test block after the RV30 horizon and
embargo protection. Phase 6 has five expanding folds; the independent block
has one sealed target fold. The smallest observed training-to-test gap is 1,115
minutes. Parameters were selected inside historical training data before the
registered outcomes and are preserved in the model-variant ledgers.

Evidence: `artifacts/canonical_validation_v1/phase6/model_variant_ledger.json`,
`artifacts/canonical_validation_v1/independent_replication/model_variant_ledger.json` and
the two `causal_audit.parquet` files.

## Registered result boundary

Gamma shows positive B2 in both blocks but reverses B1 from positive in Phase 6
to negative in independent replication. It therefore supports model-specific
findings only, not a universal B1 or B2 claim.

Evidence: `artifacts/canonical_validation_v1/contrasts.json`.

## Principal limitations

- Gamma calibration differs meaningfully between the blocks and information sets.
- Positive RV30 support and a floor do not protect against model misspecification.
- Agreement with the LightGBM robustness role is required for a universal claim;
  that agreement is absent.
