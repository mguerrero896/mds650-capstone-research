# Canonical RV30 claims and limitations ledger

This ledger is the only allowed source for numerical claims in the capstone
report, presentation and oral defense. `SUPPORTED` means the stated artifact
directly supports the bounded statement; it does not imply a universal effect.
`CONDITIONAL` means it is limited to the exact model/block. `NOT_SUPPORTED`
must be reported as a negative result or omitted from positive-result framing.

## Claims ledger

| claim_id | claim_text | status | evidence_path | metric | model_role | block | limitation | allowed_presentation_context |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| CLM-001 | All canonical nested comparisons are paired on identical origins and have no unpaired rows. | SUPPORTED | artifacts/canonical_validation_v1/contrasts.json | paired QLIKE integrity | all_models | phase6_and_independent | This proves pairing, not predictive value. | methods and reproducibility |
| CLM-002 | Phase 6 Gamma B1v2a minus B0v2 is +0.01180281 with a positive interval but below the frozen 0.02168578 MDE. | CONDITIONAL | artifacts/canonical_validation_v1/contrasts.json | QLIKE delta B1 | gamma_glm_confirmatory | phase6 | Below MDE and not replicated with the same sign by Gamma. | bounded results table |
| CLM-003 | Phase 6 Gamma B2v2 minus B1v2a is +0.00443912 with a positive interval but below the frozen 0.00503510 MDE. | CONDITIONAL | artifacts/canonical_validation_v1/contrasts.json | QLIKE delta B2 | gamma_glm_confirmatory | phase6 | Below MDE and does not establish a global effect. | bounded results table |
| CLM-004 | Independent Gamma B1v2a minus B0v2 is -0.08698073 with a wholly negative interval. | SUPPORTED | artifacts/canonical_validation_v1/contrasts.json | QLIKE delta B1 | gamma_glm_confirmatory | independent_replication | Contradicts a universal positive B1 statement. | limitations and robustness |
| CLM-005 | Independent Gamma B2v2 minus B1v2a is +0.03291534, CI [0.02444358, 0.04162629], and exceeds the frozen MDE. | CONDITIONAL | artifacts/canonical_validation_v1/contrasts.json | QLIKE delta B2 | gamma_glm_confirmatory | independent_replication | LightGBM is negative for the same contrast in the same block. | targeted Gamma result only |
| CLM-006 | Independent LightGBM B1v2a minus B0v2 is +0.00553712 but its interval includes zero and it is below MDE. | CONDITIONAL | artifacts/canonical_validation_v1/contrasts.json | QLIKE delta B1 | lightgbm_robustness | independent_replication | Not a statistically or practically decisive result. | robustness table |
| CLM-007 | Independent LightGBM B2v2 minus B1v2a is -0.00180221 with a wholly negative interval. | SUPPORTED | artifacts/canonical_validation_v1/contrasts.json | QLIKE delta B2 | lightgbm_robustness | independent_replication | Prevents a model-independent B2 claim. | limitations and robustness |
| CLM-008 | B1v2a and B2v2 have MODEL_FAMILY_DEPENDENT eligibility across the registered families. | SUPPORTED | artifacts/canonical_validation_v1/contrasts.json | claim eligibility | gamma_glm_confirmatory_and_lightgbm_robustness | phase6_and_independent | Does not identify the causal source of disagreement. | executive conclusion |
| CLM-009 | Some B2 feature pairs are materially correlated, including Phase 6 mean and max trade-premium z-scores at 0.87057727. | SUPPORTED | artifacts/canonical_validation_v1/redundancy.json | target-blind pairwise correlation | b2_feature_set | phase6 | Correlation is descriptive and does not select or remove features. | feature diagnostics |
| CLM-010 | The five-model table contains Gamma GLM and LightGBM as registered evidence and HAR-RV, Ridge and Elastic Net as post-read fixed extension analyses. | SUPPORTED | artifacts/canonical_validation_v1/phase6/model_variant_ledger.json | analysis status | all_models | phase6_and_independent | Extensions cannot confirm the registered claim. | methods and limitations |

## Non-negotiable limitations

1. **No universal positive edge:** The registered model families disagree in
   the independent evidence for both B1 and B2. The result cannot be converted
   into a global positive statement by averaging signs or selecting a model.
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
