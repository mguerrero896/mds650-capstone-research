# B2 mechanism model cards

All cards use the 80-session development panel only. No independent outcome was read for selection.

## Gamma GLM (confirmatory)

A positive-mean log-link GLM. Its coefficients are smooth and additive; it can miss thresholded interactions.

## HAR-RV, Ridge and Elastic Net (linear challengers)

These log-linear challengers expose whether the effect survives a simpler conditional mean specification.

## LightGBM (robustness challenger)

A shallow gamma tree ensemble that can model nonlinearities and interactions, but is more sensitive to drift and tuning.

## Residual learner

Each B2 variant is fit only to cross-fitted `RV30 - B1 forecast`; its output is an additive correction with a positive forecast floor.

Primary candidate count: 25 evaluated; retained: 0.

## Development decision

The 25 pre-registered B2 residual variants were evaluated only on the 80-session
development panel. None met the frozen retention rule after paired-day
bootstrap and Holm correction. The direct B2 comparison remains a registered
fallback for the two new independent blocks; it is not evidence that a
residual learner was retained.
