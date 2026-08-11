# Canonical RV30 validation conclusion

## Decision

**Canonical decision: `MODEL_FAMILY_DEPENDENT` for both nested contrasts.**

The data-engineering and causal-split contracts pass, but the registered model
families do not support a universal claim that either ordinary option state
(B1v2a) improves B0v2, or that trade-derived activity (B2v2) incrementally
improves B1v2a. This is a scientific result, not a missing calculation: the
direction of the independent evidence changes with the model family.

| Question | Defensible answer | Evidence |
| --- | --- | --- |
| Does B1v2a improve B0v2 globally? | Not established. Gamma is positive in Phase 6 but negative in the independent block; LightGBM is positive in both blocks but the independent interval includes zero and its effect is below the frozen MDE. | `artifacts/canonical_validation_v1/contrasts.json` |
| Does B2v2 add value beyond B1v2a globally? | Not established. Gamma is positive in both blocks, but LightGBM turns negative in the independent block. | `artifacts/canonical_validation_v1/contrasts.json` |
| Is there a targeted result worth reporting? | Yes, conditionally: independent Gamma B2v2 has a QLIKE gain of `0.03291534`, 95% CI `[0.02444358, 0.04162629]`, exceeding its frozen MDE `0.00503510`. It cannot be presented as a model-independent or universal result. | `artifacts/canonical_validation_v1/contrasts.json` |

## What was compared

- **Target:** RV30 at each five-minute forecast origin: 31 observed one-minute
  closes form exactly 30 log returns. No model receives future target prices as
  predictors.
- **B0v2:** underlying and market controls.
- **B1v2a:** B0v2 plus point-in-time ATM implied volatility in the 30–60 DTE
  bucket. This is the minimum ordinary-option-state benchmark; it does not
  claim a complete skew or term-structure surface.
- **B2v2:** B1v2a plus the nine frozen, target-blind trade-activity features.
- **Outcome assets:** AAPL, AMZN, META, MSFT, NVDA and TSLA. SPY and QQQ were
  acquired as market-control inputs, not as outcomes. Thus eight symbols were
  acquired but six eligible outcome panels were intentionally evaluated; this
  is a data-role rule rather than selection by performance.

## Evidence and temporal integrity

| Block | Origins per information set | Registered families | Causal audit | Minimum retained gap |
| --- | ---: | --- | --- | ---: |
| Phase 6 | 38,976 | Gamma GLM and LightGBM | 25 role-fold rows pass | 1,115 minutes |
| Independent replication | 11,664 | Gamma GLM and LightGBM | 5 role-fold rows pass | 1,115 minutes |

Every B0v2, B1v2a and B2v2 comparison uses the same origin identifiers within
each block, fold and model role. The report recomputes QLIKE from stored RV30
and forecasts, clusters the bootstrap by XNYS trading day with all assets held
together, and uses Holm adjustment only for the two declared nested contrasts
within each block/model family. The training-only frozen MDEs are `0.02168578`
for B1v2a versus B0v2 and `0.00503510` for B2v2 versus B1v2a.

Evidence: `artifacts/canonical_validation_v1/phase6/causal_audit.parquet`,
`artifacts/canonical_validation_v1/independent_replication/causal_audit.parquet`,
`artifacts/canonical_validation_v1/contrasts.json`, and
`artifacts/canonical_validation_v1/report_manifest.json`.

## Why the families disagree

The discrepancy is observable rather than assumed. In the independent block,
Gamma reports B1v2a `-0.08698073` and B2v2 `+0.03291534`; LightGBM reports
B1v2a `+0.00553712` and B2v2 `-0.00180221`. Calibration also differs by role
and information set, while the B2 feature-only diagnostic finds material
correlation among some frozen predictors. Those diagnostics describe possible
mechanisms for sensitivity; they do not prove a causal explanation or authorize
feature reselection.

Evidence: `artifacts/canonical_validation_v1/contrasts.json`,
`artifacts/canonical_validation_v1/calibration.json`, and
`artifacts/canonical_validation_v1/redundancy.json`.

## Interpretation boundary

Gamma GLM and LightGBM are the registered outcome-bearing families. HAR-RV,
Ridge and Elastic Net were fit only as **post-read fixed extension** analyses
with fixed parameters and are retained for diagnostic breadth. They may inform
future pre-registered design, but they cannot upgrade this decision or be
presented as independent confirmation.

No new provider download, feature reselection, model tuning, QLIKE rerun on a
new test set, or holdout access is authorized by this report. A stronger future
claim requires a newly sealed, independent sample and a method freeze before
its outcomes are read.
