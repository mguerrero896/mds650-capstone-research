# Research requirements quality checklist: MDS650 PIT options / RV30

**Purpose**: review the written requirements before implementation. This is a
requirements-quality gate, not the executable test suite.

## Scope and traceability

- [x] CHK001 The research question identifies the outcome, horizon, information set, and out-of-sample objective.
- [x] CHK002 The eight candidate assets are named exactly and consistently.
- [x] CHK003 The 4–6 asset freeze is based only on coverage and data quality, not preliminary predictive performance.
- [x] CHK004 The maximum common verified history rule is explicit.
- [x] CHK005 The six data components are separated into independently auditable contracts.
- [x] CHK006 Every acceptance criterion is objectively testable or produces a documented blocked status.
- [x] CHK007 Requirements map to user stories, functional requirements, and success criteria in `spec.md`.

## Temporal and statistical validity

- [x] CHK008 The forecast-origin clock, regular-session calendar, timezone conversion, and DST behavior are specified.
- [x] CHK009 The RV30 target uses only future one-minute closes and defines missing-close behavior.
- [x] CHK010 Point-in-time predictor eligibility is stated as a cutoff invariant.
- [x] CHK011 Purging and embargo are required for overlapping 30-minute labels.
- [x] CHK012 B0, B1, and B2 are nested and the primary comparison is B2 versus B1.
- [x] CHK013 The specification blocks incremental-activity claims when B1 cannot be constructed.
- [x] CHK014 QLIKE, secondary metrics, confidence intervals, seeds, and multiple-comparison handling are required.
- [x] CHK015 The requirements distinguish predictive association from causal information and prohibit intent overclaiming.

## Provider evidence and licensing

- [x] CHK016 FMP audit requirements cover OHLCV, earnings, timestamps, completeness, duplicates, nulls, rate behavior, and bandwidth-safe extraction.
- [x] CHK017 Unusual Whales audit requirements cover pagination, contract identity, event fields, PIT IV/skew/term structure, and proxy limitations.
- [x] CHK018 Massive is constrained to directed contract validation and explicitly excludes full historical OPRA quote download.
- [x] CHK019 Sanitized manifests, immutable raw payload hashes, schema fingerprints, and license status are required.
- [x] CHK020 Missing credentials, schema drift, inadequate overlap, and licensing conflicts fail closed.
- [x] CHK021 The absent user-named source folder is recorded as a provenance gap rather than silently replaced.

## Pilot and reproducibility

- [x] CHK022 The pilot includes all eight candidates, event and no-event origins, and a recorded window-expansion rule.
- [x] CHK023 Deduplication keys and quality flags are specified for every normalized component.
- [x] CHK024 Row-level traceability connects origins, source hashes, cutoffs, future closes, and target calculations.
- [x] CHK025 Local modular code is the source of truth and Colab is limited to orchestration/presentation.
- [x] CHK026 Public-function documentation, typed interfaces, dependency locking, and structured audit output are required.
- [x] CHK027 The test-first policy includes unit, contract, integration, pagination, timezone/DST, leakage, missingness, target, and end-to-end tests.
- [x] CHK028 Research-only safety boundaries prohibit broker orders, emails, publication, deployment, and other external mutations.

## Literature and recovery

- [x] CHK029 The literature matrix requires ten verifiable empirical studies dated January 2023–July 2026 with all specified fields.
- [x] CHK030 Literature categories distinguish ordinary implied state, unusual flow, intraday RV forecasting, and ML benchmark comparisons.
- [x] CHK031 Week-4 recovery gates identify evidence needed to resume after provider, overlap, PIT, or licensing failure.
- [x] CHK032 Every stop condition has an explicit decision point and does not permit silent asset, window, or feature substitution.
