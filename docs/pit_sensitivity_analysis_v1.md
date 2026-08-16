# PIT sensitivity analysis v1

Evidence: `artifacts/pit/pit_sensitivity_grid_v1.parquet` and
`artifacts/pit/pit_sensitivity_summary_v1.csv`. The primary convention remains
FMP +1 minute and UW 60 seconds; the grid does not choose the largest sample.

| FMP delay | UW cutoff | Strict rows | Retention of 14,200 | B1Q coverage | B2 activity coverage | Material change |
|---:|---:|---:|---:|---:|---:|---|
| +1m | 60s | 9,589 | 67.53% | 90.96% | 100% | No |
| +1m | 120s | 9,589 | 67.53% | 90.96% | 100% | No |
| +1m | 300s | 9,589 | 67.53% | 90.96% | 0% | No strict-row change; activity coverage changes |
| +2m | 60s | 0 | 0% | 90.96% | 100% | Yes; all rows lost |
| +2m | 120s | 0 | 0% | 90.96% | 100% | Yes; all rows lost |
| +2m | 300s | 0 | 0% | 90.96% | 0% | Yes; all rows lost |

The +2-minute result is a structural consequence of the five-minute origin grid
and the current conservative anchor convention, not evidence that +2 minutes is
wrong in every provider context. It is retained as a sensitivity failure and
cannot replace the approved +1-minute primary convention.

The 120-second UW cutoff does not change strict row IDs in this retained sample.
The 300-second cutoff has no eligible events in the five-minute event bin, which
is why its activity-presence rate is zero. No convention was selected to maximize
retention; all row-ID differences are stored in the grid.

Status: **PASS for reproducible sensitivity accounting; PARTIAL for provider
semantics**. The grid is not predictive evidence.
