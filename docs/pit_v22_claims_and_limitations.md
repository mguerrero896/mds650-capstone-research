# MDS650 PIT v2.2 — Claims and Limitations Ledger

## Scope

This ledger is target-blind. It contains no RV30, forecast, loss, QLIKE,
model-fit or sealed out-of-sample payload. It records what the corrected
PIT input evidence supports and what remains untested.

```text
SAFE_TO_RECONCILE_EXISTING_RESULTS=NO
SAFE_TO_OPEN_OR_EVALUATE_OOS=NO
MODEL_FIT_PERFORMED=NO
```

## Claims

| ID | Status | Claim | Limitation | Evidence |
| --- | --- | --- | --- | --- |
| PITV22-C001 | SUPPORTED_TARGET_BLIND | The corrected B0/B1Q/B2 predictor construction preserved 77328 forecast origins and 62266 common-complete origins across 6 outcome assets. | These are input-coverage counts, not predictive metrics. | artifacts/target_blind_v22/target_blind_common_predictor_manifest_v22.json; artifacts/target_blind_v22/confirmation_readiness_v1.json |
| PITV22-C002 | PROXY_ONLY | Unusual Whales created_at is retained only as an operational availability proxy at the registered cutoff. | It is not provider-proven publication time or client receipt time. | docs/provider_timing_pit_contract_v21.md; docs/provider_timing_claim_matrix_v21.md |
| PITV22-C003 | STUDY_CONSERVATIVE_RULE | FMP plus one minute (with plus two minutes sensitivity) and Massive SIP as-of selection remain conservative study rules. | They do not prove provider or client-side message receipt latency. | docs/provider_timing_pit_contract_v21.md; docs/provider_timing_claim_matrix_v21.md |
| PITV22-C004 | SUPPORTED_TARGET_BLIND | The primary B2 availability sidecar marks 451 of 77328 rows as excluded rather than treating delayed source records as zero activity. | The correction changes eligibility only; it does not validate performance. | artifacts/provider_timing_v22/b2_availability_manifest_v22.json; artifacts/provider_timing_v22/b2_availability_summary_v22.json; artifacts/target_blind_v22/target_blind_common_predictor_manifest_v22.json |
| PITV22-C005 | BLOCKED_RECONCILIATION | Pre-v2.2 sealed results are not eligible for reconciliation. | No prior sign, metric or ranking may be carried into a corrected claim. | artifacts/target_blind_v22/target_blind_common_predictor_manifest_v22.json; artifacts/target_blind_v22/confirmation_readiness_v1.json; artifacts/provider_timing_v22/b2_availability_manifest_v22.json; artifacts/provider_timing_v22/b2_availability_summary_v22.json; artifacts/target_blind_v22/target_blind_common_predictor_manifest_v22.json |
| PITV22-C006 | NOT_EVALUATED_AFTER_PIT_CORRECTION | Whether B1 improves B0 for RV30 is not yet evaluated after PIT v2.2. | A successor method freeze and authorized evaluation are required. | artifacts/target_blind_v22/target_blind_common_predictor_manifest_v22.json; artifacts/target_blind_v22/confirmation_readiness_v1.json; artifacts/provider_timing_v22/b2_availability_manifest_v22.json; artifacts/provider_timing_v22/b2_availability_summary_v22.json; artifacts/target_blind_v22/target_blind_common_predictor_manifest_v22.json |
| PITV22-C007 | NOT_EVALUATED_AFTER_PIT_CORRECTION | Whether B2 adds incremental value over B1 is not yet evaluated after PIT v2.2. | The target-blind ledger contains no loss or model output. | artifacts/target_blind_v22/target_blind_common_predictor_manifest_v22.json; artifacts/target_blind_v22/confirmation_readiness_v1.json; artifacts/provider_timing_v22/b2_availability_manifest_v22.json; artifacts/provider_timing_v22/b2_availability_summary_v22.json; artifacts/target_blind_v22/target_blind_common_predictor_manifest_v22.json |
| PITV22-C008 | NOT_EVALUATED_AFTER_PIT_CORRECTION | Stability by asset, session segment, volatility regime and latency assumption is not yet evaluated after PIT v2.2. | No corrected forecasts, contrasts or stability payloads were read. | artifacts/target_blind_v22/target_blind_common_predictor_manifest_v22.json; artifacts/target_blind_v22/confirmation_readiness_v1.json; docs/provider_timing_pit_contract_v21.md; docs/provider_timing_claim_matrix_v21.md |

## Scientific questions not yet evaluated

| Question | Status | Reason |
| --- | --- | --- |
| Q1_B1_VERSUS_B0 | NOT_EVALUATED_AFTER_PIT_CORRECTION | A corrected successor evaluation has not been authorised or run. |
| Q2_B2_INCREMENTAL_OVER_B1 | NOT_EVALUATED_AFTER_PIT_CORRECTION | Pre-v2.2 sealed results are not eligible for reconciliation. |
| Q3_STABILITY_BY_ASSET_TIME_REGIME_AND_LATENCY | NOT_EVALUATED_AFTER_PIT_CORRECTION | No corrected model/evaluation payload has been read. |

## Required next gate

A successor method freeze must bind the corrected panel, temporal splits,
estimand, bootstrap, multiplicity policy, development-only MDE and a zero-OOS
access ledger before a separate explicit authorization can permit evaluation.
