---
title: Independent RV30 replication execution contract
type: research
created: 2026-08-10
---

# Independent RV30 replication execution contract

Status: `ACQUISITION_IN_PROGRESS`; no independent target outcome has been read.

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
