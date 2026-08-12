# Protocol v4: frozen confirmation method, target-blind readiness only

This successor protocol is an offline, source-bound method freeze. It creates no
predictive or comparative claim and does not authorize result reconciliation,
OOS access, acquisition, prospective capture, model fitting, or metric
evaluation.

## Frozen method

- Target label: `RV30`.
- Information sets: the source-bound `B0`, `B1a_addition`, and `B2_addition`
  contracts are retained verbatim from preregistration v3. The nine frozen B2
  fields remain exactly the v3 list; they are not reselected here.
- Confirmatory specification: Gamma GLM with log link.
- Fixed robustness specification: LightGBM with no tuning.
- Metrics: QLIKE primary; MAE and RMSE secondary.
- Inference: paired trading-day cluster bootstrap with Holm adjustment. Selection
  by sign is prohibited.

## Evidence binding and status

`scripts/seal_target_blind_confirmation_package_v4.py` validates the local
schemas and semantic self-hashes of the v2.4 predictor-only manifest, the v1
provider-timing evidence policy gate, and preregistration v3. It additionally
requires the v2.4 PIT, Massive, B2 manifest, and B2 sidecar hashes to match the
corresponding policy evidence records. The output pair is write-if-identical and
fails on conflicting existing bytes.

| Scope | Current state | Boundary |
|---|---|---|
| Frozen method / target-blind package | `YES` | Metadata-only readiness, no scientific result. |
| Existing sealed-result reconciliation | `NO` | Literal `SAFE_TO_RECONCILE_EXISTING_RESULTS=NO` remains current. |
| OOS access or evaluation | `NO` | Separate frozen-method review and explicit human authorization are required. |
| New historical acquisition | `NO` | It can be considered only after a date-level PIT preflight. |
| Prospective capture | `NO` | It can be considered only after receipt-logger validation. |

## Seal command

The following metadata-only command is reproducible once the source commit is
known. It is not a data build, model run, or preflight.

```powershell
$commit = git rev-parse HEAD
uv run python scripts/seal_target_blind_confirmation_package_v4.py --source-commit $commit
```

It emits, under `artifacts/target_blind_v24_sourcebound_20260812/`,
`next_confirmation_preregistration_v4.json` and `confirmation_readiness_v3.json`.
Each output binds its own schema by byte hash and contains a semantic self-hash.

## Date-level PIT preflight: declared, not executed

The exact existing-gate recheck command is:

```powershell
uv run python scripts/aggregate_pit_reconciliation_gate_v21.py
```

It must be run only after an approved exact session plan and plan SHA-256 are
recorded. The subsequent workflow is: retain the registered timing contract;
record date-level evidence without OOS or metric payloads; then obtain separate
human authorization before any acquisition. This recheck alone does not call a
provider and does not authorize acquisition, OOS access, reconciliation, model
fitting, or metric evaluation. No provider-side date-level runner is declared by
this protocol because none is implemented or authorized here.
