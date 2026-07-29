# Specification Quality Checklist: Point-in-Time Options Activity for RV30 Forecasting

**Purpose**: Validate specification completeness and quality before planning
**Created**: 2026-07-20
**Feature**: [spec.md](../spec.md)

## Content Quality

- [x] No implementation details (languages, frameworks, APIs)
- [x] Focused on research value and scientific decision needs
- [x] Written for research stakeholders and reviewers
- [x] All mandatory sections completed

## Requirement Completeness

- [x] No `[NEEDS CLARIFICATION]` markers remain
- [x] Requirements are testable and unambiguous
- [x] Success criteria are measurable
- [x] Success criteria are technology-agnostic
- [x] All acceptance scenarios are defined
- [x] Edge cases are identified
- [x] Scope is clearly bounded
- [x] Dependencies and assumptions identified

## Feature Readiness

- [x] All functional requirements have clear acceptance implications
- [x] User stories cover the primary research flows
- [x] Feature meets the measurable outcomes defined in Success Criteria
- [x] No implementation details leak into the specification

## Recovery iteration gates

- [x] The recovery branch and initial repository state are recorded before edits.
- [x] The preserved v0 manifest is classified as exploratory and is not rewritten as v1.
- [x] RV30 uses 31 prices: the origin close plus thirty future closes and exactly thirty
  one-minute log returns.
- [x] FMP bar start/close semantics, origin close, last valid origin, missing bars, early
  closes and halts are explicit unresolved gates; silent interpolation is prohibited.
- [x] The provider manifest contract requires schema version 1.1, explicit enums, request IDs,
  timestamp validation and separate authentication/endpoint/schema/entitlement diagnostics.
- [x] The manifest uniqueness key is explicit and duplicate keys fail validation.
- [x] Unusual Whales aliases and the distinction between event IV fields and ordinary PIT
  option state are explicit; `executed_at` is not asserted without raw evidence.
- [x] Structured earnings validate the returned symbol and classify ETF responses as
  `not_applicable` unless applicability is proven.
- [x] Provider audit and literature verification are parallel Phase 3A/3B workstreams.
- [x] The compatibility matrix and clean-install gate preceded the approved runtime mutation;
  Python 3.12.12 was selected by compatibility evidence, not novelty.
- [x] Every valid origin is retained; option-activity prevalence is natural and no
  no-operation origin is required or fabricated.
- [x] The primary evaluation is the single predeclared `Delta_Q` contrast with day-clustered
  paired bootstrap, predeclared multiplicity, regimes and training-only MDE estimation.

## Planned tests before implementation

- [x] Duplicate manifest entries and duplicate hashes under different requests fail.
- [x] JSON Schema 1.1 validation rejects missing identifiers, invalid timestamps, personal
  paths, secret-like fields, invalid enums and repeated composite keys.
- [x] Alias and field-time semantics fixtures cover `iv_start`, `iv_end`, `created_at`,
  `start_time` and `end_time` without inventing `executed_at`.
- [x] FMP calendar fixtures cover winter, summer, DST transition, early close, halt and the
  AMZN/TSLA missing-minute diagnostic.
- [x] Target fixtures prove 31-price RV30 arithmetic and fail closed on any missing price.
- [x] Are Windows and Colab clean-install parity requirements, covered packages, expected
  results and evidence hashes explicitly specified? [Completeness, Spec §SC-013]

## Pilot V2 correction gates

- [x] B2 continuous features are distinguished from `option_activity_present` and
  `unusual_event` remains explicitly uncalibrated. [Clarity, Spec §FR-030–FR-031]
- [x] The primary panel retains all valid five-minute origins without an artificial
  event/no-event requirement. [Consistency, Spec §FR-010, §SC-004]
- [x] Massive quote selection is specified per origin with nanosecond `timestamp.lte`,
  descending order, and bounded no-quote diagnostics. [Gap, Spec §FR-032]
- [x] B1a, B1b and B1c completeness are defined per origin and separated from numerical IV
  inversion success. [Gap, Spec §FR-032]
- [x] FMP exact-session filtering, provider-over-return dates, and symbol-specific BMO/AMC
  semantics are specified without claiming provider confirmation. [Gap, Spec §FR-033]
- [x] Common-history V2 resolves date-relative historical contracts rather than reusing a
  current contract. [Gap, Spec §FR-034]

## B1 Feasibility and Common-History Closure

- [x] Are B1Q Massive and B1T Full Tape explicitly distinguished in independence, provenance
  and fallback semantics? [Clarity, Spec §FR-036–FR-038]
- [x] Does the specification define contract-day caching, checkpoints and idempotency rather
  than an unbounded request per origin and contract? [Completeness, Spec §FR-036]
- [x] Are DTE buckets, target moneyness, quote-age limits and spread limits quantified for
  primary and sensitivity analyses? [Measurability, Spec §FR-037]
- [x] Are B1a ATM interpolation, B1b skew fallback and B1c term-structure slopes defined
  independently at each forecast origin? [Clarity, Spec §FR-039]
- [x] Are B1 coverage thresholds and session-tercile minimums explicit and independent of
  predictive performance? [Consistency, Spec §FR-040]
- [x] Does the all-assets common-history requirement distinguish monthly sampled overlap from
  unproven daily continuity? [Gap, Spec §FR-041]
- [x] Are all ten literature rows required to resolve real sources before methodological
  claims or variable freezes? [Completeness, Spec §FR-042]
- [x] Are the twenty-session extension gates and no-download boundary explicit and jointly
  testable? [Acceptance Criteria, Spec §FR-043, §SC-017]

## B1 Forensic Validation and Asset-Coverage Decision

- [x] Are component availability fields distinct from nested benchmark completeness? [Completeness, Spec §FR-045]
- [x] Are `b1a_complete`, `b1b_complete` and `b1c_complete` defined as nested predicates? [Clarity, Spec §FR-045]
- [x] Are monotonicity constraints explicit globally, by asset, date, session segment and route? [Measurability, Spec §FR-046]
- [x] Are all 17 failure-waterfall stages and exact failure-code categories documented? [Completeness, Spec §FR-047]
- [x] Are SPY, QQQ, META, TSLA and their 12 controlled diagnostic cases explicitly scoped? [Coverage, Spec §FR-048]
- [x] Does the requirement distinguish missing dividends from asset-level data failure and constrain q=0? [Consistency, Spec §FR-049]
- [x] Are recomputation strata and sensitivity dimensions specified without predictive selection? [Completeness, Spec §FR-050]
- [x] Is twenty-session file availability explicitly separated from PIT validity and ZIP download? [Clarity, Spec §FR-051]
- [x] Does each literature claim require a full-text location or explicit unresolved status? [Traceability, Spec §FR-052]

## B1Q Integration Repair and Earnings Contract Closure

- [x] Contract resolution is bucket-scoped and historical `as_of` is preserved.
- [x] Contract, quote and origin cache keys contain all required identity fields.
- [x] Controlled/full-matrix row reconciliation records the first divergent stage.
- [x] `INVALID_DTE` is explained by asset, date, origin, side, bucket and contract.
- [x] First-failure codes are mutually exclusive and additional failures are separate.
- [x] Earnings are applicable to equities only; ETFs have no synthetic earnings.
- [x] Dividends/distributions remain separate PIT IV inputs.

## Twenty-Session Historical Calibration and Method Freeze

- [x] Are the exact twenty sessions, excluded Pilot V2 dates and prohibited downstream activities explicit? [Completeness, Spec §FR-057–FR-060]
- [x] Are storage, write-access, presence-only secret and per-session resumability gates measurable before network calls? [Acceptance Criteria, Spec §FR-057]
- [x] Are legacy cache files separated from explicitly keyed active calibration cache entries? [Consistency, Spec §FR-059]
- [x] Are continuous B2 features, provider cumulative-field exclusions and all three availability cutoffs specified? [Completeness, Spec §FR-061]
- [x] Is the operational availability proxy clearly distinguished from publication time? [Clarity, Spec §FR-061]
- [x] Are 30-minute historical bands, median/MAD, IQR/asset fallbacks and the five core score features unambiguous? [Measurability, Spec §FR-062]
- [x] Are sensitivity bands, percentiles and cutoffs defined without predictive selection? [Consistency, Spec §FR-063]
- [x] Is the calibration-to-Pilot V2 separation and no-future/no-RV30 rule explicit? [Traceability, Spec §FR-064]
- [x] Are B1Q nested invariants and B1T diagnostic-only status retained for twenty sessions? [Coverage, Spec §FR-065]
- [x] Are asset quality roles based only on PIT/data-quality evidence and not predictive outcomes? [Consistency, Spec §FR-066]
- [x] Does the literature gate require source-text coordinates or limited-claim status for all ten studies? [Completeness, Spec §FR-067]
- [x] Are telemetry fields and the prohibition on automatic larger backfill authorization specified? [Acceptance Criteria, Spec §FR-068]
- [x] Are all required Phase 3F artifacts and the four mutually exclusive final recommendations listed? [Completeness, Spec §FR-069, §SC-025–SC-030]

## Notes

- The unavailable Downloads source folder is documented as a provenance dependency and
  cannot be claimed as read until its path and contents are supplied.
- Provider feasibility and B1 viability are empirical gates, not assumptions of success.

## Phase 5 Ninety-Session Evaluation Requirements

- [x] CHK001 Are the exact development and holdout dates, counts, disjointness and retained/new
  session split specified without ambiguity? [Completeness, Spec §FR-070]
- [x] CHK002 Are B0, B1a and B2 defined as nested information sets on identical origins, with
  B1b/B1c explicitly limited to robustness roles? [Consistency, Spec §FR-071]
- [x] CHK003 Are all nine compact B2 names, formulas and zero-denominator rules frozen and
  traceable without consulting RV30 or QLIKE? [Clarity, Spec §FR-072 and Frozen formulas]
- [x] CHK004 Are primary and sensitivity event windows, half-open boundaries and both timestamp
  cutoffs specified without calling `created_at` publication time? [Clarity, Spec §FR-073]
- [x] CHK005 Does the specification define the canonical row, common-origin rule, target-hash
  equality and every prohibited missing-data shortcut? [Completeness, Spec §FR-074]
- [x] CHK006 Are confirmatory and challenger model roles unambiguous, including the prohibition
  on promotion based on a favorable outcome? [Consistency, Spec §FR-075]
- [x] CHK007 Are both estimands, their direction, primary/secondary status and the roles of
  QLIKE, MAE and RMSE objectively defined? [Measurability, Spec §FR-076]
- [x] CHK008 Are the clustering unit, multiplicity family and parameters that must freeze before
  loss computation explicit? [Completeness, Spec §FR-077]
- [x] CHK009 Are all four expanding test intervals and the minimum purge/embargo duration
  specified? [Measurability, Spec §FR-078]
- [x] CHK010 Are incomplete-session, pre-freeze, hash-mismatch and second-read holdout cases
  covered by fail-closed requirements? [Edge Cases, Spec §FR-079 and §SC-035]
- [x] CHK011 Are stability strata and quality-only asset eligibility distinguished from
  predictive selection? [Consistency, Spec §FR-080]
- [x] CHK012 Is the supported-edge criterion predeclared while requiring preservation of
  positive, negative and null registered outcomes? [Clarity, Spec §FR-081]
- [x] CHK013 Are D: storage placement, the 80-GB peak floor and safe-deletion preconditions
  measurable before each acquisition batch? [Acceptance Criteria, Spec §FR-082]
- [x] CHK014 Do success criteria cover preregistration hashing, PIT panel integrity, target-blind
  features, positive forecasts, deterministic inference, one-time holdout access and complete
  sign reporting? [Coverage, Spec §SC-031–SC-036]
