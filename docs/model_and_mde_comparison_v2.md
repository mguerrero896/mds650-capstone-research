# Development model and MDE comparison (development-only)

Status: `PASS_DEVELOPMENT_MODEL_COMPARISON`; no independent/OOS rows were read.

## What was trained

The repository has already trained two supervised models under the frozen
protocol: Gamma GLM (`gamma_glm_confirmatory`) and LightGBM
(`lightgbm_robustness`). This audit adds persistence, log-linear HAR-RV and a
fixed outcome-blind Ridge challenger. Elastic Net remains implemented and
ledger-registered but was not fitted in this gate to avoid multiplying a
development-only model family; running it requires a separately registered
extension.

## Design and MDE

The panel is the six-outcome-asset, 80-session Phase 5 development panel with
15,548 common forecast origins and 233,220 paired forecast rows. Each fit uses
chronological outer folds, a 30-minute purge/embargo, and training-only inner
selection. QLIKE is the primary loss; MAE and RMSE are descriptive. Confidence
intervals use a paired bootstrap clustered by trading session. The MDE is a
training-only planning quantity estimated from outer-fold daily effects; it is
not an economic hurdle and was not tuned from independent results.

## Nested contrasts

`delta_b1 = QLIKE(B0) - QLIKE(B1a)` and
`delta_b2 = QLIKE(B1a) - QLIKE(B2)`. Positive values favour the richer
information set.

| Model | B1 delta (95% CI) | Holm p | B2 delta (95% CI) | Holm p |
|---|---:|---:|---:|---:|
| Persistence | 0.000000 [0.000000, 0.000000] | 1.0000 | 0.000000 [0.000000, 0.000000] | 1.0000 |
| HAR-RV | 0.006512 [-0.001898, 0.015560] | 0.1320 | 0.029053 [0.014871, 0.044308] | 0.0004 |
| Ridge | 0.006507 [-0.001917, 0.015559] | 0.1324 | 0.029036 [0.014877, 0.044280] | 0.0004 |
| Gamma GLM | -0.000288 [-0.007583, 0.006896] | 0.9501 | 0.013118 [0.003323, 0.024098] | 0.0120 |
| LightGBM | 0.004831 [0.000459, 0.010346] | 0.0500 | 0.002191 [-0.001882, 0.006493] | 0.3214 |

The development signs are heterogeneous across model classes. This is useful
diagnostic evidence, not permission to choose a favourable model after seeing
the result. It does not establish a global edge.

## Planning MDE comparison

| Model | B1 MDE | B2 MDE |
|---|---:|---:|
| HAR-RV | 0.014505 | 0.023727 |
| Ridge | 0.014522 | 0.023699 |
| Gamma GLM | 0.011459 | 0.017215 |
| LightGBM | 0.008704 | 0.006829 |

Only the development-only HAR-RV/Ridge B2 estimates exceed their planning MDE;
that comparison is descriptive and must not be read as a final claim. The
independent block remains required.

## Reproducibility and evidence

- Results: `artifacts/methodology/development_model_comparison.json`.
- Forecast rows: `artifacts/methodology/development_model_comparison.parquet`.
- Contrasts: `artifacts/methodology/development_contrasts_v2.json`.
- Stability: `artifacts/methodology/development_stability_v2.parquet`.
- Variant ledger: `artifacts/methodology/development_model_variant_ledger.json`.
- OOS reads: `0` in this comparison.
- Independent acquisition and evaluation are separate from these artifacts.

## RL/DL decision

Reinforcement learning is out of scope because the estimand is a conditional
RV30 forecast, not a sequential action policy or trading reward. Deep learning
is not the optimal next confirmatory method for this sample: it would add many
degrees of freedom and selection risk without solving timestamp, leakage or
independent-power limitations. A small MLP/LSTM may be a later, explicitly
registered challenger after the independent replication, but it cannot replace
the frozen supervised comparison.
