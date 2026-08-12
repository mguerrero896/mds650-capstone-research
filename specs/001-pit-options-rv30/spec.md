# Feature Specification: Point-in-Time Options Activity for RV30 Forecasting

**Feature Branch**: `001-pit-options-rv30` (Spec Kit feature identifier; recovery branch: `001-pit-options-rv30-recovery`)

**Created**: 2026-07-20

**Status**: Phase 5 design approved; PIT v2.1 remediation and the source-bound corrected
development-release gate remain required before any new development evaluation. Existing sealed
results and the prospective holdout remain closed.

**Input**: User description: "Evaluate whether unusual options activity provides incremental out-of-sample information for forecasting the next 30 minutes of realized variance, using authenticated provider audits, a point-in-time pilot, and a Spec-Driven Development workflow."

## Clarifications

### Session 2026-07-21

- Q: Should the primary panel require no-operation origins? → A: No; retain every valid origin and preserve natural prevalence.
- Q: Does any eligible option trade define unusual activity? → A: No; it defines only `option_activity_present`, an operational availability proxy.
- Q: When may `unusual_event` be calculated? → A: Only after at least 15 prior sessions support trailing, leakage-safe calibration.
- Q: How must Massive quotes be selected? → A: Last SIP quote with `sip_timestamp <= origin`, using nanosecond `timestamp.lte` and descending order.
- Q: What is authorized now? → A: Pilot V2 correction only; backfill, models, QLIKE, final test, asset freeze and Word remain blocked.

### Session 2026-07-22

- Q: What additional work is authorized after the Phase 3E repair? → A: Exactly the twenty
  pre-Pilot-V2 sessions from 2026-06-11 through 2026-07-10 for leakage-safe B2 calibration,
  B1Q stability, quality-only role evidence and literature closure. Larger backfill, models,
  tuning, QLIKE, final testing, definitive asset freeze, Word/PowerPoint edits, publication and
  email remain blocked.
- Q: What status may the Pilot V2 binary label receive after this history is fit? → A:
  `CALIBRATED_SECONDARY_EXPLORATORY`; continuous B2 features remain primary and the label is not
  used for predictive selection.

### Session 2026-07-29

- Q: What sample design is approved? → A: Ninety XNYS sessions: eighty development sessions
  and ten prospective holdout sessions read analytically only once after method freeze.
- Q: What model and inference contract is approved? → A: Gamma GLM is confirmatory,
  LightGBM is a fixed nonlinear robustness challenger, QLIKE is primary, uncertainty uses
  paired whole-day cluster bootstrap, and Holm covers the two confirmatory comparisons.
- Q: What information sets are approved? → A: Nested B0, B1a and B2, with the compact
  target-blind nine-feature B2 definition frozen before RV30 or QLIKE is consulted.
- Q: Which FMP timing convention governs the primary study? → A:
  `available_at = timestamp_raw + 1 minute` is the explicit conservative research
  assumption; `+2 minutes` is a prespecified sensitivity, not provider-confirmed semantics.
- Q: Has the written design been approved? → A: Yes; negative, null and positive registered
  results must all be retained and reported without optimizing for a favorable sign.

### Session 2026-08-12

- Q: Does confirmed historical availability of FMP and Unusual Whales establish point-in-time
  semantics? → A: No. FMP passed 90/90 exact-session historical probes and Unusual Whales
  passed metadata probes for 90/90 historical Full Tape files; these are availability findings.
  FMP `+1`/`+2` minutes and Unusual Whales `created_at` with the 60-second cutoff remain the
  registered conservative study rule and operational-availability proxy, respectively.
- Q: May a corrected B2 availability mask reopen sealed legacy results? → A: No.
  `SAFE_TO_RECONCILE_EXISTING_RESULTS=NO` remains literal for those results. A new,
  source-bound development-only release is the only permitted correction path.
- Q: What is the scope of a corrected development release? → A: It joins the immutable
  target-blind controls to a predictor source constructed specifically for the predeclared 80
  development sessions, retains all B2 exclusions as missing with a reason, and does not read,
  acquire, or evaluate the ten-session prospective holdout.
- Q: Can the existing 180-session v2.4 predictor panel be relabelled as the frozen
  80-session source? → A: No. It is a target-blind control/provenance artifact only. A new
  exact-window source build must prove date equality and source coverage. Any B1Q row with a
  same-session or missing exact pre-origin rate and dividend provenance remains missing with a
  recorded blocker; it is never filled from a later, stale, same-session, or carried-forward
  input.

## User Scenarios & Testing *(mandatory)*

### Recovery iteration boundary

This Pilot V2 correction may reuse the five already downloaded Full Tape ZIPs and their
filtered Parquet derivatives without re-downloading matching hashes. It may correct B2
feature construction, run bounded per-origin B1 probes, correct FMP/common-history probes,
and emit Pilot V2 evidence. It MUST NOT run full historical backfill, fit or tune models,
run QLIKE/final evaluation, freeze assets definitively, generate final Word documents, or
download an additional 20-session extension. Pilot V1 is invalid for acceptance, while its
raw data and valid RV30 targets remain reusable.

### Clarifications

- The primary target is only RV30; no return, direction or alternate horizon is a primary
  target.
- All eight candidates are audited together; four to six may be frozen only by coverage,
  quality and common-overlap criteria.
- The preserved v0 manifest is exploratory evidence, not an accepted v1 audit.
- Pilot V1 is `INVALID_FOR_ACCEPTANCE`; its raw data is `VALID_AND_REUSABLE`, its RV30
  target is `VALID`, and Pilot V2 correction is authorized.
- `option_activity_present` means at least one eligible option trade under the operational
  availability proxy; it does not mean unusual activity. `unusual_event` is secondary and
  remains `NOT_CALIBRATED` before trailing history is available. After the authorized Phase 3F
  history is fit, the Pilot V2 application may emit
  `CALIBRATED_SECONDARY_EXPLORATORY`; it never becomes the primary continuous B2 design.
- The primary panel retains every valid five-minute origin and preserves natural prevalence;
  the pilot need not contain an origin without any option operation.
- Literature verification is Phase 3B and runs in parallel with Phase 3A provider audit;
  all ten studies must be verified before freezing variables, benchmarks, models, metrics,
  validation or methodological claims.

## B1 Feasibility and Common-History Closure

This controlled phase accepts Pilot V2 for data engineering only. It may complete B1
feasibility on the existing 2,840 origins, verify common-history evidence for all eight
candidates, and finish the ten-study literature matrix. It MUST NOT download the proposed
twenty-session extension, run a full backfill, train or tune models, run QLIKE/final testing,
freeze assets definitively, modify Word deliverables, publish externally or send email.

The frozen input state is: `PILOT_V2_RV30=ACCEPTED_FOR_DATA_ENGINEERING`,
`PILOT_V2_B2_CONTINUOUS_FEATURES=ACCEPTED_PROVISIONALLY`,
`B2_UNUSUAL_EVENT_LABEL=NOT_CALIBRATED`, `B1A_ATM_IV=INCOMPLETE`,
`B1B_SKEW=INCOMPLETE`, `B1C_TERM_STRUCTURE=INCOMPLETE`,
`COMMON_HISTORY_ALL_ASSETS=NOT_ESTABLISHED`, `LITERATURE_MATRIX=MUST_BE_COMPLETED`,
`BACKFILL=BLOCKED`, `MODELING=BLOCKED` and `FINAL_TEST=BLOCKED`.

## B1Q Integration Repair and Earnings Contract Closure

This controlled phase repairs the discrepancy between successful controlled
Massive traces and zero full-matrix coverage for SPY, QQQ, META and TSLA. It
freezes corporate events by instrument type: individual equities may use ex-ante
FMP `date` and BMO/AMC `time`, while ETFs have `earnings_applicable=false` and
no synthetic earnings events. Dividend and distribution inputs remain separate
point-in-time inputs for IV only.

The phase MUST use bucket-scoped historical contract queries, auditable cache
keys, row-level controlled-versus-pipeline reconciliation, a sequential
mutually-exclusive first-failure waterfall and an explicit `INVALID_DTE`
diagnosis. It MUST NOT download the twenty-session extension, train models, run
QLIKE, freeze assets or modify Word/PowerPoint deliverables.

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

As the data researcher, I need a small pilot containing every valid five-minute origin with
continuous option-activity features so that joins, timezones, deduplication, missingness and
the 30-minute target can be audited at row level before a full backfill.

**Why this priority**: The pilot is the smallest independent proof that the research data
model preserves the information available at each forecast origin.

**Independent Test**: Reconstruct the pilot from immutable raw responses and verify the
profile report, row-trace sample, duplicate keys, timezone conversions, continuous
option-activity coverage and deterministic target values without using future predictors.
The Pilot V2 correction is authorized, but downstream backfill and modeling remain blocked.

**Acceptance Scenarios**:

1. **Given** a bounded historical window, **When** the pilot is assembled, **Then** it
   contains all eight candidates and every valid five-minute origin with UTC plus
   `America/New_York` timestamps, documented source keys, and natural option-activity
   prevalence. It is not required to contain an origin without an operation.
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

As the research evaluator, I need a common out-of-sample comparison of B0, B1a and B2 plus
an auditable notebook and manifest so that incremental information from trade-derived activity is
tested without leakage, silent sample changes or live-trading claims.

**Why this priority**: This is the scientific decision the capstone is meant to answer, but
it depends on the feasibility and pilot gates from Stories 1 and 2.

**Independent Test**: Re-run the local pipeline and the Colab orchestration on the frozen
configuration, inspect the validation status and manifest, and reproduce the primary B2 vs
B1a QLIKE comparison on the one-time prospective holdout.

**Acceptance Scenarios**:

1. **Given** B1a ATM-IV state passes its point-in-time gate, **When** B0, B1a and B2
   are evaluated on common expanding walk-forward splits, **Then** B2 is compared directly
   with B1a using QLIKE as the primary loss.
2. **Given** B1a is infeasible under authenticated coverage, **When** the gate is evaluated,
   **Then** the project stops the requested B2-vs-B1a claim and returns
   `REVISE_RESEARCH_DESIGN`; it does not silently promote B2 versus B0.
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
- **FR-009**: Earnings MUST remain excluded from the primary B0/B1a/B2 comparison. Ex-ante
  BMO/AMC timing variables MAY appear only in predeclared diagnostic stability analysis after
  their point-in-time contract passes; actual EPS/revenue values are prohibited. General news
  remains out of scope until its own timestamp, coverage and reproducibility gate passes.
- **FR-010**: The primary panel MUST retain every valid five-minute origin for all eight
  candidates and include a row-level trace from normalized values to source response
  identifiers. It MUST preserve natural prevalence and MUST NOT require an origin without
  an option operation.
- **FR-011**: The target MUST use the fully observed close at forecast origin t and the next thirty consecutive one-minute closes, producing exactly thirty one-minute log returns.
  For asset `i`, `r(i,t+j) = ln[C(i,t+j) / C(i,t+j-1)]`, for `j = 1,...,30`, and
  `RV(i,t:t+30) = Σ[j=1 to 30] {r(i,t+j)}²`. Any missing one of the 31 required closes,
  an unresolved bar start/close convention, an early-close boundary or an unidentified
  halt makes the target invalid; no price interpolation is permitted. No future close,
  future event revision or future option state may enter predictors.
- **FR-012**: Deduplication keys MUST be documented for each component and duplicate/failure
  counts MUST be reported rather than silently discarded.
- **FR-013**: B0 MUST contain underlying and market controls; B1a MUST add only authenticated
  point-in-time ATM IV; B1b/B1c MAY add skew/term structure as robustness levels; B2 MUST add
  only the frozen trade-derived activity variables to B1a.
- **FR-014**: The primary scientific comparison MUST be B2 versus B1a; if B1a is infeasible,
  the run MUST stop that claim and return `REVISE_RESEARCH_DESIGN` rather than silently
  substituting B2 versus B0.
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
  `Delta_B2 = QLIKE(B1a) - QLIKE(B2)`, with
  `Delta_B1 = QLIKE(B0) - QLIKE(B1a)` as the key secondary confirmatory contrast and a
  day-clustered paired bootstrap keeping all observed assets and origins on each trading day
  together. Primary, secondary and robustness analyses, Holm over these two comparisons,
  regimes and the minimum detectable effect protocol MUST
  be frozen before final-test inspection. The minimum detectable effect MUST be estimated
  from simulation, bootstrap, pilot or training data only.

- **FR-030**: B2 MUST use continuous option-activity variables computed from eligible
  contract-level rows, not a trade-presence indicator. `option_activity_present` is an
  operational-availability proxy and MUST NOT be called unusual activity. Provider
  cumulative fields (`volume`, `ask_vol`, `bid_vol`, `mid_vol`, `no_side_vol`) are excluded
  until their point-in-time semantics are independently proven.
- **FR-031**: `unusual_event` MUST remain secondary. Before a trailing history of at least 15
  prior sessions (preferably 20 or more) supports asset- and time-of-day-specific percentile/MAD
  rules without future information, its status MUST be `NOT_CALIBRATED`. After the authorized
  Phase 3F history is fit and applied without leakage, the Pilot V2 application status MUST be
  `CALIBRATED_SECONDARY_EXPLORATORY`; the continuous B2 variables remain primary.
- **FR-032**: Massive B1 extraction MUST select the last quote with `sip_timestamp <= t`
  for each contract and origin using a nanosecond `timestamp.lte` query, descending order
  and limit one. A missing result MUST be classified by a bounded range retry rather than
  represented by a zero quote.
- **FR-033**: FMP OHLCV requests MUST filter locally to the requested local session and
  record provider-over-return dates. Earnings MUST use the symbol-specific endpoint that
  exposes `date`, `time` and BMO/AMC semantics when available; actual EPS/revenue values
  MUST NOT enter predictors.
- **FR-034**: Common-history V2 MUST resolve a historical Massive contract using `as_of`
  and date-relative expiry/strike before querying quotes; current contracts MUST NOT be
  reused for old months. Each month MUST record FMP, UW and Massive component passes.
- **FR-035**: Pilot V2 MUST write new artifacts under `artifacts/pilot_v2/` and preserve
  all V1 artifacts, including the invalid common-history probe and invalidated B2 outputs.
- **FR-036**: B1 feasibility MUST evaluate every one of the 2,840 valid origins using a
  cached contract-day Massive quote route (`B1Q`) and a diagnostically separate Full Tape
  route (`B1T`). Contract-day responses MUST be reused through checkpoints; one request per
  origin and contract is prohibited.
- **FR-037**: B1Q MUST resolve historical contracts with `as_of`, select short/medium/long
  DTE buckets (7–21, 30–60, 90–180 days) and target moneyness (0.95, 0.975, 1.00, 1.025,
  1.05), then perform a local as-of join selecting the last valid quote with
  `sip_timestamp <= forecast_origin`. Primary filters are bid > 0, ask > bid, quote age
  <= 60 seconds and relative spread <= 25%; 300 seconds/50% are sensitivity filters.
- **FR-038**: B1T MUST use only existing Full Tape rows with `created_at <= origin-60s`,
  valid NBBO, contract validity and expiry after the origin. It MUST be labeled a dependent
  fallback/sensitivity route and MUST NOT be treated as independent of B2.
- **FR-039**: Each B1Q and B1T origin MUST expose separate component availability and nested
  benchmark completeness. Components MUST be `atm_iv_available`, `skew_available` and
  `term_structure_available`; nested fields MUST be `b1a_complete = atm_iv_available`,
  `b1b_complete = atm_iv_available AND skew_available` and `b1c_complete = atm_iv_available
  AND skew_available AND term_structure_available`. Quote/contract counts, age/spread
  diagnostics, interpolation flags, IV success rate and missing reason remain required.
  Black–Scholes–Merton remains an explicitly documented approximation for American options.
- **FR-040**: B1 coverage MUST be reported by asset, date, session tercile, DTE, moneyness,
  route and threshold (50%, 60%, 70%, 80%). A twenty-session extension may be proposed only
  when B1a reaches global coverage >=70%, asset coverage >=50%, every session tercile >=40%,
  valid PIT and no close-only concentration; B1b/B1c may remain robustness levels.
- **FR-041**: Common-history closure MUST test SPY, QQQ, AAPL, MSFT, NVDA, TSLA, AMZN and META
  for January/July 2024, January/July 2025 and January/July 2026 using exact FMP sessions,
  observed UW file evidence and date-relative Massive contracts/quotes. Six monthly points
  MUST NOT be described as daily continuity; earliest/latest dates and common assets per date
  MUST be reported.
- **FR-042**: The literature matrix MUST contain ten independently verified studies with
  traceable DOI/stable URL, exact models, benchmark, temporal validation, leakage controls,
  metrics, result, limitation and project implication. Unverified or invented citations MUST
  be excluded from methodological claims.
- **FR-043**: The twenty-session calibration request MUST remain a proposal only. If accepted,
  it MUST use the twenty trading sessions immediately before 13 July 2026, exclude the five
  Pilot V2 sessions, preserve natural prevalence and remain training/calibration-only.

## B1 Forensic Validation and Asset-Coverage Decision

This repair gate follows the invalid nested-coverage evidence. It MUST archive the prior
result, prove nested monotonicity, diagnose B1Q failure stages, audit SPY/QQQ/META/TSLA and
decide whether a twenty-session request is admissible. It MUST NOT download those sessions,
run models, QLIKE, tuning, full backfill, final testing, definitive asset freezing or Word
changes.

- **FR-044**: The prior result MUST be preserved at
  `artifacts/b1_full_origin/invalid_nested_coverage_v1.json`; invalid evidence MUST NOT be
  deleted or overwritten.
- **FR-045**: Each origin and route MUST expose `atm_iv_available`, `skew_available`,
  `term_structure_available`, `b1a_complete`, `b1b_complete` and `b1c_complete` separately.
- **FR-046**: The pipeline MUST fail closed unless `b1c_complete` implies `b1b_complete`,
  `b1b_complete` implies `b1a_complete`, and coverage is monotone globally, by asset, date,
  session tercile and route (`B1Q` and `B1T`).
- **FR-047**: B1Q MUST emit a failure waterfall for the 17 required stages from forecast
  origins through nested B1c, with exact failure codes and totals reconciling to 2,840 origins.
- **FR-048**: Controlled diagnostics MUST cover AAPL, SPY, META and TSLA at opening, midday
  and closing origins, including spot, New York/UTC timestamps, as-of contract identity,
  quote timestamps, bid/ask, age, spread, rate, dividend assumption, IV result and failure code.
- **FR-049**: IV attempts MUST persist asset, origin, contract, call/put, spot, strike, DTE,
  pre-origin rate/dividend inputs, midpoint, age, spread, success, failure code and IV. q=0
  is permitted only when no pre-origin dividend is known and the assumption is recorded.
- **FR-050**: After controlled diagnostics pass, B1Q coverage MUST be recomputed for
  components and nested benchmarks globally, by asset/date/session tercile, ETF versus
  equity, DTE bucket and quote/spread sensitivity without predictive selection.
- **FR-051**: The twenty-session availability probe MUST inspect exact FMP sessions, UW file
  existence/size and one historical Massive ATM contract/quote per candidate session without
  downloading Full Tape ZIP contents; availability MUST NOT be called PIT proof.
- **FR-052**: Literature evidence MUST include full-text status, evidence location, page,
  section/table/figure, exact supported claim and verification notes; Crossref-only metadata
  MUST NOT be labeled full-text verification.
- **FR-053**: B1Q contract resolution MUST query each DTE bucket using the historical origin
  date and retain cache keys containing provider, asset, session date, expiry, strike, option
  type and contract.
- **FR-054**: Controlled and full-matrix observations MUST reconcile by asset/date/origin/
  contract and record the first divergent stage.
- **FR-055**: The primary failure waterfall MUST contain exactly one first-failure code per
  origin and preserve additional failures separately.
- **FR-056**: Earnings MUST be applicable only to individual equities; SPY and QQQ MUST receive
  no synthetic corporate earnings events.

## Phase 3F — Twenty-Session Historical Calibration and Method Freeze

This controlled phase is authorized only after the repaired Phase 3E gates. It downloads and
processes exactly the twenty pre-Pilot-V2 sessions 2026-06-11 through 2026-07-10, excluding
2026-07-13 through 2026-07-17. It calibrates continuous B2 activity and evaluates B1Q stability;
it MUST NOT run a full backfill, predictive models, tuning, QLIKE, final testing, definitive
asset freezing, Word/PowerPoint edits or external publication.

- **FR-057**: Before any provider request, the run MUST record available storage, require at
  least 90 GB free, verify write access and verify a per-session resumable checkpoint design.
  Secret checks MUST report presence only and all manifests MUST contain no secret values or
  personal paths.
- **FR-058**: The download set MUST contain exactly the twenty configured sessions and no Pilot
  V2 date. Each session MUST be streamed to an immutable ZIP, hashed with SHA-256, CRC-tested,
  schema-checked and given an independent manifest; a valid completed session MUST be reused by
  hash rather than downloaded again.
- **FR-059**: Legacy cache files without explicit keys MUST remain retained as
  `LEGACY_CACHE_READ_ONLY` and MUST NOT be read by Phase 3F. Active cache keys MUST include
  provider, asset, session date, expiry, strike, option type, contract, route and schema version;
  duplicate active keys or hash collisions MUST fail the run.
- **FR-060**: The twenty-session panel MUST retain every valid five-minute origin with UTC and
  America/New_York timestamps, conservative FMP availability, natural option-activity
  prevalence and no silent interpolation or balancing. RV30 MAY be recomputed only as a contract
  check; no predictive evaluation is permitted.
- **FR-061**: B2 features MUST use only eligible Full Tape rows satisfying
  `created_at <= forecast_origin - 60 seconds`; 15-second and zero-second cutoffs are
  sensitivities. Provider cumulative fields without PIT proof MUST be excluded, open interest
  MUST be treated as prior-session information, and `created_at` MUST remain an
  `operational_availability_proxy`, not publication time.
- **FR-062**: Primary B2 normalization MUST be by asset and 30-minute time band using only the
  twenty sessions as historical information. It MUST use median/MAD, IQR and asset-level
  fallbacks with explicit fallback labels, compute robust z-scores for five log-transformed core
  features, define the score as the median of the three largest positive z-scores, and set the
  secondary `unusual_event` threshold at the historical 95th percentile without RV30 selection.
- **FR-063**: Sensitivities MUST include asset-only and exact-five-minute normalization,
  60-minute bands, 90/95/97.5 percentiles and 15/0-second cutoffs. The primary definition
  remains 30-minute bands, 95th percentile and 60 seconds; results MUST NOT be selected by
  association with RV30.
- **FR-064**: Calibration parameters MUST be estimated only from the twenty pre-Pilot-V2
  sessions and then applied unchanged to Pilot V2. The output MUST include calibration bounds,
  sample size, fallback, cutoff and source hashes for every Pilot V2 origin.
- **FR-065**: B1Q MUST be recomputed for all twenty sessions using the repaired nested predicates
  and the existing PIT quote contract. B1T MUST remain diagnostic-only. Global, asset, date,
  session-tercile, route and instrument invariants MUST be asserted and fail closed.
- **FR-066**: Quality roles MUST be recommended only from coverage, IV success, FMP/Full Tape
  completeness, Massive PIT validity, integration consistency and stable missingness. RV30,
  QLIKE, correlations, feature importance and any predictive result MUST be excluded.
- **FR-067**: The literature evidence ledger MUST contain source-text coordinates or an explicit
  limited-claim status for all ten studies before any method-freeze recommendation. Metadata-only
  evidence MUST NOT support a strong methodological claim.
- **FR-068**: Storage, download, decompression, filtering, aggregation, memory, retries,
  failures and resumability MUST be measured for twenty sessions and used only to update
  feasibility estimates; Phase 3F MUST NOT authorize a larger backfill automatically.
- **FR-069**: The phase MUST emit the required calibration, B1, telemetry, quality, literature,
  test and evidence-index artifacts under `artifacts/calibration_20d/` and `docs/`, while
  preserving all V1/V2 artifacts and recording one of the four explicit final recommendations.

### Pre-registered evaluation strata

Before any final-test result is inspected, the plan MUST define volatility regimes,
earnings versus no-earnings origins, first versus last session segments, asset versus ETF,
and normal versus stressed market conditions. These are secondary or robustness analyses;
none may replace the single primary `Delta_Q` comparison. Training-only subsampling or
weighting, if ever used for a continuous target, must be documented while validation and
final testing preserve the natural event prevalence:

> Construct the full valid forecast-origin panel while preserving natural option-activity
> prevalence. Any training-only subsampling or weighting must be explicitly documented, and
> validation and final testing must preserve the natural distribution.

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
  `option_activity_present`, secondary `unusual_event` status and source trace.
- **RealizedVarianceTarget**: thirty-minute future target, its one-minute close inputs,
  computation version and validity flags.
- **BenchmarkRun**: frozen B0/B1a/B2 configuration, split dates, purge/embargo, model,
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
- **SC-004**: The pilot retains every valid five-minute origin for every candidate, passes
  deterministic recomputation of the thirty-minute target on a traced row sample, and
  reports natural option-activity prevalence without artificial balancing or a requirement
  for no-operation origins.
- **SC-005**: At least four and at most six assets pass the predeclared quality/coverage gate;
  if fewer pass, modeling does not start.
- **SC-006**: Every predictor in the pilot has `available_at` no later than its forecast
  origin, or is excluded with a recorded reason.
- **SC-007**: The literature matrix contains ten independently verifiable studies in the
  specified date range with all required fields populated or explicitly marked unavailable.
- **SC-008**: B0, B1a and B2 use identical eligible origins, target hashes and chronological
  splits; the prospective holdout remains untouched until the development method is frozen.
- **SC-009**: Any claim of incremental B2 value requires lower B2 QLIKE than B1a in
  development, a 95% paired whole-day interval for `QLIKE(B1a)-QLIKE(B2)` above zero, the same
  sign on the one-time holdout, Holm-adjusted confirmatory inference and no material systematic
  reversal across the prespecified stability strata.
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
- **SC-014**: B1Q and B1T produce complete per-origin artifacts for all 2,840 origins, with
  route, threshold, asset and session-segment coverage plus explicit missing reasons; no
  route is selected using predictive performance.
- **SC-015**: The all-assets common-history artifact contains 48 asset-date records, exact
  component pass fields, candidate common-window calculations and an explicit statement that
  monthly probes do not prove daily continuity.
- **SC-016**: Each of ten literature rows resolves to a real source and passes field-level
  verification; unverifiable rows cannot support frozen variables, benchmarks or claims.
- **SC-017**: The extension request is emitted only when all stated B1a, PIT, common-history,
  resumability, test and storage-margin gates pass; the request itself does not download data.
- **SC-018**: Invalid nested-coverage evidence is archived and every recomputed route passes
  monotonicity assertions globally and across every declared subgroup.
- **SC-019**: The B1Q failure waterfall reconciles all 2,840 origins without unexplained false
  values or unclassified losses.
- **SC-020**: The controlled four-asset diagnostic contains 12 traced cases (four assets by
  three session origins) with exact request/response and failure evidence, without secrets.
- **SC-021**: The twenty-session availability artifact contains exactly 20 session records,
  excludes the five Pilot V2 dates, downloads no Full Tape ZIP payload and does not claim PIT
  from Range/Content-Range alone.
- **SC-022**: Every literature row has an explicit evidence status and location; unresolved
  claims cannot support benchmark or methodological decisions.
- **SC-023**: The repaired B1Q matrix reconciles controlled/full observations, explains
  INVALID_DTE and passes sequential first-failure and nested monotonicity assertions.
- **SC-024**: The earnings contract classifies equities and ETFs correctly and keeps
  dividends/distributions separate from earnings.
- **SC-025**: The calibration manifest contains exactly twenty configured session records,
  excludes all five Pilot V2 dates, records a SHA-256 and independent checkpoint for each valid
  day, and reports no secret values or personal paths.
- **SC-026**: The B2 calibration panel preserves all valid origins, uses natural prevalence,
  passes the 60/15/0-second cutoff checks, and has no eligible row with `created_at` after its
  cutoff.
- **SC-027**: Calibration parameters are reproducible from the twenty-session history, expose
  MAD/IQR/asset fallback usage, and apply unchanged to Pilot V2 without future or RV30-based
  threshold selection.
- **SC-028**: The twenty-session B1Q artifact passes nested monotonicity globally and across
  every declared asset/date/session-tercile/route/instrument subgroup and reports explicit IV
  failure reasons.
- **SC-029**: Storage telemetry contains real per-day bytes, timings, memory and retry/failure
  values plus mean/P95 projections for 3/6/12 months, with no automatic backfill authorization.
- **SC-030**: The final calibration recommendation is one of
  `AUTHORIZE_METHOD_FREEZE_AND_BACKFILL_PLAN`, `REVISE_CALIBRATION`, `REVISE_SCOPE` or
  `STOP_PROJECT`, and remains blocked from models, QLIKE and final testing.

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

## Phase 4B implementation contract

The retained 25-session development dataset MUST be repaired locally before any staged
backfill. Primary FMP availability MUST select the latest underlying bar whose raw timestamp
plus one minute is no later than the forecast origin; plus two minutes is a prespecified
sensitivity. Both conventions MUST preserve the existing origin IDs, 31 target prices and
30 RV30 returns. The source timestamp, availability timestamp and feature age MUST be retained.

Unusual Whales features MUST use separate five-minute half-open event-time windows
`[origin - delay - 5m, origin - delay)` for delays 60, 120 and 300 seconds. `executed_at` may
define that event-time window only when it is an observed raw Full Tape field in the accepted
source schema; a source/session without that field fails B2 acceptance rather than inventing it.
For an accepted source, `created_at <= origin - delay` is the separate operational-availability
cutoff before aggregation. `created_at` MUST remain labelled an operational availability proxy
and MUST NOT be called publication time.

The canonical B2 field is `b2_within_bin_iv_change`. Its missingness and observation count MUST
be preserved; it is optional and MUST NOT remove a primary B2 row. Known aliases, exact duplicate
predictors and deterministic algebraic identities MUST be rejected by the feature registry, while
high correlation alone MUST remain diagnostic rather than an automatic deletion rule.

Phase 4B MUST emit nested B0, B0+B1Q, B0+B1Q+B2-core and exact-intersection matrices with
deterministic ordering, identical target values on common origins and explicit exclusion reasons.
Every session checkpoint MUST carry configuration, input, schema, request and output hashes and
fail closed on corruption or duplicate output. A ten-session XNYS prospective holdout MUST be
sealed strictly after the Phase 4B seal timestamp, marked `SEALED_NOT_ACQUIRED`, and blocked from
reads until method freeze and human approval. No new provider request, backfill, model, tuning or
performance metric is allowed in Phase 4B.

## Phase 5 — Ninety-Session Preregistered RV30 Evaluation

This approved phase supersedes earlier acquisition and modeling prohibitions only after its
Spec Kit consistency report has zero critical contradictions and its preregistration has been
written and SHA-256 hashed. It does not authorize selecting specifications for a favorable
result, reading an incomplete holdout session, deleting retained provider evidence, publishing
externally, sending email, trading, or changing the frozen methods after holdout access.

- **FR-070**: The study sample MUST contain exactly eighty XNYS development sessions from
  2026-03-24 through 2026-07-17 and ten prospective holdout sessions on 2026-07-20 through
  2026-07-24 and 2026-07-27 through 2026-07-31. The twenty-five retained sessions MUST be
  reused only after hash verification; fifty-five additional development sessions are required.
- **FR-071**: The canonical information sets MUST be nested on identical eligible origins:
  B0 contains PIT underlying and market state; B1a adds Massive-reconstructed ATM IV; B2 adds
  exactly the nine frozen trade-derived features listed in the approved design. B1b and B1c
  remain enriched robustness benchmarks and MUST NOT be imputed to force coverage.
- **FR-072**: The nine primary B2 features MUST be
  `b2_log_trade_count`, `b2_unique_contract_share`, `b2_log_mean_trade_premium`,
  `b2_log_max_trade_premium`, `b2_call_put_premium_imbalance_scaled`,
  `b2_execution_side_premium_imbalance`, `b2_repeated_contract_premium_share`,
  `b2_strike_concentration` and `b2_expiry_concentration`. Their definitions MUST be frozen
  without consulting RV30, QLIKE or predictive results; provider cumulative fields remain
  excluded.
- **FR-073**: Primary B2 eligibility MUST use a half-open five-minute event-time window ending
  sixty seconds before the forecast origin. `executed_at` may define that window only where it
  is an observed raw Full Tape field in the accepted source schema; if absent, the source/session
  MUST fail B2 acceptance rather than substituting another timestamp. Independently,
  `created_at` MUST be no later than the window end as the operational-availability cutoff.
  Cutoffs of 120 and 300 seconds are prespecified sensitivities. `created_at` remains an
  operational availability proxy, never publication time or evidence of trader intention.
- **FR-074**: One canonical row MUST represent one asset at one valid five-minute forecast
  origin. B0, B1a, B2 and RV30 comparisons MUST share identical `origin_id` values and target
  hashes. Missing B1a or B2 inputs MUST receive an explicit reason and MUST NOT be silently
  imputed, interpolated, balanced or converted to zero except for a mathematically defined
  zero-denominator activity ratio.
- **FR-075**: The confirmatory model MUST be Gamma GLM with its log link and strictly positive
  forecasts. LightGBM with a frozen Gamma objective and grid MUST remain a challenger robustness
  analysis and MUST NOT replace the confirmatory model because of a favorable outcome. All
  preprocessing and tuning MUST be fit on training history only.
- **FR-076**: The confirmatory estimands MUST be
  `Delta_B1 = QLIKE(B0) - QLIKE(B1a)` and
  `Delta_B2 = QLIKE(B1a) - QLIKE(B2)`, where positive values favor the expanded information
  set and `Delta_B2` is primary. QLIKE is the primary loss; MAE and RMSE are secondary
  descriptive metrics.
- **FR-077**: Uncertainty MUST use a paired whole-day cluster bootstrap that keeps all assets
  and forecast origins from a trading date together. Holm correction MUST apply to the two
  confirmatory information-set comparisons. Bootstrap repetitions, random seeds, model grids,
  forecast floor and fold dates MUST be frozen before QLIKE is computed.
- **FR-078**: Development evaluation MUST use four expanding chronological outer folds:
  train through 2026-05-19/test 2026-05-20–2026-06-03; train through
  2026-06-03/test 2026-06-04–2026-06-17; train through 2026-06-17/test
  2026-06-18–2026-07-02; and train through 2026-07-02/test 2026-07-06–2026-07-17.
  Every boundary MUST purge and embargo at least the overlapping thirty-minute target horizon.
- **FR-079**: The prospective holdout MUST remain `SEALED_NOT_ACQUIRED` until its sessions
  complete at `2026-07-31T20:00:00Z`. Before that instant, the acquisition command MUST fail
  before any provider request. After completion it MAY acquire and hash provider evidence,
  construct and seal the common panel and target-blind timing sidecar, and run quality gates,
  but MUST NOT fit a model, compute QLIKE or summarize target outcomes. Analytical access MUST
  occur exactly once after preregistration, method freeze, leakage tests, reproducibility tests
  and an explicit access-ledger transition. No method, feature, asset or threshold may change
  after this read.
- **FR-080**: Stability MUST be reported by asset, session tercile, development-defined
  volatility regime, FMP +1/+2-minute availability and B2 60/120/300-second cutoff. Asset
  eligibility MUST use only PIT validity, coverage, missingness and temporal stability, never
  RV30 association, QLIKE, feature importance or preliminary predictive performance. Session
  terciles MUST use the frozen B0 session-minute bounds `[0,130)`, `[130,260)` and
  `[260,end]`; volatility regimes MUST use pooled selected-asset development-only linear
  tertiles of lagged B0 RV30. Stability uses the frozen primary hyperparameters without
  retuning and does not expand the confirmatory Holm family. A stratum is materially negative
  only when its paired-day bootstrap `ci_high < 0`; a systematic stratum reversal requires at
  least two such strata within one dimension, at least two sessions per stratum and at least
  50% of that dimension's origins. Any non-primary timing variant with `ci_high < 0` is a
  material timing reversal. The dimensions were preregistered; this numerical materiality rule
  is an explicitly disclosed post-development/pre-holdout method-freeze clarification and MUST
  NOT be represented as having been frozen before development QLIKE.
- **FR-081**: Every registered B2 variant and every positive, negative or null result MUST be
  retained. A supported edge requires the prespecified development contrast to be positive
  with uncertainty excluding zero, the one-time holdout effect to have the same sign, and no
  material systematic reversal in the prespecified stability strata.
- **FR-082**: Raw ZIPs, Parquet data and provider caches MUST reside under the configured
  `D:\MDS650` data roots. The run MUST stop before another acquisition batch if projected
  minimum free space during the peak is below 80 GB. No raw evidence may be deleted before
  hashes, manifests and reproducibility are independently verified.

## Phase 5A — Corrected Development Evidence Release

This phase corrects the interpretation of B2 availability without rewriting any sealed legacy
output. It uses only already-acquired development evidence and the frozen method. It is neither
a new historical acquisition nor a prospective holdout read. Its results are development evidence
only; no final scientific claim is permitted until the separately controlled holdout phase passes.

- **FR-083**: Historical source availability MUST be reported independently of point-in-time
  semantics. The registered FMP `PASS_90_OF_90_SESSIONS` and Unusual Whales
  `PASS_90_OF_90_FILE_METADATA` findings MUST NOT upgrade FMP bar-label/latency semantics,
  Unusual Whales publication timing, or the prospective-holdout gate.
- **FR-084**: A corrected development release MUST first bind a target-free predictor source
  constructed specifically for the exact 80-session development manifest. The immutable
  180-session target-blind v2.4 manifest MAY supply control and provenance rules but MUST NOT be
  relabelled or filtered as the 80-session source. The source coverage ledger, B2 availability
  sidecar, PIT v2.1 gate and Massive reselection evidence MUST be bound by SHA-256. It MUST
  reject every holdout session, target-like input during predictor construction, legacy result
   path, source-hash mismatch and source-window mismatch. A B1Q row with same-session or
   missing exact pre-origin rate/dividend provenance MUST be explicitly missing with
   `B1Q_EXOGENOUS_INPUT_PROVENANCE_UNRESOLVED`; stale or carried-forward exogenous inputs are
   forbidden. A calendar date strictly before the session is insufficient by itself: each rate
   and dividend input MUST retain a sanitized raw-payload SHA-256 and an availability timestamp
   no later than the forecast origin. Missing, malformed or later evidence is unresolved.
   A target-free put-call-parity diagnostic MAY establish only whether the cached contract grid
   has at least two valid paired strikes at a common expiry; it MUST NOT substitute a rate or
   dividend input, alter B1Q, or release the coverage gate unless a separately approved method
   amendment and PIT-reviewed source contract exist.
   The provider semantics supporting those fields MUST be submitted through the review-only
   timing-evidence intake before a raw-payload bundle is considered admissible; that intake alone
   never authorizes a source rebuild or evaluation.
- **FR-085**: The corrected B2 policy MUST encode a delayed or unavailable activity window as
  all nine B2 fields missing with an eligibility flag and explicit reason. It MUST NOT encode it
  as no activity or as a numerical zero. A genuine zero is permitted only for an eligible window
  with no qualifying activity and no delay incident.
- **FR-086**: Target binding MAY occur only after the predictor-only release passes FR-084 and
  MUST use the predeclared development session list, deterministic origin IDs and matching RV30
  target hashes. It MUST reject duplicate origins, a target not exactly matched to its origin, a
  predictor timestamp later than its forecast origin, and any holdout date.
- **FR-087**: Development evaluation MUST use the frozen B0, B1a and B2 information sets,
  Gamma GLM confirmatory role, LightGBM fixed robustness role, expanding folds, purge/embargo,
  QLIKE, MAE, RMSE, paired-day bootstrap, Holm family and registered timing sensitivities. It
  MUST preserve every sign and variant and MUST NOT tune features, assets, thresholds or models
  to obtain a favorable result.
- **FR-088**: The release MUST emit a new, self-hashed corrected-development manifest and
  result ledger under a new artifact root. It MAY set
  `SAFE_TO_EVALUATE_CORRECTED_DEVELOPMENT=YES` only for the fixed 80-session development run.
  It MUST retain `SAFE_TO_RECONCILE_EXISTING_RESULTS=NO` and
  `SAFE_TO_OPEN_OR_EVALUATE_OOS=NO`; neither may be inferred from a successful development run.

### Frozen compact B2 formulas

For each eligible five-minute window:

1. `b2_log_trade_count = log1p(option_trade_count_5m)`.
2. `b2_unique_contract_share = unique_contract_count_5m / option_trade_count_5m`.
3. `b2_log_mean_trade_premium =
   log1p(total_premium_5m / option_trade_count_5m)`.
4. `b2_log_max_trade_premium = log1p(max_trade_premium_5m)`.
5. `b2_call_put_premium_imbalance_scaled =
   (call_premium_5m - put_premium_5m) /
   (call_premium_5m + put_premium_5m)`.
6. `b2_execution_side_premium_imbalance =
   ask_side_premium_share - bid_side_premium_share`.
7. `b2_repeated_contract_premium_share =
   repeated_contract_premium / total_premium_5m`.
8. `b2_strike_concentration =
   maximum eligible trade count at one strike / option_trade_count_5m`.
9. `b2_expiry_concentration =
   maximum eligible trade count at one expiry / option_trade_count_5m`.

A zero denominator yields documented zero only for a valid window with no eligible activity;
missing provider data remains missing with an explicit reason.

- **SC-031**: A frozen preregistration records the exact 80/10 session arrays, nine B2 features,
  two nested estimands, model grids, folds, seeds, missingness policy, inference contract and
  `holdout_reads=0`; its SHA-256 hash is recorded before any model fit or QLIKE computation.
- **SC-032**: The development panel contains exactly eighty unique sessions, no holdout dates,
  unique deterministic origin IDs, matching RV30 hashes across B0/B1a/B2 and no predictor later
  than its origin.
- **SC-033**: Automated tests prove that the nine B2 columns reproduce their frozen formulas
  from eligible raw aggregates and that neither RV30 nor any loss or forecast column enters
  feature construction.
- **SC-034**: Gamma GLM and LightGBM produce finite strictly positive forecasts under identical
  expanding folds; the paired day bootstrap is deterministic for the frozen seed and Holm
  adjustment is reproducible.
- **SC-035**: The holdout access ledger rejects early, mismatched and second reads, then records
  exactly one authorized analytical read after all release gates pass. Automated acquisition
  tests also prove an early invocation exits with `HOLDOUT_PERIOD_INCOMPLETE` before network
  access and that the sealed ledger remains at `holdout_reads=0`.
- **SC-036**: Final evidence reports both information-set deltas, uncertainty, multiplicity,
  all prespecified stability strata, all registered variants and all positive, negative and
  null results without post-holdout method changes.
- **SC-037**: The corrected-development input manifest proves exactly 80 ordered, unique
  development sessions, source-window equality (not filtering of another date range), zero
  holdout overlap, source-hash equality for every bound input, no unproven B1Q exogenous-input
  substitution, and zero target or metric payload reads during predictor construction.
- **SC-038**: The corrected-development panel proves that every B2 exclusion has nine null
  B2 features, `b2v2_availability_eligible=false`, and a non-empty reason; it proves that no
  delayed-source incident is represented as a confirmed zero-activity window.
- **SC-039**: A development evaluation may start only after the corrected-development gate,
  target-origin binding, no-leakage checks, frozen-method hash and deterministic replay checks
  pass. Its output records all B0/B1a/B2 deltas, intervals, adjusted p-values and variants
  without accessing any holdout input.
- **SC-040**: A successful corrected-development evaluation does not change the status of any
  legacy result or of the prospective holdout. Final edge support remains conditional on the
  one-time holdout read under the already frozen protocol.
- **SC-041**: If any fixed development asset-date lacks an exact B1Q source state or has a
  same-session, missing, unhashed, or not-yet-available exact pre-origin rate/dividend input,
  the source-coverage artifact MUST be `BLOCKED_SOURCE_COVERAGE`, all affected B1Q fields MUST
  remain null with a machine-readable reason, and target binding or development evaluation MUST
  NOT start.
