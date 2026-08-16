# Model and inference candidate dossier v1

This is a decision dossier, not implementation. The machine-readable matrices
are `artifacts/methodology/model_candidate_decision_matrix_v1.csv` and
`artifacts/methodology/inference_candidate_decision_matrix_v1.csv`; descriptive
collinearity evidence is in
`artifacts/methodology/collinearity_diagnostics_v1.json`.

## Model candidates

The dossier covers naive persistence, rolling historical mean, HAR-RV/HARQ,
OLS, Ridge, LASSO, Elastic Net and one tree-based nonlinear candidate. It
records role, positivity, collinearity, missingness, tuning risk, sample-size
requirements, nesting compatibility and implementation status. Naive, rolling
mean and HAR-RV/HARQ are `INCLUDE_CANDIDATE`; OLS, Ridge, LASSO, Elastic Net and
the tree candidate are `ROBUSTNESS_ONLY` at most. These labels are not a final
selection and no candidate is implemented here.

The strict calibration view has 9,589 rows and 31 mandatory predictors. The
diagnostic artifact records the full correlation matrix, condition number,
VIF values and pairs with absolute correlation at least 0.95. These diagnostics
are descriptive only; they cannot select an algorithm before a temporal split.
Rolling coefficient-instability fits were deliberately not run because this
phase forbids model fitting. Any regularisation parameter must be chosen inside
training/validation history, never on the final test.

## Loss and inference candidates

- **QLIKE:** prospective primary loss-difference estimand once forecasts exist;
  requires strictly positive variance forecasts and same eligible origins.
- **MAE/RMSE:** secondary descriptive losses; RMSE is tail-sensitive and MAE is
  not scale-invariant.
- **Paired daily-cluster bootstrap:** primary uncertainty candidate; resamples
  whole trading days with all observed assets together.
- **HAC loss-difference inference:** robustness candidate; bandwidth must reflect
  overlapping targets and cross-asset dependence.
- **Diebold–Mariano:** robustness candidate only; not supervisor-required and
  not implemented.
- **Clark–West:** only potentially compatible for strictly nested squared-error
  forecasts with a frozen restricted/expanded pair; not implemented.

No loss series, p-value, confidence interval or performance result exists. The
matrix explicitly records `supervisor_required=false` for all methods and
records assumptions, finite-sample risks, overlap compatibility and treatment
of cross-asset dependence.

Status: **PASS as evidence dossier; NO method freeze and NO implementation**.
