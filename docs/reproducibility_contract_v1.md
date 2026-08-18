# Reproducibility contract (v1, 2026-08-18 — decision 63)

Reviewer correction accepted: **computational reproducibility ≠ data
reproducibility**, and the repo now states exactly which one a stranger gets.

## What a third party CAN reproduce (no licenses, no local storage)

From a clean public clone — or the container — with zero provider keys:

1. **The hermetic suite** (189/193 test files, coverage ≥ 80 %): every
   methodological unit, property, schema and synthetic end-to-end contract.
2. **The public demo pipeline** `scripts/run_public_repro_demo.py` — the complete
   methodological chain on redistributable synthetic data:
   PIT availability join (late quotes excluded, never hindsight) → feature
   construction → purge/embargo split → gamma_glm / lightgbm / har_rv
   (log-linear ext.) → QLIKE → wild + moving-block bootstrap → Model Confidence
   Set → claim-ledger generation. Deterministic (seed 650); runs in CI on every
   push (`tests/e2e/test_public_repro_demo.py`). Its numbers are synthetic and say
   nothing about the licensed results.

Container:

```bash
docker build -t mds650-repro .
docker run --rm mds650-repro
```

## What requires the data custodian

Rebuilding the licensed panels and the registered numbers needs provider
entitlements (FMP, Unusual Whales, Massive) and the local evidence store; the
canonical route (`artifacts/canonical_validation_v1/reproduce.ps1`, tier-2 gates)
validates hashes end-to-end for the custodian. Reviewers can additionally request
gated derived files per `data/DATA_ACCESS.md` and verify them against published
SHA-256 pointers.

## Windows-path residuals — honest status

Hardcoded `D:/MDS650` paths remain **only inside frozen-campaign scripts**, kept
verbatim as the reproducibility record of what actually ran (editing frozen-era
code would violate decision 62's spirit). Everything current is root-agnostic:
`MDS650_EXTERNAL_ROOT` / `MDS650_EVIDENCE_ROOT` env vars, and the four tests that
hard-require the local store are tier-2-only (`docs/ci_contract_v1.md`). The
hermetic suite and the demo touch none of them — proven on every ubuntu run.
