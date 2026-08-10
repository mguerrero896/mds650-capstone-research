# Independent 30-session replication request

Status: bounded acquisition is permitted only after the 90-session metadata
probe and the method-freeze artifact pass. No target RV30 has been read by the
replication workflow.

## Window

- Calendar: XNYS.
- Causal warm-up/training: 60 sessions immediately before 2025-05-21.
- Independent target: 30 sessions from 2025-05-21 through 2025-07-03.
- The 60 warm-up sessions are never scored; they provide only causal history
  for B2 trailing normalization and model fitting.
- The target block is disjoint from the Phase 5 90-session panel and the Phase
  6 180-session panel.

## Why 60 warm-up sessions are required

B2 normalization requires at least 20 prior sessions. A 20-session warm-up
would make the first target day computable but would leave no complete B2 rows
for a causal training sample. Sixty sessions provide 40 B2-complete training
sessions after the minimum 20-session history, while retaining the 30-session
target block as an untouched evaluation set.

## Frozen method

The method is frozen in
`artifacts/independent_replication/method_freeze.json` before target outcome
access:

- target: RV30, 31 prices and 30 one-minute log returns;
- information sets: B0v2, B1v2a, B2v2;
- confirmatory model: Gamma GLM;
- robustness model: LightGBM;
- primary metric: QLIKE;
- descriptive metrics: MAE and RMSE;
- paired whole-session bootstrap with Holm correction;
- 30-minute purge/embargo;
- B2 cutoff: `created_at <= forecast_origin - 60 seconds`;
- natural prevalence; no balancing and no target-driven feature design.

HAR-RV and Ridge are retained as development diagnostics. They are not
substituted into the independent test after observing the target block.

## Provider and storage gates

The metadata probe must pass for all 90 dates and all three providers. UW
Range/Content-Range is evidence that the Full Tape file exists and its size is
known; it is not a PIT claim. Row-level PIT is validated only after ZIP
filtering. Raw ZIPs, filtered Parquet and checkpoints remain on D: with an
80-GiB minimum free-space floor.

## Stop rules

Stop without scoring if any ZIP hash, schema, timestamp, target completeness,
provider overlap, causal cutoff, or storage-floor check fails. Preserve every
partial checkpoint and never delete an immutable raw archive to make room.
