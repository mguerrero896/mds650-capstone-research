# Canonical RV30 defense quality gate

Audit checkpoint: 2026-08-11, branch `codex/b2-defense-readiness-20260811`.

## Results

| Gate | Command | Result |
| --- | --- | --- |
| Full tests | `uv run pytest -q -rA` | **PASS** — 325 passed, 12 explicit skips, 0 failures (337 collected) |
| Ruff | `uv run ruff check src tests scripts` | **PASS** |
| Mypy | `uv run mypy` | **PASS** — no issues in 34 source files |
| Coverage | `uv run coverage run -m pytest -q; uv run coverage report` | **PASS** — 80% total, configured floor met |
| Notebook contract | `uv run pytest tests/contract/test_canonical_notebook.py -q` | **PASS** — 2 tests |
| Handoff contract | `uv run pytest tests/contract/test_final_validation_handoff.py -q` | **PASS** — 2 tests |
| Package rerender | `uv run python scripts/build_canonical_defense_package.py --source artifacts/canonical_validation_v1 --output <temporary-output>` | **PASS** — source validated; output hashes equal the recorded package hashes |
| Notebook execution | execute every code cell in `notebooks/MDS650_Canonical_RV30_Defense.ipynb` with `uv run python` | **PASS** |
| Notebook reproducibility | regenerate twice and compare SHA-256 | **PASS** — `B8884E0496D2035C3C0DEACE894FC5E50965A150F58100B41359BC8A02003A9B` |
| Diff hygiene | `git diff --check` | **PASS** |
| Sanitized artifact scan | scan new notebook/report/script for secrets and personal paths | **PASS** |

The 12 skips are explicit: ten evidence tests require the external
`MDS650_EVIDENCE_ROOT`, and two legacy Phase 4A checks require artifacts that are not part of
this defense worktree. They are not converted to passes.

## Scientific gates

- Causal audits: 25/25 Phase 6 role-fold rows and 5/5 independent role-fold rows pass.
- Shared-origin pairing: zero unpaired rows.
- Minimum observed train-to-test separation: 1,115 minutes; protected interval: 60 minutes.
- Registered decision: `MODEL_FAMILY_DEPENDENT` for B1 and B2 contrasts.
- Independent Gamma B2: positive and above the frozen MDE.
- Independent LightGBM B2: negative and below the frozen MDE.
- FMP bar start/close semantics: **UNVERIFIED**.
- UW publication-time semantics for `created_at`: **UNVERIFIED**; operational proxy only.
- Continuous all-provider common history: **UNVERIFIED**.

## Release boundary

The package is ready for an evidence-bounded academic defense. It is not authorization for a
new model family, new data acquisition, trading deployment, or a universal predictive-edge
claim. Existing V1/V2 provider and pilot artifacts remain immutable; the new notebook and
handoff are additive.
