# Tasks: Point-in-Time Options Activity for RV30 Forecasting

**Input**: `spec.md`, `plan.md`, `research.md`, `data-model.md`, and the three
contracts under `contracts/`.

**Tests**: Required by the specification and must be written before production
implementation. Live integration tests are small, authenticated, sanitized, and
skipped/blocked when a required secret is absent; they never trigger backfill.

**Research safety**: all tasks are local/research-only. No broker order, email,
publication, deployment, destructive deletion, or secret-value logging is
permitted.

## Recovery iteration control

This revision records Pilot V1 as invalid for acceptance while preserving its raw data and valid
RV30 targets. Pilot V2 is authorized as a bounded correction using the five existing ZIP hashes
and filtered Parquet files. No full backfill, modeling, QLIKE, final evaluation, asset freeze or
Word generation is authorized. `[x]` items are completed controls or evidence tasks; unchecked
tasks remain intentionally pending.

## Phase 1: Setup

- [x] T001 Historical baseline and approved runtime: `pyproject.toml` targets Python 3.12.12 (`>=3.12,<3.13`) after compatibility-matrix approval; provider calls were not used for the migration.
- [x] T002 Create `uv` configuration and regenerate a reproducible `uv.lock` without provider calls; clean Python 3.12.12 installation passed.
- [ ] T003 [P] Create the `src/mds650/` package skeleton and public module exports.
- [ ] T004 [P] Create `tests/unit/`, `tests/contract/`, `tests/integration/`, `tests/e2e/`, and sanitized fixture directories.
- [ ] T005 [P] Configure `ruff`, `mypy`, `pytest`, coverage, and test markers in `pyproject.toml`.
- [ ] T006 [P] Add `.gitignore`, `.env.example` with variable names only, and raw-data exclusion rules.

## Phase 2: Foundational (blocking prerequisites)

- [ ] T007 Write failing unit tests for strict settings, presence-only secret checks, research-only mode, and forbidden external mutations in `tests/unit/test_settings.py`.
- [ ] T008 [P] Write failing contract tests for all sanitized fixture schema fingerprints in `tests/contract/test_provider_schemas.py`.
- [ ] T009 [P] Write failing unit tests for UTC/New York conversion, regular-session boundaries, DST transitions, and five-minute origin alignment in `tests/unit/test_time.py`.
- [ ] T010 [P] Write failing unit tests for deterministic duplicate keys, null policy, and invalid OHLC relationships in `tests/unit/test_quality.py`, then execute TDD's red baseline before any implementation task.
- [ ] T011 [P] Implement `src/mds650/config.py` with `pydantic-settings`, presence-only secret validation, explicit research-only defaults, and typed configuration.
- [ ] T012 [P] Implement `src/mds650/logging.py` with structured standard-library logging and secret redaction.
- [ ] T013 [P] Implement `src/mds650/errors.py` with typed fail-closed errors for authentication, schema drift, licensing, PIT, quality, and overlap failures.
- [ ] T014 Implement `src/mds650/time.py` for timezone-aware parsing, DST-safe session calendars, and origin windows (depends on T009).
- [ ] T015 Implement `src/mds650/quality.py` for configurable completeness, duplicates, nulls, and schema acceptance (depends on T010).
- [ ] T016 Implement `src/mds650/storage.py` for immutable raw payload hashing, Parquet/DuckDB normalized storage, and provenance links.
- [ ] T017 Implement `src/mds650/contracts.py` with typed records matching `data-model.md` and contract documents.
- [ ] T018 [P] Add sanitized provider fixtures and fixture metadata under `tests/fixtures/providers/` with no credentials or unrestricted raw redistribution.
- [x] T018A [P] Import `artifacts/api_audit/exploratory_v0/provider_audit_manifest.json` as byte-preserved sanitized fixtures and record its provenance.
- [x] T018B [P] Validate fixture hashes and fail on duplicate manifest composite keys or duplicate hashes under distinct requests in `tests/contract/test_authenticated_audit_manifest.py` and `tests/unit/test_audit_manifest.py`.
- [x] T018C [P] Create and validate JSON Schema 1.1 at `specs/001-pit-options-rv30/contracts/provider-audit-manifest.schema.json`.
- [x] T018D [P] Plan and exercise schema-validation, secret-scan, personal-path, deterministic-order and idempotency tests without executing production provider connectors.
- [ ] T019 Run foundational tests and static gates after T011–T018; record red baseline and contract status in `docs/recovery/spec_kit_analysis_report.md`.

**Checkpoint**: foundational contracts, safety controls, time semantics, and
storage conventions are ready; no provider client or pilot may run before this
checkpoint passes.

## Phase 3A: User Story 1 — Authenticated data feasibility (Priority: P1)

**Goal**: produce sanitized, machine-readable and human-readable audits for
FMP, Unusual Whales, and directed Massive contract data.

**Independent test**: fixture contract tests pass, secret presence is verified
without values, and a small live audit either produces a valid manifest or an
explicit blocked failure code.

### Tests first

- [ ] T020 [P] [US1] Add failing FMP fixture tests for one-minute OHLCV and structured earnings fields in `tests/contract/test_fmp_contract.py`.
- [ ] T021 [P] [US1] Add failing Unusual Whales fixture tests for pagination, contract/event fields, activity proxies, and PIT option-state availability in `tests/contract/test_unusual_whales_contract.py`.
- [ ] T022 [P] [US1] Add failing Massive fixture tests for directed contract trades/quotes, bid/ask, condition codes, timestamp precision, and empty windows in `tests/contract/test_massive_contract.py`.
- [ ] T023 [P] [US1] Add failing pagination tests with repeated-page, cursor, and maximum-page fixtures in `tests/unit/test_pagination.py`.
- [ ] T024 [P] [US1] Add failing sanitized-manifest tests proving no secret values or authorization headers are emitted in `tests/unit/test_audit_manifest.py`.
- [ ] T025 [P] [US1] Add failing small live integration smoke tests guarded by presence-only secret checks in `tests/integration/test_provider_smoke.py`.
- [x] T025A [P] [US1] Diagnose Massive host, authentication, contract format and entitlement status in `docs/recovery/provider_audit_v1_plan.md`; do not download full OPRA quotes. The initial raw-ticker probe returned 404/403; the corrected `O:`-prefixed event-returned contract on `api.massive.com` returned 200 for reference, trades and quotes, while broader coverage remains unverified.
- [x] T025B [P] [US1] Resolve Unusual Whales canonical aliases and field-by-field time semantics for `created_at`, `start_time` and `end_time`; prohibit undocumented `executed_at`. Aliases, official term-structure/skew field coverage and timestamp metadata are recorded; PIT ordinary option state remains unverified because availability timing is absent.
- [x] T025C [P] [US1] Probe FMP timezone using winter, summer, DST-transition and early-close requests; exact bar semantics remain an acceptance blocker pending official-calendar comparison.
- [x] T025D [P] [US1] Classify FMP earnings applicability as `applicable`, `not_applicable`, `unsupported` or `invalid_response` and require returned/requested symbol equality; SPY/QQQ are `not_applicable` unless evidence changes that classification.
- [x] T025E [P] [US1] Probe whether FMP timestamps are bar starts or closes and define the exact origin close/last valid origin in `docs/methodology_decisions.md`; result remains unresolved and blocks RV30 implementation.
- [x] T025F [P] [US1] Locate the missing AMZN and TSLA minute candidates and classify them as `unclassified_provider_calendar_or_halt` without interpolation; further official-calendar/halt resolution remains required.

### Implementation

- [ ] T026 [P] [US1] Implement `src/mds650/providers/base.py` with typed retry/backoff, timeout, pagination, rate-limit observation, and schema-fingerprint interfaces.
- [ ] T027 [P] [US1] Implement `src/mds650/providers/fmp.py` for one-minute OHLCV and structured earnings audit requests.
- [ ] T028 [P] [US1] Implement `src/mds650/providers/unusual_whales.py` for historical unusual activity and point-in-time option-state probes.
- [ ] T029 [P] [US1] Implement `src/mds650/providers/massive.py` for directed contract trades and quote validation only.
- [ ] T030 Implement `src/mds650/audit.py` to orchestrate the three provider audits and classify hard/soft failures (depends on T026–T029).
- [ ] T031 Implement `src/mds650/manifests.py` to write the provider-audit contract, hashes, schema fields, coverage, and sanitized human report (depends on T016, T030).
- [x] T031A [P] Migrate raw evidence from Temp to restricted persistent storage without exposing personal paths in distributable reports; record migration hashes in `docs/recovery/audit_v0_findings.md`.
- [x] T031B [P] Generate and validate manifest `schema_version: "1.1"` with explicit enums and separate diagnostics in `specs/001-pit-options-rv30/contracts/provider-audit-manifest.schema.json`.
- [x] T031C [P] Prove audit idempotency using composite request keys, repeated-page detection and deterministic order in `tests/contract/test_authenticated_audit_manifest.py`.
- [x] T031D [P] Prove absence of secrets and personal paths in manifests, fixtures, logs and reports in `tests/contract/test_authenticated_audit_manifest.py` and `tests/unit/test_audit_manifest.py`.
- [x] T031E [US1] Generate provider-audit summary v1 exclusively from a validated manifest and preserve v0 as exploratory evidence; latest validated bounded evidence is `artifacts/api_audit/authenticated_v1r/provider_audit_summary.md`, with v1m–v1q retained immutably and lineage documented in `docs/recovery/provider_audit_v1_plan.md`.
- [ ] T032 [US1] Add configurable acceptance thresholds and provider license checks in `config/acceptance.yaml` and `src/mds650/acceptance.py`.
- [ ] T033 [US1] Run fixture and bounded live integration tests in `tests/integration/test_provider_smoke.py`; emit no backfill command when the audit is red.

**Checkpoint**: US1 is complete only when the audit manifest is reproducible,
sanitized, and reports the oldest accessible dates, common overlap, B1
feasibility, and exact failure codes.

## Phase 3B: User Story 3 — Verified literature base (Priority: P2, parallel with Phase 3A)

**Goal**: verify ten empirical studies before freezing variables, benchmarks, exact models,
metrics, validation or methodological claims.

**Independent test**: each row resolves to a DOI/stable URL and records APA 7, authors, year,
title, venue/status, market/sample, frequency, objective, predictors, exact models, exact
benchmark, temporal protocol, leakage control, metrics, result, limitation, exact project
implication and verification status.

- [x] T049 [P] [US3] Add a literature schema and validation tests in `tests/contract/test_literature_matrix.py`.
- [x] T050 [P] [US3] Create `docs/literature_matrix.csv` with ten verified rows and all required fields; do not use generic model-superiority claims.
- [x] T051 [P] [US3] Create `docs/literature_sources/` index with DOI/stable URL, publication status, retrieval date and verification notes.
- [x] T052 [US3] Validate date range January 2023–July 2026, categories and exact models (HAR, HARQ, OLS, LASSO, Elastic Net, Random Forest, XGBoost, LightGBM, MLP, LSTM) in `docs/literature_matrix.csv`.
- [x] T053 [US3] Record recent empirical justification for HAR and QLIKE while separating foundational citations in `docs/literature_sources/`.
- [x] T054 [US3] Run literature verification and mark unresolved source/licensing issues as explicit blockers in `docs/recovery/spec_kit_analysis_report.md` before any variable/benchmark/model freeze.

**Checkpoint**: Phase 3B is accepted only when all ten studies are independently verifiable;
it may proceed in parallel with Phase 3A but blocks later freeze decisions.

## Phase 3C: B1 Feasibility and Common-History Closure (controlled)

**Goal**: close B1 feasibility over all 2,840 Pilot V2 origins, compare the independent Massive
route (`B1Q`) with the dependent Full Tape diagnostic route (`B1T`), verify common-history
evidence for all eight assets, and prepare—but do not execute—a twenty-session request.

**Independent test**: the route-specific matrices are complete, cached and resumable; B1a/B1b/
B1c coverage and PIT gates are explicit; 48 all-assets monthly probes are recorded without
claiming daily continuity; the literature matrix passes source-level verification; and no
twenty-session download is performed.

- [ ] T084 [P] [US1] Record the frozen Pilot V2 input statuses and phase boundary in `docs/recovery/b1_closure_spec_analysis.md` and `artifacts/b1_full_origin/evidence_index.csv`.
- [ ] T085 [P] [US1] Add the B1 route/data contract with B1Q/B1T provenance, quote filters, as-of join keys and missing reasons in `docs/b1_data_contract.md`.
- [ ] T086 [P] [US1] Implement contract-day Massive caching, checkpointing and request-hash idempotency in `src/mds650/providers/massive.py` and `src/mds650/storage.py`; prohibit one-request-per-origin extraction.
- [ ] T087 [P] [US1] Implement historical `as_of` contract resolution for the 7–21, 30–60 and 90–180 DTE buckets and target moneyness grid in `scripts/b1_massive_contract_days.py`.
- [ ] T088 [P] [US1] Implement local last-quote as-of joins with nanosecond `timestamp.lte`, primary 60-second/25% filters and 300-second/50% sensitivity filters in `src/mds650/providers/massive.py`.
- [ ] T089 [P] [US2] Implement the dependent B1T Full Tape fallback using `created_at <= origin-60s`, valid NBBO, expiry and configurable five/fifteen-minute age windows in `scripts/b1_full_tape_route.py`.
- [ ] T090 [P] [US2] Integrate B1Q and B1T IV inversion by origin with B1a ATM interpolation flags, B1b skew definition, B1c slopes and failure diagnostics in `src/mds650/pilot.py`.
- [ ] T091 [US2] Write `artifacts/b1_full_origin/b1_origin_matrix.parquet` for all 2,840 origins with route-specific fields, quote/contract counts, age/spread metrics and missing reasons.
- [ ] T092 [US2] Generate `artifacts/b1_full_origin/b1_coverage_summary.json`, `b1_coverage_by_asset.csv`, `b1_coverage_by_session_segment.csv` and `b1q_vs_b1t_comparison.csv` at 50/60/70/80% thresholds.
- [ ] T093 [US2] Generate `artifacts/b1_full_origin/iv_inversion_diagnostics.json` with success/failure reason, bounds, iterations, call/put, DTE, moneyness, age and spread for every attempt.
- [ ] T094 [P] [US1] Create `artifacts/api_audit/common_history_all_assets_v3.json` with 48 asset-date records, exact FMP session filtering, UW file evidence and date-relative Massive contracts/quotes.
- [ ] T095 [US1] Compute earliest/latest observed common dates, common assets per date and candidate window without claiming daily continuity in `scripts/common_history_all_assets_v3.py`.
- [ ] T096 [P] [US3] Verify all ten literature rows against DOI/stable URLs and source text, record retrieval/status/claims in `docs/literature_sources/index.csv`, and write `docs/literature_synthesis.md`.
- [ ] T097 [US3] Fail the literature gate for invented DOI, unverified result, generic model-superiority claim or missing exact benchmark/model in `tests/contract/test_literature_matrix.py`.
- [ ] T098 [US2] Write `docs/b1_coverage_decision.md` selecting B1Q, B1T fallback or `REVISE_B1` solely from PIT/coverage gates, never predictive performance.
- [ ] T099 [US2] Add route, quote-age, nanosecond, interpolation, skew, term-structure, cache/idempotency and all-assets common-history tests in `tests/unit/test_b1_closure.py` and `tests/e2e/test_b1_closure.py`.
- [ ] T100 [US2] Run pytest, ruff, mypy, coverage, JSON Schema, secret/path scans and deterministic rerun checks; record results in `artifacts/b1_full_origin/test_report.txt`.
- [ ] T101 [US2] Generate `docs/20_session_calibration_request.md` only as a conditional request with the 30% P95 storage margin, resumability and no-download assertion.

## Phase 3D: B1 Forensic Validation and Asset-Coverage Decision (controlled)

**Goal**: repair the invalid nested B1 result, diagnose zero-coverage assets and decide the
twenty-session request without downloading it.

**Independent test**: the archived invalid result remains intact; all component/nested
invariants pass across every route and subgroup; the failure waterfall reconciles 2,840 origins;
the 12-case controlled trace is complete; and the availability/literature gates are explicit.

- [ ] T102 [P] [US2] Archive the prior non-monotone B1 result at `artifacts/b1_full_origin/invalid_nested_coverage_v1.json` and record the forensic status in `docs/recovery/b1_forensic_spec_analysis.md`.
- [ ] T103 [P] [US2] Add component fields and nested predicates (`atm_iv_available`, `skew_available`, `term_structure_available`, `b1a_complete`, `b1b_complete`, `b1c_complete`) to `scripts/run_b1_closure.py` and `scripts/build_b1t_route.py`.
- [ ] T104 [US2] Implement fail-closed global, asset, date, session-segment and route monotonicity assertions in `scripts/validate_b1_nested_coverage.py`.
- [ ] T105 [US2] Build the 17-stage B1Q failure waterfall with exact failure codes and origin reconciliation in `artifacts/b1_forensic/failure_waterfall.csv`.
- [ ] T106 [P] [US2] Execute the 12-case controlled Massive trace for AAPL, SPY, META and TSLA and write `artifacts/b1_forensic/controlled_asset_tests.json`.
- [ ] T107 [US2] Persist per-attempt IV diagnostics (asset, origin, contract, inputs, success, failure code and IV) in `artifacts/b1_forensic/iv_failures.csv`.
- [ ] T108 [US2] Diagnose ETF roots, OCC tickers, distributions, dividend assumptions, strike scaling, mappings, corporate actions, expiry and quote filters for the four zero-coverage assets in `docs/b1_zero_coverage_diagnosis.md`.
- [ ] T109 [US2] Recompute component and nested B1Q/B1T coverage globally, by asset/date/session segment, ETF/equity, DTE bucket and quote/spread sensitivity in `artifacts/b1_forensic/b1_nested_coverage.json`.
- [ ] T110 [US2] Generate `artifacts/b1_forensic/b1_coverage_by_asset.csv` and `artifacts/b1_forensic/b1_coverage_by_session_segment.csv` with monotone component and nested fields.
- [ ] T111 [US2] Document the PIT-only B1 benchmark choice in `docs/b1_benchmark_selection.md` using coverage and validity gates, never predictive performance.
- [ ] T112 [P] [US1] Probe the twenty exact pre-Pilot-V2 sessions with FMP, UW metadata and one historical Massive ATM quote per candidate without downloading Full Tape payloads in `scripts/twenty_session_availability_probe.py`.
- [ ] T113 [US1] Write `artifacts/api_audit/twenty_session_availability_probe.json` with 20 session records, excluded Pilot V2 dates and `pit_claim=false` for file metadata.
- [ ] T114 [P] [US3] Add full-text evidence status/location fields and verification notes for each literature row in `docs/literature_evidence_ledger.csv`.
- [ ] T115 [US2] Add nested monotonicity, waterfall reconciliation, no-future-quote, as-of contract, ETF/equity and q=0 assumption tests in `tests/contract/test_b1_forensic.py`.
- [ ] T116 [US2] Run pytest, Ruff, Mypy, coverage, JSON Schema and secret/path scans; write `artifacts/b1_forensic/test_report.txt` and `artifacts/b1_forensic/evidence_index.csv`.
- [ ] T117 [US2] Write `docs/20_session_calibration_decision.md` with exactly one of `AUTHORIZE_20_SESSION_CALIBRATION`, `REVISE_B1_AGAIN`, `REVISE_RESEARCH_DESIGN` or `STOP_PROJECT`, without downloading sessions.

**Checkpoint**: Phase 3C is accepted only if B1a/B1b/B1c route coverage, PIT, common-history
and literature gates are explicit. It must return `REVISE_RESEARCH_DESIGN` if neither B1Q nor
B1T reaches the declared B1a threshold; it never authorizes the twenty-session download.

## Phase 3E: B1Q Integration Repair and Earnings Contract Closure (controlled)

- [ ] T118 [P] [US2] Add bucket-scoped historical Massive contract resolution and auditable cache keys in `scripts/run_b1_closure.py`.
- [ ] T119 [P] [US2] Reconcile controlled traces with matching full-matrix rows in `artifacts/b1_repair/controlled_vs_pipeline_diff.csv`.
- [ ] T120 [P] [US2] Audit contract, quote and origin keys and join cardinality in `artifacts/b1_repair/cache_key_audit.json`.
- [ ] T121 [US2] Diagnose every `INVALID_DTE` row by asset/date/origin/side/bucket/contract in `artifacts/b1_repair/dte_failure_diagnosis.csv`.
- [ ] T122 [US2] Emit mutually exclusive `first_failure_code` and separate `all_failed_checks` artifacts for B1Q.
- [ ] T123 [US2] Recompute corrected B1Q nested coverage and stratified CSVs after the integration repair.
- [ ] T124 [P] [US2] Create `docs/corporate_event_contract.md` and ETF/equity earnings tests.
- [ ] T125 [US2] Create `docs/etf_role_decision.md` using only data-quality and PIT criteria.
- [ ] T126 [US2] Complete literature `claim_strength_allowed` classification and evidence coordinates.
- [ ] T127 [US2] Run all quality gates and write `docs/20_session_calibration_decision_v2.md` without downloading sessions.

**Phase 3E checkpoint**: authorize twenty-session calibration only if controlled/full
reconciliation, DTE diagnosis, sequential waterfall, B1a gates, PIT, storage and literature
evidence all pass.

## Phase 3F: Twenty-Session Historical Calibration and Method Freeze (controlled)

**Goal**: process exactly the twenty authorized pre-Pilot-V2 sessions, calibrate continuous B2
features without leakage, recompute B1Q stability and produce a quality-only role recommendation.

**Independent test**: twenty independent day manifests and immutable ZIP hashes exist; the
calibration panel and Pilot V2 application are reproducible from the same hashes; B1Q nested
invariants pass across all declared strata; and no model, QLIKE, tuning, backfill or final-test
artifact is produced.

- [x] T128 [P] Record the exact twenty-session allow-list, excluded Pilot V2 dates, free-space/write gates, presence-only secret check and prohibited downstream actions in `artifacts/calibration_20d/download_manifest.json`.
- [x] T129 [P] Create a resumable streaming Full Tape downloader with per-day checkpoints, SHA-256, CRC/schema validation, sanitized request metadata and retry telemetry in `scripts/download_calibration_20d.py`.
- [x] T130 [US2] Stream-filter the eight assets into date/asset Parquet partitions without loading a ZIP into memory and emit `artifacts/calibration_20d/raw_integrity_report.json`.
- [x] T131 [US2] Enforce `LEGACY_CACHE_READ_ONLY` for the 199 unkeyed files and create V2-only explicit cache keys with duplicate/hash-collision failure tests in `tests/contract/test_calibration_20d.py`.
- [x] T132 [US2] Fetch exact-session FMP bars, apply the conservative availability rule, build UTC/NY five-minute origins and persist `artifacts/calibration_20d/underlying_1min_20d.parquet` and `b2_calibration_origins.parquet`.
- [x] T133 [US2] Build primary and sensitivity continuous B2 panels from eligible `created_at` rows with internal aggregates, natural prevalence and no provider cumulative fields in `scripts/build_b2_calibration_20d.py`.
- [x] T134 [P] [US2] Add unit and contract tests for cutoffs, no-future rows, natural prevalence, duplicate handling and reproducible feature aggregation in `tests/unit/test_b2_calibration.py`.
- [x] T135 [US2] Fit asset/time-band median-MAD calibration with IQR/asset fallbacks, five log-core robust z-scores, top-three median score and historical p95 threshold in `scripts/build_b2_calibration_20d.py`.
- [x] T136 [US2] Apply frozen twenty-session parameters to Pilot V2 and write `artifacts/calibration_20d/pilot_v2_unusual_scores.parquet`, prevalence and sensitivity artifacts without target-based selection.
- [x] T137 [P] [US2] Add calibration leakage, fallback, percentile, score determinism and calibration/pilot separation tests in `tests/unit/test_b2_calibration.py`.
- [x] T138 [US2] Recompute B1Q on all twenty-session origins using the repaired contract-day/as-of quote route and V2-only cache in `scripts/run_b1_calibration_20d.py`.
- [x] T139 [US2] Assert B1Q nested monotonicity globally, by asset/date/tercile/route/instrument and emit explicit IV failure codes in `artifacts/calibration_20d/b1_coverage_20d.json`.
- [x] T140 [P] [US2] Add twenty-session B1Q quote-age, nanosecond, IV, nested and B1T-separation tests in `tests/contract/test_calibration_20d.py`.
- [x] T141 [US2] Generate `artifacts/calibration_20d/b1_coverage_by_asset.csv` and `b1_coverage_by_session_segment.csv` plus a route/instrument stability summary.
- [x] T142 [US1] Record actual download, decompression, filtering, aggregation, retry, memory, free-space and resumability telemetry in `artifacts/calibration_20d/storage_telemetry.csv`.
- [x] T143 [US1] Recompute preliminary 3/6/12-month mean/P95 storage and duration estimates from measured twenty-session telemetry in `docs/backfill_feasibility_v3.md`; keep larger backfill blocked.
- [x] T144 [P] [US3] Complete source-text coordinates, limited-claim statuses and verification notes for all ten literature rows in `docs/literature_evidence_ledger.csv`.
- [x] T145 [US2] Classify target candidates, market controls and diagnostic exclusions from quality/PIT criteria only in `docs/calibrated_asset_quality_decision.md`.
- [x] T146 [US2] Write the B2 calibration and unusual-activity contracts in `docs/b2_calibration_contract.md` and `docs/unusual_activity_definition.md`.
- [x] T147 [US2] Produce `artifacts/calibration_20d/b2_feature_distributions.csv`, `unusual_score_distribution.csv`, `b2_calibration_parameters.json` and `unusual_event_prevalence.csv`.
- [x] T148 [US2] Write `artifacts/calibration_20d/test_report.txt` and `evidence_index.csv` after pytest, Ruff, Mypy, coverage, JSON Schema, hash, secret/path and reproducibility gates.
- [x] T149 [US2] Add the Phase 3F result and one explicit recommendation to `docs/recovery/twenty_session_calibration_spec_analysis.md`, preserving model, QLIKE, backfill, freeze and Word gates as blocked.
- [x] T150 [US2] Run the complete Phase 3F quality gate and record final status; do not download further sessions or start predictive evaluation.

**Phase 3F checkpoint**: the method-freeze/backfill-plan recommendation is eligible only when
all twenty sessions are valid and resumable, B2 calibration is leakage-safe, B1Q nested coverage
is coherent, quality roles meet their stated data-only criteria, literature evidence is bounded,
tests pass and storage margin is documented. This phase does not itself authorize a larger
backfill or model evaluation.

## Phase 4: User Story 2 — Point-in-time pilot dataset (Priority: P1)

**Goal**: construct a leakage-safe eight-asset pilot with immutable raw
provenance, six normalized components, five-minute origins, and RV30 targets.

**Independent test**: the end-to-end pilot fixture produces deterministic rows for every valid
origin, continuous option-activity features, quality profile and row-level traceability without
future predictor fields; no artificial no-event requirement is imposed.

### Tests first

- [ ] T034 [P] [US2] Add failing normalization tests for all six component tables in `tests/unit/test_normalize.py`.
- [ ] T035 [P] [US2] Add failing point-in-time leakage tests for contemporaneous and future fields in `tests/unit/test_pit.py`.
- [ ] T036 [P] [US2] Add failing deterministic RV30 tests using only future one-minute closes in `tests/unit/test_target.py`.
- [ ] T037 [P] [US2] Add failing ex-ante earnings diagnostic-join and optional-news gating tests in `tests/unit/test_event_joins.py`; earnings remain outside primary B0/B1a/B2.
- [ ] T038 [P] [US2] Add failing asset quality/freeze tests proving 4–6 assets are selected only on configured quality and overlap metrics in `tests/unit/test_asset_freeze.py`.
- [ ] T039 [P] [US2] Add failing missing-window, duplicate, and insufficient-event tests in `tests/unit/test_pilot_failures.py`.
- [ ] T040 [P] [US2] Add failing end-to-end pilot test with sanitized fixtures in `tests/e2e/test_pilot_dataset.py`.

### Implementation

- [ ] T041 [P] [US2] Implement `src/mds650/normalize.py` for six typed component tables, UTC/NY timestamps, deduplication, and provenance.
- [ ] T042 [P] [US2] Implement `src/mds650/events.py` for PIT-gated diagnostic earnings strata and post-validation optional-news inclusion, never primary benchmark predictors.
- [ ] T043 [P] [US2] Implement `src/mds650/origins.py` for every valid five-minute forecast origin, regular-session validation, `option_activity_present`, and secondary `unusual_event=NOT_CALIBRATED`; preserve natural prevalence without requiring no-operation origins.
- [ ] T044 [P] [US2] Implement `src/mds650/targets.py` for deterministic 30-minute realized variance from future one-minute closes.
- [ ] T045 [P] [US2] Implement `src/mds650/asset_selection.py` for quality/coverage-only freeze and common-history calculation.
- [ ] T046 Implement `src/mds650/pilot.py` to orchestrate extraction, normalization, joins, target construction, and fail-closed output (depends on T041–T045).
- [ ] T047 [US2] Implement `src/mds650/profiling.py` for machine-readable profile, human report, and row trace.
- [ ] T048 [US2] Run the fixture end-to-end pilot in `tests/e2e/test_pilot_dataset.py` and verify that a few-event window widens only through a recorded configuration change.

### Pilot V2 correction tasks (bounded, no backfill/modeling)

- [ ] T070 [P] [US2] Add regression tests proving all 2,840 valid origins are retained and trade presence is not labeled `unusual_event` in `tests/e2e/test_pilot_v2.py`.
- [ ] T071 [P] [US2] Add PIT tests for `created_at <= origin-60s`, sensitivity cutoffs, provider cumulative-field exclusion, and internally computed aggregates in `tests/unit/test_b2_pit_v2.py`.
- [ ] T072 [P] [US2] Add Massive quote-selection tests for nanosecond `timestamp.lte`, descending order, last SIP quote, and bounded range diagnostics in `tests/unit/test_massive_quote_selection.py`.
- [ ] T073 [P] [US2] Add B1 per-origin coverage tests for B1a ATM IV, B1b skew, B1c term structure, valid contracts, and IV failure reasons in `tests/unit/test_b1_origin_coverage.py`.
- [ ] T074 [P] [US2] Add FMP date-filtering and provider-over-return tests for winter, summer, DST, early close, first/last minute and symbol-specific earnings timing in `tests/unit/test_fmp_pilot_v2.py`.
- [ ] T075 [P] [US2] Add common-history V2 tests requiring `as_of`-resolved historical contracts and session-level component pass fields in `tests/unit/test_common_history_v2.py`.
- [ ] T076 [US2] Rebuild `scripts/run_authorized_pilot.py` B2 output under `artifacts/pilot_v2/` with continuous features, `option_activity_present`, `unusual_event_status=NOT_CALIBRATED`, and no provider cumulative fields.
- [ ] T077 [US2] Implement per-origin Massive quote extraction in `src/mds650/providers/massive.py` using nanosecond `timestamp.lte` and explicit no-quote diagnostics before reusing IV inversion.
- [ ] T078 [US2] Integrate IV inversion by origin and produce B1a/B1b/B1c fields plus `artifacts/pilot_v2/b1_component_coverage_v2.csv` and `artifacts/pilot_v2/iv_robustness_v2.json`.
- [ ] T079 [US2] Correct FMP exact-session filtering and symbol-specific earnings timing in `src/mds650/providers/fmp.py`; emit `artifacts/pilot_v2/fmp_timestamp_validation_v2.json` without claiming provider confirmation.
- [ ] T080 [US2] Replace `common_history_probe.json` with preserved `common_history_probe_v1_invalid.json` and generate `artifacts/api_audit/common_history_probe_v2.json` using date-relative historical contracts.
- [ ] T081 [US2] Generate `artifacts/pilot_v2/pilot_manifest_v2.json`, `artifacts/pilot_v2/evidence_index.csv`, and a human-readable `artifacts/pilot_v2/pilot_profile_v2.html` without secrets or personal paths.
- [ ] T082 [US2] Generate preliminary 3/6/12-month storage/time/memory estimates from the five observed sessions in `docs/backfill_feasibility_v2.md`; keep backfill status `BLOCKED`.
- [ ] T083 [US2] Run Pilot V2 pytest, ruff, mypy, coverage, JSON Schema and reproducibility checks; record results in `artifacts/pilot_v2/test_report.txt`.

**Checkpoint**: US2 is complete only when every pilot row has a valid cutoff,
future-close trace, source hash, and target status, and no asset was selected by
preliminary predictive performance.

## Historical benchmark scaffold superseded

The unexecuted T055–T063 scaffold used the pre-Phase-5 B1 definition. It is superseded by
T179–T196, which implement the approved B0/B1a/B2, Gamma/LightGBM, QLIKE, paired-day
bootstrap, Holm and one-read holdout contract. Git history preserves the former text; those
IDs are not active execution tasks.

## Phase 7: Colab and documentation polish

- [x] T064 [P] Create `notebooks/MDS650_Research_Pipeline.ipynb` from modular imports with research question, Colab Secrets presence gate, frozen configuration, schemas, QC tables, preview, validation status, and sanitized exports.
- [x] T065 [P] Add `docs/architecture.md` describing local source-of-truth boundaries and the Colab orchestration layer.
- [x] T066 [P] Add `docs/week4_evidence_recovery.md` with provider, overlap, PIT, licensing, and evidence-recovery decision trees.
- [x] T067 [P] Add `docs/data_dictionary.md` generated from returned schemas and normalized model definitions, plus a contract test in `tests/contract/test_public_data_dictionary.py` that checks the six observed components, PIT fields and public architecture boundary.
- [ ] T068 Run `uv sync --locked`, `pytest`, `ruff check .`, `mypy src`, and coverage gates; record exact results in the execution manifest.
- [ ] T069 Run the non-destructive quickstart from `specs/001-pit-options-rv30/quickstart.md`, compare local and Colab configuration/schema/QC manifest hashes, and confirm no secret values appear in logs, reports, fixtures, or notebook output.

## Phase 4B: Local PIT Repair and Staged-Backfill Readiness

- [x] T151 [P] Add Phase 4B unit and contract tests for fixed UW windows, FMP +2 sensitivity as-of snapshots, canonical aliases, optional IV missingness, matrix nesting, checkpoints and holdout read guards.
- [x] T152 Implement the local-only `scripts/run_phase4b.py` runner and shared `scripts/phase4b_common.py` contracts using retained Parquet inputs only.
- [x] T153 Repair the FMP +2 sensitivity with `source_timestamp + 2 minutes <= forecast_origin`; preserve the +1 primary assumption, origin IDs, RV30 targets, source timestamps and feature ages.
- [x] T154 Replace truncated UW bins with exact `[origin-delay-5m, origin-delay)` windows for 60/120/300 seconds and enforce both event-time and operational cutoff predicates.
- [x] T155 Canonicalize `b2_within_bin_iv_change`, reject aliases/exact duplicate predictor identities, preserve optional IV missingness and exclude no row solely for IV-change absence.
- [x] T156 Emit B0, B1Q, B2-core, exact-intersection matrices, row-set/target hashes and non-IV Pilot exclusion diagnostics.
- [x] T157 Emit verifiable per-session checkpoints, restart/corruption evidence and a deterministic metadata-only ten-session `SEALED_NOT_ACQUIRED` holdout with a read guard.
- [x] T158 Run the full local pytest, coverage, Ruff, Mypy and two-rebuild hash gates; no provider request or performance computation is permitted.
- [x] T159 Generate `reports/CODEX_PHASE4B_HANDOFF.md` and preserve all V1/V2 artifacts unchanged.

**Phase 4B checkpoint**: Stage A data acquisition remains out of scope. The phase is accepted only
when the corrected local artifacts, tests, hashes and holdout guard pass, with any Pilot loss
explicitly attributed to non-IV B0/B1Q coverage rather than optional IV missingness.

## Phase 8: Phase 5 design, preregistration and storage foundation

- [x] T160 Update Spec Kit artifacts and write the zero-critical consistency result to `docs/recovery/phase5_90_session_spec_analysis.md`.
- [x] T161 [P] Add failing exact-session, disjointness and canonical-hash tests in `tests/unit/test_phase5_study_design.py`.
- [x] T162 Implement exact 80/10 XNYS session construction and canonical JSON hashing in `src/mds650/study_design.py`.
- [x] T163 [P] Add failing preregistration schema, status, feature-registry, fold, model-role and zero-holdout-read tests in `tests/contract/test_phase5_preregistration.py`.
- [x] T164 Create `specs/001-pit-options-rv30/contracts/phase5-preregistration.schema.json` with exact arrays, enums, hashes and cross-field invariants.
- [x] T165 Implement preregistration freezing in `scripts/freeze_phase5_preregistration.py` and generate `artifacts/phase5/study_sessions_90.json` plus `artifacts/phase5/preregistration.json` before any model or QLIKE call.
- [x] T166 [P] Add failing D: root, write probe, 80-GB peak floor, holdout-exclusion and resumability tests in `tests/contract/test_phase5_storage.py`.
- [x] T167 Parameterize the existing streaming downloader and builders with explicit allow-lists and roots in `scripts/download_calibration_20d.py`, `scripts/build_b2_calibration_20d.py` and `scripts/run_b1_calibration_20d.py`.
- [x] T168 Implement non-destructive D: preparation and verified-copy manifests in `scripts/prepare_phase5_storage.py`; never delete the retained C: evidence.
- [x] T169 Verify and record all 25 reusable input hashes in `artifacts/phase5/reused_25_session_manifest.json`.

## Phase 9: User Story 2 — Eighty-session PIT development panel (Priority: P1)

- [x] T170 [US2] Acquire only the 55 missing development Full Tape sessions resumably into `D:\MDS650\raw` and write per-session manifests under `D:\MDS650\manifests`.
- [x] T171 [P] [US2] Build exact-session FMP B0 sources for the 55 missing dates in `D:\MDS650\data\fmp` using +1 primary and +2 sensitivity availability.
- [x] T172 [P] [US2] Build Massive B1Q contract-day caches and origin ATM-IV rows for the 55 missing dates in `D:\MDS650\cache\massive` and `D:\MDS650\data\b1q`.
- [x] T173 [US2] Reconcile 25 reused plus 55 new sessions and emit `artifacts/phase5/development_source_manifest_80d.json` with no holdout dates.
- [x] T174 [P] [US2] Add failing exact-formula, zero-denominator, target-blind and cutoff tests in `tests/unit/test_phase5_features.py`.
- [x] T175 [US2] Implement only the nine frozen compact B2 formulas by reusing Phase 4B eligibility logic in `src/mds650/phase5_features.py`.
- [x] T176 [P] [US2] Add failing unique-origin, PIT, common-row, target-hash, missing-reason and no-holdout tests in `tests/contract/test_phase5_panel.py`.
- [x] T177 [US2] Build `artifacts/phase5/common_development_80d.parquet` from identical B0/B1a/B2/RV30 origins in `scripts/build_phase5_common_panel.py`.
- [x] T178 [US2] Write coverage, missingness, timestamp and session-segment diagnostics to `artifacts/phase5/development_panel_quality.json`, freeze four to six eligible assets using quality/PIT rules only, and fail when fewer than four pass.

## Phase 10: User Story 4 — Preregistered development evaluation (Priority: P2)

- [x] T179 Add only `scikit-learn>=1.7,<2` and `lightgbm>=4.6,<5` with `uv`, update `pyproject.toml` and `uv.lock`, and rerun the clean-install compatibility gate.
- [x] T180 [P] [US4] Add failing fold, 30-minute purge/embargo and training-only preprocessing tests in `tests/unit/test_temporal_validation.py`.
- [x] T181 [P] [US4] Add failing positive-prediction and fixed-role tests for Gamma GLM and LightGBM in `tests/unit/test_modeling.py`.
- [x] T182 [P] [US4] Add failing QLIKE, MAE/RMSE, paired-day bootstrap and Holm tests in `tests/unit/test_metrics.py`.
- [x] T183 [US4] Implement the four frozen expanding folds in `src/mds650/temporal_validation.py`.
- [x] T184 [P] [US4] Implement deterministic QLIKE, MAE/RMSE, 10,000-draw paired-day bootstrap and Holm adjustment in `src/mds650/metrics.py`.
- [x] T185 [P] [US4] Implement confirmatory `GammaRegressor` and fixed `LGBMRegressor(objective="gamma")` training in `src/mds650/modeling.py`.
- [x] T186 [US4] Run common-row development forecasts and write `artifacts/phase5/development_forecasts.parquet` plus `artifacts/phase5/development_results.json` in `scripts/run_phase5_development_evaluation.py`.
- [x] T187 [US4] Preserve every registered feature/model/timing variant and result sign in `artifacts/phase5/variant_ledger.json`.
- [x] T188 [US4] Freeze code, data, feature, fold, model, prediction and result hashes in `artifacts/phase5/method_freeze.json` with `holdout_reads=0`.

## Phase 11: User Story 4 — One-time prospective holdout and final evidence (Priority: P2)

- [x] T189 [P] [US4] Add failing incomplete-session, pre-freeze, hash-mismatch and second-read tests in `tests/contract/test_phase5_holdout_guard.py`.
- [x] T190 [US4] Implement the fail-closed `0 -> 1` holdout access transition in `src/mds650/holdout.py` and `scripts/run_phase5_holdout.py`.
- [x] T190A [P] [US4] Implement and test the resumable, isolated
  `scripts/acquire_phase5_holdout.py` path, exact ten-session allow-list, pre-network release
  guard, provider/source hashing, common-panel seal and target-blind stability sidecar without
  fitting models or computing QLIKE.
- [ ] T191 [US4] After all ten sessions complete, acquire holdout provider evidence into restricted D: roots without analytical outcome reads and record `artifacts/phase5/holdout_access_ledger.json`.
- [ ] T192 [US4] Execute the sole authorized holdout read and write `artifacts/phase5/holdout_results.json`; a second invocation MUST fail.
- [ ] T193 [P] [US4] During the sole T192 read, report asset, frozen session-tercile,
  development-B0 volatility-regime, FMP +1/+2 and B2 60/120/300-second stability in
  `artifacts/phase5/stability_results.json`; reuse frozen hyperparameters without retuning and
  apply the FR-080 material-reversal rule without expanding Holm.
- [ ] T194 [US4] Run pytest, Ruff, Mypy, coverage, JSON Schema, secret/path and deterministic-hash gates and write `artifacts/phase5/test_report.txt`.
- [ ] T195 [P] [US4] Reproduce the locked install and compact validation path in Colab and record sanitized parity hashes in `artifacts/phase5/colab_compatibility.json`.
- [ ] T196 [US4] Write `reports/CODEX_PHASE5_FINAL_HANDOFF.md` with both deltas, uncertainty, Holm, all registered variants and every positive, negative or null result.

## Phase 12: Corrected Development Evidence Release after PIT v2.1 (controlled)

**Goal**: Produce one new source-bound development-only B0/B1a/B2 evidence release using the
immutable B2 availability correction, while preserving the sealed legacy-result and prospective
holdout gates.

**Independent test**: The release binds exactly 80 development sessions and all approved source
hashes, rejects every holdout/result-like input and delayed-source zero encoding, and can run the
frozen development protocol without reading any holdout path.

- [x] T197 [US4] Update the corrected-development specification, plan, data model, contracts,
  quickstart and decision record under `specs/001-pit-options-rv30/` and write
  `docs/recovery/corrected_development_spec_analysis.md`.
- [x] T198 [P] [US4] Add failing contract tests for the corrected-development release schema,
  immutable source bindings, literal legacy/OOS gates and no secret/personal-path output in
  `tests/contract/test_corrected_development_release.py`.
- [x] T199 [P] [US4] Add failing unit tests for exact 80-session isolation, zero holdout overlap,
  duplicate/future predictor rejection, B2 all-null exclusion encoding and no target during
  predictor construction in `tests/unit/test_corrected_development_gate.py`.
- [x] T200 [US4] Implement the immutable release-state validator and canonical self-hash logic
  in `src/mds650/corrected_development_release.py` using
  `contracts/corrected-development-release-v1.schema.json`.
- [x] T201 [US4] Implement `scripts/build_corrected_development_release.py` to reject a
  target-blind predictor source whose date coverage differs from the exact development manifest;
  v2.4 remains an approved control/provenance input, never a relabelled 80-session source.
- [x] T201A [P] [US4] Add failing source-coverage and exact-origin-grid tests in
  `tests/unit/test_corrected_development_sources.py`, including no stale B1Q rate/dividend
  substitution, mandatory sanitized payload hashes and availability timestamps, and all-null B1Q
  missing rows for unresolved same-session or retained-session provenance. Extend the review-only
  FMP timing-evidence intake with exact Treasury/dividend semantics and revision claims; it must
  not authorize a provider request or B1Q rebuild by itself.
- [x] T201B [US4] Implement `src/mds650/corrected_development_sources.py` and
  `contracts/corrected-development-source-coverage-v1.schema.json` to build a target-free
  exact-80 source coverage ledger from FMP, Full Tape and B1Q sources; emit
  `BLOCKED_SOURCE_COVERAGE` before target binding on an unresolved input.
- [x] T201B1 [P] [US4] Add the target-free, source-hashed B1Q put-call-parity grid diagnostic
  in `src/mds650/b1q_put_call_parity_feasibility.py` with a JSON Schema, immutable report and
  tests. It may diagnose insufficient paired strikes but must not substitute rate/dividend
  evidence, change B1Q, bind a target or alter legacy/OOS gates.
- [ ] T201C [US4] Implement `scripts/build_corrected_development_predictors.py` to create the
  exact 80-session B0/B1Q/B2 target-free panel only from source-bound local inputs, preserving
  B2 exclusions and B1Q missingness; write all bulk outputs under `D:\MDS650`. The current
  coverage-first implementation intentionally stops after the self-hashed
  `BLOCKED_SOURCE_COVERAGE` ledger because all B1Q origins lack admissible exogenous-input
  provenance; it does not materialize a predictor panel or bind targets.
- [x] T202 [US4] Run the exact-window source build idempotently, validate the coverage schema
  and emit either `artifacts/corrected_development_v1/target_blind_release_manifest.json` when
  all B1Q source coverage passes or a self-hashed `BLOCKED_SOURCE_COVERAGE` artifact without
  opening RV30, metrics, legacy results or holdout paths. The recorded 80-session run emitted
  `artifacts/corrected_development_v1/source_coverage_ledger.json` with B0/B2 source coverage
  passing and B1Q blocked by `B1Q_EXOGENOUS_INPUT_PROVENANCE_UNRESOLVED`.
- [ ] T203 [P] [US4] Add failing development target-binding tests for exact origin/target hashes,
  holdout-path rejection, target-before-predictor ordering and deterministic release identity in
  `tests/contract/test_corrected_development_target_binding.py`.
- [ ] T204 [US4] Implement `src/mds650/corrected_development_target_binding.py` and
  `scripts/bind_corrected_development_targets.py` to bind RV30 only after T202 passes and only
  for the fixed 80 sessions; emit a separate bound manifest and fail closed on any mismatch.
- [ ] T205 [P] [US4] Add failing tests that the corrected evaluator uses frozen B0/B1a/B2,
  folds, methods and registered timing variants; preserves all signs; and cannot resolve an OOS
  path in `tests/contract/test_corrected_development_evaluation.py`.
- [ ] T206 [US4] Implement and execute `scripts/run_corrected_development_evaluation.py` on the
  newly bound development release only, producing immutable forecasts, all registered
  B0/B1a/B2 metrics, bootstrap/Holm output and a variant ledger under
  `artifacts/corrected_development_v1/` without retuning.
- [ ] T207 [US4] Seal data, code, method, prediction and result hashes; run deterministic replay
  and write `artifacts/corrected_development_v1/method_freeze.json` with
  `SAFE_TO_RECONCILE_EXISTING_RESULTS=NO` and `SAFE_TO_OPEN_OR_EVALUATE_OOS=NO`.
- [ ] T208 [US4] Run scoped pytest, Ruff, Mypy, coverage, JSON Schema, secret/path scans and
  Ponytail review; write `artifacts/corrected_development_v1/test_report.txt` and
  `docs/recovery/corrected_development_validation.md`.
- [ ] T209 [US4] Amend the prospective-holdout decision artifact only to bind the corrected
  development method freeze; retain its single-read guard and do not acquire or evaluate a
  holdout session in `artifacts/phase5/holdout_access_ledger.json`.

## Phase 13: Institutional closure and B1v3 decision (controlled)

**Goal**: Reconcile the repository narrative with the immutable evidence, then decide whether
to run a new, preregistered B1v3 confirmation without selecting features or variants by sign.

**Independent test**: A reviewer can trace every scientific statement from the master dossier
to an immutable artifact and can distinguish completed historical work, superseded diagnostics,
current evidence and work that still requires explicit approval.

- [x] T210 [P] Produce `reports/MDS650_MASTER_PROJECT_DOSSIER.md` with the complete package and
  script catalogues, data joins, backfill inventory, trained-model history, scientific results,
  limitations, reproducibility commands and cascaded roadmap.
- [x] T211 [P] Reconcile `README.md`, `docs/methodology_decisions.md`,
  `docs/risk_register.md` and this task graph with the corrected forensic interpretation while
  preserving all prior artifacts and signs.
- [ ] T212 Obtain explicit owner approval for the target-blind B1v3 contract, then write and
  review its Spec Kit specification and preregistration. Current status:
  `PENDING_EXPLICIT_APPROVAL`.
- [ ] T213 [P] After T212 only, add failing tests and implement B1v3 from coherent same-expiry
  geometry and corrected point-in-time exogenous evidence without reading RV30, QLIKE,
  predictions or sealed results.
- [ ] T214 After T212 only, execute the bounded provider preflight and acquire a genuinely new
  chronological confirmation sample using directed contract-day extraction, resumable caches,
  immutable raw evidence and the 80-GiB storage gate.
- [ ] T215 Build and seal one source-bound B0/B1v3/B2 panel; prove origin preservation,
  availability at or before origin, missingness semantics, deterministic hashes and absence of
  outcome access during feature construction.
- [ ] T216 Execute one frozen confirmation with Gamma as confirmatory model, LightGBM as fixed
  challenger, QLIKE as primary metric, whole-day paired bootstrap and Holm; preserve every sign
  and do not retune after opening results.
- [ ] T217 Produce the final institutional release with code/data/method/result hashes,
  environment lock, sanitized fixtures, evidence index, limitations, defense-ready tables and
  an explicit distinction between scientific forecasting evidence and any future economic/P&L
  validation.

## Dependencies and parallel execution

- Setup T001–T006 precedes foundational work.
- Foundational T007–T019 blocks all user stories.
- Within each story, tests precede their implementation; `[P]` marks tasks in distinct files with no dependency.
- Phase 3A (US1) and Phase 3B (US3 literature) can proceed in parallel after foundational
  fixture/schema gates. US2 depends on an accepted v1 provider audit; B1 depends on verified
  ordinary option-state PIT status; asset freeze depends on verified common overlap; backfill
  depends on an approved pilot; modeling depends on the frozen dataset; T064–T069 depend on
  real evidence, accepted pilot/literature/benchmark contracts and runtime approval. Pilot V2
  tasks T070–T083 are bounded and must complete before any backfill request; they do not waive
  the constitution's no-email/no-publication rule.
- T049–T054 are Phase 3B tasks and MUST NOT be deferred until after the pilot.
- Phase 3C tasks T084–T101 may run in parallel with Phase 3B after the Pilot V2 data-engineering
  acceptance gate, but T101 only emits a request and never downloads the twenty sessions.
- Phase 3D tasks T102–T117 depend on the Phase 3C artifacts and MUST run archive → controlled
  trace → waterfall/invariants → full recomputation → availability/literature gates. T117 only
  records a decision and never downloads the twenty sessions.
- Phase 3F tasks T128–T150 depend on the accepted Phase 3E checkpoint and run in this order:
  storage/secret gate → per-day download/checkpoints → filtered partitions → origins/B2 panel →
  calibration → Pilot V2 application and B1Q recalculation. Literature ledger and telemetry may
  run in parallel after the manifests exist. No Phase 3F task authorizes a larger backfill,
  model, QLIKE, tuning, final test, definitive asset freeze or Word/PowerPoint modification.
- B1Q is preferred to B1T when both pass PIT/coverage; B1T remains dependent on the Full Tape
  source and cannot be presented as independent evidence.
- Stop immediately and record a blocked status if any user-specified stopping condition is met.
- Phase 4B tasks T151–T159 are local-only and depend on the retained 25-session artifacts. They
  must run tests/contracts before the runner, then rebuild matrices/checkpoints/holdout, then run
  the full quality gates. They do not authorize Stage A acquisition, new historical data, models,
  tuning, QLIKE or final testing.
- Phase 5 follows T160 → T161–T169 → T170–T178 → T179–T188 → T189–T196. T165 is the
  preregistration barrier: no T170+ acquisition and no T179+ model dependency mutation may run
  before its hashes pass. T174/T176 precede T175/T177; T178 freezes the quality-only asset
  set before T180–T188; T180–T182 precede T183–T186.
- T171 and T172 may run in parallel after T170 establishes the date checkpoints. T193 and T195
  may run in parallel only after T192. T191 waits for the final 2026-07-31 XNYS session to
  complete at `2026-07-31T20:00:00Z`; T190A MUST pass before T191 can make any provider request.
  T192 requires T188, T189–T191 and permits exactly one analytical holdout read.
- No Phase 5 task selects assets, features, models or thresholds using RV30 association, QLIKE,
  preliminary prediction quality or holdout outcomes.
- Phase 12 follows T197 → T198/T199 → T200/T201 → T201A → T201B → T201C → T202 → T203 → T204 → T205 → T206 →
  T207/T208 → T209. It is the only correction path for the B2 v2.2 availability sidecar;
  it never changes sealed legacy results, performs acquisition, opens the OOS holdout or
  selects any method by a favorable development sign.

## Requirement traceability

| Requirements | Planned task coverage |
|---|---|
| FR-001–FR-005 | T020–T033, T025A–T025F |
| FR-006, FR-012, FR-022, FR-023 | T018A–T018D, T024, T031A–T031D |
| FR-007, FR-007A, FR-011 | T009, T014, T025C, T025E, T025F, T035, T036, T039 |
| FR-008, FR-010 | T038, T040, T043, T045, T048, T070, T076 |
| FR-009, FR-028 | T025D, T037, T042 |
| FR-013–FR-016, FR-029 | T179–T196 |
| FR-017 | T049–T054 |
| FR-018–FR-020 | T064–T069 |
| FR-021 | T007–T010, T020–T025, T034–T040, T180–T182, T189, T194 |
| FR-024 | T006, T007, T069 |
| FR-025–FR-027 | T018B–T018D, T025B, T031B–T031E |
| FR-030–FR-035 | T070–T083 |
| FR-036–FR-043 | T084–T101 |
| FR-044–FR-052 | T102–T117 |
| FR-053–FR-056, SC-023–SC-024 | T118–T127 |
| FR-057–FR-069, SC-025–SC-030 | T128–T150 |
| FR-070, FR-079, SC-031, SC-035 | T161–T165, T189–T192 |
| FR-071–FR-074, FR-080, SC-032–SC-033 | T169–T178 |
| FR-075–FR-078, FR-081, SC-034, SC-036 | T179–T188, T193–T196 |
| FR-082 | T166–T173, T191 |
| FR-083–FR-088, SC-037–SC-040 | T197–T209 |
| SC-001–SC-003 | T018A–T018D, T024, T031A–T031E, T033 |
| SC-004–SC-006 | T034–T048, T070–T076 |
| SC-007 | T049–T054 |
| SC-008–SC-009 | T179–T196 |
| SC-010–SC-013 | T064–T069, T081–T083 and compatibility approval gate |
| SC-014–SC-017 | T084–T101 |
| SC-018–SC-022 | T102–T117 |

## MVP strategy

The recovery MVP is T018A–T018D plus the documentation corrections, schema review and
Spec Kit coherence gates. The executed evidence increment is represented by the authenticated
v1x audit, PIT artifact, pilot manifest and frozen-window backfill manifest; it does not waive
the unchecked production tests or authorize B1/B2 benchmark claims.
