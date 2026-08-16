#!/usr/bin/env sh
set -eu

python -m pip install --disable-pip-version-check -q uv==0.9.24
UV_PROJECT_ENVIRONMENT=/tmp/mds650-venv uv sync --frozen --link-mode copy
/tmp/mds650-venv/bin/python -c "import duckdb, lightgbm, mds650, polars, pyarrow, sklearn; print('IMPORTS_PASS')"
/tmp/mds650-venv/bin/pytest -q -p no:cacheprovider --override-ini addopts= \
  tests/contract/test_phase5_preregistration.py \
  tests/contract/test_phase5_holdout_guard.py \
  tests/unit/test_phase5_study_design.py
/tmp/mds650-venv/bin/ruff check --cache-dir /tmp/ruff-cache src tests
/tmp/mds650-venv/bin/mypy --cache-dir /tmp/mypy-cache src
