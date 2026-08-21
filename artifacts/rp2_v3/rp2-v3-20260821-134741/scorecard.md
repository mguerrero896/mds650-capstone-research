# RP2-v3 scorecard

Schema `rp2-v3-scorecard-v1.0`. The run this describes is named by the directory it sits in and by `run_manifest.json` beside it; the rendering does not repeat it, so two runs of the same experiment produce the same document.

Code commit `08a4a06448c925920053ec2f82635910f8863e4e`.

## data

| Field | Value |
| --- | ---: |
| `assets` | 6 |
| `b0_rows` | 184632 |
| `b1_rows` | 184632 |
| `b2_rows` | 184632 |
| `common_evaluation_rows` | {"D": 61336, "V": 12672} |
| `duplicate_keys` | 0 |
| `masked_rows_by_role` | {"D": 152954, "V": 31678} |
| `provider_failures` | 0 |
| `sessions_by_role` | {"D": 389, "V": 80} |
| `sparse_session_assets` | 0 |

## b1

| Field | Value |
| --- | ---: |
| `b1_core_coverage` | 0.9934247584384072 |
| `b1_duplicate_contracts_per_snapshot` | 0 |
| `b1_median_quote_age_s` | 578.753286 |
| `b1_missing_rate_share` | 0.4305375016248537 |
| `b1_p95_quote_age_s` | 1723.9153418499998 |
| `b1_post_cutoff_observations` | 0 |
| `b1_rows_dropped_for_rate_or_dividend` | 0 |
| `b1_surface_contracts_per_origin` | 783.1134906191776 |
| `b1_surface_expiry_coverage` | 0.9978281121365744 |

## b2

| Field | Value |
| --- | ---: |
| `b2_empty_window_share` | 0.0023181247021101434 |
| `b2_mean_provider_latency_s` | 1.2213247210614415 |
| `b2_multileg_share` | 0.23057409460579115 |
| `b2_p95_provider_latency_s` | 0.28019322317457684 |
| `b2_pit_violation_count` | 0 |
| `b2_provider_failure_share` | 0.0 |
| `b2_zero_dte_count` | 102445819 |

## engineering

| Field | Value |
| --- | ---: |
| `artifact_sha256` | {"input_manifest.json": "d799ed167e7e9a7bafe533163b869f5b409978e093f71ff0acaca5b3ed1a9bff", "rp2_block3_target/target_panel.parquet": "c7d6a2b6fbcf84b96523eccc716e9433186b685eff19f4dcc37721dfdc010447", "rp2_block3_target/comparison.json": "cd1de8f5dde0cb0902541b4c05e31f4f2dd8bb8e01fe2a7856984006ecbdd6e6", "rp2_block4_b0/b0_panel.parquet": "c2d230c38df2677e9b36b24855eb8bab9b9a9c4747f7fc0e29b0b54fbdd1d9a2", "rp2_block4_b0/ladder.json": "83dee648edf8e3ed1133852f7088a2cbce7186c99d158ff0738f29f9aa1772ea", "rp2_block5_surface/b1_surface_panel.parquet": "d9e55b285e11e0b6850f233f1f5a8df897177914f61a697e0d5e745846a0104d", "rp2_block5_surface/surface_coverage.json": "112ec900e23211d1e5db6d7b884aba12aa4df23d15587b70333d5e16b494ac1b", "rp2_block6_flow/b2_flow_panel.parquet": "1206e5fc4f2dcb6a9a9cb3c015f2baefa464ff264617b856a532483eaceb558f", "rp2_block6_flow/flow_coverage.json": "573d553e822b303631d8ac2dfbab8eeb8336fc25585971d25b68ea90a439681b", "feature_registry_report.json": "9e50396995ed9dee07fc05823da613467a7c2b7c36ee5f3ae4e773af41262b87", "common_masks.json": "60b5a709af1db14e928b39b40648f78d54ba5689dabce6d7737177e271bbc4fc", "rp2_block8_ladder/ladder.json": "d14094910c6deed14dc278884dc92194c1708f3ce10356ad99d02c5874b25d2f", "rp2_block7_dml/dml.json": "742687d051778eef0c34d8cd067fb5bf60d7fe9c23cf85434b7e690f2ea738c0", "rp2_block10_inference/inference.json": "1ed0b8891c39721b0030adb9e9985035231da3a2aae3a9d2683d23fb3dc27b89"} |
| `code_commit` | 08a4a06448c925920053ec2f82635910f8863e4e |
| `feature_registry_sha256` | 3c108a14a5a88e4da08bade7debd5dc05a1d51ea50c1e5adea6d1e88dc0acb9c |
| `input_manifest_sha256` | 30076d04d2c8f86a9d2565543301443da803d31fe5818b8dd4fbf32bf1fa465f |
| `model_config_sha256` | 0c35efea1cabbac2c39406ba99bf88db1728c7b65124a7988bad65ee5b8f57d5 |
| `peak_memory_bytes` | see `run_manifest.json` |
| `runtime_seconds` | see `run_manifest.json` |

## forecast

| Family | Role | QLIKE B0 | ΔB1 | ΔB2\|B1 | MDE ΔB1 |
| --- | --- | ---: | ---: | ---: | ---: |
| `gamma_glm` | D | 0.14837 | +0.00408 | -0.02549 | 0.00245 |
| `gamma_glm` | V | 0.17500 | -0.00111 | -0.00222 | 0.00413 |
| `lightgbm_qlike` | D | 0.13893 | +0.00381 | +0.00065 | 0.00410 |
| `lightgbm_qlike` | V | 0.21145 | +0.00092 | -0.00051 | 0.01770 |
| `ridge_log` | D | 0.14901 | +0.00424 | -0.15509 | 0.00241 |
| `ridge_log` | V | 0.17849 | -0.00084 | -0.00195 | 0.00268 |

Calibration slope 1.0222775821510186, intercept 0.16698611876401465.
