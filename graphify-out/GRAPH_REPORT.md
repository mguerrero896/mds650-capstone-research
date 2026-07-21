# Graph Report - MDS650-Capstone  (2026-07-21)

## Corpus Check
- 182 files · ~405,620 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1602 nodes · 2125 edges · 147 communities (130 shown, 17 thin omitted)
- Extraction: 93% EXTRACTED · 7% INFERRED · 0% AMBIGUOUS · INFERRED: 153 edges (avg confidence: 0.53)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `3a0212c0`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- Community 0
- Community 1
- Community 2
- Community 3
- Community 4
- Community 5
- Community 6
- Community 7
- Community 8
- Community 9
- Community 10
- Community 11
- Community 12
- Community 13
- Community 14
- massive.py
- Community 16
- Community 17
- Community 18
- Community 19
- Community 20
- Community 21
- Community 22
- Community 23
- Community 24
- Community 25
- Community 26
- Community 27
- Community 28
- Community 29
- Community 30
- Community 31
- Community 32
- Community 33
- Community 34
- Community 35
- Community 36
- Community 37
- Community 38
- Community 39
- Community 40
- Community 41
- Community 42
- SchemaDriftError
- Community 44
- Community 45
- Community 46
- Community 47
- Community 48
- Community 49
- Community 50
- Community 51
- Community 52
- parse_flow_alert_payload
- Community 54
- Community 55
- Community 56
- Community 57
- Community 58
- Community 59
- Community 60
- Community 61
- Community 62
- Community 63
- Community 64
- Community 65
- Community 66
- Community 67
- Community 68
- Community 69
- Community 70
- Community 71
- Community 72
- Community 73
- Community 74
- Community 75
- Community 76
- Community 77
- Community 78
- Community 79
- Community 80
- Community 81
- Community 82
- Community 83
- Community 84
- Community 85
- Community 86
- Community 87
- Community 88
- Community 89
- Community 90
- Community 91
- Community 92
- Community 93
- Community 94
- Community 95
- Community 96
- Community 97
- Community 98
- Community 99
- Community 100
- Community 101
- Community 102
- Community 103
- Community 104
- Community 105
- probe_summary.md
- Any
- Client
- Community 109
- Path
- CorporateEvent
- MassiveProvider
- Community 113
- Community 114
- Community 115
- test_provider_contracts.py
- OptionStateSnapshot
- OptionTrade
- datetime
- Community 120
- normalize_underlying_bars
- Community 122
- Community 123
- Community 124
- Community 125
- Community 126
- Auditoría de completitud de la iteración de recuperación
- Authenticated provider audit v1 summary
- Runtime compatibility matrix — recovery evidence
- Authenticated provider audit v1 summary
- Authenticated provider audit v1 summary
- Authenticated provider audit v1 summary
- Authenticated provider audit v1 summary
- test_authenticated_audit_manifest.py
- freeze_assets
- MDS650 observed data dictionary
- providerResult
- .validate_cutoff
- .validate_origin_asset
- Fixture-only dataset preview
- Any
- Client

## God Nodes (most connected - your core abstractions)
1. `target_exclusions` - 49 edges
2. `QualityGateError` - 31 edges
3. `SchemaDriftError` - 30 edges
4. `required` - 24 edges
5. `ProviderHTTPClient` - 24 edges
6. `null` - 21 edges
7. `Provider audit v1 plan` - 19 edges
8. `Spec Kit cross-artifact analysis report` - 18 edges
9. `ProviderResponse` - 18 edges
10. `UnderlyingBar` - 17 edges

## Surprising Connections (you probably didn't know these)
- `test_provider_client_fails_closed_on_authentication()` --calls--> `ProviderHTTPClient`  [INFERRED]
  tests/unit/test_provider_client.py → src/mds650/providers/base.py
- `test_provider_client_retries_rate_limit_without_putting_key_in_url()` --calls--> `ProviderHTTPClient`  [INFERRED]
  tests/unit/test_provider_client.py → src/mds650/providers/base.py
- `materialize()` --calls--> `parse_flow_alert_payload()`  [INFERRED]
  scripts/materialize_backfill_from_raw.py → src/mds650/providers/unusual_whales.py
- `run()` --calls--> `parse_flow_alert_payload()`  [INFERRED]
  scripts/run_window_pipeline.py → src/mds650/providers/unusual_whales.py
- `UnusualOptionEvent` --uses--> `CorporateEvent`  [INFERRED]
  tests/e2e/test_pilot_dataset.py → src/mds650/contracts.py

## Import Cycles
- 1-file cycle: `src/mds650/contracts.py -> src/mds650/contracts.py`
- 1-file cycle: `src/mds650/time.py -> src/mds650/time.py`
- 1-file cycle: `src/mds650/origins.py -> src/mds650/origins.py`
- 1-file cycle: `src/mds650/providers/massive.py -> src/mds650/providers/massive.py`

## Communities (147 total, 17 thin omitted)

### Community 0 - "Community 0"
Cohesion: 0.10
Nodes (34): Any, Client, _calendar_diagnostics(), _derived_common_history_status(), _derived_pit_status(), _diagnostic(), _fingerprint(), _fmp_rows() (+26 more)

### Community 1 - "Community 1"
Cohesion: 0.11
Nodes (30): build_forecast_origins(), Construction of point-in-time five-minute forecast origins., Build unique five-minute origins using only information at the cutoff.      Pa, align_five_minute_origin(), is_regular_session_minute(), parse_market_timestamp(), Timezone and regular-session invariants for market timestamps., Return the New York exchange session date for an aware timestamp. (+22 more)

### Community 2 - "Community 2"
Cohesion: 0.15
Nodes (26): AuditValidation, _identity_key(), load_and_validate_audit_manifest(), _massive_directed_probe_passed(), Sanitized provider-audit manifest validation and fail-closed gates., Enforce v1.1 identity, hash and distributable-path invariants.      JSON Schema, Serialize the manifest's seven-field request identity deterministically., Machine-readable result of validating a sanitized audit manifest. (+18 more)

### Community 3 - "Community 3"
Cohesion: 0.15
Nodes (8): Point-in-time unusual-options event without inferred trader intent., Require timezone information for event and availability timestamps., Reject negative source measures without imputing missing values., Require non-negative finite trade measures., Keep null as missing and reject negative quote values., Allow an explicit missing volume but reject negative values., _require_finite_nonnegative(), UnusualOptionEvent

### Community 4 - "Community 4"
Cohesion: 0.07
Nodes (38): null, number, string, type, type, type, type, pattern (+30 more)

### Community 5 - "Community 5"
Cohesion: 0.14
Nodes (17): BaseTransport, Headers, AuthenticationError, ProviderBlockedError, Raised when a provider rejects authentication., Raised when a provider gate fails closed with an exact blocker code., Create a provider error preserving its machine-readable code.          Paramet, ProviderResponse (+9 more)

### Community 6 - "Community 6"
Cohesion: 0.12
Nodes (20): ForecastOrigin, Five-minute forecast origin with an explicit predictor cutoff., Reject an origin outside the ratified candidate universe., Render the origin boundary in ``America/New_York``., Prevent predictors from being available after the origin boundary., PITError, Raised when point-in-time availability cannot be established., eligible_earnings_events() (+12 more)

### Community 7 - "Community 7"
Cohesion: 0.20
Nodes (9): Artefactos versionables, Comandos operativos, Componentes verificados, Estado inicial verificado, Integración local de memoria y grafo, Objetivo y alcance, Provenencia de las herramientas, Relación con el flujo Spec Kit (+1 more)

### Community 8 - "Community 8"
Cohesion: 0.07
Nodes (26): Dependencies & Execution Order, Format: `[ID] [P?] [Story] Description`, Implementation for User Story 1, Implementation for User Story 2, Implementation for User Story 3, Implementation Strategy, Incremental Delivery, MVP First (User Story 1 Only) (+18 more)

### Community 9 - "Community 9"
Cohesion: 0.08
Nodes (25): 1. Initialize Analysis Context, 2. Load Artifacts (Progressive Disclosure), 3. Build Semantic Models, 4. Detection Passes (Token-Efficient Analysis), 5. Severity Assignment, 6. Produce Compact Analysis Report, 7. Provide Next Actions, 8. Offer Remediation (+17 more)

### Community 10 - "Community 10"
Cohesion: 0.16
Nodes (19): hash_payload(), query_parquet(), Immutable raw-response storage and provenance references., Run a read-oriented DuckDB query against one Parquet file.      Parameters, Hash-addressed reference to a raw provider response stored outside Git., Return the lowercase SHA-256 digest of immutable raw bytes.      Parameters, Persist a raw response once and return its provenance reference.      Paramete, Write normalized rows to a bounded Parquet table.      Parameters     ------- (+11 more)

### Community 11 - "Community 11"
Cohesion: 0.06
Nodes (33): $ref, type, type, $ref, $ref, type, type, type (+25 more)

### Community 12 - "Community 12"
Cohesion: 0.29
Nodes (6): Path, Contract validation against the versioned provider-audit JSON Schema., Each retained sanitized authenticated run must conform to schema version 1.1., Request timestamps are RFC3339 date-times, not free-form dates., test_authenticated_manifests_validate_against_manifest_schema(), test_manifest_schema_rejects_invalid_timestamp()

### Community 13 - "Community 13"
Cohesion: 0.07
Nodes (28): type, type, format, pattern, type, $ref, properties, acceptance (+20 more)

### Community 14 - "Community 14"
Cohesion: 0.12
Nodes (21): CorporateEvent, Structured corporate event with an explicit timestamp precision label., ProviderHTTPClient, Small retrying HTTP client that keeps provider keys out of URLs., Close the underlying HTTP connection pool., FMPProvider, parse_earnings_payload(), parse_minute_payload() (+13 more)

### Community 15 - "massive.py"
Cohesion: 0.30
Nodes (16): Raised when a provider response changes its required schema., SchemaDriftError, _conditions(), _number(), _optional_number(), parse_directed_quotes(), parse_directed_trades(), Directed Massive/Polygon-compatible option trade and quote parsers. (+8 more)

### Community 16 - "Community 16"
Cohesion: 0.12
Nodes (16): Assumptions, Clarifications, Edge Cases, Feature Specification: Point-in-Time Options Activity for RV30 Forecasting, Functional Requirements, Key Entities *(include if feature involves data)*, Measurable Outcomes, Pre-registered evaluation strata (+8 more)

### Community 17 - "Community 17"
Cohesion: 0.16
Nodes (13): Logger, LogRecord, configure_logging(), _JsonFormatter, Structured standard-library logging with conservative secret redaction., Return a shallow mapping copy with secret-like fields redacted.      Parameter, Serialize log records as compact JSON without arbitrary extras., Prevent formatter input from carrying a clear-text secret token. (+5 more)

### Community 18 - "Community 18"
Cohesion: 0.04
Nodes (49): target_exclusions, AAPL:2026-07-16T13:40:00+00:00, AAPL:2026-07-16T13:45:00+00:00, AAPL:2026-07-16T13:50:00+00:00, AAPL:2026-07-16T13:55:00+00:00, AAPL:2026-07-16T14:00:00+00:00, AAPL:2026-07-16T14:05:00+00:00, AMZN:2026-07-16T13:40:00+00:00 (+41 more)

### Community 19 - "Community 19"
Cohesion: 0.07
Nodes (42): authorized_for_backfill, b1_status, blockers, candidate_assets, common_history_status, covered_assets, fixture_data_only, frozen_assets (+34 more)

### Community 20 - "Community 20"
Cohesion: 0.12
Nodes (15): 1. Initialize Convergence Context, 2. Load Artifacts (Progressive Disclosure), 3. Build the Intent Inventory, 4. Assess the Codebase and Classify Findings, 5. Assign Severity, 6. Present the In-Session Findings Summary, 7. Append Convergence Tasks (or report converged), 8. Provide Next Actions (Handoff) (+7 more)

### Community 21 - "Community 21"
Cohesion: 0.50
Nodes (3): Authenticated provider audit v1 summary, Explicit limitations, Gate status

### Community 22 - "Community 22"
Cohesion: 0.14
Nodes (13): BenchmarkRun, CorporateEvent, Data Model: Point-in-Time Options Activity for RV30 Forecasting, ExecutionManifest, ForecastOrigin, OptionQuote, OptionStateSnapshot, OptionTrade (+5 more)

### Community 23 - "Community 23"
Cohesion: 0.14
Nodes (13): Decision 10: Week-4 evidence recovery, Decision 11: Exploratory v0 classification and audit corrections, Decision 12: Pre-registered evaluation and natural prevalence, Decision 1: Treat provider documentation and response schemas separately, Decision 2: Preserve six independently governed data components, Decision 3: Define point-in-time availability explicitly, Decision 4: Freeze assets using quality only, Decision 5: Use RV30 and nested benchmarks (+5 more)

### Community 24 - "Community 24"
Cohesion: 0.10
Nodes (26): applicable, blocked, fail, invalid_response, not_applicable, not_verified, pass, unknown (+18 more)

### Community 25 - "Community 25"
Cohesion: 0.22
Nodes (10): Find-SpecifyRoot(), Format-SpecKitCommand(), Get-CurrentBranch(), Get-FeaturePathsEnv(), Get-InvokeSeparator(), Get-Python3Command(), Get-RepoRoot(), Resolve-SpecifyInitDir() (+2 more)

### Community 26 - "Community 26"
Cohesion: 0.08
Nodes (24): format, pattern, type, items, type, items, type, items (+16 more)

### Community 27 - "Community 27"
Cohesion: 0.21
Nodes (11): assess_rows(), QualityReport, Explicit, non-destructive data-quality accounting., Counts and ratios needed by the quality gate., Count duplicate keys, required nulls, and expected-row completeness.      Para, TDD tests for explicit duplicate, null and completeness accounting., An empty response is an explicit zero-completeness result., Quality failures are counted, not silently removed. (+3 more)

### Community 28 - "Community 28"
Cohesion: 0.09
Nodes (23): applicability, asset, authentication_diagnostic, component, endpoint_diagnostic, endpoint_fingerprint, entitlement_diagnostic, event_iv_fields_present (+15 more)

### Community 29 - "Community 29"
Cohesion: 0.15
Nodes (12): Assumptions, Edge Cases, Feature Specification: [FEATURE NAME], Functional Requirements, Key Entities *(include if feature involves data)*, Measurable Outcomes, Requirements *(mandatory)*, Success Criteria *(mandatory)* (+4 more)

### Community 30 - "Community 30"
Cohesion: 0.43
Nodes (7): Page, paginate(), Collect pages while failing closed on loops or unbounded extraction.      Para, One bounded provider page and its opaque continuation cursor., test_paginate_collects_pages_until_cursor_is_absent(), test_paginate_fails_at_configured_page_limit(), test_paginate_fails_on_repeated_cursor()

### Community 31 - "Community 31"
Cohesion: 0.17
Nodes (11): Evidencia mínima de cierre de semana 4, Evidencia vigente, FMP Ultimate, Massive Options Advanced, Recuperación bibliográfica, Semana 4 — Plan de recuperación de evidencia, Unusual Whales, Árbol de decisión de proveedores (+3 more)

### Community 32 - "Community 32"
Cohesion: 0.11
Nodes (18): Dependencies and parallel execution, Implementation, Implementation, Implementation, MVP strategy, Phase 1: Setup, Phase 2: Foundational (blocking prerequisites), Phase 3A: User Story 1 — Authenticated data feasibility (Priority: P1) (+10 more)

### Community 33 - "Community 33"
Cohesion: 0.21
Nodes (13): QualityGateError, Raised when configured data-quality acceptance criteria fail., _as_float(), normalize_underlying_bars(), Provider-row normalization with explicit schema and duplicate gates., Normalize FMP one-minute OHLCV rows without silent repair.      Parameters, assert_directed_only(), Reject an extraction request that would download all historical OPRA quotes. (+5 more)

### Community 34 - "Community 34"
Cohesion: 0.18
Nodes (10): Core Principles, Data, Licensing and Security, Governance, I. Evidence and Point-in-Time Truth, II. Frozen Objective, Benchmarks and Scope, III. Tests First and Fail-Closed Data Contracts, IV. Reproducibility, Security and Auditability, MDS650 Research Pipeline Constitution (+2 more)

### Community 35 - "Community 35"
Cohesion: 0.18
Nodes (10): Completion Report, Done When, Key rules, Mandatory Post-Execution Hooks, Outline, Phase 0: Outline & Research, Phase 1: Design & Contracts, Phases (+2 more)

### Community 36 - "Community 36"
Cohesion: 0.18
Nodes (10): Completion Report, Done When, For AI Generation, Mandatory Post-Execution Hooks, Outline, Pre-Execution Checks, Quick Guidelines, Section Requirements (+2 more)

### Community 37 - "Community 37"
Cohesion: 0.18
Nodes (10): Checklist Format (REQUIRED), Completion Report, Done When, Mandatory Post-Execution Hooks, Outline, Phase Structure, Pre-Execution Checks, Task Generation Rules (+2 more)

### Community 38 - "Community 38"
Cohesion: 0.18
Nodes (10): Core Principles, Governance, [PRINCIPLE_1_NAME], [PRINCIPLE_2_NAME], [PRINCIPLE_3_NAME], [PRINCIPLE_4_NAME], [PRINCIPLE_5_NAME], [PROJECT_NAME] Constitution (+2 more)

### Community 39 - "Community 39"
Cohesion: 0.20
Nodes (9): Acceptance defaults, FMP Ultimate, Massive Options Advanced, Provider audit manifest contract v1.1, Provider-specific acceptance requirements, Required provider-result identity and diagnostics, Status and provenance, Top-level schema (+1 more)

### Community 40 - "Community 40"
Cohesion: 0.09
Nodes (22): conversion, name, origin_relation, post_availability_possible, raw_type, semantics, timezone, unit (+14 more)

### Community 41 - "Community 41"
Cohesion: 0.10
Nodes (20): integer, minimum, type, minimum, type, maximum, minimum, type (+12 more)

### Community 42 - "Community 42"
Cohesion: 0.08
Nodes (39): compute_realized_variance(), Deterministic realized-variance target construction., Compute non-annualized RV from one anchor and future one-minute closes.      P, main(), materialize(), _payloads(), Any, Path (+31 more)

### Community 43 - "SchemaDriftError"
Cohesion: 0.14
Nodes (15): BaseSettings, Validated, presence-only configuration for bounded research runs., Environment-backed settings with fail-closed research safety.      Notes, Reject configurations that could enable external mutations.          Raises, Return provider-key presence without exposing values.          Returns, Fail closed unless all three provider keys are present.          Raises, ResearchSettings, MonkeyPatch (+7 more)

### Community 44 - "Community 44"
Cohesion: 0.22
Nodes (8): Complexity Tracking, Constitution Check, Documentation (this feature), Implementation Plan: [FEATURE], Project Structure, Source Code (repository root), Summary, Technical Context

### Community 45 - "Community 45"
Cohesion: 0.25
Nodes (7): Compatibility gate, Planned implementation gate, Prerequisites, Presence-only secret gate, Spec-driven quickstart, Target contract checkpoint, Validate the current gates

### Community 46 - "Community 46"
Cohesion: 0.17
Nodes (9): BaseModel, OptionStateSnapshot, ProvenanceRecord, Validated records for the six point-in-time data components., Ordinary option state available at a point-in-time cutoff., Prevent a state record from becoming available before it was observed., Common provenance fields emitted by every normalized pilot table., Require the canonical observation timestamp to carry timezone data. (+1 more)

### Community 47 - "Community 47"
Cohesion: 0.18
Nodes (11): acceptance, cross_provider_summary, generated_at_utc, provider_results, research_feature, research_only, run_id, schema_version (+3 more)

### Community 48 - "Community 48"
Cohesion: 0.40
Nodes (5): post-commit script, _GBRAIN_SYNC(), GRAPHIFY_CHANGED, GRAPHIFY_REBUILD_LOG, PYTHONHASHSEED

### Community 49 - "Community 49"
Cohesion: 0.25
Nodes (7): Anti-Examples: What NOT To Do, Checklist Purpose: "Unit Tests for English", Example Checklist Types & Sample Items, Execution Steps, Post-Execution Checks, Pre-Execution Checks, User Input

### Community 50 - "Community 50"
Cohesion: 0.29
Nodes (6): FMP, FMP depth probe, Gate status, Massive Options Advanced, MDS650 provider audit summary, Unusual Whales

### Community 51 - "Community 51"
Cohesion: 0.29
Nodes (6): Literature and recovery, Pilot and reproducibility, Provider evidence and licensing, Research requirements quality checklist: MDS650 PIT options / RV30, Scope and traceability, Temporal and statistical validity

### Community 52 - "Community 52"
Cohesion: 0.43
Nodes (5): Contract tests for the verified recent-literature matrix., _rows(), test_matrix_has_exactly_ten_recent_empirical_rows(), test_matrix_has_unique_stable_identifiers_and_no_generic_superiority_claim(), test_matrix_schema_and_verification_fields_are_nonempty()

### Community 53 - "parse_flow_alert_payload"
Cohesion: 0.29
Nodes (9): _load(), Raw aliases and event times are present without inventing executed_at., Calendar gaps remain explicit and are never treated as interpolable data., test_fmp_calendar_fixture_preserves_unclassified_missing_minutes(), test_fmp_contract_parsers_preserve_observed_schema_semantics(), test_massive_directed_parsers_preserve_precision_and_empty_windows(), test_massive_parser_rejects_contract_mismatch(), test_unusual_whales_parser_keeps_proxies_without_intent_labels() (+1 more)

### Community 54 - "Community 54"
Cohesion: 0.50
Nodes (3): post-checkout script, GRAPHIFY_REBUILD_LOG, PYTHONHASHSEED

### Community 55 - "Community 55"
Cohesion: 0.29
Nodes (6): Benchmark evaluation contract, Benchmark nesting, Evaluation record, Recovery status, Reproducibility and safety, Statistical safeguards

### Community 56 - "Community 56"
Cohesion: 0.29
Nodes (6): Keys and quality rules, Pilot dataset contract, Recovery status, Required outputs, Required tables, Temporal invariants

### Community 57 - "Community 57"
Cohesion: 0.08
Nodes (25): event, no_event, event, no_event, event_no_event_counts, AAPL, AMZN, META (+17 more)

### Community 58 - "Community 58"
Cohesion: 0.11
Nodes (18): Authenticated v1 evidence — run `08a704db-8fe3-41a9-aa74-776111e63936`, Authenticated v1j correction evidence — run `58824eef-1962-4bfd-aed3-a9614b842756`, Authenticated v1m refresh — 2026-07-21, Authenticated v1n refresh — 2026-07-21, Authenticated v1p Massive pagination refresh — 2026-07-21, Authenticated v1r Massive refresh — 2026-07-21, Constitution alignment, Coverage summary (+10 more)

### Community 59 - "Community 59"
Cohesion: 0.29
Nodes (6): Completion Report, Done When, Mandatory Post-Execution Hooks, Outline, Pre-Execution Checks, User Input

### Community 60 - "Community 60"
Cohesion: 0.29
Nodes (6): Completion Report, Done When, Mandatory Post-Execution Hooks, Outline, Pre-Execution Checks, User Input

### Community 61 - "Community 61"
Cohesion: 0.18
Nodes (11): contract_quotes, contract_reference, contract_trades, ordinary_option_state, structured_earnings, underlying_1min, underlying_1min_depth_probe, unusual_option_events (+3 more)

### Community 62 - "Community 62"
Cohesion: 0.09
Nodes (31): CorporateEvent, datetime, OptionQuote, OptionStateSnapshot, OptionTrade, _build(), _components(), _event() (+23 more)

### Community 63 - "Community 63"
Cohesion: 0.33
Nodes (5): Gaps found and disposition, New authenticated evidence update, Recovery gap analysis, Scope, Stop conditions

### Community 64 - "Community 64"
Cohesion: 0.40
Nodes (4): Exploratory provider audit v0 findings, Observed evidence, Recovery evidence handling, What v0 does not prove

### Community 65 - "Community 65"
Cohesion: 0.40
Nodes (4): Initial Repository State — Recovery Iteration, Preserved state, Scope, Verification commands

### Community 66 - "Community 66"
Cohesion: 0.40
Nodes (4): Outline, Post-Execution Checks, Pre-Execution Checks, User Input

### Community 67 - "Community 67"
Cohesion: 0.40
Nodes (4): Outline, Post-Execution Checks, Pre-Execution Checks, User Input

### Community 68 - "Community 68"
Cohesion: 0.40
Nodes (4): [Category 1], [Category 2], [CHECKLIST TYPE] Checklist: [FEATURE NAME], Notes

### Community 69 - "Community 69"
Cohesion: 0.50
Nodes (3): Authenticated provider audit v1 summary, Explicit limitations, Gate status

### Community 70 - "Community 70"
Cohesion: 0.50
Nodes (3): Authenticated provider audit v1 summary, Explicit limitations, Gate status

### Community 71 - "Community 71"
Cohesion: 0.50
Nodes (3): Authenticated provider audit v1 summary, Explicit limitations, Gate status

### Community 72 - "Community 72"
Cohesion: 0.50
Nodes (3): Authenticated provider audit v1 summary, Explicit limitations, Gate status

### Community 73 - "Community 73"
Cohesion: 0.50
Nodes (3): Authenticated provider audit v1 summary, Explicit limitations, Gate status

### Community 74 - "Community 74"
Cohesion: 0.50
Nodes (3): Authenticated provider audit v1 summary, Explicit limitations, Gate status

### Community 75 - "Community 75"
Cohesion: 0.50
Nodes (3): Authenticated provider audit v1 summary, Explicit limitations, Gate status

### Community 76 - "Community 76"
Cohesion: 0.50
Nodes (3): Authenticated provider audit v1 summary, Explicit limitations, Gate status

### Community 77 - "Community 77"
Cohesion: 0.50
Nodes (3): Authenticated provider audit v1 summary, Explicit limitations, Gate status

### Community 78 - "Community 78"
Cohesion: 0.50
Nodes (3): Authenticated provider audit v1 summary, Explicit limitations, Gate status

### Community 79 - "Community 79"
Cohesion: 0.50
Nodes (3): Authenticated provider audit v1 summary, Explicit limitations, Gate status

### Community 80 - "Community 80"
Cohesion: 0.50
Nodes (3): Authenticated provider audit v1 summary, Explicit limitations, Gate status

### Community 81 - "Community 81"
Cohesion: 0.15
Nodes (19): ProviderResponse, _bool(), _epoch_ms(), _execution_proxy(), _expiry(), _float(), _option_type(), _optional_float() (+11 more)

### Community 82 - "Community 82"
Cohesion: 0.12
Nodes (16): OptionQuote, OptionTrade, Directed historical option trade preserving provider condition codes., Directed consolidated bid/ask observation, retaining empty quotes., Reject an inverted bid/ask pair when both sides are present., MassiveProvider, Request a bounded historical trade window for one contract., Request a bounded historical quote window for one contract. (+8 more)

### Community 83 - "Community 83"
Cohesion: 0.17
Nodes (11): Complexity Tracking, Constitution Check, Documentation (this feature), Implementation Plan: Point-in-Time Options Activity for RV30 Forecasting, Phase 0: Research Decisions, Phase 1: Design and Contracts, Project Structure, Source Code (repository root) (+3 more)

### Community 84 - "Community 84"
Cohesion: 0.29
Nodes (7): blocker, evidence, status, diagnostic, additionalProperties, required, type

### Community 85 - "Community 85"
Cohesion: 0.29
Nodes (6): additionalProperties, description, $id, $schema, title, type

### Community 86 - "Community 86"
Cohesion: 0.33
Nodes (5): 1. Financial Modeling Prep (FMP), 2. Unusual Whales, 3. Massive (formerly Polygon.io), Error triage cheat-sheet, Provider HTTP reference (FMP, Unusual Whales, Massive)

### Community 87 - "Community 87"
Cohesion: 0.33
Nodes (6): fmp, massive, unusual_whales, provider, enum, type

### Community 88 - "Community 88"
Cohesion: 0.29
Nodes (6): Audit gate facts (do not re-block on these), Execution order, Execution outcome, Recorded decisions (authorized by Miguel in chat, 2026-07-21), Root cause chain (fixed), Unblock handoff — 2026-07-21

### Community 89 - "Community 89"
Cohesion: 0.50
Nodes (3): Authenticated provider audit v1 summary, Explicit limitations, Gate status

### Community 92 - "Community 92"
Cohesion: 0.50
Nodes (3): Authenticated provider audit v1 summary, Explicit limitations, Gate status

### Community 93 - "Community 93"
Cohesion: 0.50
Nodes (3): Authenticated provider audit v1 summary, Explicit limitations, Gate status

### Community 94 - "Community 94"
Cohesion: 0.50
Nodes (3): Authenticated provider audit v1 summary, Explicit limitations, Gate status

### Community 95 - "Community 95"
Cohesion: 0.50
Nodes (4): type, additionalProperties, type, canonical_aliases

### Community 96 - "Community 96"
Cohesion: 0.28
Nodes (12): _get(), main(), _need(), probe_fmp(), probe_massive(), probe_uw(), Client, Empirically measure each provider's usable historical window.  Evidence-first: b (+4 more)

### Community 97 - "Community 97"
Cohesion: 0.50
Nodes (4): record_key, minLength, pattern, type

### Community 98 - "Community 98"
Cohesion: 0.50
Nodes (4): request_end, format, pattern, type

### Community 99 - "Community 99"
Cohesion: 0.50
Nodes (4): request_id, minLength, pattern, type

### Community 100 - "Community 100"
Cohesion: 0.17
Nodes (10): One-minute underlying OHLCV bar with an auditable deduplication key., Render the canonical bar start in ``America/New_York``., Reject assets outside the ratified candidate universe., Require finite positive OHLC values., Ensure high/low contain the open, close, and each other., UnderlyingBar, _provenance(), test_six_option_component_records_expose_required_fields() (+2 more)

### Community 101 - "Community 101"
Cohesion: 0.25
Nodes (6): Validated primary 30-minute realized-variance target record., Reject non-finite target values., Enforce the sole primary horizon and its exact future-bar count., RealizedVarianceTarget, test_forecast_origin_and_target_require_pit_cutoff_and_thirty_closes(), test_target_rejects_invalid_primary_horizon()

### Community 102 - "Community 102"
Cohesion: 0.50
Nodes (3): Authenticated provider audit v1 summary, Explicit limitations, Gate status

### Community 103 - "Community 103"
Cohesion: 0.50
Nodes (3): Authenticated provider audit v1 summary, Explicit limitations, Gate status

### Community 104 - "Community 104"
Cohesion: 0.15
Nodes (13): _event(), _raw_bars(), test_pilot_builds_all_assets_origins_targets_and_trace(), test_pilot_fails_if_one_candidate_is_absent(), Keep optional event timestamps timezone-aware when supplied., Require aware timestamps for observed and available option state., Require provider precision to remain timezone-aware., Require an aware timestamp while preserving sub-second precision. (+5 more)

### Community 107 - "Any"
Cohesion: 0.67
Nodes (3): maximum, minimum, completeness_ratio

### Community 108 - "Client"
Cohesion: 0.67
Nodes (3): pattern, type, endpoint_fingerprint

### Community 109 - "Community 109"
Cohesion: 0.50
Nodes (3): graphify, Provider HTTP calls (FMP / Unusual Whales / Massive), Study window rule (binding)

### Community 113 - "Community 113"
Cohesion: 0.10
Nodes (19): Acceptance outputs, Authenticated v1k refresh — 2026-07-21 (superseded by v1l), Authenticated v1l refresh — 2026-07-21, Authenticated v1m refresh — 2026-07-21, Authenticated v1n refresh — 2026-07-21, Authenticated v1p refresh — 2026-07-21, Authenticated v1q refresh — 2026-07-21, Authenticated v1r refresh — 2026-07-21 (+11 more)

### Community 116 - "test_provider_contracts.py"
Cohesion: 0.25
Nodes (7): Content Quality, Feature Readiness, Notes, Planned tests before implementation, Recovery iteration gates, Requirement Completeness, Specification Quality Checklist: Point-in-Time Options Activity for RV30 Forecasting

### Community 119 - "datetime"
Cohesion: 0.12
Nodes (16): Exception, LicensingError, MDS650Error, Typed fail-closed errors used by the research pipeline., Raised when one or more provider credentials are absent., Raised when a configuration would permit an external mutation., Raised when a response cannot be used under verified license terms., Base class for expected pipeline failures. (+8 more)

### Community 120 - "Community 120"
Cohesion: 0.29
Nodes (6): Boundary, Evaluation boundary, Evidence flow, MDS650 pipeline architecture, Provider responsibilities, Storage and reproducibility

### Community 121 - "normalize_underlying_bars"
Cohesion: 0.33
Nodes (5): Contract checks for the observed-schema data dictionary., The public dictionary must expose all six requested components., Colab must call the local package rather than duplicate production logic., test_architecture_keeps_colab_as_orchestration_only(), test_dictionary_covers_six_observed_components_and_pit_rules()

### Community 124 - "Community 124"
Cohesion: 0.17
Nodes (11): Actualización de evidencia autenticada v1m — 2026-07-21, Actualización de evidencia autenticada v1n — 2026-07-21, Actualización de evidencia autenticada v1p — 2026-07-21, Actualización de evidencia autenticada v1q — 2026-07-21, Actualización de evidencia autenticada v1r — 2026-07-21, Cierre de fixtures contractuales — 2026-07-21, Gates que permanecen abiertos, Reproducibilidad (+3 more)

### Community 130 - "Auditoría de completitud de la iteración de recuperación"
Cohesion: 0.25
Nodes (7): Auditoría de completitud de la iteración de recuperación, Decisiones requeridas antes de la siguiente fase, Estados, Matriz requisito → evidencia, Puertas de detención vigentes, Refresh de completitud contra el estado canónico — 2026-07-21, Verificación ejecutada

### Community 131 - "Authenticated provider audit v1 summary"
Cohesion: 0.50
Nodes (3): Authenticated provider audit v1 summary, Explicit limitations, Gate status

### Community 133 - "Runtime compatibility matrix — recovery evidence"
Cohesion: 0.29
Nodes (6): Approved runtime, Decision rule, Evidence collected 2026-07-20, Reproduction commands, Required package set, Runtime compatibility matrix — recovery evidence

### Community 134 - "Authenticated provider audit v1 summary"
Cohesion: 0.50
Nodes (3): Authenticated provider audit v1 summary, Explicit limitations, Gate status

### Community 136 - "Authenticated provider audit v1 summary"
Cohesion: 0.50
Nodes (3): Authenticated provider audit v1 summary, Explicit limitations, Gate status

### Community 137 - "Authenticated provider audit v1 summary"
Cohesion: 0.50
Nodes (3): Authenticated provider audit v1 summary, Explicit limitations, Gate status

### Community 138 - "Authenticated provider audit v1 summary"
Cohesion: 0.50
Nodes (3): Authenticated provider audit v1 summary, Explicit limitations, Gate status

### Community 139 - "test_authenticated_audit_manifest.py"
Cohesion: 0.11
Nodes (17): _document(), Contract checks for the bounded authenticated audit artifact., Calendar diagnostics must expose session gaps separately from minute gaps., Latest directed Massive evidence must expose contract-level fields and paging., The newest bounded refresh is valid evidence but cannot authorize backfill., Correct provider parameters leave only the unresolved research gates., FMP's local timezone is documented; start-versus-close remains unresolved., The refreshed audit must derive states and clear provider/common-history failure (+9 more)

### Community 140 - "freeze_assets"
Cohesion: 0.10
Nodes (28): AssetQuality, ForecastOrigin, AssetQuality, freeze_assets(), FrozenAssetSet, Quality-only asset freezing and common-history calculation., Audited coverage and data-quality measurements for one candidate asset., Reject impossible rates and inverted history ranges. (+20 more)

### Community 141 - "MDS650 observed data dictionary"
Cohesion: 0.40
Nodes (4): Canonical normalized fields, MDS650 observed data dictionary, Provenance and keys, Six component groups

### Community 142 - "providerResult"
Cohesion: 0.50
Nodes (4): $defs, providerResult, additionalProperties, type

### Community 143 - ".validate_cutoff"
Cohesion: 0.33
Nodes (5): Contract checks for the explicitly non-historical fixture preview., The preview must never masquerade as provider backfill evidence., The preview preserves natural event labels and the 31-price RV30 contract., test_fixture_preview_has_eight_assets_and_exact_rv30_shape(), test_fixture_preview_is_not_authorized_or_historical()

### Community 144 - ".validate_origin_asset"
Cohesion: 0.50
Nodes (3): Authenticated provider audit v1 summary, Explicit limitations, Gate status

### Community 145 - "Fixture-only dataset preview"
Cohesion: 0.50
Nodes (3): Fixture-only dataset preview, Gate status, Table row counts

## Knowledge Gaps
- **650 isolated node(s):** `Estados`, `Matriz requisito → evidencia`, `Puertas de detención vigentes`, `Decisiones requeridas antes de la siguiente fase`, `Verificación ejecutada` (+645 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **17 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `properties` connect `Community 11` to `Community 97`, `Community 98`, `Community 99`, `Community 4`, `Community 40`, `Community 41`, `Any`, `Client`, `Community 13`, `providerResult`, `Community 87`, `Community 24`, `Community 26`, `Community 61`, `Community 95`?**
  _High betweenness centrality (0.055) - this node is a cross-community bridge._
- **Why does `asset` connect `Community 4` to `Community 11`, `Community 19`?**
  _High betweenness centrality (0.023) - this node is a cross-community bridge._
- **Why does `enum` connect `Community 19` to `Community 4`?**
  _High betweenness centrality (0.022) - this node is a cross-community bridge._
- **Are the 21 inferred relationships involving `QualityGateError` (e.g. with `AssetQuality` and `BaseTransport`) actually correct?**
  _`QualityGateError` has 21 INFERRED edges - model-reasoned connections that need verification._
- **Are the 18 inferred relationships involving `SchemaDriftError` (e.g. with `BaseTransport` and `Headers`) actually correct?**
  _`SchemaDriftError` has 18 INFERRED edges - model-reasoned connections that need verification._
- **What connects `Estados`, `Matriz requisito → evidencia`, `Puertas de detención vigentes` to the rest of the system?**
  _859 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Community 0` be split into smaller, more focused modules?**
  _Cohesion score 0.09747899159663866 - nodes in this community are weakly interconnected._