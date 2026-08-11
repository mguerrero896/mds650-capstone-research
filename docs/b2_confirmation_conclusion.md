# B2 confirmation conclusion

**Status:** `PASS_TWO_NEW_BLOCKS_EVALUATED`

This confirmation used the frozen 80-session development fit and two disjoint
historical Unusual Whales Full Tape blocks, without using the new blocks for
model or feature selection:

- Block A: 30 XNYS sessions, 2024-08-02–2024-09-13.
- Block B: 30 XNYS sessions, 2024-10-01–2024-11-11.
- 23,760 valid forecast origins (11,880 per block; six outcome assets).
- Primary contrast: `Delta_B2 = QLIKE(B1a) - QLIKE(B2)`.
- Confirmatory model: Gamma GLM; LightGBM is the nonlinear robustness
  challenger; HAR-RV, Ridge and Elastic Net are registered challengers.
- 10,000 paired XNYS-session bootstrap repetitions, Holm adjustment, and
  frozen MDE `0.005035098377136471`.

## Primary B2 contrasts

Positive values mean that adding the nine continuous B2 activity features
reduces QLIKE relative to B1a.

| Block | Model | Estimate | 95% bootstrap interval | Holm p | At least MDE? |
|---|---|---:|---:|---:|---|
| A | Gamma GLM | +0.078432 | [0.048421, 0.113205] | 0.0020 | Yes |
| A | LightGBM | −0.024514 | [−0.040817, −0.011656] | 0.0020 | No; adverse |
| A | HAR-RV | +0.055451 | [0.026255, 0.088535] | 0.0020 | Yes |
| A | Ridge | +0.055671 | [0.026476, 0.088794] | 0.0020 | Yes |
| A | Elastic Net | +0.016301 | [−0.005528, 0.041472] | 0.3088 | Not confirmed |
| B | Gamma GLM | +0.034819 | [0.021244, 0.047424] | 0.0020 | Yes |
| B | LightGBM | −0.008609 | [−0.012865, −0.004505] | 0.0020 | No; adverse |
| B | HAR-RV | +0.040635 | [0.027591, 0.053909] | 0.0020 | Yes |
| B | Ridge | +0.040456 | [0.027450, 0.053677] | 0.0020 | Yes |
| B | Elastic Net | +0.002126 | [−0.006324, 0.010603] | 0.6363 | No |

## B1 versus B0

The ordinary option-state benchmark also improves on B0 for the confirmatory
Gamma GLM in both blocks: `+0.084420` in Block A (21.35% lower QLIKE) and
`+0.029015` in Block B (11.61% lower QLIKE).  Adding B2 then lowers Gamma
QLIKE by 25.21% and 15.76% relative to B1a in Blocks A and B, respectively.
This supports incremental information in B1 relative to the underlying/market
controls and a positive B2 increment under the frozen QLIKE protocol.

## Stability and scientific classification

- Gamma GLM B2 gains are positive in every session tercile in both blocks.
- Gamma GLM gains are positive for all six assets in Block B; Block A has one
  small negative asset slice (MSFT) and several intervals whose confidence
  intervals include zero.
- Gamma GLM gains are strongest in the high-volatility regime in Block A; the
  low/normal slices are not uniformly significant. Block B is positive in low
  and high regimes, while normal volatility is weaker.
- LightGBM is negative in both complete blocks and most of its asset, time and
  regime slices. This is a model-dependent divergence, not evidence to hide.

**Conclusion:** `B2_EDGE_STATUS = MODEL_DEPENDENT_POSITIVE`.  The frozen
confirmatory Gamma GLM result is positive, replicated across two disjoint
historical blocks, exceeds the MDE and survives Holm correction.  The evidence
does **not** justify the stronger claim of a universal model-independent edge,
because LightGBM deteriorates and some asset/regime slices are mixed.

## Why Gamma and LightGBM diverge

The development-only mechanism audit did not select a positive result after
searching the residual learner. All 25 residual candidates were recorded, but
zero passed the frozen retention rule; the signed residual corrections were
unstable and repeatedly reached the forecast floor. The direct B2 protocol was
therefore frozen before the new blocks, rather than choosing a residual variant
after seeing them.

The divergence is also consistent with measurable data and model diagnostics:

- B2 feature redundancy reached absolute Pearson correlation 0.8651 and the
  largest train/test PSI was 0.6204 for expiry concentration.
- Global correlations with the B1 residual were small; the largest absolute
  value was 0.0570 in the LightGBM diagnostic.
- Development calibration showed much larger Gamma forecast-to-actual ratios
  (median about 6.7 for B1 and 9.0 for residual variants) than LightGBM (median
  about 0.89 for B1 and 1.01 for residual variants), while Gamma's QLIKE
  contrast improved on the independent blocks and LightGBM's worsened.

These observations support a model-dependent result: Gamma's smooth positive
mean structure benefits from the B2 signal under this loss, while the shallow
tree challenger is more sensitive to feature drift, redundancy and interaction
thresholds. They do not prove a causal mechanism or authorize RL/DL.

The nine B2 variables were constructed before any RV30 or QLIKE read for the
new blocks, using `created_at <= forecast_origin - 60 seconds`; no balancing or
future provider fields were used.  RL and deep neural networks were not used:
the registered task is supervised tabular RV30 forecasting, for which adding an
action/reward loop or a high-capacity network would not improve identification
and would increase overfitting risk.

## Reproducibility artifacts

| Artifact | SHA-256 |
|---|---|
| `artifacts/methodology/b2_confirmation_acquisition_manifest_v1.json` | `4f0564751eb91190f5d4504a6a1f7ec676a54fbf75bd04f6b5f819b96dbccbda` |
| `artifacts/b2_confirmation/b2_manifest.json` | `425c9b704a7d1b429217d63f2ecb4337aa15b684849e8af20b8d136e415e8d7e` |
| `artifacts/b2_confirmation/b1/b1_origin_matrix_20d.parquet` | `7f976b8df6038f05e73b6508efa110aed057b2abc84eae40640e99d194b42057` |
| `artifacts/b2_confirmation/panel_manifest.json` | `29ffc33eb3fda0148ba4f983f5b09bf147f4ba16e5357e4fbaf6113f77f7ed4b` |
| `artifacts/b2_confirmation/frozen_evaluation_results.json` | `9f2e275febed2fb4057da18204f19617a19dc1549458a55b92b3f8e335308824` |
| `artifacts/b2_confirmation/frozen_evaluation_forecasts.parquet` | `db20b76248afce02e04009c510b408214d267a30e7cff3f8dc184d370574ce8b` |
| `artifacts/b2_confirmation/frozen_evaluation_metrics.csv` | `b58e956f5035feeef15d4ac25122abeae4b177d371ba824fb139e01b23b5ffe1` |
| `artifacts/b2_confirmation/frozen_evaluation_stability.csv` | `7155bfc540353886ea93a304b94e0bef665ad8a95bee174106928e06f9d7d079` |
| `artifacts/b2_confirmation/frozen_evaluation_calibration.csv` | `86f68601e6eb4e969359722367c9cd69d40348ffd2ba604b73c2dff5ea72531a` |
| `artifacts/b2_confirmation/frozen_evaluation_qlike_effects.svg` | `dcf443195bda00d0cf213516efbae9856a13982780a9f69122bae1a180491b16` |
| `docs/b2_confirmation_model_card.md` | `c812443b6b4a435dbc50d182a0a3a09bf65e5ba59b1a606a5bcc43fca1d8d738` |
