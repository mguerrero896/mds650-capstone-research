# Research Decisions: Point-in-Time Options Activity for RV30 Forecasting

## Decision 1: Treat provider documentation and response schemas separately

**Decision**: Documentation is used to design bounded probes, but only authenticated response
schemas, permissions, timestamps and license terms can establish usable coverage.

**Rationale**: The proposal document records prior public documentation review and a failed
network attempt, not reproducible authenticated responses in this repository. A provider label
or advertised field is not evidence that the licensed account can retrieve the field historically.

**Alternatives considered**:

- Trust documentation alone: rejected because it cannot prove account permissions, history or
  point-in-time availability.
- Start a full backfill and inspect later: rejected because it risks bandwidth, licensing and
  irreversible leakage before feasibility is known.

## Decision 2: Preserve six independently governed data components

**Decision**: Underlying bars, corporate events, unusual events, ordinary option state,
contract trades and contract quotes have separate schemas, raw provenance and quality reports.

**Rationale**: Their timestamps, revision behavior, identifiers, missingness and licensing are
different. A single wide provider table would hide which component failed and would make B1/B2
comparisons difficult to audit.

**Alternatives considered**:

- One provider-normalized wide table: rejected because it collapses provenance and makes
  component-level schema drift invisible.
- Use only event data plus underlying bars: rejected because it cannot construct the required
  B1 ordinary option-state benchmark.

## Decision 3: Define point-in-time availability explicitly

**Decision**: Every predictor carries an `available_at` timestamp or a documented availability
  rule. A row is eligible only when `available_at <= forecast_origin` and the source timestamp
  is not a later revision.

**Rationale**: Event time alone does not prove when a provider made a value retrievable. This is
  the central guard against look-ahead bias in B1 and B2.

**Alternatives considered**:

- Use provider event timestamp as availability: rejected unless the response contract proves
  equivalence.
- Forward-fill the latest value through unknown availability: rejected; it creates hidden
  look-ahead and unreported imputation.

## Decision 4: Freeze assets using quality only

**Decision**: Audit all eight candidates, then select four to six using only predeclared
coverage, timestamp integrity, regular-session completeness, event frequency, contract
resolution and common-window overlap.

**Rationale**: Selecting by preliminary predictive performance would introduce selection bias
and invalidate the out-of-sample claim.

**Proposed configurable defaults**: 95% regular-session one-minute completeness, zero critical
duplicate keys, zero critical null prices, at least four passing assets, and a minimum overlap
parameter to be fixed after the provider audit. The exact overlap value is not asserted until
the common calendar and licensed history are observed.

## Decision 5: Use RV30 and nested benchmarks

**Decision**: The main target uses 31 prices: the fully observed close `C(i,t)` at the
forecast origin and `C(i,t+1)` through `C(i,t+30)`. It computes
`r(i,t+j)=ln[C(i,t+j)/C(i,t+j-1)]` for `j=1..30` and
`RV(i,t:t+30)=Σ(r(i,t+j)^2)`. B0 contains underlying/market controls, B1 adds ordinary
option state when independently validated, and B2 adds unusual activity. QLIKE is primary.

**Rationale**: The target and nested information sets isolate incremental information. A common
origin set and common chronological splits prevent sample changes from masquerading as signal.

**Alternatives considered**:

- Predict direction or returns: rejected because the ratified target is variance only.
- Use 15/60 minutes as primary: rejected; they remain robustness horizons only.
- Compare B2 with B0 by default: rejected; B2 versus B1 is the scientific comparison whenever
  B1 is feasible.

## Decision 6: Use a local package as the source of truth

**Decision**: Production logic, schemas and tests live in `src/mds650`; Colab imports that
package and presents configuration, quality tables, previews, validation status and manifests.

**Rationale**: A single modular implementation prevents notebook-only state and logic drift.

**Alternatives considered**:

- Build the pipeline entirely in a notebook: rejected because it hides state and duplicates
  production logic.
- Make Colab the canonical artifact: rejected because local tests and reproducible package
  imports are required.

## Decision 7: Python and dependency policy

**Decision**: Use Python 3.12.12 as the approved conservative runtime baseline. The automated
compatibility matrix proved clean installation and
imports/tests on Google Colab and Windows for Polars, PyArrow, DuckDB, LightGBM, scikit-learn,
SHAP, Optuna, Pydantic, Ruff, Mypy and Pytest. The final version is selected by demonstrated
compatibility, not by recency.

**Rationale**: A conservative baseline reduces wheel and Colab drift while preserving a
reproducible path. The owner approved the matrix on 2026-07-21, and only the runtime metadata
and lockfile were migrated; provider and production gates remain separate.

**Alternatives considered**:

- Use Python 3.10/3.14 solely because it is installed or newer: rejected because the matrix
  demonstrates compatibility across all required packages and platforms.
- Add every possible ML library immediately: rejected because the pilot and benchmark gates
  must justify dependencies and avoid supply-chain/compatibility drift.

## Decision 8: Fail closed on secrets, schema drift and licensing

**Decision**: Check only presence of credential variables before network calls; load values from
an approved runtime secret store; never print or commit them. Missing permissions, schema drift,
unresolved timestamps or restrictive licenses stop the affected gate.

**Rationale**: The credentials in the original prompt are exposed and must be rotated before
use. User-scope environment presence is not sufficient proof of safe use.

## Decision 9: Literature verification is a deliverable, not a promise

**Decision**: The ten-study matrix is accepted only when each source is independently resolved
by DOI or stable URL and its recorded claims, sample, target, model, benchmark and validation
match the primary source. Recent applications justify HAR and QLIKE; foundational papers are
reported separately.

**Rationale**: The available proposal contains a preliminary matrix, but those entries require
fresh verification and must not be promoted to confirmed evidence by repetition.

Literature is Phase 3B and runs in parallel with Phase 3A provider audit. The ten studies
must be verified before freezing variables, benchmarks, exact models (HAR, HARQ, OLS, LASSO,
Elastic Net, Random Forest, XGBoost, LightGBM, MLP and LSTM), metrics or methodological claims.
Each row records APA 7, authors, year, title, venue/status, DOI or stable URL, market/sample,
frequency, objective, predictors, exact models, exact benchmark, temporal protocol, leakage
control, metrics, result, limitation, exact project implication and verification status.

## Decision 11: Exploratory v0 classification and audit corrections

The existing manifest at `artifacts/api_audit/exploratory_v0/provider_audit_manifest.json` is
preserved byte-for-byte and classified as exploratory v0. It reports HTTP 200 FMP samples,
390 recent-session rows, an observed January 2015 depth window, zero sampled duplicates/nulls,
401/403 Massive directed-data blockers, duplicated eight-asset depth probes, and unresolved
timestamp semantics. It is not evidence that B1 is feasible.

The Unusual Whales schema uses `iv_start` and `iv_end`; the canonical alias map records
`ivStart -> iv_start` and `ivEnd -> iv_end`. `event_iv_fields_present` is separate from
`ordinary_option_state_pit_verified`. Only `created_at`, `start_time` and `end_time` may be
described unless another raw field is observed; `executed_at` is not asserted. Each field's
raw type, unit, semantics, timezone, conversion, forecast-origin relation and possible
post-availability must be documented in v1.

## Decision 12: Pre-registered evaluation and natural prevalence

The primary contrast is `Delta_B2 = QLIKE(B1a) - QLIKE(B2)` and the key secondary contrast is
`Delta_B1 = QLIKE(B0) - QLIKE(B1a)`. Uncertainty is a paired bootstrap by trading day, keeping
all assets and origins from a day together. Holm correction covers these two confirmatory
comparisons. Volatility/session/asset and timing-sensitivity strata are frozen before final-test
inspection. Minimum detectable effect is estimated using simulation, bootstrap, pilot or
training data only. Event/no-event origins preserve natural prevalence; any training-only
weighting is documented and never applied to validation/final testing.

## Decision 13: Use a 90-session champion–challenger design

**Decision**: Use eighty XNYS development sessions and ten prospective holdout sessions.
Reuse the existing twenty-five sessions after hash validation and acquire only fifty-five
missing development sessions. Freeze a compact nine-feature B2 information set without
consulting RV30 or QLIKE. Use Gamma GLM as the confirmatory positive-mean model, LightGBM with
Gamma objective as a fixed robustness challenger, QLIKE as primary loss, a paired whole-day
bootstrap and Holm correction. Read the holdout analytically once after method freeze.

**Rationale**: Twenty-five sessions are sufficient engineering evidence but too short for
credible temporal stability and model comparison. The 80/10 split supplies four expanding
development folds and an independent prospective check while reusing all valid evidence.
Gamma GLM is a parsimonious distribution-aligned confirmatory model; LightGBM tests nonlinear
robustness without allowing model shopping. The compact B2 registry reduces collinearity and
multiple-testing exposure while preserving distinct activity mechanisms.

**Alternatives considered**:

- Treat the current twenty-five sessions as final: rejected because stability and prospective
  validation would be weak.
- Use all candidate B2 fields: rejected because aliases, algebraic redundancy and target-blind
  dimensionality control favor the compact registry.
- Select the best model or feature set by QLIKE: rejected because it would optimize the
  specification to the observed sign.
- Use FMP `+2 minutes` as primary: rejected; `+1 minute` is the approved conservative research
  assumption and `+2 minutes` remains a sensitivity.

## Decision 10: Week-4 evidence recovery

**Decision**: If the initial network attempt remains unavailable, run a bounded authenticated
Colab audit after secret rotation, produce sanitized manifests and hashes, and stop before
backfill if B1 or the minimum asset gate fails.

**Rationale**: This preserves the distinction between regenerated artifacts and fresh provider
evidence and creates a durable handoff for the supervisor.

## Decision 14: Rebuild corrected development evidence without reconciling legacy results

**Decision**: Treat the FMP 90/90 exact-session and Unusual Whales 90/90 Full Tape metadata
findings as historical availability evidence, distinct from provider timing semantics. Keep FMP
`+1` minute primary / `+2` minute sensitivity as conservative study assumptions and retain UW
`created_at` as an operational-availability proxy. Build a new target-free predictor source
specifically for the eighty development sessions; v2.4 supplies control/provenance rules but is
not an interchangeable data window. Record an unresolved retained-session B1Q rate/dividend
input as a missing source, never as a stale substitute. Only then may a passing exact-window
release bind the predeclared eighty development sessions. Preserve the literal
`SAFE_TO_RECONCILE_EXISTING_RESULTS=NO` for sealed legacy outputs and
`SAFE_TO_OPEN_OR_EVALUATE_OOS=NO` until a separate holdout authorization.

**Rationale**: On 2025-10-20, observed record-creation delays can make a B2 zero ambiguous.
The v2.2 sidecar marks such rows excluded rather than inactive. Reusing the prior outcome
artifacts would hide this correction, whereas a separately hashed development release makes the
data lineage and exclusion policy auditable without reading the prospective holdout.

**Alternatives considered**:

- Flip the legacy reconciliation flag after the sidecar exists: rejected because sealed legacy
  outputs did not consume the mask.
- Treat all source-file availability as proof of publication timing: rejected because historical
  availability does not establish bar label, provider latency or customer receipt timing.
- Omit B2 delayed-source rows silently: rejected because the missingness mechanism is material
  and must remain visible in the release manifest.
- Retune the model or B2 registry after correction: rejected because it would introduce
  outcome-dependent model selection.

## Decision 15: Implement B1v3 additively and confirm it on a pristine sample

**Decision**: Keep legacy B1v2 immutable and implement B1v3 in a new target-blind module. Use
same-expiry/same-strike call-put consensus; near-30-day log ATM variance; same-expiry symmetric
0.975/1.025 log skew; and short/medium/long forward variance derived from total variance.
Changes use exact same-session 5/30-minute origins. Coverage must be nested and meet the explicit
FR-097 technical gates. Before outcomes, build a date-only exposure ledger and freeze the
earliest contiguous pristine 30-session XNYS block with 60 eligible preceding sessions.

**Rationale**: The legacy geometry can mix maturities and raw-IV term differences. The approved
construction measures coherent option-state quantities while preserving the scientific boundary:
feature formulas and feasibility are determined without RV30, QLIKE, predictions or result signs.
A pristine one-read confirmation separates a new test from earlier exploratory and forensic
exposure.

**Alternatives considered**:

- Rewrite legacy B1v2 in place: rejected because it would destroy auditability of sealed results.
- Choose the strongest target-free coverage variant after modeling: rejected because coverage
  may determine feasibility, but predictive sign may not determine the method.
- Use nearest or overnight values for missing lags: rejected because it changes the registered
  timing estimand and can introduce stale information.
- Clip negative forward variance to zero: rejected because it hides invalid quote/geometry states.
- Reuse a prior OOS interval: rejected because it is not a pristine independent confirmation.

## Decision 16: Diagnose B1 on development evidence and replicate B2 without a sign target

**Decision**: Preserve the sealed B1v3 result and diagnose the negative B1 contrast using only
the rolling 60-session training block from `2024-09-16` through `2024-12-09` and previously
exposed development evidence. Freeze a new, disjoint 30-session XNYS replication block from
`2024-12-10` through `2025-01-24` before any
provider payload or outcome access. Reuse the exact B0/B1v3a/B2 information sets, Gamma GLM,
fixed LightGBM challenger, QLIKE, descriptive MAE/RMSE, paired whole-day bootstrap, Holm family,
seed, timing assumptions and training-only MDE. Accept and retain positive, null or negative
replication outcomes without retrying or modifying the design by sign.

**Rationale**: The sealed evidence supports a Gamma-specific B2 improvement but does not show
that B1 improves B0 and does not establish model-independent replication. A development-only
mechanism diagnostic explains where B1 can fail without contaminating a fresh temporal test.
The date choice is a recorded replication-only amendment to the default study-window rule. The
default `2025-07-21`–`2026-07-21` interval has no 30-session block absent from prior Phase 5/6
exposure ledgers. The selected block is the earliest 30-session XNYS interval after the sealed
B1v3 evidence cutoff and before the next exposed interval. It is authorized only if FMP, UW and
Massive pass authenticated historical preflight for every frozen date. This preserves a
falsifiable replication without feature, asset, model or timing selection based on its result.

**Alternatives considered**:

- Declare the existing Gamma B2 result globally confirmed: rejected because the frozen
  LightGBM challenger disagrees and the same evaluation cannot be its own replication.
- Tune B1/B2 until both deltas are positive: rejected as outcome-driven model selection.
- Diagnose B1 with the new replication outcomes: rejected because it would contaminate the
  confirmatory block.
- Add RL, DL or another model family: rejected because this phase tests information-set
  replication, not an expanded model search.
- Replace RV30 or alter the six-asset universe: rejected because neither change is justified by
  target-blind data-quality evidence in this phase.
