# Runtime compatibility matrix — recovery evidence

Status: approved and applied on 2026-07-21. The runtime contract is now Python 3.12.
The lockfile was regenerated from the approved metadata; the audit-only development dependency
remains available for calendar/schema checks.

## Decision rule

Select the lowest conservative Python version that has demonstrated package resolution and
import smoke coverage on Windows, plus a Linux wheel-resolution check representative of Google
Colab. Do not select a version because it is newest. Apply the selected version only after a
clean install from the repository lockfile and explicit owner approval.

## Required package set

The smoke set covers the requested data, model, explanation, tuning and quality tools:

`polars`, `pyarrow`, `duckdb`, `lightgbm`, `scikit-learn`, `shap`, `optuna`, `pydantic`,
`pydantic-settings`, `ruff`, `mypy`, `pytest`, and `coverage`.

The audit-only calendar diagnostic additionally uses `exchange-calendars>=4.11,<5` for the
XNYS session schedule. It is a development/audit dependency and does not change the runtime
selection decision.

## Evidence collected 2026-07-20

| Python | Windows resolution | Linux/Colab resolution | Windows import smoke | Result |
|---|---|---|---|---|
| 3.12.12 | PASS (`uv pip install --dry-run`) | PASS (`uv pip install --dry-run`) | PASS; all required imports | Candidate |
| 3.13.11 | PASS (`uv pip install --dry-run`) | PASS (`uv pip install --dry-run`) | PASS; all required imports | Candidate |
| 3.14.2 | PASS (`uv pip install --dry-run`) | PASS (`uv pip install --dry-run`) | PASS with `coverage>=7.10,<8`; an unconstrained ephemeral smoke inherited an incompatible coverage/numba combination | Conditional |

The Windows import smoke used isolated `uv run --no-project --link-mode=copy` environments,
never the repository environment. The 3.12 run installed 47 packages and printed
`3.12.12 imports=pass`; 3.13 printed `3.13.11 imports=pass`; 3.14 printed
`3.14.2 imports=pass` after explicitly including the repository's coverage range.

Linux resolution used `uv pip install --dry-run --python-platform linux`; it verifies that
Colab-compatible wheels and dependency metadata resolve, but it is not a Linux execution test.
The local WSL image lacks `python3-venv`, so a Linux import smoke was not falsely claimed.

## Approved runtime

Python **3.12.12** is approved and applied because it passed the complete Windows import smoke,
resolves the Linux/Colab target, and avoids making the project depend on the newest interpreter.
The repository contract and lockfile now target Python 3.12. A fresh installation was executed:

```powershell
uv venv --python 3.12 .venv-matrix
uv sync --frozen --link-mode copy --python 3.12.12 --project .
uv run --python .venv-matrix\Scripts\python.exe pytest -q
uv run --python .venv-matrix\Scripts\python.exe ruff check src tests
uv run --python .venv-matrix\Scripts\python.exe mypy src
```

The temporary target `<LOCAL_VERIFY_ENV>` installed
the exported locked project with `uv sync --frozen --link-mode copy --python 3.12.12` and ran
Python 3.12.12, 68 tests, Ruff and Mypy successfully. No provider request was made.

## Reproduction commands

The resolution probe used the following bounded requirement ranges for each Python/platform
pair; it did not access provider APIs:

```powershell
uv pip install --dry-run --target <temporary-target> --python-version 3.12 \
  --python-platform windows \
  "polars>=1.35,<2" "pyarrow>=22,<23" "duckdb>=1.4,<2" \
  "lightgbm>=4.6,<5" "scikit-learn>=1.7,<2" "shap>=0.48,<1" \
  "optuna>=4.5,<5" "pydantic>=2.12,<3" "pydantic-settings>=2.11,<3" \
  "ruff>=0.14,<1" "mypy>=1.18,<2" "pytest>=8.4,<9" "coverage>=7.10,<8"
```

Repeat with `3.13`, `3.14`, and `--python-platform linux`. Treat any resolver failure,
missing wheel, import failure or clean-install test failure as a hard compatibility blocker.
