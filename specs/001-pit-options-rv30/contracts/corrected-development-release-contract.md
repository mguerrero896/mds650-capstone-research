# Corrected development-release contract

## Purpose and boundary

This contract governs one new, immutable development-only evidence release after the PIT v2.1
correction. It is not a reconciliation or alteration of sealed legacy results. It does not read
or evaluate the prospective holdout, acquire provider data, alter the nine B2 features, or
change model, asset or inference settings to seek a preferred result.

## Required bound inputs

The release must hash-bind all of the following before any target is read:

1. target-blind v2.4 predictor manifest and predictor/common Parquet files;
2. B2 v2.2 availability manifest and sidecar;
3. PIT v2.1 reconciliation gate and UW anomaly evidence;
4. Massive v2.1 as-of reselection sensitivity evidence;
5. exact 80-session development source manifest and frozen comparison contract.

The release rejects a changed hash, missing schema, untracked source builder, personal path,
secret-like field, target/loss/forecast input during predictor construction, duplicate origin,
future predictor timestamp, or any of the ten prospective holdout dates.

## B2 availability semantics

For a delayed or unavailable activity window, every frozen B2 feature is null; the release stores
`b2v2_availability_eligible=false` and a non-empty reason. It must not substitute numerical zero,
`option_activity_present=false`, or an unlabelled missing value. A zero is valid only if the
window is eligible, has no qualifying trade and has no observed delay incident.

## States

| State | Meaning | Prohibited actions |
|---|---|---|
| `TARGET_BLIND_READY` | Source hashes, date isolation and B2 exclusion policy passed. | Target reads, modeling, metrics, OOS. |
| `TARGET_BOUND_READY` | Exact development-only RV30 targets bind to predictor origin IDs. | OOS, legacy reconciliation, method change. |
| `EVALUATED_DEVELOPMENT_ONLY` | Frozen development protocol completed and all variants were retained. | OOS, acquisition, legacy reconciliation, rerun for sign. |
| `BLOCKED` | Any contract or leakage condition failed. | All downstream steps. |

`SAFE_TO_RECONCILE_EXISTING_RESULTS` is always `NO` and
`SAFE_TO_OPEN_OR_EVALUATE_OOS` is always `NO` in every state. Only the final state may record
`SAFE_TO_EVALUATE_CORRECTED_DEVELOPMENT=YES`.

## Evaluation contract

The development evaluator uses the frozen B0, B1a and B2 information sets, Gamma GLM
confirmatory role, LightGBM robustness role, four expanding folds, 30-minute purge and embargo,
QLIKE, MAE, RMSE, paired whole-day bootstrap and Holm correction. It retains all positive,
negative and null results and every registered timing variant. A development finding is not a
final supported edge: that requires the separate, one-time holdout protocol.

## Machine-readable contract

Every release must validate against
`corrected-development-release-v1.schema.json` and store canonical JSON with `release_sha256`
computed over the document excluding that field.
