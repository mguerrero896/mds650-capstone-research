# RP2-v3 scorecard

Schema `rp2-v3-scorecard-v1.0`. The run this describes is named by the directory it sits in and by `run_manifest.json` beside it; the rendering does not repeat it, so two runs of the same experiment produce the same document.

Code commit `7225fdfaa7d75f634a1037df15c4b26360ba4d00`.

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
| `b1_median_quote_age_s` | 450.0 |
| `b1_missing_rate_share` | 0.4305375016248537 |
| `b1_p95_quote_age_s` | 1350.0 |
| `b1_post_cutoff_observations` | 0 |
| `b1_rows_dropped_for_rate_or_dividend` | 0 |
| `b1_surface_contracts_per_origin` | 783.1134906191776 |
| `b1_surface_expiry_coverage` | 0.9978281121365744 |

## b2

| Field | Value |
| --- | ---: |
| `b2_empty_window_share` | 0.0023181247021101434 |
| `b2_mean_provider_latency_s` | 1.221522874453539 |
| `b2_multileg_share` | 0.23693619596357562 |
| `b2_p95_provider_latency_s` | 0.3555064279213946 |
| `b2_pit_violation_count` | 0 |
| `b2_provider_failure_share` | 0.0 |
| `b2_zero_dte_count` | 102568762 |

## engineering

| Field | Value |
| --- | ---: |
| `artifact_sha256` | {"input_manifest.json": "9a2a1633127623a9ff806051ee75da5b57633e277619e3005ae41d22dbd20984", "rp2_block3_target/target_panel.parquet": "4723e433b7feb2043270c463924cfbc975ccf44cc665845f9ee80346770ba992", "rp2_block3_target/comparison.json": "71ea4e179103ed4b0788c9e4fde30624796d06667fa7a092f0f0a34ac7890d35", "rp2_block4_b0/b0_panel.parquet": "7a6b8dc721ae9fca974f6c574da66e33b433c4f27f7ee6935182cd6447d3c56f", "rp2_block4_b0/ladder.json": "79e0d26bc2b2f429533f916279041385e0babacb2d7b68d4f4a38fdfe458919c", "rp2_block5_surface/b1_surface_panel.parquet": "3da2195176468f0f2fd83c6e3a085cb6436d026989cfdec7e6d4627ea2dec5ba", "rp2_block5_surface/surface_coverage.json": "ce518771dbcd0b84902b3f71346344e9cf08c9ecc4025aa8965328cf508ffbff", "rp2_block6_flow/b2_flow_panel.parquet": "5375ef33a13f188ebaa84dd4db5bb7813aecd2eb19f5b09027d725a8f9053eda", "rp2_block6_flow/flow_coverage.json": "d5836b7b4c12fcb6a91d2038c8f9cbb1c014a225fa7ebe13e5574f99f5a52b0f", "feature_registry_report.json": "9e50396995ed9dee07fc05823da613467a7c2b7c36ee5f3ae4e773af41262b87", "common_masks.json": "60b5a709af1db14e928b39b40648f78d54ba5689dabce6d7737177e271bbc4fc", "rp2_block8_ladder/ladder.json": "102c05e44ba0fecadac235b0496b1b51500fedd9317b171e135086e7f97d8eba", "rp2_block7_dml/dml.json": "68113e76b46d33cf1c3145b9a163d1204bc04df2d29a0cdf7e78d7ec418b1cc9", "rp2_block10_inference/inference.json": "e380162d9ff8def9dbb09a4d749ed05b74c0d2db358634979fa5479a0b4df95b"} |
| `code_commit` | 7225fdfaa7d75f634a1037df15c4b26360ba4d00 |
| `feature_registry_sha256` | 3c108a14a5a88e4da08bade7debd5dc05a1d51ea50c1e5adea6d1e88dc0acb9c |
| `input_manifest_sha256` | 11a158b302ade3c4c6b475f6cde973a93b275ec1c4b894ace66bccbc84ded8ab |
| `model_config_sha256` | 0c35efea1cabbac2c39406ba99bf88db1728c7b65124a7988bad65ee5b8f57d5 |
| `peak_memory_bytes` | see `run_manifest.json` |
| `runtime_seconds` | see `run_manifest.json` |

## forecast

| Family | Role | QLIKE B0 | ΔB1 | ΔB2\|B1 | MDE ΔB1 |
| --- | --- | ---: | ---: | ---: | ---: |
| `gamma_glm` | D | 0.13881 | +0.00234 | -0.00506 | 0.00179 |
| `gamma_glm` | V | 0.17500 | -0.00111 | -0.00222 | 0.00413 |
| `lightgbm_qlike` | D | 0.13646 | +0.00314 | +0.00113 | 0.00393 |
| `lightgbm_qlike` | V | 0.21145 | +0.00092 | -0.00051 | 0.01770 |
| `ridge_log` | D | 0.13961 | +0.00250 | -0.01451 | 0.00169 |
| `ridge_log` | V | 0.17849 | -0.00084 | -0.00195 | 0.00268 |

Calibration slope 1.0221155000148259, intercept 0.16580068030397307.
