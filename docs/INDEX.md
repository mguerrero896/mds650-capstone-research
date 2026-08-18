# Documentation index

Classification of every file in `docs/` (housekeeping 2026-08-18, decision-56 era).
Rule: nothing scientific is deleted — superseded and historical documents are the
audit trail of the preregistration process. When two docs disagree, the `current`
one governs; the binding chain is always `methodology_decisions.md` ->
`results_reconciliation_v2.md` -> the frozen artifacts.

Subdirectories: `superpowers/` (historical session plans), `handoffs/` (one legacy
handoff), `literature_sources/` (ledger-backed source index). CSV ledgers
(`literature_evidence_ledger_v2.csv`, `method_claim_source_map_v1.csv`) are current;
`literature_evidence_ledger.csv` and `literature_matrix.csv` are superseded by v2.

## Current (governing / latest of chain / evergreen)

| Doc | Topic | Note |
|---|---|---|
| `architecture.md` | architecture | Evergreen pipeline architecture reference: package-vs-Colab boundary and evidence flow from bounded provider request to B0/B1/B2 evaluation. |
| `calibrated_asset_quality_decision.md` | asset-quality | Provisional 20-session asset roles (five targets plus NVDA eligible, SPY/QQQ B0 controls) from data-only gates; final freeze still blocked. |
| `b1_data_contract.md` | b1-benchmark | Governing B1Q/B1T data contract: quote-selection rule (sip_timestamp <= origin, 60s/25% filters), DTE/moneyness buckets and per-origin fields. |
| `b2_calibration_contract.md` | b2-contracts | Phase 3F B2 calibration contract: 20-session window, created_at <= t-60s PIT rule, disk-backed dedup and per-asset session-band robust scaling. |
| `b2_feature_contract_v2.md` | b2-contracts | Pilot V2 B2 feature contract: full-panel availability rules, continuous variables, excluded provider cumulative fields and non-directional interpretation. |
| `b2_unusualness_definition.md` | b2-contracts | Governing definition of the secondary unusual_event label and its provisional trailing-percentile calibration contract. |
| `unusual_activity_definition.md` | b2-definition | Evergreen Phase 3F definition of option_activity_present and the calibrated descriptive unusual_event label (robust z-scores, p95 threshold) with prespecified sensitivities. |
| `backfill_execution_plan_v2.md` | backfill | Latest resumable runbook (not an authorization) for the recommended 60-session backfill with per-session checkpoints, gates and a passing restart dry run. |
| `backfill_feasibility_v3.md` | backfill | Latest feasibility report from measured 20-session telemetry with empirical P95 projections; FULL_BACKFILL stays BLOCKED. |
| `backfill_window_decision_v2.md` | backfill | Latest window decision recommending 60 sessions (fits disk with 30% reserve); 120 is fallback, 180 infeasible; recommendation only, not authorization. |
| `20_session_calibration_decision_v3.md` | calibration-20s | Latest of the chain: AUTHORIZE_METHOD_FREEZE_AND_BACKFILL_PLAN with full 20-session evidence disposition and provisional six-asset quality universe. |
| `results_reconciliation_v2.md` | campaign-reconciliation | Single cross-campaign view (C1-C6) required by decision 53: campaign register, contrast table and null-known-at-freeze flags, compiled 2026-08-17. |
| `canonical_claims_and_limitations.md` | canonical | Governing claims ledger (CLM-001..019) that is the sole allowed source of numerical claims, with SUPPORTED/CONDITIONAL/INVALIDATED_INPUT statuses. |
| `canonical_validation_conclusion.md` | canonical | Final canonical decision MODEL_FAMILY_DEPENDENT for both nested contrasts: no universal B1 or B2 edge, with a conditional corrected Gamma B2 gain. |
| `common_sample_data_contract_v1.md` | common-sample | Defines the canonical 25-session common-sample row key, strict/availability-aware/target matrices, and the B0/B1Q/B2 information-set contracts. |
| `confirmation_protocol_v4_sourcebound.md` | confirmation-protocol | Governing frozen confirmation method: RV30 target, Gamma GLM confirmatory plus LightGBM robustness, QLIKE primary, additive B1a-vs-B0 and B2-vs-B1a comparison ladder. |
| `data_dictionary.md` | data-dictionary | Evergreen observed-field dictionary for the six component groups plus canonical normalized timestamp fields, provenance keys and acceptance state. |
| `corporate_event_contract.md` | earnings-pit | Frozen rules for corporate-event predictors: ex-ante FMP date/BMO-AMC only, published actuals excluded, no synthesized ETF earnings, executable guard named. |
| `earnings_pit_contract_v2.md` | earnings-pit | Earnings-predictor PIT contract: primary benchmark excludes earnings pending publication-timestamp integration; defines instrument applicability and allowed derived variables. |
| `docs/positive_findings_v1.md` | gates-2026-08 | Decision-56 exploratory summary (2026-08-18): 2024 cross-family positive option-information effect and the uniform era map through 2026Q1, with the B1-definition caveat stated. |
| `docs/model_naming_note_v1.md` | gates-2026-08 | Reviewer correction (2026-08-18): the registered `har_rv`/`har_rv_fixed_extension` family is a log-linear fixed extension, not the Gate-3 intraday HAR/HARQ; binding citation rules. |
| `docs/provider_license_review_v1.md` | gates-2026-08 | Provider ToS review (2026-08-18): exact FMP/UW/Massive clauses vs what the public mirror and gated bucket expose; quote-level CSV remediation; bucket access discipline; consent-email path. |
| `docs/ci_contract_v1.md` | gates-2026-08 | Two-tier CI contract (decision 61): hosted hermetic suite + coverage ≥80% as required checks; local licensed-evidence tier; branch-protection and mirror-signature rationale. |
| `docs/evidence_immutability_v1.md` | gates-2026-08 | Physical-immutability contract (decision 62): append-only frozen registry + CI tripwire + writer guard + content-addressed writes + read-only locks + release snapshot; WORM limitation documented. |
| `execution_backlog_20260817.md` | gates-2026-08 | Source of truth for the gate cascade: definition of done, honesty and decision-52 governance rules, strict gate ordering with Gate 5 running in the background. |
| `gate1_inference_hardening_v1.md` | gates-2026-08 | Studentized re-inference over the frozen campaigns (cluster t, Newey-West, wild bootstrap, MCS): C2 holdout null, C4c/C6 B2 gains highly significant. |
| `gate2_calibration_vs_information_v1.md` | gates-2026-08 | Mincer-Zarnowitz recalibration test: the C6 B2 gain survives well above MDE while C4c collapses and reverses, marking it a calibration artifact. |
| `gate3_har_harq_ladder_v1.md` | gates-2026-08 | Adds intraday HAR/HARQ baselines on fresh FMP bars, empirically pins the bar-label convention (A001), and selects the prospective base model by pooled OOF QLIKE. |
| `gate4_prospective_design_v1.md` | gates-2026-08 | Pre-read decay-aware design for the Phase 8 prospective read: measured Gamma effect decay, n=30 MDEs, TOST adequately powered only for the tree-family primary. |
| `gate5_pit_foundations_v1.md` | gates-2026-08 | End-to-end PIT foundations: FMP bar semantics resolved via cross-provider reconciliation (A001 retired with a tripwire test); UW created_at latency campaign running unattended. |
| `gate6_regime_composition_v1.md` | gates-2026-08 | Regime/event composition check: contrasts survive leave-event-week-out (two of three increase); the decay is time-linked, not regime-linked. |
| `gate7_noise_robust_target_v1.md` | gates-2026-08 | Noise-robust target sensitivity: the C6 Gamma gain and LightGBM reversal are unchanged under the AC(1)-corrected RV30, retiring the microstructure-artifact explanation for C6. |
| `provider_timing_evidence_policy_gate_v1_20260812.md` | gates-2026-08 | Fail-closed evidence-scoped policy gate keeping SAFE_TO_RECONCILE_EXISTING_RESULTS=NO for sealed pre-v2.2 results and OOS evaluation blocked; supplements the v1 gate amendment. |
| `provider_timing_gate_amendment_v1.md` | gates-2026-08 | Replaces the absolute timing NO-GO with evidence-scoped per-stream gates (existing evidence interpretable, PIT preflight for new historical, receipt logger for prospective); supplemented, not replaced, by the 2026-08-12 policy gate. |
| `target_blind_panel_b1q_eligibility_v1.md` | gates-2026-08 | Fail-closed provenance gate: PANEL_NOT_ELIGIBLE_FOR_EVALUATION because all 34,080 registered B1Q origins lack demonstrated exogenous-input PIT provenance. |
| `risk_register.md` | governance | Living risk register R-001..R-024 covering credential exposure, PIT assumptions, model dependence, multiplicity, custody and backup, with mitigations and gates. |
| `sealed_cohorts_disposition_v1.md` | governance | D006 disposition record for the three sealed unread cohorts (Validation A/B, Phase 8), RESOLVED_20260817 under decision 55; complete-or-close options and recommendation. |
| `target_horizon_decision.md` | governance | Owner-approved decision fixing RV30 (31 prices, 30 one-minute log returns) as the sole primary target; RV10 not introduced. |
| `docs/project_knowledge_system.md` | infrastructure | Evergreen reference for the repo-local GBrain/Graphify knowledge system, its isolation contract and the 15-minute auto-sync task. |
| `docs/literature_reconciliation_v1.md` | literature | Ex-ante predictions of each literature strand vs what the project observed, plus the four-point thesis contribution statement (2026-08-18). |
| `docs/literature_synthesis_v2.md` | literature | v2 evidence synthesis over the ten-study ledger with verification tiers (6 full-text, 1 abstract-only, 3 publisher-metadata-only) and citation discipline rules. |
| `docs/methodology_decisions.md` | methodology | Recovery-baseline methodology decisions (RV30 target, asset freeze rules, B0/B1/B2 ladder, timestamp fail-closed policy) governing since the Phase 5 approval of 2026-07-29. |
| `docs/model_and_mde_comparison_v2.md` | model-selection | Development-only comparison of persistence/HAR-RV/Ridge/Gamma/LightGBM on the 80-session panel with training-only MDE estimates (PASS). |
| `docs/phase8_one_shot_protocol_v1.md` | phase8-holdout | Governing one-read protocol for the sealed Phase 8 holdout: blind-collector automation state, seal hashes, and the owner one-shot authorization steps expected ~2026-08-29. |
| `date_level_pit_preflight_plan_v1.md` | pit-preflight | Calendar-derived 8-asset x 7-sentinel-session PIT preflight plan with semantic self-hash; no provider calls, candidate approval still required. |
| `date_level_pit_preflight_request_budget_v1.md` | pit-preflight | Deterministic request budget for the preflight plan: 119 unconditional requests, 343 hard cap, fail-closed pagination rule; authorizes nothing. |
| `date_level_pit_preflight_runner_v1.md` | pit-preflight | Fail-closed dry-run preflight runner spec: injectable transport only, boolean key-presence checks, per-session midpoint forecast-origin derivation. |
| `date_level_pit_preflight_status_v2.md` | pit-preflight | v2.1 immutable status emitter binding plan/catalog/budget; zero attempts reserved or sent, all network transport still blocked by remaining timing-evidence gaps. |
| `effective_sample_size_and_power_planning_v1.md` | power-planning | Planning-only effective-sample-size analysis: 25 effective independent days, detectable standardized effects 0.073-0.322 across 60/120/180-session clustered designs. |
| `b1v3_preregistration.md` | preregistration | Frozen B1v3 preregistration (SHA-256 bound): information sets, QLIKE contrasts, 60 dev / 30 confirmation sessions, bootstrap and Holm plan. |
| `target_blind_comparison_contract_v1.md` | preregistration | Additive metadata contract making the two primary nested comparisons (B0 vs B1a, B1a vs B2) first-class frozen estimands with anti-selection rules; does not alter the v4 freeze. |
| `temporal_validation_protocol_v2.md` | preregistration | Specification-only temporal validation protocol: chronological expanding windows, 30-minute purge/embargo, day-clustered inference, proposed 60/120/180-session folds; not executed. |
| `docs/pit_v22_decision_ledger.md` | provider-timing | Latest PIT decision ledger: Decision 37 attaches a deterministic B2 availability sidecar excluding 451 delayed rows instead of coding them as zero activity. |
| `docs/provider_support_questions.md` | provider-timing | Open question list for FMP, Unusual Whales and Massive support on timestamp, publication and availability semantics. |
| `docs/provider_timing_academic_appendix_v21.md` | provider-timing | v2.1 academic appendix: the four session-asset record-creation-delay incidents (2025-10-20 worst at ~24,000 s) and the canonical B2 coding audit. |
| `provider_timing_claim_matrix_v21.md` | provider-timing | Latest PIT claim matrix (v2.1) binding each timing claim to its evidence class, with official documentation identified by body SHA-256. |
| `provider_timing_future_execution_guide.md` | provider-timing | Standing guide for a future authorized prospective timing capture (receipt logging requirements) and safe local replay validation; pending, non-blocking. |
| `provider_timing_pit_contract_v22.md` | provider-timing | Governing PIT contract: v2.2 offline correction of B2 numeric-zero interpretation via an immutable eligibility sidecar; canonical matrices stay untouched. |
| `provider_timing_semantics_evidence_intake_v1.md` | provider-timing | Standing intake contract for sanitized provider documentation or support-case evidence against the unresolved timing blocks; completeness is review-only and opens no gate. |
| `timing_sensitivity_execution_plan_v1.md` | provider-timing | READY_TO_EXECUTE local-compute plan (R-023) to rerun C4/C5 under the registered 120s/300s UW created_at sensitivities without overwriting frozen 60s artifacts. |
| `etf_role_decision.md` | sample-design | SPY/QQQ fixed as B0 market controls only, not target assets; equity target eligibility recorded provisionally without any predictive statistic. |
| `target_blind_common_predictor_panel_v23.md` | target-blind-panel | Latest panel doc: v2.3 source-bound predictor-only B0/B1Q/B2 matrix with immutable provenance preflight; reconciliation and OOS remain NO (a v2.4 manifest exists only as a registered artifact). |
| `threats_to_validity_matrix_v1.md` | threats-to-validity | Examiner-facing matrix (2026-08-18) of 14 named validity threats with evidence, executed mitigation gates and plainly stated residual risk; bounded by decision 53. |

## Superseded (kept for the preregistration audit trail)

| Doc | Topic | Note |
|---|---|---|
| `b2_confirmation_conclusion.md` | b2-confirmation | → `canonical_validation_conclusion.md` — PASS_TWO_NEW_BLOCKS_EVALUATED result: B2 contrast positive for Gamma/HAR-RV/Ridge, negative for LightGBM; conclusions now carried by the canonical validation docs. |
| `b2_feature_contract.md` | b2-contracts | → `b2_feature_contract_v2.md` — Bounded-pilot B2 feature contract: executed_at window, created_at cutoffs, Level 1 variables and interpretation constraints. |
| `backfill_feasibility.md` | backfill | → `backfill_feasibility_v2.md` — First feasibility note from the five-session pilot (7.6 GB, 40 GB memory incident); all horizons unauthorized. |
| `backfill_feasibility_v2.md` | backfill | → `backfill_feasibility_v3.md` — Pilot V2 capacity estimates extrapolating five sessions to 3/6/12-month raw and Parquet footprints. |
| `20_session_calibration_decision.md` | calibration-20s | → `20_session_calibration_decision_v2.md` — First 20-session decision: REVISE_B1_AGAIN, download withheld due to 46.55% B1Q coverage and zero-coverage assets. |
| `20_session_calibration_decision_v2.md` | calibration-20s | → `20_session_calibration_decision_v3.md` — Post-repair decision AUTHORIZE_20_SESSION_CALIBRATION after bucket-scoped B1Q integration fix; authorizes only a future human-approved download. |
| `confirmation_protocol_v1.md` | confirmation-protocol | → `confirmation_protocol_v4_sourcebound.md` — First pre-confirmation protocol gating a corrected target-blind panel rebuild on the v2.2 sidecar state; fully replaced by the source-bound v4 method freeze. |
| `confirmation_protocol_v2_sourcebound.md` | confirmation-protocol | → `confirmation_protocol_v4_sourcebound.md` — Binds the pre-method-freeze decision to the source-bound v2.3 panel and v3 preregistration; replaced by the v4 frozen method. |
| `docs/independent_replication_30_session_results.md` | independent-replication | → `docs/canonical_claims_and_limitations.md` — First replication report claiming TARGETED_B2V2_REPLICATION_CONFIRMED (Gamma B2 +0.0329); the canonical claims ledger later ruled these numbers INVALIDATED_INPUT due to the duplicated B1 dividend input. |
| `docs/literature_synthesis.md` | literature | → `docs/literature_synthesis_v2.md` — First synthesis of the ten-study literature matrix checked against Crossref (2026-07-21). |
| `docs/pit_field_classification.md` | provider-timing | → `docs/provider_time_semantics_and_pit_register_v2.md` — Pilot-era field-by-field PIT eligibility rules (created_at cutoffs, previous-session OI only, provider accumulators excluded). |
| `docs/pit_reconciliation_gate_v21_addendum_20260812.md` | provider-timing | → `docs/pit_v22_decision_ledger.md` — v2.1 target-blind reconciliation gate left CONDITIONAL_NOT_CLOSED over the B2 zero-coding confound; closed by the v2.2 availability-sidecar decisions. |
| `docs/pit_v21_decision_ledger.md` | provider-timing | → `docs/pit_v22_decision_ledger.md` — v2.1 gate states including B2 FAIL_ZERO_ACTIVITY_NOT_DISAMBIGUATED and the blocked reconciliation of sealed results, remediated by v2.2. |
| `docs/pit_v22_claims_and_limitations.md` | provider-timing | → `docs/canonical_claims_and_limitations.md` — Target-blind v2.2 claims ledger written before any corrected evaluation; its NOT_EVALUATED questions were later answered under the canonical RV30 claims ledger. |
| `docs/provider_time_semantics_and_pit_register_v2.md` | provider-timing | → `docs/provider_timing_pit_contract_v22.md` — v2 field register separating provider statements, authenticated observations and research conventions; its role passed to the v2.1/v2.2 timing contract and claim matrix chain. |
| `docs/provider_timing_academic_appendix_v2.md` | provider-timing | → `docs/provider_timing_academic_appendix_v21.md` — v2 academic appendix on the timestamp contract and evidence taxonomy (PROVIDER_DOCUMENTED / PAYLOAD_OBSERVED / STUDY_CONSERVATIVE_RULE / UNVERIFIED). |
| `provider_timing_claim_matrix_v2.md` | provider-timing | → `provider_timing_claim_matrix_v21.md` — v2 matrix separating provider-documented, payload-observed, conservative-rule and unverified timing claims for FMP/Massive/UW with official-source archive. |
| `provider_timing_pit_contract_v2.md` | provider-timing | → `provider_timing_pit_contract_v21.md` — v2 PIT contract fixing FMP +1/+2-minute rules, UW created_at buffers and Massive as-of selection, with record-creation-lag CDFs. |
| `provider_timing_pit_contract_v21.md` | provider-timing | → `provider_timing_pit_contract_v22.md` — v2.1 target-blind amendment (CONDITIONAL_NOT_CLOSED): FAIL_ZERO_ACTIVITY_NOT_DISAMBIGUATED — B2 zeros confounded by created_at delay need a sidecar before use. |
| `confirmation_readiness_v1.md` | readiness | → `confirmation_readiness_v2_sourcebound_20260812.md` — v2.2 target-blind operational readiness gate (PASS, acquisition not requested); replaced by the source-bound v2 readiness check. |
| `target_blind_common_predictor_panel_v22.md` | target-blind-panel | → `target_blind_common_predictor_panel_v23.md` — v2.2 target-blind B0/B1Q/B2 input panel applying the availability sidecar before completeness; first panel eligible under the PIT v2.2 contract. |

## Diagnostic (one-time investigations, findings absorbed)

| Doc | Topic | Note |
|---|---|---|
| `b1_diagnostic_findings_20260815.md` | b1-diagnosis | Development-only diagnosis that B1v3's failure to improve B0 stems from model-and-regime instability, not missing quotes or IV-inversion failure. |
| `b1_zero_coverage_diagnosis.md` | b1-diagnosis | Forensic trace of zero B1Q coverage for SPY/QQQ/META/TSLA pointing to a selection/integration defect; findings absorbed by the later B1Q repair. |
| `b1q_put_call_parity_feasibility_v1.md` | b1-diagnosis | Target-free data-geometry check of whether cached B1Q quote pairs can identify the put-call-parity discount-factor slope. |
| `b2_mechanism_audit_v1.md` | b2-mechanism | Development mechanism audit: all 25 residual B2 variants failed the frozen gates, so the direct protocol became the registered fallback; documents the all_variants_retained naming defect. |
| `common_sample_quality_and_bias_v1.md` | common-sample | Descriptive retention, concentration and missingness audit of the 25-session common sample (13,240 availability-aware / 9,589 strict rows; no predictive claims). |
| `cross_provider_alignment_audit_v1.md` | common-sample | Descriptive FMP/Massive/UW alignment pass rates (93.2/91.0/80.0%) and join/normalization controls for the retained 25-session inputs. |
| `development_stability_audit_v2.md` | development-stability | Stratum-level stability audit of the frozen Phase 5 development contrasts: B1a-to-B2 positive in 11/12 strata for Gamma/HAR/Ridge, LightGBM weaker with material-negative strata. |
| `docs/gate8_selection_bias_v1.md` | gates-2026-08 | Gate 8 IPW audit: common-complete selection bias on the binding C6 sample is bounded at negligible (97.4% inclusion, contrasts unmoved). |
| `docs/gate9_signal_localization_v1.md` | gates-2026-08 | Gate 9 exploratory localization: no B2 feature group carries signal in development, and the Gamma effect lives outside earnings windows, rejecting the informed-flow mechanism. |
| `docs/pit_sensitivity_analysis_v1.md` | provider-timing | One-time FMP-delay x UW-cutoff sensitivity grid: +1m/60s primary unchanged across UW cutoffs; +2-minute delay structurally empties the strict sample. |
| `docs/provider_timing_b1q_reselection_v21_addendum_20260812.md` | provider-timing | One-time Massive B1Q cache-reselection audit (PASS, hash-bound): target-blind quote-selection and cache-integrity diagnostic only, no latency or predictive claim. |
| `fmp_b1q_exogenous_docs_review_v1.md` | provider-timing | Official FMP documentation review concluding B1Q Treasury/dividend PIT provenance UNRESOLVED; SAFE_TO_BUILD_B1Q=false remains binding. |
| `provider_timing_official_docs_audit_v1_20260812.md` | provider-timing | One-time 2026-08-12 audit of official FMP/UW/Massive documentation: historical source availability PASS while PIT timestamp semantics stay UNVERIFIED; findings absorbed into the v2.1 claim matrix and policy gate. |
| `provider_timing_semantics_audit_v1.md` | provider-timing | One-time offline audit (2026-08-11) of FMP official docs and 819M UW Full Tape rows establishing PROXY_ONLY latency evidence; findings absorbed into the claim matrices and PIT contracts. |
| `provider_timing_uw_anomaly_addendum_v21.md` | provider-timing | Target-blind forensic check of four UW Full Tape sessions showing created_at delays coinciding with canonical B2 zero coding; findings absorbed into the v2.2 sidecar correction. |

## Historical (process records: requests, old plans, readiness checks)

| Doc | Topic | Note |
|---|---|---|
| `b1_benchmark_selection.md` | b1-benchmark | REVISE_B1_AGAIN-era selection record naming B1Q primary and B1T diagnostic at corrected 46.55% B1a coverage; overtaken by the integration repair and later coverage evidence. |
| `b1_coverage_decision.md` | b1-benchmark | Old Pilot V2 readiness check (REVISE_B1) against the 70%/50%/40% coverage gate; kept as the audit record of the gate at that time. |
| `b2_confirmation_model_card.md` | b2-confirmation | Model card for the two-block B2 confirmation run with interpretation guardrails (replicated but model-dependent signal); kept for audit. |
| `b2_direct_protocol_freeze_v1.md` | b2-confirmation | Record of freezing direct B2 augmentation with Gamma GLM as the confirmatory protocol before new-block acquisition; the frozen run has since executed. |
| `b2_mechanism_model_cards.md` | b2-mechanism | Companion model cards for the mechanism development phase (Gamma GLM, linear challengers, LightGBM, residual learner; 25 evaluated, 0 retained). |
| `20_session_calibration_request.md` | calibration-20s | Original conditioned request (Spanish) for the 20-session window with storage estimates; kept as the request record that led to the decision chain. |
| `consolidation_record_20260817.md` | governance | Audit record of the 2026-08-17 repository consolidation: backups, archive branch, fast-forward to main, evidence-root materialization and EOL pinning. |
| `repository_hygiene_decision_v1.md` | governance | Pre-consolidation hygiene gate record (inventory, secret scan, reproducibility manifest, deferred checkpoint, status PARTIAL); overtaken by the 2026-08-17 repository consolidation. |
| `supervisor_request_pack_v1.md` | governance | Request pack tracking pending human decisions D001-D004 with ready-to-send supervisor email drafts (assessment template, metadata, framing sign-off), 2026-08-17. |
| `docs/independent_replication_30_session_request.md` | independent-replication | Original bounded-acquisition request for the 30-session independent block (2025-05-21..07-03) with the 60-session warm-up rationale. |
| `docs/independent_replication_execution.md` | independent-replication | Execution contract and acquisition record: 89/90 sessions acquired, the 2025-04-04 warm-up CRC failure retained as a named provider incident, all 30 target bodies complete. |
| `docs/independent_replication_power_note.md` | independent-replication | PLANNING_ONLY power note: ~26 session clusters suffice for HAR/Ridge, 64 for Gamma, 371 for LightGBM at 80% power under development effects. |
| `docs/model_and_inference_candidate_dossier_v1.md` | model-selection | Pre-implementation decision dossier of model, loss and inference candidates with descriptive collinearity diagnostics; no fitting performed. |
| `docs/phase4a_scientific_design_freeze_v1.md` | phase4-design | Phase 4A local-only scientific design freeze (question, incremental estimand, RV30 unit definition) predating the Phase 5 recovery baseline. |
| `docs/phase4b_feature_contract.md` | phase4-design | Phase 4B local-only feature contract: B0 delay views (+1/+2 min) and half-open B2 windows over retained pilot Parquet; no new backfill authorized. |
| `docs/pit_gate_authorization_20260722.md` | provider-timing | Owner authorization record (2026-07-22) bounding RV30 as target, the FMP +1-minute assumption, and UW created_at as operational proxy only. |
| `provider_timing_clarification_request_v1.md` | provider-timing | Copy-ready provider support questions requesting timestamp, availability and revision facts; responses flow through the evidence-intake contract, review-only. |
| `confirmation_readiness_v2_sourcebound_20260812.md` | readiness | 2026-08-12 source-bound method-freeze readiness check (PASS_SOURCE_BOUND_METHOD_FREEZE_PREPARATION) for the v2.3 panel; readiness record kept for audit, machine state moved on to the v3 readiness JSON. |
| `current_research_readiness_v1.md` | readiness | 2026-08-12 target-blind ledger answering 'may we move to a B0/B1/B2 evaluation' with no; readiness record kept for audit, execution is now governed by the 2026-08-17 backlog. |
| `week4_evidence_recovery.md` | recovery-week4 | Week-4 evidence recovery plan (Spanish) from the early RESEARCH_ONLY state with B1 blocked and backfill unauthorized; kept as an audit-trail record of past process. |
