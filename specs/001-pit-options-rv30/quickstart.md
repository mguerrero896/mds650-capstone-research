# Spec-driven quickstart

This quickstart validates the repository and specification gates without
performing provider requests, historical backfill, broker activity, or other
external mutation.

## Prerequisites

PowerShell 7, Git, `uv`, and the Spec Kit CLI must be available. Python 3.12.12 is the
approved runtime baseline. The compatibility matrix proves clean installation on Windows and
resolution for Google Colab for Polars,
PyArrow, DuckDB, LightGBM, scikit-learn, SHAP, Optuna, Pydantic, Ruff, Mypy and Pytest.

## Validate the current gates

```powershell
specify self check
specify check-prerequisites
git status --short
Get-ChildItem -Recurse -File .specify, specs\001-pit-options-rv30
Get-FileHash -Algorithm SHA256 artifacts\api_audit\exploratory_v0\provider_audit_manifest.json
```

The first two commands must succeed. The recovery working tree may contain only the
Spec Kit scaffolding, documentation/contracts and the preserved exploratory manifest at
this stage. The manifest hash must match the recorded recovery evidence; its duplicate
depth probes are expected defects, not reasons to rewrite the artifact.

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

## Planned implementation gate

After the tasks are implemented and the runtime is approved, use `uv sync --locked`, then run `pytest`,
`ruff check .`, `mypy src`, and the documented small live-integration tests. The
first live request must generate a sanitized provider-audit manifest and raw
response hashes; it must not start a backfill when any acceptance rule fails.

The Colab notebook will install a tagged repository revision and call the same
`src/mds650` functions. It is an orchestration and presentation layer, not a
second implementation.

## Target contract checkpoint

For an origin `t`, the target requires the fully observed close `C(i,t)` plus exactly the
next thirty consecutive one-minute closes. It produces exactly thirty returns:
`r(i,t+j)=ln[C(i,t+j)/C(i,t+j-1)]`, `j=1..30`, and their squared sum. Missing any of the
31 prices, unresolved FMP bar start/close semantics, an early close or an unidentified halt
is a hard invalid status; no silent interpolation is allowed.
