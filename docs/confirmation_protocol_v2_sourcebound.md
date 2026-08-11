# Confirmation Protocol v2 — Source-Bound, Pre-Method-Freeze

## Purpose

This protocol binds the next MDS650 method-freeze decision to the corrected,
source-bound B0/B1Q/B2 predictor panel. It is a planning and integrity
artifact only. It does not authorize acquisition, model fitting, QLIKE,
reconciliation of earlier results, or access to sealed OOS data.

## Current canonical inputs

| Contract | Canonical source |
|---|---|
| Source-bound predictor manifest | `artifacts/target_blind_v23_sourcebound_20260812/target_blind_common_predictor_manifest_v23.json` |
| Source-bound successor preregistration | `artifacts/target_blind_v23_sourcebound_20260812/next_confirmation_preregistration_v3.json` |
| Predictor panel | `D:/MDS650/phase6/derived/target_blind_v23_sourcebound_20260812/target_blind_common_predictors_v23.parquet` |
| Common-complete subset | `D:/MDS650/phase6/derived/target_blind_v23_sourcebound_20260812/target_blind_common_complete_v23.parquet` |

The v3 preregistration is self-hashed and binds the v2.3 manifest, the prior
method template, the source hashes, the builder hashes and the timing rules.
It carries forward exactly nine B2 features from the already sealed template;
it does not select features using RV30, QLIKE, model output, or a favorable
sign.

## Non-negotiable current gates

```text
SAFE_TO_RECONCILE_EXISTING_RESULTS=NO
SAFE_TO_OPEN_OR_EVALUATE_OOS=NO
MODEL_FIT_PERFORMED=NO
```

The source-bound panel and preregistration establish that the inputs are
traceable, not that conventional option state improves B0 or that B2 improves
B1. No predictive conclusion may be made from their coverage counts.

## Preserved timing claim boundary

- FMP: `timestamp_raw + 1 minute` is the primary conservative study
  assumption; `+2 minutes` is a registered sensitivity, not provider-confirmed
  semantics.
- Massive: B1Q uses the registered SIP as-of origin state, with retained
  60-second and 300-second re-selection sensitivities.
- Unusual Whales: `created_at` is an operational availability proxy with a
  60-second cutoff; it is not publication or client-receipt time.

## Required before any one-time OOS access

1. Freeze a successor method specification that binds the v3 panel hash,
   temporal train/validation/holdout splits, estimands, bootstrap, Holm policy,
   development-only MDE, and the registered B0/B1a/B2 contrasts.
2. Record a zero-OOS-read ledger at the instant of method freeze.
3. Preserve the proxy-limited provider-timing language in every result claim.
4. Obtain explicit human authorization for exactly one OOS access.

No acquisition preflight, storage availability, credential presence, or model
implementation substitutes for these four conditions.

## Reproduction

Run from the repository root:

```powershell
uv run python scripts/seal_target_blind_confirmation_preregistration_v3.py
uv run pytest -q tests/unit/test_target_blind_preregistration_v3.py tests/unit/test_seal_target_blind_confirmation_preregistration_v3.py
uv run ruff check src/mds650/target_blind_preregistration_v3.py scripts/seal_target_blind_confirmation_preregistration_v3.py
uv run mypy src/mds650/target_blind_preregistration_v3.py scripts/seal_target_blind_confirmation_preregistration_v3.py
```

The sealing command is idempotent only for byte-identical output and fails
closed if its code, lockfile, schemas, template, manifest or output identity
changes.
