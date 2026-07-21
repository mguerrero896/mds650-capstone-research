# Feature Specification: Point-in-Time Options Activity for RV30 Forecasting

**Feature Branch**: `001-pit-options-rv30` (Spec Kit feature identifier; recovery branch: `001-pit-options-rv30-recovery`)

**Created**: 2026-07-20

**Status**: Recovery specification revision; implementation blocked pending coherence gates

**Input**: User description: "Evaluate whether unusual options activity provides incremental out-of-sample information for forecasting the next 30 minutes of realized variance, using authenticated provider audits, a point-in-time pilot, and a Spec-Driven Development workflow."

## User Scenarios & Testing *(mandatory)*

### Recovery iteration boundary

This iteration is specification-only. It may inspect and classify the existing
`artifacts/api_audit/exploratory_v0/provider_audit_manifest.json`, write contracts,
schemas, acceptance criteria and planned tests, and rerun Spec Kit coherence gates. It
MUST NOT implement provider connectors, make provider requests, backfill, normalize data,
build a pilot dataset, fit models, or create a productive notebook. Existing source files
are historical baseline evidence and are not authorization to execute those activities.

### Clarifications

- The primary target is only RV30; no return, direction or alternate horizon is a primary
  target.
- All eight candidates are audited together; four to six may be frozen only by coverage,
  quality and common-overlap criteria.
- The preserved v0 manifest is exploratory evidence, not an accepted v1 audit.
- Literature verification is Phase 3B and runs in parallel with Phase 3A provider audit;
  all ten studies must be verified before freezing variables, benchmarks, models, metrics,
  validation or methodological claims.

### User Story 1 - Establish authenticated data feasibility (Priority: P1)

As the research auditor, I need to test the three licensed providers with bounded,
authenticated requests so that the usable history, schemas, timestamps, permissions and
quality gates are known before any historical backfill.

**Why this priority**: Without verified provider coverage and point-in-time semantics, a
pilot or model comparison could be irreproducible or invalid.

**Independent Test**: Run the bounded audit for all eight candidates, inspect the sanitized
manifest and human report, and confirm that every acceptance threshold is either passed or
produces an explicit stop condition.

**Acceptance Scenarios**:

1. **Given** the three credentials are present in the approved runtime secret store, **When**
   the audit runs, **Then** it records only sanitized request metadata, HTTP status, schema,
   pagination, rate-limit observations, timestamp semantics and quality results.
2. **Given** a provider returns an authentication error, schema drift, incomplete pagination,
   or an unresolvable material timestamp, **When** the audit evaluates the response, **Then**
   it fails closed and records the exact blocker without fabricating data.
3. **Given** all eight candidates have been evaluated, **When** coverage and integrity are
   compared, **Then** four to six assets are frozen using only predeclared quality and
   coverage criteria, never predictive performance.

### User Story 2 - Build a point-in-time pilot (Priority: P1)

As the data researcher, I need a small pilot with event and no-event forecast origins so
that joins, timezones, deduplication, missingness and the 30-minute target can be audited at
row level before a full backfill.

**Why this priority**: The pilot is the smallest independent proof that the research data
model preserves the information available at each forecast origin.

**Independent Test**: Reconstruct the pilot from immutable raw responses and verify the
profile report, row-trace sample, duplicate keys, timezone conversions, event/no-event
coverage and deterministic target values without using future predictors. The pilot is
not authorized in this recovery iteration.

**Acceptance Scenarios**:

1. **Given** a bounded historical window containing events and quiet periods, **When** the
   pilot is assembled, **Then** it contains all eight candidates, five-minute origins with
   and without events, UTC plus `America/New_York` timestamps, and documented source keys.
2. **Given** a forecast origin at time `t`, **When** the target is calculated, **Then** it
   uses the fully observed origin close and the next thirty consecutive one-minute closes,
   yielding exactly thirty one-minute log returns.
3. **Given** a field is contemporaneous or future relative to `t`, **When** predictors are
   validated, **Then** the field is rejected unless its point-in-time availability is proven.
4. **Given** expected bars, events or contract identifiers are missing, **When** the pilot
   is profiled, **Then** the missingness is reported and the run fails if a configured gate is
   breached.

### User Story 3 - Verify the scientific evidence base (Priority: P2)

As the research author, I need a verified matrix of ten recent empirical studies and a
traceable evidence register so that model choices, benchmarks and limitations are supported
by real sources rather than generic claims.

**Why this priority**: The literature determines which comparisons are defensible and
prevents the project from treating unverified provider labels as scientific evidence.

**Independent Test**: Inspect the matrix and source register and confirm that each study has
an APA 7 reference, DOI or stable URL, publication status, data/sample, frequency, question,
predictors, target, exact models and benchmark, temporal validation, leakage controls,
metrics, result, limitation and project implication.

**Acceptance Scenarios**:

1. **Given** a study is included in the matrix, **When** its identifier is resolved, **Then**
   the cited source and the recorded claims agree, with no invented result or citation.
2. **Given** a study concerns ordinary option information, option flow, intraday realized
   volatility or ML benchmark comparison, **When** it is classified, **Then** it appears in
   exactly the appropriate thematic category and its target is distinguished from RV30.
3. **Given** a source cannot be independently verified, **When** the matrix is reviewed,
   **Then** it is marked unverified and cannot be used as support for a confirmed conclusion.

### User Story 4 - Compare nested benchmarks and publish reproducible evidence (Priority: P2)

As the research evaluator, I need a common out-of-sample comparison of B0, B1 and B2 plus
an auditable notebook and manifest so that incremental information from unusual activity is
tested without leakage, silent sample changes or live-trading claims.

**Why this priority**: This is the scientific decision the capstone is meant to answer, but
it depends on the feasibility and pilot gates from Stories 1 and 2.

**Independent Test**: Re-run the local pipeline and the Colab orchestration on the frozen
configuration, inspect the validation status and manifest, and reproduce the primary B2 vs
B1 QLIKE comparison on the untouched final period.

**Acceptance Scenarios**:

1. **Given** B1 ordinary option state passes its point-in-time gate, **When** B0, B1 and B2
   are evaluated on common expanding walk-forward splits, **Then** B2 is compared directly
   with B1 using QLIKE as the primary loss.
2. **Given** B1 is infeasible under authenticated coverage, **When** the gate is evaluated,
   **Then** the project stops the requested B2-vs-B1 claim and records B2-vs-B0 only as a
   declared fallback comparison.
3. **Given** model results are produced, **When** the final report is generated, **Then** it
   includes daily paired uncertainty, effect size, asset/regime consistency, purging and
   embargo details, and explicitly avoids causal, directional-intent or profitability claims.
4. **Given** the notebook is opened in Colab, **When** it runs, **Then** it loads secrets from
   Colab Secrets, imports the local modular package, shows frozen configuration and schemas,
   renders quality controls and a preview, reports validation status, and exports sanitized
   run evidence.

### Edge Cases

- What happens when the requested source folder is absent or incomplete? The run records a
  provenance blocker and cannot present that source as read or verified.
- What happens when a provider returns HTTP 401/403, 429, 5xx, an empty page, or a changed
  schema? The exact response class is recorded; retries are bounded and schema/permission
  failures stop the affected gate.
- What happens when pagination repeats a cursor or ends unexpectedly? The audit fails closed
  and does not treat the partial response as complete.
- What happens when a market timestamp is naive, duplicated, outside regular hours, or falls
  across daylight-saving changes? The row is rejected or quarantined until its semantics are
  resolved.
- What happens when a contract has no quote in an event window? It remains an explicit
  illiquid/no-record observation; it is never replaced with zero bid, zero ask or a proxy.
- What happens when event volume exceeds prior open interest? The field is reported as an
  association only; it is not labeled confirmed opening activity.
- What happens when a flow is near the ask or marked as a sweep, floor or multileg? It is
  retained as a feature candidate but never translated into certain bullish/bearish intent.
- What happens when fewer than four assets pass quality or the common window is too short?
  The project stops before modeling and records the exact acceptance failure.
- What happens when future target windows overlap training rows? The split applies a purge
  and an embargo at least as long as the thirty-minute target horizon.
- What happens when the pilot contains too few events? The historical window is widened
  without changing assets based on preliminary predictive performance.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST audit SPY, QQQ, AAPL, MSFT, NVDA, TSLA, AMZN and META together
  before asset selection.
- **FR-002**: The system MUST verify six data components separately: one-minute underlying
  OHLCV, structured corporate events, unusual-option events, point-in-time ordinary option
  state, contract-level option trades, and consolidated bid/ask quotes.
- **FR-003**: The FMP audit MUST test one-minute OHLCV and structured earnings for every
  candidate and record endpoint, HTTP status, response schema, timestamp format/timezone,
  rows by asset/date, earliest/latest complete history, regular-session completeness,
  duplicates, nulls, rate-limit behavior and safe extraction strategy.
- **FR-004**: The Unusual Whales audit MUST test historical flow events, pagination, contract
  identifiers, event timestamps, premium, size, volume, open interest, volume/OI, call/put,
  strike, expiry, moneyness, sweep, floor, multileg, execution-side proxies, IV change when
  available, and the historical point-in-time feasibility of IV, skew and term structure.
- **FR-005**: The Massive audit MUST use contracts returned by the event source to test
  reference data, historical trades, historical quotes, timestamp precision, bid/ask,
  condition codes, pagination and empty/illiquid windows; it MUST NOT download all
  historical OPRA quotes.
- **FR-006**: Every audit MUST preserve raw responses immutably outside distributable reports
  and produce a sanitized machine-readable manifest plus a human-readable report. The
  existing v0 manifest MUST remain byte-preserved at
  `artifacts/api_audit/exploratory_v0/provider_audit_manifest.json` and MUST be labelled
  exploratory, not accepted as v1.
- **FR-007**: Every material market timestamp MUST be normalized to UTC and
  `America/New_York`, with the original representation preserved and a documented
  `available_at` or equivalent point-in-time interpretation.
- **FR-007A**: Before implementation, the design MUST resolve whether FMP's bar timestamp
  denotes bar start or bar close, identify the exact close used as origin `C(i,t)`, define
  the last valid origin in a regular or early-close session, and define fail-closed handling
  for missing closes, halts, early closes and non-session minutes. Missing prices MUST NOT
  be silently interpolated.
- **FR-008**: Asset freezing MUST select four to six instruments only from configurable
  coverage, timestamp integrity, regular-session completeness, event frequency, contract
  resolution and provider overlap criteria; predictive metrics MUST be excluded from the
  selection rule.
- **FR-009**: Earnings publication controls MUST be included in every benchmark where the
  timestamp is usable point-in-time; general news MUST remain out of scope until its own
  timestamp, coverage and reproducibility gate passes.
- **FR-010**: The pilot MUST cover all eight candidates, contain event and no-event
  five-minute origins, and include a row-level trace from normalized values to source
  response identifiers.
- **FR-011**: The target MUST use the fully observed close at forecast origin t and the next thirty consecutive one-minute closes, producing exactly thirty one-minute log returns.
  For asset `i`, `r(i,t+j) = ln[C(i,t+j) / C(i,t+j-1)]`, for `j = 1,...,30`, and
  `RV(i,t:t+30) = Σ[j=1 to 30] {r(i,t+j)}²`. Any missing one of the 31 required closes,
  an unresolved bar start/close convention, an early-close boundary or an unidentified
  halt makes the target invalid; no price interpolation is permitted. No future close,
  future event revision or future option state may enter predictors.
- **FR-012**: Deduplication keys MUST be documented for each component and duplicate/failure
  counts MUST be reported rather than silently discarded.
- **FR-013**: B0 MUST contain underlying and market controls; B1 MUST add only authenticated
  point-in-time IV, skew and term structure; B2 MUST add unusual-activity variables.
- **FR-014**: The primary scientific comparison MUST be B2 versus B1; if B1 is infeasible,
  the run MUST stop that claim and explicitly declare the fallback comparison.
- **FR-015**: The evaluation MUST use common chronological expanding splits, a final intact
  test period, purging and embargo at least thirty minutes, QLIKE as primary loss and daily
  paired uncertainty with asset/regime breakdowns.
- **FR-016**: The project MUST apply a predeclared multiple-testing and effect-size policy
  before inspecting final test results.
- **FR-017**: The literature matrix MUST contain ten empirical studies published or
  materially updated between January 2023 and July 2026 with all fields required by the
  research brief and verified DOI or stable URL.
- **FR-018**: The local modular package MUST be the source of truth; the Colab notebook MUST
  orchestrate imports and presentation without duplicating production logic or hiding state
  in giant cells.
- **FR-019**: The notebook MUST load secrets from Colab Secrets, show frozen configuration,
  schemas, quality controls, data preview, validation/test status, execution manifest and a
  sanitized report.
- **FR-020**: Public functions in the implementation MUST expose type information, NumPy-style
  docstrings, assumptions, exceptions, return schema and a short example when non-trivial.
- **FR-021**: Tests MUST be written before production backfill and MUST include unit,
  sanitized contract, bounded live-query, pagination, timezone/DST, leakage, duplicate and
  missingness, deterministic-target and pilot end-to-end classes.
- **FR-022**: The project MUST fail explicitly when expected data, permissions, licensing,
  timestamps or schemas are not available; it MUST NOT fabricate, substitute or silently
  change assets.
- **FR-023**: No provider request may occur until each credential variable is confirmed present
  without exposing its value, and no provider credential may be printed or committed.
- **FR-024**: The pipeline MUST remain research-only: no broker orders, capital deployment,
  email, external publication, remote repository mutation or production deployment.
- **FR-025**: The provider manifest MUST use schema version 1.1 with explicit enums for
  applicability, point-in-time status and separate authentication, endpoint, schema and
  entitlement diagnostics. Each provider result MUST carry the unique key
  `(run_id, provider, component, asset, request_start, request_end, endpoint_fingerprint)`;
  repeated keys MUST fail validation.
- **FR-026**: The audit MUST classify the preserved v0 duplicate `underlying_1min_depth_probe`
  entries for all eight assets as an idempotency defect, retaining the evidence and never
  deleting or collapsing it silently.
- **FR-027**: Unusual Whales field aliases MUST map `ivStart` to `iv_start` and `ivEnd` to
  `iv_end`; `event_iv_fields_present` MUST be reported separately from
  `ordinary_option_state_pit_verified`. The latter cannot be inferred from alert fields.
  Only raw fields actually present may be described; `executed_at` MUST NOT be mentioned
  unless observed in the response. `created_at`, `start_time` and `end_time` require
  separate raw type, unit, semantics, timezone, conversion, origin relationship and
  possible-post-availability documentation.
- **FR-028**: Structured earnings MUST validate `returned_symbol == requested_symbol` and
  classify each response as `applicable`, `not_applicable`, `unsupported` or
  `invalid_response`; SPY and QQQ MUST NOT inherit a corporate earnings contract for a
  company.
- **FR-029**: The primary evaluation MUST be predeclared as
  `Delta_Q = QLIKE(B1) - QLIKE(B2)`, with day-clustered paired bootstrap keeping all
  observed assets on each trading day together. Primary, secondary and robustness analyses,
  Holm or Benjamini-Hochberg use, regimes and the minimum detectable effect protocol MUST
  be frozen before final-test inspection. The minimum detectable effect MUST be estimated
  from simulation, bootstrap, pilot or training data only.

### Pre-registered evaluation strata

Before any final-test result is inspected, the plan MUST define volatility regimes,
earnings versus no-earnings origins, first versus last session segments, asset versus ETF,
and normal versus stressed market conditions. These are secondary or robustness analyses;
none may replace the single primary `Delta_Q` comparison. Training-only subsampling or
weighting, if ever used for a continuous target, must be documented while validation and
final testing preserve the natural event prevalence:

> Construct event and no-event forecast origins while preserving their natural prevalence.
> Any training-only subsampling or weighting must be explicitly documented, and validation
> and final testing must preserve the natural distribution.

### Key Entities *(include if feature involves data)*

- **ProviderAuditRun**: bounded authenticated audit with provider, request metadata,
  sanitized status, schema fingerprint, rate-limit observations and gate outcomes.
- **SourceResponse**: immutable raw response reference with hash, retrieval time, endpoint
  label, license state and redacted metadata.
- **UnderlyingBar**: one-minute OHLCV observation with asset, exchange/session date, UTC and
  New York timestamps, values and quality flags.
- **CorporateEvent**: structured earnings/publication event with event time, availability
  time, asset and provenance.
- **UnusualOptionEvent**: provider event label plus contract, event timestamp, premium,
  size, volume, OI, call/put, strike, expiry, moneyness and execution proxies.
- **OptionStateSnapshot**: ordinary IV, skew and term-structure values with availability
  time and interpolation/coverage flags.
- **OptionTrade**: contract-level historical trade with timestamp, price, size and condition.
- **OptionQuote**: consolidated bid/ask observation with timestamp, bid, ask and conditions;
  absence is distinct from zero.
- **ForecastOrigin**: asset and five-minute origin with the predictor availability cutoff,
  event/no-event indicator and source trace.
- **RealizedVarianceTarget**: thirty-minute future target, its one-minute close inputs,
  computation version and validity flags.
- **BenchmarkRun**: frozen B0/B1/B2 configuration, split dates, purge/embargo, model,
  metrics, uncertainty and asset/regime coverage.
- **ExecutionManifest**: sanitized run configuration, package versions, hashes, tests,
  evidence paths, decisions and stop-condition status.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: The audit produces a machine-readable and human-readable evidence package for
  all eight candidates, with zero secret values in reports, logs or committed files.
- **SC-002**: Every accepted underlying asset-day meets at least 95% regular-session
  one-minute completeness, zero critical duplicate keys and zero critical null prices; the
  exact threshold is recorded in the frozen configuration.
- **SC-003**: The audit records a complete pagination trace and exact blocker string for every
  provider/component failure; no partial response is labeled complete.
- **SC-004**: The pilot reconstructs at least one event and one no-event origin for every
  candidate and passes deterministic recomputation of the thirty-minute target on a traced
  row sample.
- **SC-005**: At least four and at most six assets pass the predeclared quality/coverage gate;
  if fewer pass, modeling does not start.
- **SC-006**: Every predictor in the pilot has `available_at` no later than its forecast
  origin, or is excluded with a recorded reason.
- **SC-007**: The literature matrix contains ten independently verifiable studies in the
  specified date range with all required fields populated or explicitly marked unavailable.
- **SC-008**: B0, B1 and B2 use identical eligible origins and chronological splits; the final
  test period remains untouched until the evaluation is frozen.
- **SC-009**: Any claim of incremental value requires lower B2 QLIKE than B1 on the final
  period, a 95% daily paired uncertainty interval for `QLIKE(B1)-QLIKE(B2)` above zero, a
  predeclared minimum detectable effect, and consistency across the majority of frozen
  assets and declared regimes.
- **SC-010**: A fresh local run and the Colab orchestration produce matching configuration,
  schema, quality and validation-manifest results without notebook-only state.
- **SC-011**: All mandatory test classes run before any production backfill; a schema or
  point-in-time failure causes a non-success status rather than a silent fallback.
- **SC-012**: The final report distinguishes verified evidence, source assertions, inference,
  assumptions and unresolved blockers, and makes no live-profitability or causal claim.
- **SC-013**: A clean-install compatibility matrix demonstrates the approved runtime against
  Colab, Windows, Polars, PyArrow, DuckDB, LightGBM, scikit-learn, SHAP, Optuna, Pydantic,
  Ruff, Mypy and Pytest before runtime/dependency mutation is approved; version choice MUST
  be compatibility-first, not novelty-first.

## Assumptions

- The eight named U.S. assets are the fixed candidate universe; no asset is added or removed
  because of preliminary predictive performance.
- Provider credentials will be rotated after their exposure in the chat and then loaded from
  an approved runtime secret store. User-scope environment presence is not treated as proof
  that a credential is safe to use.
- The requested Downloads source folder is currently unavailable. Existing MDS650 proposal
  documents and the course ZIP are usable as provisional design sources, but no claim will
  cite the missing folder as read until its path is supplied and its contents are inspected.
- A forecast origin is the end of a five-minute interval during regular market hours. Exact
  calendar handling, early closes and daylight-saving rules will be frozen in the plan.
- The maximum common provider history, not a fixed calendar period, determines the eligible
  modeling window, subject to configurable minimum overlap and quality gates.
- B1 is conditional: ordinary option state enters the comparison only when authenticated
  point-in-time history and coverage are demonstrated independently of event selection.
- Massive contract trades and quotes are a directed validation sample and are not a proxy for
  a complete historical OPRA market.
- HAR and QLIKE may use foundational references, but all project-specific empirical claims
  require recent verified studies.
- The modular local package is authoritative and Colab is limited to orchestration,
  presentation and sanitized export.
