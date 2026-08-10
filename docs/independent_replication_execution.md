---
title: Independent RV30 replication execution contract
type: research
created: 2026-08-10
---

# Independent RV30 replication execution contract

Status: `ACQUISITION_IN_PROGRESS`; no independent target outcome has been read.

## Current acquisition gate (2026-08-10)

The provider metadata probe reports the 90 planned historical dates as
available, but the local body acquisition is not complete: 31 of 90 sessions
have passed immutable ZIP/Parquet/hash validation and the manifest still has
status `IN_PROGRESS`. The completed records end on 2025-04-25, before the 30
target dates (2025-05-21 through 2025-07-03). The 2025-04-04 warm-up archive is
quarantined after two identical CRC failures; a fresh one-byte Range probe
returned the same ETag and byte count. This is an explicit provider-archive
block, not a silently skipped date. The evidence is recorded in
`artifacts/independent_replication/acquisition_manifest.json`,
`artifacts/independent_replication/acquisition_incidents/2025-04-04_crc_failure.json`,
and `artifacts/independent_replication/acquisition_incidents/2025-04-04_refresh_probe.json`.

Until the provider replaces that archive (or the frozen window is formally
re-authorized), the target gate remains closed and no B2 feature build, RV30
read, QLIKE evaluation, or new model fitting may consume this block.

The frozen block contains 60 warm-up sessions and 30 independent target
sessions from the XNYS allow-list in `window_manifest.json`. Full Tape is read
with immutable per-day ZIP and Parquet checkpoints on `D:`. The B2 cutoff is
`created_at <= forecast_origin - 60 seconds`; `created_at` remains an
operational availability proxy, not publication time.

The independent model parameters are frozen in
`artifacts/independent_replication/parameter_freeze.json`. They are the
selected variants from Phase 6 fold 1, chosen before target access and reused
unchanged for Gamma GLM (confirmatory) and LightGBM (robustness) on B0v2,
B1v2a and B2v2. No target-driven tuning or favorable-result selection is
permitted.

The target gate writes `target_access_ledger.json` before the first RV30 read,
allows exactly one completed read, and then writes a common panel. The
evaluator retains every primary and timing-sensitivity sign, clusters
uncertainty by XNYS session date with all assets, applies the frozen Holm
family and compares effects with training-only MDEs.
