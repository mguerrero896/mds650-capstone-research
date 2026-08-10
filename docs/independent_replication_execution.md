---
title: Independent RV30 replication execution contract
type: research
created: 2026-08-10
---

# Independent RV30 replication execution contract

Status: `ACQUISITION_IN_PROGRESS`; no independent target outcome has been read.

## Current acquisition gate (2026-08-10)

The provider metadata probe reports the 90 planned historical dates as
available, but the local body acquisition is not complete: 61 of 90 sessions
have passed immutable ZIP/Parquet/hash validation and the manifest remains
`IN_PROGRESS`. This consists of 31 warm-up sessions through 2025-04-25 and all
30 target dates from 2025-05-21 through 2025-07-03. The 2025-04-04 warm-up
archive is quarantined after two identical CRC failures; a fresh one-byte Range
probe returned the same ETag and byte count. This is an explicit
provider-archive block, not a silently skipped date. The evidence is recorded in
`artifacts/independent_replication/acquisition_manifest.json`,
`artifacts/independent_replication/acquisition_incidents/2025-04-04_crc_failure.json`,
and `artifacts/independent_replication/acquisition_incidents/2025-04-04_refresh_probe.json`.

The bounded `--role target` continuation completed all 30 target bodies on
2026-08-10. The target summary is recorded in
`artifacts/independent_replication/target_acquisition_summary_v1.json`:
30/30 target checkpoints are valid, all target responses were HTTP 200, one
schema fingerprint was observed, eight Parquet partitions were produced per
session, and duplicate event IDs were zero. The 90-session manifest remains
`IN_PROGRESS` because the warm-up archive is still missing.

Until the provider replaces that archive (or the frozen window is formally
re-authorized), the target gate remains closed and no B2 feature build, RV30
read, QLIKE evaluation, or new model fitting may consume this block.

The frozen block contains 60 warm-up sessions and 30 independent target
sessions from the XNYS allow-list in `window_manifest.json`. Full Tape is read
with immutable per-day ZIP and Parquet checkpoints on `D:`. The B2 cutoff is
`created_at <= forecast_origin - 60 seconds`; `created_at` remains an
operational availability proxy, not publication time.

When a provider archive blocks a warm-up date, the acquisition script may be
run with `--role target` to materialize only the frozen target bodies. This
mode never marks the 90-session manifest `PASS`, never bypasses the blocked
date, and cannot build features, read RV30, calculate QLIKE or fit a model.
The remaining warm-up bodies may be resumed with `--role warmup
--exclude-session YYYY-MM-DD` only when that date has the exact stable provider
archive incident; the exclusion is explicit, hash-audited and leaves the
frozen window incomplete.

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
