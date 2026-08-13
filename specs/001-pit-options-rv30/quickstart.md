# Spec-driven quickstart

This quickstart first validates the repository, specification and preregistration gates
without provider requests or external mutation. Later commands are enabled only after those
gates pass and remain development-only until the one-time holdout release.

## Prerequisites

PowerShell 7, Git, `uv`, and the Spec Kit CLI must be available. Python 3.12.12 is the
approved runtime baseline. The compatibility matrix must prove clean installation on Windows
and resolution for Google Colab for Polars,
PyArrow, DuckDB, LightGBM, scikit-learn, SHAP, Optuna, Pydantic, Ruff, Mypy and Pytest.

## Validate the current gates

```powershell
specify self check
specify check-prerequisites
git status --short
Get-ChildItem -Recurse -File .specify, specs\001-pit-options-rv30
Get-FileHash -Algorithm SHA256 artifacts\api_audit\exploratory_v0\provider_audit_manifest.json
```

The first two commands must succeed. The recovery working tree is intentionally preserved and
may contain earlier evidence; every new commit must therefore be scoped to exact paths. The
exploratory manifest hash must match the recorded recovery evidence; its duplicate depth probes
are expected defects, not reasons to rewrite the artifact.

## Compatibility gate

Record an executable matrix with columns `runtime`, `platform`, `package`, `version`,
`install_result`, `import_result`, `smoke_result`, `colab_result`, and `evidence_hash`.
Run it in a disposable environment from the existing lockfile. The matrix must cover
Python 3.12 first and compare later interpreters only as compatibility hypotheses. The selected
baseline is recorded in `pyproject.toml` and `uv.lock`; rerun the gate after dependency changes.

## Presence-only secret gate

```powershell
'UNUSUALWHALES_API_KEY','MASSIVE_API_KEY','FMP_API_KEY' | ForEach-Object {
  [pscustomobject]@{ Name = $_; Present = [bool](Get-Item "Env:$_" -ErrorAction SilentlyContinue) }
}
```

Never print values. Before enabling live audit requests, rotate credentials that
were exposed in chat and load replacement values from the local secret store or
Colab Secrets. A missing value is a hard, fail-closed result.

## Phase 5 preregistration gate

After the Phase 5 tasks are implemented:

```powershell
uv sync --locked
uv run pytest -q
uv run python scripts/freeze_phase5_preregistration.py
Get-FileHash -Algorithm SHA256 artifacts\phase5\study_sessions_90.json
Get-FileHash -Algorithm SHA256 artifacts\phase5\preregistration.json
uv run python scripts/prepare_phase5_storage.py --dry-run
```

The session manifest must contain exactly 80 development and 10 holdout dates. The
preregistration must have status `FROZEN_BEFORE_MODEL_OR_QLIKE`, `holdout_reads=0`, the nine
B2 fields, four outer folds, Gamma/LightGBM roles, QLIKE, 10,000 day-bootstrap draws, seed 650
and Holm. The dry-run must show writable `D:\MDS650` roots and projected peak free space of at
least 80 GB.

## Development acquisition and panel gate

Only after preregistration:

```powershell
uv run python scripts/run_phase5_development.py --development-only --resume
uv run python scripts/build_phase5_common_panel.py
uv run pytest tests\unit\test_phase5_features.py tests\contract\test_phase5_panel.py -q
```

The run reuses 25 matching retained hashes, acquires 55 missing development sessions and never
reads a holdout date. The common panel must have 80 unique sessions, unique origin IDs, matching
RV30 hashes across B0/B1a/B2 and no predictor timestamp after its origin.

## Development evaluation and holdout gate

```powershell
uv run python scripts/run_phase5_development_evaluation.py
uv run python scripts\run_phase5_holdout.py --check-only
```

The first command may run only with the frozen preregistration and records every registered
variant. The holdout check must remain blocked until all ten sessions complete, method hashes
are frozen, leakage/reproducibility tests pass and the access ledger still shows zero reads.
After release, the analytical holdout command may succeed exactly once; a second read must fail.

Before any claim, run:

```powershell
uv run pytest -q
uv run ruff check .
uv run mypy src
uv run coverage run -m pytest
uv run coverage report --fail-under=80
```

The first live request must generate sanitized request metadata and raw response hashes; it must
not continue when any acceptance rule fails.

The Colab notebook will install a tagged repository revision and call the same
`src/mds650` functions. It is an orchestration and presentation layer, not a
second implementation.

## Corrected development release gate

This gate is local and development-only. It does not acquire data, change sealed legacy results
or open the prospective holdout.

```powershell
uv run pytest -q tests\contract\test_corrected_development_release.py `
  tests\unit\test_corrected_development_gate.py
uv run python scripts\build_corrected_development_release.py --check-only
```

The gate must prove: an exact-window target-free source for the eighty development dates (the
180-session v2.4 panel is control/provenance only); zero holdout overlap; source-hash bindings
for the source-coverage ledger, B2 sidecar, PIT v2.1 gate and Massive reselection; no target
payload during predictor construction; explicit B2 exclusions rather than zeroes; and no stale
or carried-forward B1Q rate/dividend substitute. If coverage is incomplete, it writes a
`BLOCKED_SOURCE_COVERAGE` artifact and must not bind targets.
Only then may the separate development target-binding command run. It must retain
`SAFE_TO_RECONCILE_EXISTING_RESULTS=NO` and `SAFE_TO_OPEN_OR_EVALUATE_OOS=NO`.

After a development-only method freeze, use:

```powershell
uv run python scripts\run_corrected_development_evaluation.py --development-only
```

The command must use the frozen B0/B1a/B2 information sets and method settings, write a new
result ledger, retain all signs and registered variants, and fail before reading any holdout path.

## Target contract checkpoint

For an origin `t`, the target requires the fully observed close `C(i,t)` plus exactly the
next thirty consecutive one-minute closes. It produces exactly thirty returns:
`r(i,t+j)=ln[C(i,t+j)/C(i,t+j-1)]`, `j=1..30`, and their squared sum. Missing any of the
31 prices, unresolved FMP bar start/close semantics, an early close or an unidentified halt
is a hard invalid status; no silent interpolation is allowed.

## B1v3 target-blind implementation checkpoint

Run the focused tests before materializing the full target-free corpus:

```powershell
uv run pytest -q tests\unit\test_b1v3.py `
  tests\unit\test_build_b1v3_target_blind.py
uv run ruff check src\mds650\b1v3.py scripts\build_b1v3_target_blind.py `
  tests\unit\test_b1v3.py tests\unit\test_build_b1v3_target_blind.py
uv run mypy --strict src\mds650\b1v3.py scripts\build_b1v3_target_blind.py
```

Then verify at least 80 GiB free on `D:` and run exactly one target-free build:

```powershell
uv run python scripts\build_b1v3_target_blind.py `
  --input D:\MDS650\phase6\data\b1q\b1_iv_attempts_20d.parquet `
  --output-root artifacts\b1v3_target_blind
```

The command must emit schema-valid, self-hashed evidence, one unique row per origin, exact
0/60/300-second Massive cutoff variants, nested coverage and no RV30/QLIKE/result field. A second
identical run must preserve every output byte or fail closed.

Plan the independent sample without reading outcomes:

```powershell
uv run pytest -q tests\unit\test_b1v3_confirmation.py
uv run python scripts\plan_b1v3_confirmation.py `
  --output-root artifacts\b1v3_confirmation_plan
```

Expected pre-evaluation state: exactly 60 training/warmup sessions and 30 contiguous pristine
confirmation sessions, or literal `NO_PRISTINE_30_SESSION_BLOCK`; `confirmation_reads=0` and
`SAFE_TO_EVALUATE_B1V3=NO`. QLIKE must not run from this quickstart checkpoint.
