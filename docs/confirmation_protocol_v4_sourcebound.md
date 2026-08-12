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

## Additive primary-comparison freeze

The immutable v4 record retains the component feature lists. The additive,
self-hashing v1 comparison contract fixes their scientific ladder without
rewriting that sealed record:

| Primary comparison | Fixed estimand | Interpretation convention |
| --- | --- | --- |
| B1a versus B0 | daily mean `QLIKE(B0) - QLIKE(B1a)` | Positive favors B1a |
| B2 versus B1a | daily mean `QLIKE(B1a) - QLIKE(B2)` | Positive favors B2 |

`B1a` is the only primary ordinary-options benchmark. B1b and B1c are
pre-specified robustness analyses only; they cannot be substituted after
coverage, RV30, QLIKE, a sign or any predictive outcome is observed. The
contract also prohibits feature, asset, model and primary-comparison selection
using RV30 or QLIKE.

The immutable artifact is
`artifacts/target_blind_v25_comparison_contract_20260812/target_blind_comparison_contract_v1.json`
(file SHA-256 `82f455c3c5c7d72701d2525c1965aaa434d59bb24ded52002e0590d1cd5a91da`).
It still authorizes no model fit, metric evaluation, OOS access, reconciliation
or acquisition.

Its idempotent verification command uses the sealed source commit, rather than
the moving branch head:

```powershell
$commit = 'bd8002a90adab01622dfb18f8fb3132ae28ee411'
uv run --offline python scripts/seal_target_blind_comparison_contract_v1.py --source-commit $commit
```

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
fitting, or metric evaluation. The v2 status emitter may document that the
hard gate remains closed, but is deliberately not a provider-side runner and
cannot send a request:

```powershell
$commit = 'd1c4efcccd415227db7856f477e9f278b666b772'
uv run --offline python scripts/emit_date_level_pit_preflight_status_v2.py --source-commit $commit
```
