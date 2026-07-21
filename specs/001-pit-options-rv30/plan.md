# Implementation Plan: Point-in-Time Options Activity for RV30 Forecasting

**Branch**: `001-pit-options-rv30-recovery` (feature identifier `001-pit-options-rv30`) | **Date**: 2026-07-20 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/001-pit-options-rv30/spec.md`

## Summary

The local modular package is authoritative. The authenticated audit, frozen-window pilot and
raw-evidence backfill have now been executed as bounded research artifacts after the approved
gates. The target is RV30 from 31 prices (the fully observed origin close plus the next 30
one-minute closes). B0 contains underlying/market controls, B1 validated ordinary option state
and B2 unusual activity; B2 versus B1 is the sole primary comparison and B0 is only a declared
fallback when B1 is infeasible. Current evidence declares B1 infeasible, so benchmark metrics
and predictive claims remain fail-closed.

## Technical Context

**Language/Version**: Python 3.12.12 is the approved conservative runtime baseline.
The owner approved the compatibility matrix on 2026-07-21; `pyproject.toml` and `uv.lock` now
target `>=3.12,<3.13`. The matrix covers Google Colab, Windows, Polars, PyArrow,
DuckDB, LightGBM, scikit-learn, SHAP, Optuna, Pydantic, Ruff, Mypy and Pytest. Version choice
must be compatibility-first, never based on novelty. The matrix includes a clean install from
the lockfile and an import/test smoke result for every row.

**Primary Dependencies**: `uv`, `pydantic-settings`, `httpx`, `polars`, `pyarrow`, `duckdb`,
`pytest`, `ruff`, `mypy`, `coverage`; the model set (`lightgbm`, `scikit-learn`, `shap`,
`optuna`) is compatibility-matrix gated and remains absent from runtime mutation until
approved.

**Storage**: Immutable raw responses outside Git, Parquet for normalized tables, DuckDB for
local analytical queries, and sanitized JSON/Markdown manifests. No provider raw payloads are
redistributed.

**Testing**: pytest unit/contract/integration/end-to-end tests, coverage, ruff and mypy;
bounded live queries are opt-in and never substitute for sanitized fixtures.

**Target Platform**: Windows local workstation with Colab as a presentation/orchestration
layer. The local modular package is authoritative.

**Project Type**: Internal research package and reproducible CLI-oriented pipeline.

**Performance Goals**: Bounded audit requests must respect provider rate limits and complete
without unbounded retries; pilot joins and target computation must be deterministic and
re-runnable. No production latency or trading-capacity claim is in scope.

**Constraints**: No network request before presence-only secret validation; no live orders,
email, deployment, publication or remote Git mutation; no historical backfill before audit,
pilot and tests pass; no synthetic or silent fallback data.

**Scale/Scope**: Eight candidate assets, six independently validated data components, a
configurable pilot window, and four to six frozen assets. The common provider history is the
maximum overlap verified by the audit.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **I. Evidence and Point-in-Time Truth**: PASS by design. Every normalized row carries
  source and availability metadata; unresolved timestamps fail closed.
- **II. Frozen Objective, Benchmarks and Scope**: PASS. RV30, B0/B1/B2, eight candidates,
  quality-only freeze, mandatory earnings and directed Massive validation are explicit in
  `spec.md`.
- **III. Tests First and Fail-Closed Data Contracts**: PASS. Tests precede backfill and schema
  drift/partial pagination are hard failures.
- **IV. Reproducibility, Security and Auditability**: PASS with a pre-run blocker. The
  credentials exposed in the chat must be rotated and loaded from an approved secret store;
  the unavailable requested source folder remains a provenance gap.
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
├── recovery/compatibility_matrix.md
└── recovery/{initial_repository_state,gap_analysis,audit_v0_findings,
    provider_audit_v1_plan,spec_kit_analysis_report}.md
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

## Verification Gates Before Implementation

1. Constitution, spec, clarify, plan, checklist, tasks and analyze complete with no critical
   inconsistency before implementation work is accepted.
2. Compatibility matrix and clean-install proof pass, and the runtime change is approved.
3. Secret rotation and presence-only preflight pass before any provider request.
4. Authenticated provider audit returns usable schemas and licenses before any historical
   backfill or modeling code is enabled.
5. At least four candidates meet quality/overlap gates and B1 feasibility is decided before
   asset freezing and benchmark evaluation.
6. Tests exist and pass against sanitized fixtures before production backfill.

The bounded execution produced pilot and backfill manifests under
`artifacts/pipeline_runs/window_20260721/`, while retaining raw provider bytes outside Git.
Those artifacts are evidence only: unresolved FMP bar semantics and ordinary option-state PIT
availability keep model evaluation and benchmark claims fail-closed. Any stop condition in
`spec.md` produces an exact manifest blocker and stops downstream work.

## Complexity Tracking

No constitution violations require justification. The apparent multi-provider modularity is
the minimum separation needed to prevent provider-specific timestamps, pagination and license
rules from contaminating the common analytical contract.
