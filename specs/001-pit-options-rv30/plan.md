# Implementation Plan: Point-in-Time Options Activity for RV30 Forecasting

**Branch**: `001-pit-options-rv30-recovery` (feature identifier `001-pit-options-rv30`) | **Date**: 2026-07-29 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/001-pit-options-rv30/spec.md`

## Summary

The local modular package is authoritative. The approved Phase 5 study reuses the existing
25-session PIT engineering dataset, acquires 55 additional development sessions, and reserves
10 prospective sessions for a one-time holdout. It compares nested B0, B1a and compact
nine-feature B2 information sets for RV30 using a confirmatory Gamma GLM, a fixed LightGBM
robustness challenger, QLIKE, paired whole-day bootstrap and Holm correction. Spec Kit and a
SHA-256-hashed preregistration MUST pass before acquisition, fitting or loss computation.

## Technical Context

**Language/Version**: Python 3.12.12 is the approved conservative runtime baseline.
The owner approved the compatibility matrix on 2026-07-21; `pyproject.toml` and `uv.lock` now
target `>=3.12,<3.13`. The matrix covers Google Colab, Windows, Polars, PyArrow,
DuckDB, LightGBM, scikit-learn, SHAP, Optuna, Pydantic, Ruff, Mypy and Pytest. Version choice
must be compatibility-first, never based on novelty. The matrix includes a clean install from
the lockfile and an import/test smoke result for every row.

**Primary Dependencies**: `uv`, `pydantic-settings`, `httpx`, `polars`, `pyarrow`, `duckdb`,
`pytest`, `ruff`, `mypy`, `coverage`, `scikit-learn` and `lightgbm`. Only the last two are
added for Phase 5; SHAP and Optuna remain unnecessary for the approved confirmatory design.

**Storage**: Immutable raw responses, normalized Parquet and provider caches under
`D:\MDS650`; compact code, manifests, hashes and reports remain in Git. DuckDB supports local
analytical queries. No provider raw payload is redistributed or deleted before independent
hash/manifest/reproducibility verification.

**Testing**: pytest unit/contract/integration/end-to-end tests, coverage, ruff and mypy;
bounded live queries are opt-in and never substitute for sanitized fixtures.

**Target Platform**: Windows local workstation with Colab as a presentation/orchestration
layer. The local modular package is authoritative.

**Project Type**: Internal research package and reproducible CLI-oriented pipeline.

**Performance Goals**: Bounded audit requests must respect provider rate limits and complete
without unbounded retries; pilot joins and target computation must be deterministic and
re-runnable. No production latency or trading-capacity claim is in scope.

**Constraints**: No network request before presence-only secret validation, Spec Kit
consistency and preregistration hash; no live orders, email, deployment, publication or remote
Git mutation; no synthetic or silent fallback data. The 25 retained raw ZIP hashes MUST be
reused rather than downloaded again. Development acquisition is resumable per day. Holdout
outcomes remain unread until the final session is complete and the method-freeze gate releases
one analytical read.

**Scale/Scope**: Eight candidate assets, six independently validated data components, 80
development sessions and 10 prospective holdout sessions. Four to six assets may be retained
using data-quality/PIT criteria only. The common provider history must cover every selected
session continuously.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **I. Evidence and Point-in-Time Truth**: PASS by design. Every normalized row carries
  source and availability metadata; unresolved timestamps fail closed.
- **II. Frozen Objective, Benchmarks and Scope**: PASS. RV30, B0/B1a/B2, eight candidates,
  quality-only freeze, primary earnings exclusion and directed Massive extraction are explicit in
  `spec.md`.
- **III. Tests First and Fail-Closed Data Contracts**: PASS. Tests precede backfill and schema
  drift/partial pagination are hard failures.
- **IV. Reproducibility, Security and Auditability**: PASS with a per-run secret gate. The
  owner reports that exposed credentials were rotated; every network process must still prove
  presence only from the approved runtime secret store. Raw licensed evidence remains outside
  Git and the holdout access ledger is immutable.
- **V. Statistical Validity and Honest Interpretation**: PASS. Walk-forward splits, purge,
  embargo, QLIKE, paired uncertainty and non-causal interpretation are required.

No complexity violation is claimed. The provider adapters, storage layers and benchmark
runner are separated because they have distinct provenance, retry, leakage and validation
contracts, not to add speculative services.

## Project Structure

### Documentation (this feature)

```text
specs/001-pit-options-rv30/
├── spec.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── provider-audit-manifest.md
│   ├── provider-audit-manifest.schema.json
│   ├── pilot-dataset-contract.md
│   └── benchmark-evaluation-contract.md
├── checklists/
│   ├── requirements.md
│   └── recovery.md
└── tasks.md

docs/
├── methodology_decisions.md
├── risk_register.md
├── b1_data_contract.md
├── b1_coverage_decision.md
├── literature_synthesis.md
├── literature_sources/index.csv
├── 20_session_calibration_request.md
├── recovery/compatibility_matrix.md
└── recovery/{initial_repository_state,gap_analysis,audit_v0_findings,
    provider_audit_v1_plan,spec_kit_analysis_report}.md

artifacts/b1_full_origin/
├── b1_origin_matrix.parquet
├── b1_coverage_summary.json
├── b1_coverage_by_asset.csv
├── b1_coverage_by_session_segment.csv
├── b1q_vs_b1t_comparison.csv
├── iv_inversion_diagnostics.json
└── evidence_index.csv
```

### Source Code (repository root)

```text
pyproject.toml
uv.lock
config/acceptance.yaml
src/mds650/
├── config.py, logging.py, errors.py, contracts.py, storage.py
├── time.py, quality.py, normalize.py, events.py, origins.py
├── targets.py, asset_selection.py, profiling.py, audit.py, manifests.py
├── literature.py, splits.py, metrics.py, benchmarks.py, execution.py
└── providers/{base,fmp,unusual_whales,massive}.py
tests/{unit,contract,integration,e2e}/
tests/fixtures/providers/
notebooks/MDS650_Research_Pipeline.ipynb
docs/{architecture,data_dictionary,week4_evidence_recovery}.md
docs/literature_matrix.csv
docs/literature_sources/
```

**Structure Decision**: A single Python package keeps the local implementation and Colab
imports aligned. Provider adapters never write analytical tables directly; they emit typed
responses and provenance records. Transformations consume those contracts, and benchmark
evaluation consumes only the frozen pilot/analysis tables.

## Phase 0: Research Decisions

1. Confirm the missing source-folder path or record it as an unresolved provenance input.
2. Rotate the exposed provider credentials and verify presence without printing values.
3. Import `artifacts/api_audit/exploratory_v0/provider_audit_manifest.json` as immutable,
   sanitized fixtures; compute hashes and explicitly detect the repeated eight-asset depth
   probes. Do not reinterpret v0 as v1.
4. Resolve each provider's current contract from authenticated response schemas, not only
   documentation. Record endpoint, HTTP result, timestamp semantics, pagination and licensing.
5. Define configurable quality thresholds before inspecting predictive results: regular-session
   one-minute completeness, maximum duplicate/null counts, minimum overlap, minimum event
   coverage and B1 availability coverage.
6. Freeze the target and split protocol: RV30 from the origin close plus thirty future closes,
   expanding walk-forward validation, final untouched period, purge and thirty-minute embargo.
7. Verify all ten empirical studies in parallel with the provider audit and classify them into
   ordinary option information, option flow/informed trading, intraday RV forecasting and ML
   benchmark comparison.
8. Establish the compatibility matrix and clean-install evidence; obtain approval before any
   runtime/dependency mutation.
9. Diagnose Pilot V1 acceptance failures: presence-of-trade B2 labeling, per-origin B1
   integration, Massive timestamp filtering and FMP over-return/common-history behavior.

The detailed decisions and alternatives are recorded in `research.md`.

## Phase 1: Design and Contracts

- `data-model.md` defines six source components, forecast origins, targets, benchmark runs and
  execution manifests with availability and provenance invariants.
- `contracts/provider-audit-manifest.md` and its JSON Schema 1.1 define the sanitized provider
  audit output, unique request key and separate diagnostic states.
- `contracts/pilot-dataset-contract.md` defines the typed pilot row and quality report.
- `contracts/benchmark-evaluation-contract.md` defines nested benchmark inputs, split metadata,
  metrics and stop conditions.
- `quickstart.md` defines bounded, non-destructive validation commands and expected failure
  behavior.
- Pilot V2 artifacts define continuous B2 features, per-origin B1a/B1b/B1c coverage, IV
  robustness, corrected FMP session filtering and monthly common-history diagnostics.

## Verification Gates Before Implementation

1. Constitution, spec, clarify, plan, checklist, tasks and analyze complete with no critical
   inconsistency before implementation work is accepted.
2. Compatibility matrix and clean-install proof pass, and the runtime change is approved.
3. Secret rotation and presence-only preflight pass before any provider request.
4. Authenticated provider audit returns usable schemas and licenses before any historical
   backfill or modeling code is enabled.
5. Pilot V2 retains all valid origins, demonstrates continuous B2 construction, and records
   B1a/B1b/B1c per-origin coverage before any benchmark decision.
6. At least four candidates meet quality/overlap gates and B1 feasibility is decided before
   asset freezing and benchmark evaluation.
7. Tests exist and pass against sanitized fixtures before production backfill.
8. The Phase 5 preregistration and exact 80/10 session manifest are SHA-256 hashed before
   model fitting or QLIKE.
9. The one-time holdout guard rejects incomplete sessions, pre-freeze access, hash mismatch
   and a second analytical read.

Pilot V2 artifacts are written under `artifacts/pilot_v2/` while V1 artifacts remain preserved.
Those artifacts are evidence only: unresolved ordinary option-state PIT, historical common
overlap, FMP release timing and final unusualness calibration keep model evaluation and
benchmark claims fail-closed. Any stop condition in `spec.md` produces an exact manifest
blocker and stops downstream work.

## Phase 3C: B1 Feasibility and Common-History Closure

This controlled phase runs after the Pilot V2 acceptance-for-data-engineering gate and in
parallel with the literature verification phase. The primary B1a source route is `B1Q`, using Massive
contract-day caching, historical `as_of` resolution and local as-of joins on SIP timestamps.
The diagnostic fallback `B1T` reuses existing Full Tape rows and is explicitly dependent on
the B2 source. Neither route may select a benchmark by predictive performance.

The phase evaluates all 2,840 origins, reports coverage by asset/date/session tercile/DTE/
moneyness and 50/60/70/80% thresholds, and records IV inversion diagnostics. It also creates
an all-assets common-history artifact for 48 asset-date probes (eight assets × six dates).
Those monthly points establish sampled overlap only; they do not establish daily continuity.
The ten-study literature matrix and source register must be complete before any variable,
benchmark or methodological claim is frozen.

The phase may emit a request for, but must not download, twenty pre-Pilot-V2 trading sessions.
The request requires B1a global coverage >=70%, each asset >=50%, each session tercile >=40%,
valid PIT, no close-only concentration, common history for at least four assets, resumability,
passing tests/schemas and P95 storage with a 30% margin.

## Phase 3D: B1 Forensic Validation and Asset-Coverage Decision

This phase is a fail-closed repair of Phase 3C evidence. First archive the invalid nested
coverage result, then recompute component availability and nested completeness with executable
monotonicity assertions. Before the full 2,840-origin rerun, run a controlled 12-case trace for
AAPL, SPY, META and TSLA at opening, midday and closing. The B1Q failure waterfall must retain
the first unresolved stage and exact code for every origin; missing dividend data cannot silently
zero an asset. B1T remains diagnostic-only.

The phase also verifies twenty-session availability using calendar-derived dates, exact FMP
session probes, UW Range/Content-Range metadata and one historical Massive ATM quote per
candidate. It does not download Full Tape ZIP contents. Literature claims require a full-text
status and location, with metadata-only or unresolved rows excluded from strong claims.

No phase-3D output may authorize models, QLIKE, tuning, backfill, final test, definitive asset
freeze, Word modification or the twenty-session download unless every nested invariant,
waterfall reconciliation, B1a quality gate, PIT gate, availability gate, storage margin and
literature evidence gate passes.

## Phase 3E: B1Q Integration Repair and Earnings Contract Closure

Repair is ordered as bucket-scoped historical contract resolution, cache-key audit,
controlled/full-matrix row reconciliation, DTE failure diagnosis, sequential first-failure
waterfall, corrected B1Q recomputation, ETF role decision, and earnings/literature evidence
gates. The phase is data-engineering only; the twenty-session payloads, models, QLIKE, asset
freeze and Word/PowerPoint changes remain prohibited.

## Phase 3F: Twenty-Session Historical Calibration and Method Freeze

Phase 3F is a controlled, resumable data-engineering increment over exactly twenty sessions
(2026-06-11 through 2026-07-10) and explicitly excludes the five Pilot V2 sessions. Before
network calls it performs presence-only secret checks, verifies write access and records the
90-GB storage gate. Full Tape ZIPs are streamed and hashed; each day has an independent
checkpoint, immutable raw archive, CRC/schema validation and sanitized manifest. The 199 legacy
cache files remain read-only evidence and are not active inputs. New cache identities are
provider/asset/session/expiry/strike/option/contract/route/schema-version keys.

The B2 path constructs continuous features from rows available under the 60-second `created_at`
cutoff, with 15-second and zero-second sensitivities, excluding unproven provider cumulative
fields. Historical normalization is by asset and 30-minute band, using median/MAD with explicit
IQR and asset fallbacks. A robust score uses the median of the three largest positive z-scores
among five log-transformed core features; the secondary event label uses the historical 95th
percentile only. Parameters are learned from the twenty pre-Pilot-V2 sessions and applied
unchanged to Pilot V2. No predictive model, QLIKE, tuning, full backfill or final test is in this
phase.

B1Q is recomputed by reusing the repaired contract-day/as-of quote path; B1T remains diagnostic.
Nested predicates and subgroup monotonicity are fail-closed. Asset roles are recommended only
from PIT coverage, IV success, completeness, integration consistency and stable missingness.
Telemetry updates feasibility estimates but does not authorize a larger download. Literature
source coordinates remain a gate for any method-freeze recommendation.

## Complexity Tracking

No constitution violations require justification. The apparent multi-provider modularity is
the minimum separation needed to prevent provider-specific timestamps, pagination and license
rules from contaminating the common analytical contract.

## Phase 4B: Local PIT Repair and Staged-Backfill Readiness

Phase 4B is a local-only correction over the retained 20 calibration sessions and five Pilot V2
sessions. It supersedes the legacy 15/0-second B2 sensitivities with fixed five-minute windows
ending 60, 120 and 300 seconds before each origin. For an accepted Full Tape schema containing
raw `executed_at`, the event predicate is `executed_at ∈ [origin-delay-5m, origin-delay)` and
the independent availability predicate is `created_at <= origin-delay`. A source/session without
observed raw `executed_at` fails B2 acceptance rather than receiving an invented event time;
`created_at` remains an operational availability proxy and is never called publication time.

FMP +1 is the primary conservative research assumption. FMP +2 is a separate sensitivity
snapshot: the latest raw bar satisfying
`source_timestamp + 2 minutes <= forecast_origin`. It never shifts an origin or RV30 target.
Each B0 variant records raw source timestamp, availability timestamp and feature age. The B2
within-bin IV change is canonicalized to `b2_within_bin_iv_change`, retains nulls and availability
reason, and is optional until a predeclared stability gate passes. No target-based feature choice,
imputation, balancing, model, QLIKE or new provider request is permitted.

The runner writes explicit B0-complete, B0+B1Q-complete, B0+B1Q+B2-core-complete and exact
intersection views with deterministic origin/target hashes. Per-session checkpoints include input,
schema, request, configuration and output hashes and fail closed on corruption. A metadata-only
ten-session XNYS prospective holdout is sealed strictly after the Phase 4B seal timestamp and is
guarded from reads until method freeze and human approval.

## Phase 5: Ninety-Session Preregistered Champion–Challenger Study

### 5.1 Freeze design and sessions

Record the exact 80 development and 10 prospective holdout dates, compact B2 feature registry,
two nested QLIKE estimands, four expanding outer folds, model grids, seed 650, positive forecast
floor, missingness contract, bootstrap design, Holm family and stability strata in a
machine-readable preregistration. Write its SHA-256 digest before any model fit or QLIKE call.

### 5.2 Reuse and acquire development evidence

Verify the 25 retained session hashes, copy their large evidence to `D:\MDS650` without deleting
the source, then acquire only the 55 missing development sessions. Full Tape acquisition is
streamed, CRC/schema checked, checkpointed and resumable by session. FMP and Massive acquisition
reuse their existing bounded, PIT-safe code paths and caches. Every batch records current free
space and stops if projected peak free space would fall below 80 GB.

### 5.3 Build the canonical common panel

Construct one row per asset and five-minute forecast origin. B0 uses FMP +1 as primary and +2 as
sensitivity. B1a adds the last valid Massive ATM-IV state before the origin. B2 adds only the
nine target-blind features frozen in `spec.md`, calculated from eligible Full Tape rows ending
60 seconds before the origin; 120/300 seconds are sensitivities. Intersect identical origin IDs
and RV30 hashes, retain explicit missing reasons, and fail on future timestamps, duplicate
origins, silent imputation or holdout dates.

### 5.4 Fit and evaluate development folds

Use one shared expanding-fold generator with at least a 30-minute purge/embargo. Fit
`GammaRegressor` as the confirmatory positive-mean model and `LGBMRegressor` with
`objective="gamma"` as a fixed challenger. Fit every scaler and hyperparameter choice only on
the fold's training history. Compute QLIKE, MAE and RMSE on common test rows. Estimate
`Delta_B1` and `Delta_B2` with 10,000 paired whole-day bootstrap draws and apply Holm to the two
confirmatory p-values. Preserve every attempted registered variant and every result sign.

### 5.5 Freeze method and release one holdout read

Freeze code, data, feature, model, fold, prediction and result hashes after development. The
holdout remains blocked until all ten sessions are complete, the method-freeze hash matches and
the full quality suite is green. The frozen acquisition runner uses the isolated
`D:\MDS650\data\phase5_holdout` root, downloads each provider source once with resumable
checkpoints, builds the common panel and 120/300-second sidecar without fitting models or
computing QLIKE, and emits `holdout_access_ledger.json` with `holdout_reads=0`. It fails before
any provider call prior to `2026-07-31T20:00:00Z`. One later authorized transition increments
`holdout_reads` from zero to one; every subsequent analytical read fails. No feature, asset,
threshold or method may change after release.

### 5.6 Report stability and interpretation

Report confirmatory and challenger results by asset, session tercile, development-defined
volatility regime, FMP +1/+2 and B2 60/120/300-second cutoff. A supported edge requires a
positive preregistered development contrast whose uncertainty excludes zero, the same sign in
the one-time holdout and no material systematic reversal. Negative and null results remain
first-class evidence. Freeze session-minute bounds at 130 and 260, derive the two volatility
cutpoints from pooled selected-asset development B0 lagged RV30 with linear tertiles, and reuse
the selected primary hyperparameters without retuning. The confirmatory Holm family remains
only `Delta_B1` and `Delta_B2`. A material negative requires bootstrap `ci_high < 0`; a
systematic stratum reversal requires at least two material-negative strata with at least two
sessions each and at least 50% of that dimension's origins. Any non-primary timing variant with
`ci_high < 0` is a material timing reversal. All stability calculations occur within the sole
authorized holdout read.

### 5.7 Corrected development evidence release after PIT v2.1

The previously sealed development and holdout result artifacts are never rewritten. The
availability correction creates a separate, source-bound release from a new target-free predictor
source built specifically for the fixed 80-session development manifest. The immutable v2.4
predictor-only panel is a control/provenance template, not a data source that may be relabelled
or filtered into the frozen window. Its preflight is ordered:

1. Verify the FMP 90/90 session evidence and UW 90/90 Full Tape metadata evidence as
   historical availability only; retain FMP `+1` primary / `+2` sensitivity and UW
   `created_at` minus 60 seconds as registered study conventions rather than provider latency
   claims.
2. Verify semantic hashes of the target-blind v2.4 control manifest, B2 availability sidecar,
   PIT v2.1 anomaly gate, Massive v2.1 reselection evidence, the 80-session source manifest and
   frozen comparison contract. Reject a missing, altered, untracked or forbidden input path.
3. Build and hash a source-coverage ledger before materializing a release. It must prove exact
   date equality for B0, B1Q and B2. Any B1Q row with a same-session or missing exact pre-origin
   rate/dividend input is `B1Q_EXOGENOUS_INPUT_PROVENANCE_UNRESOLVED`, not permission to carry
   forward any later value. The executed ledger records B0/FMP and B2/UW raw-source coverage for
   all 480 selected asset-date pairs, while B1Q remains blocked for all 34,080 origins until its
   exogenous inputs are rebuilt with separate pre-origin evidence. If any such gap remains, emit only a
   `BLOCKED_SOURCE_COVERAGE` artifact and stop before target binding.
4. Construct predictor rows only from the exact development source list before any target file is
   read. Reject all ten holdout dates, result-like inputs, duplicate origin IDs, a B2
   delayed-source zero encoding, source-hash drift, source-window mismatch and a predictor
   timestamp after its origin.
5. Bind RV30 only to the passing predictor release on matching deterministic origin IDs. The
   binding process is separately manifested, validates the target hash, and has no route to
   read a holdout file.
6. Run only the frozen Gamma GLM and fixed LightGBM development protocol on the corrected
   common rows. Reproduce all frozen B0/B1a/B2 comparisons and timing variants without a
   sign-based retry, feature change, asset re-selection or hyperparameter change.

The new release may state `SAFE_TO_EVALUATE_CORRECTED_DEVELOPMENT=YES` only when these six
steps pass. It deliberately preserves `SAFE_TO_RECONCILE_EXISTING_RESULTS=NO` for legacy
outputs and `SAFE_TO_OPEN_OR_EVALUATE_OOS=NO` for the prospective holdout. Its development
results are evidence for method freeze and interpretation, not final confirmation.

### Phase 5 post-design constitution check

- Evidence/PIT truth: PASS — all joins have explicit availability cutoffs and fail closed.
- Frozen objective/scope: PASS — RV30, nested information sets, quality-only asset eligibility
  and exact 80/10 sessions are fixed.
- Tests first: PASS — contract/unit/leakage/holdout tests precede acquisition and modeling.
- Reproducibility/security: PASS — D: raw evidence is immutable, secrets are presence-only,
  manifests are hashed and holdout reads are ledgered.
- Statistical validity: PASS — expanding folds, purge/embargo, QLIKE, day-cluster bootstrap,
  Holm and honest sign reporting are predeclared.
- Corrected-release isolation: PASS by design — legacy reconciliation and OOS access cannot be
  upgraded by a development-only rebuild; B2 delayed-source rows remain explicit exclusions.
