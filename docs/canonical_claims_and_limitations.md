# Canonical RV30 claims and limitations ledger

This ledger is the only allowed source for numerical claims in the capstone
report, presentation and oral defense. `SUPPORTED` means the stated artifact
directly supports the bounded statement; it does not imply a universal effect.
`CONDITIONAL` means it is limited to the exact model/block. `NOT_SUPPORTED`
must be reported as a negative result or omitted from positive-result framing.
`INVALIDATED_INPUT` retains a historical numerical output for audit but forbids
using it as scientific confirmation after a material upstream defect is found.

## Claims ledger

| claim_id | claim_text | status | evidence_path | metric | model_role | block | limitation | allowed_presentation_context |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| CLM-001 | All canonical nested comparisons are paired on identical origins and have no unpaired rows. | SUPPORTED | artifacts/canonical_validation_v1/contrasts.json | paired QLIKE integrity | all_models | phase6_and_independent | This proves pairing, not predictive value. | methods and reproducibility |
| CLM-002 | Phase 6 Gamma B1v2a minus B0v2 is +0.01180281 with a positive interval but below the frozen 0.02168578 MDE. | CONDITIONAL | artifacts/canonical_validation_v1/contrasts.json | QLIKE delta B1 | gamma_glm_confirmatory | phase6 | Below MDE and not replicated with the same sign by Gamma. | bounded results table |
| CLM-003 | Phase 6 Gamma B2v2 minus B1v2a is +0.00443912 with a positive interval but below the frozen 0.00503510 MDE. | CONDITIONAL | artifacts/canonical_validation_v1/contrasts.json | QLIKE delta B2 | gamma_glm_confirmatory | phase6 | Below MDE and does not establish a global effect. | bounded results table |
| CLM-004 | Independent Gamma B1v2a minus B0v2 was -0.08698073 with a wholly negative interval under the superseded B1 input. | INVALIDATED_INPUT | artifacts/canonical_validation_v1/contrasts.json; artifacts/independent_replication/b1_pit_v2_manifest.json | QLIKE delta B1 | gamma_glm_confirmatory | independent_replication | The B1 dividend input was duplicated ninefold for four assets and cannot support confirmation. | forensic history only |
| CLM-005 | Independent Gamma B2v2 minus B1v2a was +0.03291534, CI [0.02444358, 0.04162629], under the superseded B1 input. | INVALIDATED_INPUT | artifacts/canonical_validation_v1/contrasts.json; artifacts/independent_replication/b1_pit_v2_manifest.json | QLIKE delta B2 | gamma_glm_confirmatory | independent_replication | B2 is nested on the affected B1 baseline; the positive historical output requires a new corrected evaluation. | forensic history only |
| CLM-006 | Independent LightGBM B1v2a minus B0v2 was +0.00553712 under the superseded B1 input. | INVALIDATED_INPUT | artifacts/canonical_validation_v1/contrasts.json; artifacts/independent_replication/b1_pit_v2_manifest.json | QLIKE delta B1 | lightgbm_robustness | independent_replication | The B1 dividend input was duplicated ninefold for four assets. | forensic history only |
| CLM-007 | Independent LightGBM B2v2 minus B1v2a was -0.00180221 under the superseded B1 input. | INVALIDATED_INPUT | artifacts/canonical_validation_v1/contrasts.json; artifacts/independent_replication/b1_pit_v2_manifest.json | QLIKE delta B2 | lightgbm_robustness | independent_replication | B2 is nested on the affected B1 baseline; the sign cannot decide global robustness. | forensic history only |
| CLM-008 | The corrected reevaluation does not establish a global model-family-independent B1 or B2 edge. | NOT_SUPPORTED | artifacts/independent_replication_pit_v2/results.json | claim eligibility | gamma_glm_confirmatory_and_lightgbm_robustness | corrected_independent_reevaluation | `confirmed_contrasts` is empty; targeted Gamma evidence cannot be presented as universal confirmation. | executive conclusion |
| CLM-009 | Some B2 feature pairs are materially correlated, including Phase 6 mean and max trade-premium z-scores at 0.87057727. | SUPPORTED | artifacts/canonical_validation_v1/redundancy.json | target-blind pairwise correlation | b2_feature_set | phase6 | Correlation is descriptive and does not select or remove features. | feature diagnostics |
| CLM-010 | The five-model table contains Gamma GLM and LightGBM as registered evidence and HAR-RV, Ridge and Elastic Net as post-read fixed extension analyses. | SUPPORTED | artifacts/canonical_validation_v1/phase6/model_variant_ledger.json | analysis status | all_models | phase6_and_independent | Extensions cannot confirm the registered claim. | methods and limitations |
| CLM-011 | The retained B1Q rate and dividend values reproduce exactly for 77,328 rows, with no reconstructed availability time after its forecast origin. | SUPPORTED | artifacts/provider_timing_v21/b1q_exogenous_provenance_v1_20260813.json | target-blind source parity | b1q_input_audit | 180_sessions | Availability is reconstructed under documented conservative rules, not historical client receipt. | data provenance and PIT controls |
| CLM-012 | The corrected target-blind panel preserves 77,328 origins, excludes 451 delayed or unavailable B2 rows rather than zero-coding them, and contains 62,266 common-complete origins. | SUPPORTED | artifacts/target_blind_v24_sourcebound_20260812/target_blind_common_predictor_manifest_v24.json | predictor coverage | no_model | 180_sessions | Coverage counts do not demonstrate predictive value. | data quality and PIT controls |
| CLM-013 | The independent target-free B1 repair corrected 257,328 IV-attempt rows and changed ATM-IV for 25,773 of 38,664 origins while preserving 91.61% B1a coverage. | SUPPORTED | artifacts/independent_replication/b1_pit_v2_manifest.json | target-blind input repair | no_model | independent_90_sessions | This does not reveal whether corrected QLIKE is positive, negative or null. | data provenance and forensic correction |
| CLM-014 | Corrected Gamma B1v2a minus B0v2 is -0.09078087, CI [-0.14949654, -0.03027743], Holm p=0.00299970. | SUPPORTED | artifacts/independent_replication_pit_v2/results.json | QLIKE delta B1 | gamma_glm_confirmatory | corrected_independent_reevaluation | ATM IV worsens the registered Gamma forecast on this block; this is not a claim that option state never helps. | primary corrected result |
| CLM-015 | Corrected LightGBM B1v2a minus B0v2 is +0.00518679, CI [-0.00053310, 0.01033759], p=0.07159284, below the 0.02168578 MDE. | CONDITIONAL | artifacts/independent_replication_pit_v2/results.json | QLIKE delta B1 | lightgbm_robustness | corrected_independent_reevaluation | Direction is favorable but statistically and materially inconclusive. | robustness result |
| CLM-016 | Corrected Gamma B2v2 minus B1v2a is +0.03396090, CI [0.02542800, 0.04266183], Holm p=0.00039996, above the 0.00503510 MDE. | CONDITIONAL | artifacts/independent_replication_pit_v2/results.json | QLIKE delta B2 | gamma_glm_confirmatory | corrected_independent_reevaluation | This confirms the registered Gamma contrast, not a model-independent global edge. | primary corrected result |
| CLM-017 | Corrected LightGBM B2v2 minus B1v2a is +0.00027708, CI [-0.00020048, 0.00079472], p=0.28357164, below MDE. | CONDITIONAL | artifacts/independent_replication_pit_v2/results.json | QLIKE delta B2 | lightgbm_robustness | corrected_independent_reevaluation | The favorable sign is small and inconclusive. | robustness result |
| CLM-018 | Gamma B2 is positive in 6/6 assets, 3/3 session terciles, 3/3 volatility regimes and 6/6 session hours; five assets, all terciles, two regimes and all hours have intervals above zero. | CONDITIONAL | artifacts/independent_replication_pit_v2/results.json | QLIKE stability | gamma_glm_confirmatory | corrected_independent_reevaluation | TSLA and the high-volatility regime include zero; these are subgroup analyses, not separate confirmations. | stability result |
| CLM-019 | Gamma B2 remains positive with intervals above zero in all five registered timing sensitivities, while LightGBM is positive in only 2/5 and significantly negative under the FMP +2-minute sensitivity. | CONDITIONAL | artifacts/independent_replication_pit_v2/results.json | QLIKE timing sensitivity | gamma_glm_confirmatory_and_lightgbm_robustness | corrected_independent_reevaluation | Timing robustness is model-family dependent. | timing sensitivity and limitations |

## Non-negotiable limitations

1. **No universal positive edge:** Corrected B2 has strong confirmatory Gamma
   evidence, but the LightGBM effect is small, uncertain and below MDE. B1 also
   disagrees by model family. The registered global confirmation gate therefore
   remains closed even though the targeted Gamma B2 result is positive.
2. **B1 scope:** B1v2a is a valid ATM-IV ordinary-option-state benchmark only;
   skew and term structure are not silently imputed as if they were available.
3. **Operational availability:** B2 uses the frozen `created_at <= origin - 60
   seconds` operational availability proxy. It is not called publication time
   and does not establish trader intent or informed trading.
4. **Provider and asset roles:** SPY and QQQ are market controls. Their absence
   from outcome tables is deliberate, not a post-result asset exclusion.
5. **Extensions:** HAR-RV, Ridge and Elastic Net are post-read fixed extension
   analyses. Their results are descriptive and cannot become registered proof.
6. **Practical use:** RV30 forecasting metrics do not establish a trading
   strategy, economic profit, causality, capacity or social benefit.

## Prohibited wording

- “Options universally improve RV30 forecasts.”
- “B2 is robustly positive across models.”
- “Trades reveal informed direction.”
- “SPY and QQQ failed the outcome screen.”
- “The extension models independently confirmed the result.”
