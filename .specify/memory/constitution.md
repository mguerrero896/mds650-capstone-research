<!--
Sync Impact Report
- Version change: 1.0.0 -> 2.0.0
- Modified principles:
  - II. Frozen Objective, Benchmarks and Scope: B1a is the primary ordinary-option benchmark;
    earnings move from mandatory primary controls to gated diagnostic stability analysis.
  - V. Statistical Validity and Honest Interpretation: exact confirmatory comparisons,
    prospective one-read holdout, paired-day bootstrap, Holm and complete sign reporting added.
- Added sections: none.
- Removed sections: none.
- Templates reviewed: .specify/templates/plan-template.md, spec-template.md and
  tasks-template.md remain generic and require no edits.
- Dependent artifacts updated: specs/001-pit-options-rv30/{spec,plan,tasks,data-model,
  quickstart}.md, contracts/benchmark-evaluation-contract.md,
  docs/methodology_decisions.md.
- Deferred: clean-install parity evidence on Google Colab remains an implementation gate.
-->
# MDS650 Research Pipeline Constitution

## Core Principles

### I. Evidence and Point-in-Time Truth
Every research datum MUST have a recorded provider, request time, source timestamp,
timezone, schema version and provenance identifier. Predictors MUST be available at the
forecast origin; future values, revised values and ambiguous timestamps MUST be rejected.
Raw provider responses MUST remain immutable and separate from normalized analytical data.

### II. Frozen Objective, Benchmarks and Scope
The primary target is only the realized variance accumulated during the thirty minutes
following each five-minute forecast origin. B0 contains underlying and market controls,
B1a adds validated point-in-time ATM implied volatility, and B2 adds the preregistered
trade-derived option-activity features. B1b adds skew and B1c adds term structure only as
enriched robustness benchmarks. The primary scientific comparison is B2 versus B1a; B1a
versus B0 is the key secondary confirmatory comparison. The eight candidate assets MUST be
audited together and only four to six MAY be frozen, using coverage and data quality only;
predictive performance MUST NOT influence asset selection. Earnings MUST remain outside the
primary B0/B1a/B2 comparison; ex-ante BMO/AMC timing MAY be used only in predeclared
diagnostic stability analysis after its own point-in-time gate. Actual EPS and revenue are
prohibited predictors. News is optional and requires its own timestamp, coverage and
reproducibility gate. Massive is restricted to directed historical contract/quote extraction
and MUST NOT be used for a full historical OPRA quote download.

### III. Tests First and Fail-Closed Data Contracts
Tests MUST be written before production backfill or modeling. Unit, sanitized-contract,
live-small-query, pagination, timezone/DST, point-in-time leakage, duplicate/missing-data,
deterministic-target and pilot end-to-end tests are mandatory. A missing expected field,
schema drift, incomplete pagination or failed quality threshold MUST fail the run explicitly;
the pipeline MUST NOT silently fabricate, substitute or forward-fill provider data.

### IV. Reproducibility, Security and Auditability
Secrets MUST remain outside Git, notebooks and logs. API credentials MUST be loaded at
runtime from an approved secret store and checked only for presence before network access.
Every run MUST emit a sanitized machine-readable manifest and a human-readable report with
configuration, software versions, request metadata, hashes, seeds, decisions and licensing
constraints. The modular local package is the source of truth; Colab is orchestration and
presentation only. No broker orders, emails, deployments or external publications are in
scope.

### V. Statistical Validity and Honest Interpretation
Model comparisons MUST use common expanding walk-forward splits, a final untouched test
period read analytically once, and purging/embargo of at least the thirty-minute target
horizon. QLIKE is the primary loss; MAE and RMSE are descriptive secondary metrics.
Uncertainty MUST use a paired whole-day cluster bootstrap that keeps all assets and origins
from a date together, and Holm MUST cover the two confirmatory information-set comparisons.
Feature definitions, models, grids, folds, seeds, stability strata and effect-size protocol
MUST be preregistered before loss computation. Positive, negative and null registered results
MUST all be retained; no method may be selected or revised to obtain a favorable sign.
Option execution proxies MUST NOT be described as trader intent, opening flow, causality or
profitability without independent evidence.

## Data, Licensing and Security

The six data components are governed independently: one-minute underlying OHLCV, structured
corporate events, unusual-option events, point-in-time ordinary option state, contract-level
option trades, and consolidated bid/ask quotes. Provider licenses and redistribution limits
MUST be recorded before backfill. Raw licensed responses MUST NOT be committed or redistributed.
The requested source folder is a required provenance input; if unavailable, the gap MUST be
reported and no claim may be presented as verified solely from that missing material.

## Research Workflow and Quality Gates

The project MUST execute the following sequence before implementation: Spec Kit constitution,
specification, clarification, plan, requirements checklist, tasks and cross-artifact analysis.
The first production action after those gates is the test suite and small authenticated audit,
not historical backfill. Stop conditions are mandatory when B1a is infeasible, fewer than four
assets meet quality thresholds, provider windows do not overlap sufficiently, material
timestamps cannot be established point-in-time, or provider licenses prohibit the evidence
package.

## Governance

This constitution is the highest-priority project rule. Any amendment MUST state the reason,
impact, affected artifacts and migration or rollback implications. Versioning follows semantic
versioning: MAJOR for incompatible governance changes, MINOR for new or materially expanded
principles, and PATCH for wording-only corrections. Every change MUST update the Sync Impact
Report and the last-amended date. Spec, plan, checklist and task reviews MUST include a
constitution compliance check. No implementation may proceed with unresolved constitution
violations; a violation requires an explicit amendment before work continues.

**Version**: 2.0.0 | **Ratified**: 2026-07-20 | **Last Amended**: 2026-07-29
