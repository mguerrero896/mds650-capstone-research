# Effective sample size and planning-only feasibility

Evidence: `artifacts/feasibility/effective_sample_size_v1.json`.

The availability-aware matrix has 13,240 rows, 25 observed trading days and
200 asset-days (8 assets × 25 days). There are 71 five-minute origins per
regular session in the pilot design and RV30 targets overlap by 25 minutes
between adjacent origins. Rows are therefore not independent. All assets from a
day are treated as one cluster for future inference.

The observed effective independent-day count is conservatively 25, not 13,240.
The artifact's planning simulation uses synthetic paired loss differentials only;
it does not estimate model performance or actual power. It varies within-day
dependence in `{0, .3, .6}` and cross-asset dependence in `{0, .5}` with 200
replicates per cell.

## Selected planning cells

| Sessions | Within-day rho | Cross-asset rho | Detectable standardized effect | Interpretation |
|---:|---:|---:|---:|---|
| 60 | 0.0 | 0.0 | 0.127 | optimistic independence boundary |
| 60 | 0.6 | 0.5 | 0.322 | clustered conservative boundary |
| 120 | 0.0 | 0.0 | 0.090 | optimistic larger-window boundary |
| 120 | 0.6 | 0.5 | 0.233 | clustered larger-window boundary |
| 180 | 0.0 | 0.0 | 0.073 | optimistic maximum-window boundary |
| 180 | 0.6 | 0.5 | 0.189 | clustered maximum-window boundary |

These values are design-planning ranges, not minimum effects discovered from a
test set. Dependence must be estimated only after a frozen temporal design and
without using the final test period.

Status: **PASS for transparent planning; not a scientific power claim**.
