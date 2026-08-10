# Independent 30-Session Replication — RV30 B2

> Evidence generated from frozen manifests and `independent_results.json`; no target reread or network request is performed by this report.

## Executive conclusion

The preregistered Gamma GLM confirms a positive global B1-to-B2 QLIKE contrast that exceeds the training-only MDE. The LightGBM robustness challenger has the opposite sign and remains below its MDE. Therefore the replication supports a **model-dependent B2 signal**, not a universal or trading-profitability claim.

- Registered decision: `TARGETED_B2V2_REPLICATION_CONFIRMED`.
- Gamma B2 contrast: 0.032915 (IC 95% 0.024444 to 0.041626).
- LightGBM B2 contrast: -0.001802 (IC 95% -0.002400 to -0.001194).
- All positive, negative and null variants remain registered; no model was selected after inspecting the target outcome.

## 1. Acquisition and provider incident

- Target dates: `2025-05-21` through `2025-07-03`; 30/30 target sessions present.
- Target responses: HTTP 200, one schema fingerprint, 0 duplicate event IDs.
- Target rows: 225,810,612 seen and 84,200,233 retained; raw 31,233,185,187 bytes; Parquet 4,884,998,863 bytes.
- Warm-up status: `PASS_WITH_PROVIDER_INCIDENT` with explicit provider exclusion `2025-04-04`.
- The excluded warm-up archive is not represented as a no-event session and was not imputed; it is retained as a provider incident.
- Historical file availability is proven for the downloaded target dates only; Range metadata alone does not prove independent publication-time semantics for `created_at`.

## 2. Frozen protocol

- Target: RV30, using the fully observed origin close plus 30 future one-minute closes (31 prices and 30 log returns).
- Information sets: B0v2, B1v2a and B2v2; B2 primary cutoff `created_at <= forecast_origin - 60 seconds`.
- Primary loss: QLIKE; MAE and RMSE are descriptive only.
- Roles: Gamma GLM confirmatory; LightGBM robustness challenger.
- Inference: 10,000 paired bootstrap repetitions by XNYS session date with all assets kept together; Holm multiplicity control.
- Target access ledger: one read; no new tuning after acquisition; 30-minute purge/embargo retained.

## 3. Development-only model comparison

The development panel contains 15,548 common origins over 80 sessions. The MDE is a training-only planning quantity estimated from outer-fold daily effects; it is not an economic hurdle and was not tuned on independent outcomes.

| Modelo | Δ B1 (IC 95%) | Holm p | Δ B2 (IC 95%) | Holm p | Signo B2 |
| --- | --- | --- | --- | --- | --- |
| persistence | 0.000000 [0.000000, 0.000000] | 1.0000 | 0.000000 [0.000000, 0.000000] | 1.0000 | ZERO |
| har_rv | 0.006512 [-0.001898, 0.015560] | 0.1320 | 0.029053 [0.014871, 0.044308] | 0.0004 | POSITIVE |
| ridge | 0.006507 [-0.001917, 0.015559] | 0.1324 | 0.029036 [0.014877, 0.044280] | 0.0004 | POSITIVE |
| gamma_glm | -2.883e-04 [-0.007583, 0.006896] | 0.9501 | 0.013118 [0.003323, 0.024098] | 0.0120 | POSITIVE |
| lightgbm | 0.004831 [4.592e-04, 0.010346] | 0.0500 | 0.002191 [-0.001882, 0.006493] | 0.3214 | POSITIVE |

Elastic Net remains registered as a possible extension but was not fitted in this gate; adding it after seeing independent outcomes would violate the freeze.

## 4. Independent global contrasts and MDE

The independent target contains 11,664 origins and 69,984 paired forecast rows.

| Rol | Contraste | Estimación | IC 95% | Holm p | MDE | Supera MDE | Signo |
| --- | --- | --- | --- | --- | --- | --- | --- |
| gamma_glm_confirmatory | delta_b1v2 | -0.086981 | [-0.145203, -0.027069] | 0.0040 | 0.021686 | NO | NEGATIVE |
| gamma_glm_confirmatory | delta_b2v2 | 0.032915 | [0.024444, 0.041626] | 0.0004 | 0.005035 | YES | POSITIVE |
| lightgbm_robustness | delta_b1v2 | 0.005537 | [-1.886e-04, 0.010764] | — | 0.021686 | NO | POSITIVE |
| lightgbm_robustness | delta_b2v2 | -0.001802 | [-0.002400, -0.001194] | — | 0.005035 | NO | NEGATIVE |

Positive Δ means the richer information set has lower QLIKE. Statistical significance and exceeding the frozen MDE are separate criteria.

## 5. Stability by asset

### Gamma GLM — B2

| Estrato | Δ B2 | IC 95% | p | Signo |
| --- | --- | --- | --- | --- |
| AAPL | 0.026148 | [0.008109, 0.044104] | 0.0042 | POSITIVE |
| AMZN | 0.024537 | [0.007895, 0.040325] | 0.0050 | POSITIVE |
| META | 0.016302 | [0.002385, 0.030244] | 0.0206 | POSITIVE |
| MSFT | 0.019972 | [0.008310, 0.031224] | 0.0022 | POSITIVE |
| NVDA | 0.076260 | [0.052101, 0.099651] | 0.0002 | POSITIVE |
| TSLA | 0.034273 | [-0.003542, 0.091652] | 0.1022 | POSITIVE |

### LightGBM — B2

| Estrato | Δ B2 | IC 95% | p | Signo |
| --- | --- | --- | --- | --- |
| AAPL | 3.476e-04 | [-6.493e-04, 0.001483] | 0.5443 | POSITIVE |
| AMZN | -4.627e-04 | [-0.001084, 1.594e-04] | 0.1460 | NEGATIVE |
| META | -4.455e-04 | [-0.002133, 0.001245] | 0.6141 | NEGATIVE |
| MSFT | -0.010664 | [-0.013926, -0.007267] | 0.0002 | NEGATIVE |
| NVDA | 9.378e-04 | [-2.627e-04, 0.002071] | 0.1232 | POSITIVE |
| TSLA | -5.267e-04 | [-0.001423, 3.172e-04] | 0.2216 | NEGATIVE |

## 6. Stability by session tercile and volatility regime

### Gamma GLM — session tercile

| Estrato | Δ B2 | IC 95% | p | Signo |
| --- | --- | --- | --- | --- |
| first | 0.016718 | [0.003494, 0.029340] | 0.0150 | POSITIVE |
| last | 0.032602 | [0.014440, 0.057834] | 0.0002 | POSITIVE |
| middle | 0.045233 | [0.032342, 0.057788] | 0.0002 | POSITIVE |

### LightGBM — session tercile

| Estrato | Δ B2 | IC 95% | p | Signo |
| --- | --- | --- | --- | --- |
| first | -0.001309 | [-0.002116, -5.176e-04] | 0.0020 | NEGATIVE |
| last | -0.001331 | [-0.002165, -3.929e-04] | 0.0074 | NEGATIVE |
| middle | -0.002545 | [-0.003674, -0.001295] | 0.0006 | NEGATIVE |

### Gamma GLM — volatility regime

| Estrato | Δ B2 | IC 95% | p | Signo |
| --- | --- | --- | --- | --- |
| high | 0.037977 | [-0.008807, 0.115309] | 0.3584 | POSITIVE |
| low | 0.038690 | [0.028518, 0.048297] | 0.0002 | POSITIVE |
| normal | 0.016544 | [0.005802, 0.027608] | 0.0030 | POSITIVE |

### LightGBM — volatility regime

| Estrato | Δ B2 | IC 95% | p | Signo |
| --- | --- | --- | --- | --- |
| high | 3.268e-05 | [-0.001266, 0.001401] | 0.9859 | POSITIVE |
| low | -0.002656 | [-0.003648, -0.001627] | 0.0002 | NEGATIVE |
| normal | -4.039e-04 | [-0.001301, 5.160e-04] | 0.3800 | NEGATIVE |

## 7. Stability by New York hour

| Rol | Hora NY | Δ B2 | IC 95% | p | Signo |
| --- | --- | --- | --- | --- | --- |
| gamma_glm_confirmatory | 10 | 0.016649 | [8.322e-04, 0.029741] | 0.0410 | POSITIVE |
| gamma_glm_confirmatory | 11 | 0.020525 | [0.004564, 0.035613] | 0.0106 | POSITIVE |
| gamma_glm_confirmatory | 12 | 0.043578 | [0.025656, 0.060767] | 0.0002 | POSITIVE |
| gamma_glm_confirmatory | 13 | 0.048532 | [0.033096, 0.063288] | 0.0002 | POSITIVE |
| gamma_glm_confirmatory | 14 | 0.033052 | [0.014235, 0.055188] | 0.0004 | POSITIVE |
| gamma_glm_confirmatory | 15 | 0.035677 | [0.012360, 0.072524] | 0.0002 | POSITIVE |
| lightgbm_robustness | 10 | -0.001820 | [-0.002777, -8.834e-04] | 0.0002 | NEGATIVE |
| lightgbm_robustness | 11 | -7.063e-04 | [-0.001927, 5.172e-04] | 0.2580 | NEGATIVE |
| lightgbm_robustness | 12 | -0.003078 | [-0.004480, -0.001575] | 0.0002 | NEGATIVE |
| lightgbm_robustness | 13 | -0.002078 | [-0.003784, -1.642e-04] | 0.0366 | NEGATIVE |
| lightgbm_robustness | 14 | -0.001583 | [-0.002754, -3.730e-04] | 0.0130 | NEGATIVE |
| lightgbm_robustness | 15 | -0.001387 | [-0.003875, 5.761e-04] | 0.2076 | NEGATIVE |

## 8. Timing sensitivities

The Gamma B2 sign remains positive under the registered FMP delay and UW latency/window variants. LightGBM remains heterogeneous; these are sensitivity results, not a new selection rule.

| Rol | Sensibilidad | Δ B2 | IC 95% | p | Signo |
| --- | --- | --- | --- | --- | --- |
| gamma_glm_confirmatory | FMP_DELAY_2_MINUTES | 0.033027 | [0.024539, 0.041680] | 0.0002 | POSITIVE |
| gamma_glm_confirmatory | latency_5m_120s | 0.031675 | [0.023541, 0.040030] | 0.0002 | POSITIVE |
| gamma_glm_confirmatory | latency_5m_300s | 0.029698 | [0.020791, 0.038713] | 0.0002 | POSITIVE |
| gamma_glm_confirmatory | window_15m_60s | 0.036132 | [0.025989, 0.046346] | 0.0002 | POSITIVE |
| gamma_glm_confirmatory | window_30m_60s | 0.037240 | [0.026250, 0.048196] | 0.0002 | POSITIVE |
| lightgbm_robustness | FMP_DELAY_2_MINUTES | -0.001356 | [-0.002310, -3.943e-04] | 0.0062 | NEGATIVE |
| lightgbm_robustness | latency_5m_120s | 9.730e-04 | [1.902e-04, 0.001765] | 0.0112 | POSITIVE |
| lightgbm_robustness | latency_5m_300s | -0.001082 | [-0.001574, -6.253e-04] | 0.0002 | NEGATIVE |
| lightgbm_robustness | window_15m_60s | 6.255e-04 | [-2.885e-04, 0.001627] | 0.1916 | POSITIVE |
| lightgbm_robustness | window_30m_60s | -4.929e-04 | [-0.001762, 7.333e-04] | 0.4348 | NEGATIVE |

## 9. Calibration diagnostics

| Rol | Información | RV30 media | Pronóstico medio | Sesgo medio | Mediana real/pronóstico |
| --- | --- | --- | --- | --- | --- |
| gamma_glm_confirmatory | B0v2 | 1.436e-05 | 1.311e-05 | -1.253e-06 | 0.835882 |
| gamma_glm_confirmatory | B1v2a | 1.436e-05 | 2.369e-05 | 9.333e-06 | 0.427574 |
| gamma_glm_confirmatory | B2v2 | 1.436e-05 | 2.286e-05 | 8.504e-06 | 0.469302 |
| lightgbm_robustness | B0v2 | 1.436e-05 | 1.556e-05 | 1.199e-06 | 0.712940 |
| lightgbm_robustness | B1v2a | 1.436e-05 | 1.521e-05 | 8.559e-07 | 0.746939 |
| lightgbm_robustness | B2v2 | 1.436e-05 | 1.528e-05 | 9.223e-07 | 0.741911 |

Calibration rows are descriptive and do not authorize recalibration after target inspection.

## 10. Limitations and decision

- The provider incident removes one warm-up date; the missing date is explicit and not imputed.
- `created_at` is an operational availability proxy, not demonstrated publication time or evidence of trader intent.
- The positive Gamma result is not reproduced by LightGBM; the evidence does not establish a model-independent global edge.
- No profitability, execution, transaction-cost or capital-readiness claim is made.
- RL and deep learning are outside this frozen evaluation and would require a new preregistration and a distinct justification.

## Evidence paths

- Results: `artifacts/independent_replication/independent_results.json`.
- Flattened stability: `artifacts/independent_replication/stability.parquet`.
- Sanitized evidence index: `artifacts/independent_replication/evidence_index.csv`.
- Acquisition incident: `artifacts/independent_replication/acquisition_incidents/2025-04-04_crc_failure.json`.
