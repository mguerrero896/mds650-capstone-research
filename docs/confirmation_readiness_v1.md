# Confirmation Readiness v1 — Target-Blind Operational Gate

## Purpose and boundary

This gate converts the current v2.2 target-blind state into one explicit,
machine-readable readiness decision. It checks only local hashes, target-blind
panel structure, registered timing labels and local operational metadata. It
does **not** read RV30, forecasts, QLIKE, model outputs or sealed
out-of-sample (OOS) data. It does not make a provider request.

The generated snapshot is
`artifacts/target_blind_v22/confirmation_readiness_v1.json`. Its self-hash is
validated before it is used as evidence.

## Current snapshot

The current local run reports:

```text
CONFIRMATION_READINESS_STATUS=PASS_READY_FOR_CONFIRMATION_ACQUISITION_NOT_REQUESTED
READY_FOR_CONFIRMATION=YES
SAFE_TO_ACQUIRE_NEW_SAMPLE=NO
SAFE_TO_RECONCILE_EXISTING_RESULTS=NO
SAFE_TO_OPEN_OR_EVALUATE_OOS=NO
MODEL_FIT_PERFORMED=NO
```

`READY_FOR_CONFIRMATION=YES` means only that the target-blind B0/B1Q/B2 input
identity is internally bound and its stated PIT assumptions remain unchanged.
It is not a result, an entitlement claim, a model-ready declaration or a
permission to access OOS data.

The snapshot independently checks:

| Area | Required evidence | Current meaning |
|---|---|---|
| Bound artefacts | Full panel SHA-256, B2 availability-sidecar SHA-256, preregistration self-hash and panel binding | A modified local file fails closed. |
| Common subset | The common-complete Parquet must be the exact all-complete subset of the full target-blind panel, with matching rows and origin IDs | A separately altered subset cannot enter a future freeze. |
| PIT labels | FMP `+1` minute plus `+2` sensitivity, Massive SIP as-of, UW `created_at` proxy-only | These remain research assumptions, not provider-confirmed receipt semantics. |
| Coverage | Target-blind counts and the common-complete rate from the bound manifest | Coverage is observed, not evidence of prediction quality. |
| Acquisition | Storage, named-secret presence and a non-secret cost-approval reference | Not evaluated until an exact new acquisition is requested. |

## Future acquisition preflight

No new download is authorised by the current snapshot. Before requesting one,
the future operator must first produce an exact session allow-list with the
holdout excluded, date-level provider/PIT evidence and a conservative storage
estimate. Then run, from the repository root:

```powershell
uv run python scripts/audit_confirmation_readiness_v1.py `
  --acquisition-requested `
  --projected-peak-additional-bytes <conservative-peak-bytes> `
  --cost-authorization-id <non-secret-approved-reference>

uv run python -m jsonschema `
  -i artifacts/target_blind_v22/confirmation_readiness_v1.json `
  specs/001-pit-options-rv30/contracts/confirmation-readiness-v1.schema.json
```

For an acquisition request, the gate requires all three secret **names** to be
present in the invoking process (`FMP_API_KEY`, `MASSIVE_API_KEY`, and
`UNUSUALWHALES_API_KEY`). It records only names that are absent, never values.
It requires an explicit non-secret cost-authorization reference and verifies
that projected free storage remains at least 80 GiB after the declared peak.

Even when those operational inputs pass, the report returns
`BLOCKED_EXACT_PLAN_AND_PROVIDER_PIT_REQUIRED` and keeps
`SAFE_TO_ACQUIRE_NEW_SAMPLE=NO`. A precise session allow-list, holdout
exclusion and date-level provider/PIT evidence must be bound in a subsequent
acquisition-specific preflight; secret presence, disk space and cost approval
cannot substitute for them.

Even if that acquisition preflight passes, the gate deliberately leaves these
states unchanged:

```text
SAFE_TO_RECONCILE_EXISTING_RESULTS=NO
SAFE_TO_OPEN_OR_EVALUATE_OOS=NO
```

A separate successor method freeze must bind temporal splits, estimand,
bootstrap, Holm policy, development-only MDE and an OOS access ledger before a
single evaluation payload can be opened.

## Reproduction and failure behavior

```powershell
uv run pytest -q tests/unit/test_confirmation_readiness_v1.py
uv run ruff check src/mds650/confirmation_readiness_v1.py scripts/audit_confirmation_readiness_v1.py
uv run mypy src/mds650/confirmation_readiness_v1.py scripts/audit_confirmation_readiness_v1.py
uv run python scripts/audit_confirmation_readiness_v1.py
```

Any hash mismatch, altered common subset, timing-boundary change, missing
operational input or insufficient projected storage returns an explicit failure
or blocked state. Nothing is substituted with zero, inferred from a prior run,
or silently authorised.
