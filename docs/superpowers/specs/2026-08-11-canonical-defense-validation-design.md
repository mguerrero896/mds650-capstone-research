# Canonical RV30 Defense Validation Design

## Status and authority

**Status:** owner-approved active-goal design.

**Authority:** the active goal requires a reproducible, defense-ready conclusion about the
incremental predictive value of B2 over B1 without selecting a favourable result.  Earlier
Phase 5, Phase 6 and independent-replication artifacts remain immutable historical evidence.
This design neither rewrites their outcomes nor treats a post-read reanalysis as a fresh
holdout.

## Problem to close

The repository has valid, separately recorded evidence but lacks one canonical artifact that
does all of the following at once:

1. proves chronological train-before-test separation for every model, block and fold;
2. reconciles six outcome assets with eight acquired symbols;
3. evaluates B0, B1a and B2 on identical origins for Gamma GLM, HAR-RV, Ridge, Elastic Net
   and LightGBM; and
4. produces defense-ready claims, limitations, tables, figures, model cards, hashes and a
   reproducible notebook without hiding model disagreement.

The outcome universe is AAPL, AMZN, META, MSFT, NVDA and TSLA.  SPY and QQQ are acquired
market-control inputs, not outcome assets.  This is a data-role distinction, not an asset
selection based on predictive performance.

## Evidence boundaries

The implementation uses existing local evidence only:

- Phase 6: 180 sessions, five expanding historical OOS folds, and the pre-existing
  `GammaRegressor` and LightGBM forecasts;
- independent replication: 59 usable warm-up sessions and 30 historical target sessions,
  with the 2025-04-04 provider CRC incident retained explicitly; and
- earlier B2 confirmation and development artifacts as contextual, non-substitutable evidence.

No provider call, raw-data deletion, feature redesign, hyperparameter search, asset
reselection, or new result-based rule is permitted during this work.  A later acquisition can
be proposed only through a written necessity audit showing that existing data cannot answer a
specific unresolved question.

### External evidence custody

The current clean worktree intentionally does not contain untracked Phase 6 and
independent-replication artifacts.  Canonical-validation commands therefore accept one explicit
read-only evidence root through `MDS650_EVIDENCE_ROOT`; they fail if it is absent, if its hashes
do not match the recorded manifests, or if it points to the output worktree.  This makes the
dependency visible without modifying the dirty canonical checkout, copying commercial data into
Git, or leaking its personal absolute path into generated artifacts.  The reproducibility
handoff records only the environment-variable name and input hashes.

## Canonical row and causal contract

One canonical row represents one outcome asset at one valid five-minute XNYS forecast origin.
All B0, B1a and B2 rows for a comparison must have the identical `origin_id` set.  The target
is RV30, computed from the close at origin plus the next thirty consecutive one-minute closes,
which produces exactly thirty log returns.  Missing observations remain missing; they are never
interpolated, replaced by zero, or silently shifted.

For every `block × fold × model_role × information_set`, the audit must record:

- earliest and latest training origin and session;
- earliest and latest evaluation origin and session;
- configured target horizon, purge and embargo;
- observed temporal gap; and
- source-panel, feature-schema, parameter and prediction hashes.

The execution fails if a training origin can overlap a protected evaluation target interval, if
an evaluation origin is not later than the final training origin, or if nested information sets
do not share exactly the same origin identifiers.

## Information-set contract

The nested, frozen comparison is:

- **B0v2:** underlying and market controls available at origin;
- **B1v2a:** B0v2 plus ordinary option-state variables constructed by an as-of join;
- **B2v2:** B1v2a plus the nine target-blind abnormal-activity features.

`created_at <= origin - 60 seconds` remains an operational-availability proxy for B2, not a
claim about publication time.  No target, QLIKE, residual, OOS result or future observation is
used when constructing B2.  B1 remains point-in-time and uses only qualifying historical
quotes.  The canonical scope is B1v2a; B1v2b/B1v2c remain separately reported coverage
robustness evidence rather than silently substituted primary benchmarks.

## Model contract

Every model receives the same fold and same complete origin set for a given information-set
comparison.  The five roles are fixed:

| Role | Status | Parameters |
|---|---|---|
| Gamma GLM | historical confirmatory role | Exact frozen Phase 6 parameters when replaying Phase 6; no replacement grid. |
| HAR-RV | fixed audit extension | lagged RV predictors only; no target-period inputs. |
| Ridge | fixed audit extension | `alpha=1.0`. |
| Elastic Net | fixed audit extension | `alpha=0.01`, `l1_ratio=0.5`. |
| LightGBM | historical robustness role | Exact frozen Phase 6 parameters when replaying Phase 6; no new search. |

HAR-RV, Ridge and Elastic Net are explicitly labelled `POST_READ_FIXED_EXTENSION` for any block
whose targets have already been accessed.  They are useful for model-dependence diagnosis, not
new independent confirmation.  Gamma and LightGBM preserve their registered roles and the
original predictions remain immutable.

Deep learning and reinforcement learning are out of scope.  DL would introduce high
model-selection risk relative to the independent-day count; RL would change the question from
forecasting RV30 to sequential trading decisions and require execution, reward and cost
contracts that this study does not have.

## Evaluation and interpretation contract

The primary estimands remain:

`Delta_B1 = mean(QLIKE(B0v2) - QLIKE(B1v2a))`

`Delta_B2 = mean(QLIKE(B1v2a) - QLIKE(B2v2))`

A positive value favours the expanded information set.  QLIKE is primary; MAE, RMSE and
calibration are descriptive diagnostics.  Daily-cluster paired bootstrap intervals, frozen MDE,
Holm-adjusted families, drift, feature redundancy and stability by asset, session tercile,
volatility regime and approved timing assumptions are reported for every model and every sign.

The final conclusion follows this hierarchy:

1. **global edge** only when confirmatory and robustness evidence satisfy the frozen global
   rule and materiality threshold;
2. **model-family dependent** when credible signs differ by fixed model family;
3. **conditional** when effects are restricted to preregistered strata and cannot support a
   global statement; or
4. **not supported** when the evidence fails the prior conditions.

No positive, negative or null outcome is removed.  A post-read canonical reanalysis cannot be
presented as a second independent OOS test.

## Architecture

The implementation has two bounded deliverables.

1. **Canonical-validation package:** recover exact frozen sources, validate the historical
   evidence, construct a causal ledger, run fixed-model comparisons on shared origin sets, and
   write sanitized machine-readable artifacts under `artifacts/canonical_validation_v1/`.
2. **Defense package:** render the canonical conclusion into a report, figures, tables, model
   cards, claims/limitations ledger and a modular notebook.  The user-provided Word and
   PowerPoint originals remain untouched; any revised copies are versioned under
   `deliverables/canonical_validation_v1/`.

The canonical package will reuse existing temporal-validation, model-fitting, metrics and
hashing utilities before adding code.  New code is limited to adapters and validators required
to join their existing interfaces; no custom framework or dependency is introduced.

## Required artifacts

At minimum, the finished package must contain:

- `artifacts/canonical_validation_v1/causal_audit.parquet` and summary JSON;
- `artifacts/canonical_validation_v1/origin_set_audit.json`;
- `artifacts/canonical_validation_v1/predictions.parquet` and metrics/contrast/stability JSON;
- `artifacts/canonical_validation_v1/model_variant_ledger.json`;
- `artifacts/canonical_validation_v1/evidence_index.csv` and source snapshot hashes;
- `docs/canonical_validation_conclusion.md`, `docs/canonical_claims_and_limitations.md`, and
  five model cards;
- a reproducible notebook that imports package functions rather than duplicating production
  logic; and
- versioned report, presentation, tables and figures.

All published artifacts must be sanitized: no secrets, provider payloads, personal paths or
commercial raw data are committed.

## Verification and completion rules

The validation suite must demonstrate causal ordering, target isolation, origin equality,
nested-information-set invariants, deterministic reruns, invariant model parameters, hash
integrity, absence of secret and personal-path leakage, and agreement between human-readable
tables and machine-readable results.  It must run with `uv run` on Python 3.12.

Completion requires successful project gates, a locally committed and tagged branch, and an
evidence-backed canonical conclusion.  If the results are model-dependent, conditional or not
supported, those are completed scientific outcomes, not implementation failures.

## Design self-review

- No source evidence is overwritten or discarded.
- The post-read status of new model-family calculations is explicit.
- Existing data is used first; acquisition has a separate necessity gate.
- All required goal outputs have an artifact owner and verification rule.
