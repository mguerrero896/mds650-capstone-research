# Scripts index

Classification of every script (housekeeping 2026-08-18). Frozen-evidence and
one-shot scripts are reproducibility records for hashed artifacts; re-running them
against today's store is undefined behavior. Archived dead scripts live in
`scripts/archive/` with their own README.

## Active (runnable pipeline, gate runners, automation)

| Script | Purpose |
|---|---|
| `scripts/aggregate_pit_reconciliation_gate_v21.py` | Build the local target-blind PIT v2.1 reconciliation gate. |
| `scripts/assess_provider_timing_semantics_evidence_v1.py` | Offline intake assessor for future sanitized provider-timing evidence submissions. |
| `scripts/build_b2_confirmation_inputs.py` | Staged builder of target-free inputs and frozen RV30 target for the two 2024 confirmation blocks. |
| `scripts/build_canonical_defense_notebook.py` | Generate the portable evidence-only canonical RV30 defense notebook. |
| `scripts/build_canonical_defense_package.py` | Render the evidence-bound defense report, tables and figures from canonical RV30 artifacts. |
| `scripts/build_confirmation_readiness_v2.py` | Emit the source-bound readiness v2 snapshot for a future confirmation acquisition. |
| `scripts/build_fixture_preview.py` | Deterministic fixture-only preview of the pilot dataset exercising the local builder without providers. |
| `scripts/build_independent_replication_panel.py` | Build replication origins, FMP/B0 and target-free B2 inputs for the 30-session block. |
| `scripts/build_literature_evidence_ledger.py` | Build the conservative DOI-verified evidence ledger from the literature matrix. |
| `scripts/compare_development_models.py` | Training-only tuning and comparison of preregistered candidate models on the frozen Phase 5 panel. |
| `scripts/emit_date_level_pit_preflight_status_v2.py` | Emit the current no-network date-level PIT-preflight v2 status record. |
| `scripts/evaluate_b2_confirmation_blocks.py` | One-read frozen B0/B1a/B2 evaluator over the two 2024 confirmation blocks. |
| `scripts/gbrain_sync.ps1` | Git-hook wrapper running the gbrain knowledge sync; its callee scripts/sync_project_knowledge.ps1 is currently missing (hook step fails). |
| `scripts/generate_date_level_pit_preflight_plan_v1.py` | Generate the calendar-derived candidate plan for a date-level PIT preflight. |
| `scripts/log_uw_option_trade_receipts.py` | Build sanitized UW receipt logs from a local replay for timing evidence. |
| `scripts/publish_mirror.sh` | Republishes the single-branch GitHub publication mirror from the canonical repo with tree-hash verification. |
| `scripts/register_uw_latency_tasks.ps1` | Idempotently registers the UW latency collector/watchdog Windows scheduled tasks (Gate 5.3). |
| `scripts/report_canonical_validation.py` | Reports hash-verified canonical RV30 evidence offline, recomputing inference without refits or provider calls. |
| `scripts/run_canonical_validation.py` | Builds hash-bound canonical RV30 comparison evidence offline from registered predictions. |
| `scripts/run_gate10_positive_findings.py` | Gate 10 (decision 56a): formalizes every cross-family B0/B1/B2 contrast from frozen forecasts. |
| `scripts/run_gate11_era_map.py` | Gate 11 (decision 56b): era-information map 2024-2026 with a fixed per-era model ladder. |
| `scripts/run_gate1_inference.py` | Gate 1: studentized inference (cluster-t, DM, wild bootstrap, MCS) over every frozen forecast artifact. |
| `scripts/run_gate2_calibration.py` | Gate 2: calibration-vs-information recalibration analysis on the binding frozen samples. |
| `scripts/run_gate3_har.py` | Gate 3: HAR/HARQ intraday ladder on development data selecting the prospective base model. |
| `scripts/run_gate4_decay_power.py` | Gate 4: effect-decay regression and decay-aware power for the 2026-08-29 Phase 8 read. |
| `scripts/run_gate5_bar_reconciliation.py` | Gate 5.1: cross-provider FMP-vs-Massive 1-minute bar reconciliation measuring assumption A001. |
| `scripts/run_gate6_regimes.py` | Gate 6: regime/event composition table and leave-event-week-out sensitivity. |
| `scripts/run_gate7_noise_robust.py` | Gate 7: noise-robust RV30 target sensitivity on the frozen C6 forecasts. |
| `scripts/run_gate8_selection.py` | Gate 8: IPW re-estimation of frozen contrasts for common-complete selection bias on C6. |
| `scripts/run_gate9_localization.py` | Gate 9: signal localization via B2 feature ablation, earnings conditioning, and horizon term structure. |
| `scripts/uw_latency_collector.py` | Gate 5.2 live UW latency collector polling flow alerts every XNYS session with crash-safe appends and heartbeat. |
| `scripts/uw_latency_reconcile.py` | Gate 5.2 +7-day reconciliation of live UW observations against the historical full tape. |
| `scripts/uw_latency_verify.py` | Gate 5.3(d) same-day capture verification plus watchdog restart of the collector. |

## Frozen evidence (built/sealed registered artifacts — do not re-run)

| Script | Purpose |
|---|---|
| `scripts/acquire_b1_independent_replication_b1q.py` | Resumable Massive B1Q acquisition for the frozen 30-session B1 replication. |
| `scripts/acquire_b1_independent_replication_full_tape.py` | Acquire the frozen 30-session UW Full Tape replication batch without outcomes. |
| `scripts/acquire_b1v3_confirmation_b1q.py` | Resumable target-blind Massive B1Q acquisition for the frozen B1v3 confirmation dates. |
| `scripts/acquire_b1v3_confirmation_full_tape.py` | Acquire missing B1v3 Full Tape sessions with resumable hash checkpoints. |
| `scripts/acquire_gate3_dev_bars.py` | Fetch FMP 1-minute development bars for the six assets feeding the Gate 3 HAR/HARQ ladder. |
| `scripts/acquire_independent_replication_30d.py` | Acquire the causal warm-up plus independent 30-session Full Tape block. |
| `scripts/acquire_phase5_holdout.py` | Acquire and seal the prospective Phase 5 holdout without analysing outcomes. |
| `scripts/acquire_phase6.py` | Acquire the frozen Phase 6 Full Tape sessions with resumable hash checks. |
| `scripts/archive_provider_timing_v21_sources.py` | Archive hash-addressed metadata for the four official PIT v2.1 provider documentation pages. |
| `scripts/audit_provider_timing.py` | Offline v1 sanitized UW timing-evidence builder from already-acquired Full Tape. |
| `scripts/audit_provider_timing_v2.py` | Offline provider-timing PIT v2 evidence bundle builder. |
| `scripts/audit_provider_timing_v21.py` | Run the target-free Provider Timing PIT v2.1 audit. |
| `scripts/audit_uw_anomaly_evidence_v21.py` | Create target-blind forensic evidence for selected UW Full Tape incidents. |
| `scripts/build_b1_independent_replication_b1v3.py` | Build source-bound target-blind B1v3 predictors for the frozen replication. |
| `scripts/build_b1_independent_replication_b2.py` | Build corrected target-blind B2 predictors for the frozen replication. |
| `scripts/build_b1_independent_replication_base.py` | Build the source-bound target-blind FMP/origin/B0 replication layer. |
| `scripts/build_b1_independent_replication_common_panel.py` | Build the primary source-bound predictor-only panel for the replication. |
| `scripts/build_b1_independent_replication_timing.py` | Build the preregistered target-blind timing views for the replication. |
| `scripts/build_b1_replication_fmp_delay2.py` | Build the preregistered target-blind FMP plus-two-minute timing sensitivity. |
| `scripts/build_b1q_exogenous_provenance_v1.py` | Capture and hash-bind target-free B1Q rate/dividend provenance. |
| `scripts/build_b1v3_confirmation_b1.py` | Build canonical source-bound B1v3 predictors after the B1Q source seal. |
| `scripts/build_b1v3_confirmation_b2.py` | Build corrected 60/120/300-second B2 predictors without outcome access. |
| `scripts/build_b1v3_confirmation_base.py` | Build the source-bound B1v3 target-free origin/FMP/spot/B0 layer. |
| `scripts/build_b1v3_confirmation_common.py` | Build the source-bound target-blind B0/B1v3a/B2 common predictor panel. |
| `scripts/build_b1v3_confirmation_timing.py` | Build source-bound target-blind B1v3 provider-timing sensitivity inputs. |
| `scripts/build_b1v3_confirmation_timing_panels.py` | Build and seal the five source-bound target-blind B1v3 timing panels. |
| `scripts/build_b1v3_target_blind.py` | Build the source-bound target-blind B1v3 feature package (shared by B1v3/replication builders). |
| `scripts/build_b2_availability_v22.py` | Build the target-blind B2 availability remediation sidecar v2.2. |
| `scripts/build_b2_calibration_20d.py` | Build the twenty-session target-free B2 calibration panel applied to Pilot V2. |
| `scripts/build_canonical_evidence_index.py` | Build the sanitized SHA-256 index for canonical RV30 validation evidence. |
| `scripts/build_corrected_development_predictors.py` | Coverage-first construction guard for the corrected development predictors. |
| `scripts/build_corrected_development_release.py` | Build the immutable target-free corrected-development predictor release. |
| `scripts/build_fmp_b1q_exogenous_docs_review_v1.py` | Write the target-blind FMP B1Q documentation-review artifact. |
| `scripts/build_independent_b1.py` | Build the target-free B1v2a ATM-IV state for the 90-session replication. |
| `scripts/build_phase5_common_panel.py` | Build the canonical 80-session Phase 5 development panel. |
| `scripts/build_phase5_stability_inputs.py` | Build target-blind B2 timing sidecars from already-downloaded Full Tape. |
| `scripts/build_target_blind_common_panel_v22.py` | Build the v2.2-masked common B0/B1Q/B2 predictor panel without outcomes. |
| `scripts/build_target_blind_common_panel_v23.py` | Build the provenance-bound v2.3 predictor panel behind the closed PIT gate. |
| `scripts/build_target_blind_common_panel_v24.py` | Build the v2.4 source-bound target-blind predictor panel without evaluation. |
| `scripts/create_target_blind_confirmation_prereg_v22.py` | Seal the next confirmation preflight from target-blind v2.2 artefacts. |
| `scripts/download_calibration_20d.py` | Download and filter the authorized UW session batches for Phase 3F and Phase 5 allow-lists. |
| `scripts/finalize_calibration_20d.py` | Finalize bounded Phase 3F download telemetry and integrity evidence from checkpoints. |
| `scripts/freeze_b1_independent_replication_method.py` | Freeze the sign-agnostic replication method from development outcomes only. |
| `scripts/freeze_b1v3_confirmation_plan.py` | Freeze the target-blind B1v3 60/30 plan from authenticated provider evidence. |
| `scripts/freeze_b1v3_method.py` | Freeze B1v3 model choices and MDE using only the 60 development sessions. |
| `scripts/freeze_b2_direct_protocol.py` | Freeze the direct B2 protocol before the new independent acquisition. |
| `scripts/freeze_b2_mechanism_search.py` | Freeze the development-only B2 mechanism-search protocol before fitting. |
| `scripts/freeze_independent_parameters.py` | Freeze independent-replication model parameters before target access. |
| `scripts/freeze_independent_replication_30d.py` | Freeze the independent 30-session replication method before reading targets. |
| `scripts/freeze_phase5_preregistration.py` | Freeze the approved Phase 5 sessions and outcome-blind preregistration. |
| `scripts/freeze_phase6_method.py` | Freeze Phase 6 methods and training-only MDE before any OOS read. |
| `scripts/phase4a_common.py` | Shared deterministic helpers (availability validation, hashing) for the Phase 4A evidence builder. |
| `scripts/phase4b_common.py` | Shared deterministic Phase 4B contracts (window specs, hashing) for the local repair builders. |
| `scripts/plan_b1_independent_replication.py` | Freezes the sign-agnostic B1/B2 independent-replication plan. |
| `scripts/plan_b1v3_confirmation.py` | Builds the date-only B1v3 exposure ledger and the frozen 60/30 confirmation plan. |
| `scripts/plan_independent_replication_30d.py` | Freezes the disjoint 30-session replication window and its storage gate. |
| `scripts/prepare_b1_independent_replication_access.py` | Validates all target-blind gates and seals the single replication-read token. |
| `scripts/prepare_b1v3_confirmation_acquisition.py` | Prepares source-bound B1v3 storage and hardlinks verified reusable evidence. |
| `scripts/probe_fmp_bar_availability.py` | Replay-only validation of FMP bar timing semantics; implements no live provider request. |
| `scripts/probe_replication_30_common.py` | Probes FMP and Massive coverage for the independent 30-session block. |
| `scripts/probe_replication_30_uw.py` | Probes historical UW Full Tape metadata for the 30-session block without downloading ZIPs. |
| `scripts/reconcile_uw_live_vs_full_tape.py` | Reconciles locally replayed UW receipts against locally replayed Full Tape rows. |
| `scripts/render_provider_timing_docs.py` | Renders deterministic provider-timing v1 documentation from evidence JSON. |
| `scripts/render_provider_timing_v21_docs.py` | Renders the human-readable PIT v2.1 amendment from compact sidecars only. |
| `scripts/render_provider_timing_v2_docs.py` | Renders the PIT v2 contract and handoff documents from offline evidence. |
| `scripts/report_independent_replication_30d.py` | Materializes the independent-replication evidence without rereading targets. |
| `scripts/run_b1_calibration_20d.py` | Recomputes the repaired B1Q route over the authorized twenty-session origins. |
| `scripts/run_b1_closure.py` | Runs the bounded B1Q/B1T feasibility closure over Pilot V2 origins with cached Massive quotes. |
| `scripts/run_b1_diagnostics.py` | Runs the 60-session development-only B1v3 mechanism diagnostic. |
| `scripts/run_b1_independent_replication_once.py` | Consumes the single token and executes the preregistered independent replication. |
| `scripts/run_b1_independent_replication_provider_preflight.py` | Runs the bounded target-blind provider preflight for the Phase 7 replication. |
| `scripts/run_b1_replication_market_control_preflight.py` | Target-blind SPY/QQQ provider preflight for the predeclared B0 market controls. |
| `scripts/run_b1v3_confirmation_once.py` | Executes exactly one preregistered B1v3 confirmation after access is sealed. |
| `scripts/run_b1v3_pre_confirmation_quality.py` | Runs and seals every target-blind gate before B1v3 confirmation access. |
| `scripts/run_b2_mechanism_search.py` | Frozen development-only B2 residual-mechanism search with registered placebo/lagged variants. |
| `scripts/run_corrected_independent_replication.py` | Runs the single preregistered reevaluation with corrected independent B1 inputs. |
| `scripts/run_date_level_pit_preflight_v1.py` | Prepares the date-level PIT preflight report without a real network transport. |
| `scripts/run_date_level_pit_preflight_v2.py` | Runs the source-bound B1v3 provider preflight without opening outcomes. |
| `scripts/run_independent_replication.py` | Frozen 60/30-session replication runner with one guarded outcome read. |
| `scripts/run_phase5_development_evaluation.py` | Runs the preregistered Phase 5 development-only RV30 evaluation. |
| `scripts/run_phase5_holdout.py` | Executes the sole prospective Phase 5 holdout read after every gate passes. |
| `scripts/run_provider_timing_capture_once.ps1` | Operator wrapper for the prospective timing capture (Prepare prints the sequence; Replay validated a local source). |
| `scripts/run_window_pipeline.py` | Runs the bounded real pilot and the authorized frozen-window backfill acquisition. |
| `scripts/seal_b1_independent_replication_b1q_source.py` | Seals independent-replication B1Q attempts to immutable Massive payloads. |
| `scripts/seal_b1v3_access_ledger.py` | Seals the B1v3 one-read authorization after every pre-confirmation gate passes. |
| `scripts/seal_b1v3_confirmation_b1q_source.py` | Seals canonical B1v3 Massive attempts to their exact target-free raw payloads. |
| `scripts/seal_b1v3_preregistration.py` | Seals the source-bound B1v3 preregistration before any outcome access. |
| `scripts/seal_corrected_independent_preregistration_v1.py` | Freezes corrected independent B1 inputs and authorizes one fixed reevaluation. |
| `scripts/seal_target_blind_comparison_contract_v1.py` | CLI wrapper for the metadata-only target-blind comparison-contract sealer. |
| `scripts/seal_target_blind_confirmation_package_v4.py` | Offline metadata-only sealer of the v4 target-blind confirmation protocol and readiness package. |
| `scripts/seal_target_blind_confirmation_preregistration_v3.py` | Seals the source-bound target-blind preregistration before method freeze. |
| `scripts/verify_provider_timing_v2.py` | Verifies deterministic equality between two compact provider-timing v2 bundles. |
| `scripts/verify_provider_timing_v21.py` | Verifies PIT v2.1 evidence hygiene and byte-level canonical integrity. |

## One-shot done (governance/repair one-offs already executed)

| Script | Purpose |
|---|---|
| `scripts/audit_b1q_put_call_parity_feasibility.py` | Target-free B1Q put-call-parity feasibility report from local cache data. |
| `scripts/audit_confirmation_readiness_v1.py` | Offline readiness v1 audit for a future confirmation acquisition. |
| `scripts/audit_phase6_source_recovery.py` | Recover and verify the exact frozen Phase 6 git source blobs via local refs. |
| `scripts/build_pit_v22_claim_ledger.py` | Build the target-blind PIT v2.2 claims-and-limitations ledger. |
| `scripts/pit_verify_term_structure.py` | One-off check that retained UW option-state payloads are PIT-usable. |
| `scripts/prepare_phase5_storage.py` | Copies retained Phase 5 evidence to the external SSD with SHA-256 verification, without deleting sources. |
| `scripts/provider_audit_v1.py` | Bounded authenticated provider audit emitting sanitized hash/schema evidence only. |
| `scripts/run_phase4b.py` | Builds the local-only Phase 4B repair package from retained calibration and pilot parquets. |
| `scripts/window_probe_v1.py` | Bounded ~25-request probe measuring each provider's usable historical window. |

## Archived candidates (see scripts/archive/)

| Script | Purpose |
|---|---|
| `scripts/archive/fix_fmp_missing_window.py` | One-off FMP missing-window repair superseded by the corrected pipeline. |
| `scripts/archive/materialize_backfill_from_raw.py` | One-off backfill materialization from raw caches, superseded by the panel builders. |
| `scripts/archive/run_phase5_b1q_missing_55.py` | Superseded Phase 5 B1Q gap-fill run; already relocated to scripts/archive/. |
