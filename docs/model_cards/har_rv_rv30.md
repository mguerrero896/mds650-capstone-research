# Model card — HAR-RV RV30

## Identity

- **Role:** `har_rv_fixed_extension`
- **Evidence status:** post-read fixed extension
- **Target:** positive RV30 at each five-minute origin
- **Information sets:** B0v2, B1v2a and B2v2 on the canonical paired origins

## Intended estimand

This fixed HAR-RV adapter gives a structured linear volatility benchmark for
diagnostic comparison. It estimates forecast loss differences, not a trading
policy or a causal effect of option activity.

## Training and evaluation contract

It uses the same causal folds, same origin IDs, same RV30 target and no
hyperparameter search. Its parameter mapping is empty by contract, and its
variant ledger labels every result as a post-read fixed extension.

Evidence: `src/mds650/canonical_validation.py` and
`artifacts/canonical_validation_v1/phase6/model_variant_ledger.json`.

## Interpretation boundary

HAR-RV results are retained rather than discarded, but they cannot independently
confirm a preregistered result. Their role is to show whether the direction is
sensitive to a fixed linear volatility benchmark.

## Principal limitations

- The analysis was added after registered outcomes had been accessed.
- It does not restore a complete skew or term-structure B1 surface.
- Its positive B2 estimates cannot override registered Gamma/LightGBM disagreement.
