# Independent replication session-power note

Status: `PLANNING_ONLY`; no independent target outcome was read.

This note estimates the number of whole-session clusters needed for the first
independent block. It uses only the development comparison, not Phase 6
outcomes and not the independent target dates.

## Calculation

For each model, the daily effect is the session-level mean of

`QLIKE(B1a) - QLIKE(B2)`.

The planning approximation is

`n = ceil(((z_(1-alpha*/2) + z_0.80) * s_daily / effect)^2)`

where `alpha* = 0.025` is a conservative allocation for the two primary
nested comparisons, `s_daily` is the development daily-cluster standard
deviation, and `effect` is the development mean. This is a power approximation
only; the preregistered analysis remains the paired whole-day bootstrap with
Holm correction.

## Development-only estimates

| Model | Development B2 effect | Daily SD | Approx. clusters for 80% power | Interpretation of 30 sessions |
|---|---:|---:|---:|---|
| HAR-RV | 0.029126 | 0.047790 | 26 | potentially adequate under the same effect |
| Ridge | 0.029109 | 0.047756 | 26 | potentially adequate under the same effect |
| Gamma GLM | 0.013113 | 0.033765 | 64 | likely underpowered at 30 |
| LightGBM | 0.002192 | 0.013691 | 371 | strongly underpowered at 30 |

Source: `artifacts/methodology/development_model_comparison.parquet`, SHA-256
`d6bca4c92909fa6b6927862f1e43d15a3000fb98bcc390e611a7e89f63452ea6`.

## Decision

The preregistered 30-session block remains an initial independent replication,
not a guarantee of global detection. The estimate does not authorize changing
the frozen model, selecting a favorable model, redefining the MDE, or extending
the block after seeing target outcomes. A positive result from 30 sessions must
still satisfy the frozen confidence, multiplicity, stability and MDE rules;
failure to detect an effect at 30 sessions does not prove that the effect is
zero.

The 60 warm-up sessions remain necessary for causal B2 normalization and
training. Acquisition is still blocked until the provider replaces the stable
CRC-corrupt 2025-04-04 archive.
