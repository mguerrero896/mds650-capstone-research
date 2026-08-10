---
title: Independent RV30 replication execution contract
type: research
created: 2026-08-10
---

# Independent RV30 replication execution contract

Status: `INDEPENDENT_REPLICATION_COMPLETE_WITH_PROVIDER_INCIDENT`.

## Current acquisition gate (2026-08-10)

The provider metadata probe covered the 90 planned historical dates. Local body
acquisition completed 89 of 90 sessions with immutable ZIP/Parquet/hash
validation: 59 warm-up sessions and all 30 target dates from 2025-05-21 through
2025-07-03. The 2025-04-04 warm-up archive is explicitly excluded after two
identical CRC failures; a fresh one-byte Range probe returned the same ETag and
byte count. This is a named provider incident, not a silently skipped or
zero-filled date. Evidence is recorded in
`artifacts/independent_replication/acquisition_manifest.json`,
`artifacts/independent_replication/acquisition_incidents/2025-04-04_crc_failure.json`,
and `artifacts/independent_replication/acquisition_incidents/2025-04-04_refresh_probe.json`.

The bounded `--role target` continuation completed all 30 target bodies on
2026-08-10. The target summary is recorded in
`artifacts/independent_replication/target_acquisition_summary_v1.json`:
30/30 target checkpoints are valid, all target responses were HTTP 200, one
schema fingerprint was observed, eight Parquet partitions were produced per
session, and duplicate event IDs were zero. The 90-session manifest is
`PASS_WITH_PROVIDER_INCIDENT`; the missing warm-up date remains explicit in the
manifest and is never treated as a no-event session.

The provider incident is a documented protocol deviation for the warm-up only.
The target gate was permitted to proceed because all 30 target bodies were
present and the missing warm-up date was represented as explicit provider-gap
rows rather than imputed activity.

The frozen block contains 60 warm-up sessions and 30 independent target
sessions from the XNYS allow-list in `window_manifest.json`. Full Tape is read
with immutable per-day ZIP and Parquet checkpoints on `D:`. The B2 cutoff is
`created_at <= forecast_origin - 60 seconds`; `created_at` remains an
operational availability proxy, not publication time.

When a provider archive blocks a warm-up date, the acquisition script may be
run with `--role target` to materialize only the frozen target bodies. This
mode never marks the 90-session manifest `PASS`, never bypasses the blocked
date, and cannot build features, read RV30, calculate QLIKE or fit a model
unless the explicit incident-adjusted warm-up continuation is used.
The remaining warm-up bodies may be resumed with `--role warmup
--exclude-session YYYY-MM-DD` only when that date has the exact stable provider
archive incident; the exclusion is explicit, hash-audited and leaves the
90-date acquisition marked `PASS_WITH_PROVIDER_INCIDENT`, not `PASS`.

The independent model parameters are frozen in
`artifacts/independent_replication/parameter_freeze.json`. They are the
selected variants from Phase 6 fold 1, chosen before target access and reused
unchanged for Gamma GLM (confirmatory) and LightGBM (robustness) on B0v2,
B1v2a and B2v2. No target-driven tuning or favorable-result selection is
permitted.

The target gate wrote `target_access_ledger.json` before the first RV30 read,
allowed exactly one completed read, and then wrote the common panel. The
evaluator retained every primary and timing-sensitivity sign, clustered
uncertainty by XNYS session date with all assets, applied the frozen Holm
family and compared effects with training-only MDEs. The sealed results are in
`artifacts/independent_replication/independent_results.json`; the human report
is `docs/independent_replication_30_session_results.md`.

The Gamma GLM confirmatory role shows a positive B1-to-B2 QLIKE contrast above
the frozen MDE. LightGBM has the opposite global B2 sign, so the evidence is a
model-dependent targeted replication, not a universal edge. No new historical
backfill, RL/DL model, trading execution or target reread is authorized by this
contract.
