# Temporal validation protocol v2 (specification only)

Evidence of proposed dates: `artifacts/validation/proposed_temporal_folds_v1.csv`.
No model has been trained and no fold has been evaluated.

## Protocol

- Order rows chronologically by session date and forecast origin; never random
  split.
- Use expanding training windows for the recommended 60-session design; rolling
  windows may be a prespecified robustness comparison only.
- Keep an untouched final test period. The final test cannot affect feature
  transforms, model selection, tuning or effect-size planning.
- Purge at least 30 minutes and embargo at least 30 minutes around validation
  and test boundaries because adjacent RV30 targets overlap.
- Fit scaling, feature transformations, unusualness parameters and hyperparameters
  inside each training/validation history only. Pilot sessions cannot fit them.
- Use identical canonical row IDs for B0/B1Q/B2 and compare only common eligible
  origins for a paired primary estimand.
- Cluster uncertainty by trading day while retaining all observed assets in the
  same cluster. This controls common-day dependence but does not remove all
  serial dependence created by overlapping targets.
- Report pooled and asset-level results only when each fold has the required
  minimum valid days; incomplete asset-days are explicit exclusions.

## Proposed folds

The CSV contains one train/validation/final-test proposal for 60, 120 and 180
sessions, all with `purge_minutes=30`, `embargo_minutes=30`,
`same_origin_ids_across_benchmarks=true` and `random_split=false`. Only the
60-session proposal is operationally feasible under the current resource
projection, and it is still awaiting human approval and provider gates.

Status: **PASS as a future protocol; NOT EXECUTED**.
