# Replication acquisition atomicity recovery

## Scope

This note records a target-blind reliability correction made while the frozen
independent-replication predictor acquisition was running. It does not change
the preregistration, information sets, samples, models, target, QLIKE, MDE, or
terminal decision rule.

## Observed condition

During an active Full Tape session, six asset Parquet files did not yet contain
their footer. The files belonged to the session then being written and were not
referenced by a completed checkpoint. After that session completed, all eight
checkpoint-bound partitions were readable and hash-bound. This distinguishes
an in-progress file from corruption of accepted evidence.

The underlying producer nevertheless wrote directly to `events.parquet`.
Likewise, the legacy Massive B1Q builder wrote its two final Parquet tables
directly. An interrupted process could therefore leave an incomplete file under
a final filename.

## Correction

- Full Tape now writes every asset partition to `events.parquet.partial`.
- All partial partitions are validated before the first promotion.
- Closed, valid partitions are promoted with an atomic filesystem replacement.
- Stale partial files are disposable and removed before a retry; completed
  checkpoint-bound final files remain protected by their recorded hashes.
- Massive B1Q final tables now use the same write, validate, atomic-promote
  pattern.

The already-running processes loaded the pre-correction code. They were not
interrupted or duplicated. Their final outputs therefore require the existing
post-run schema and hash audit before they can pass the pre-read gate. Any safe
retry uses the corrected implementation.

## TDD evidence

- Full Tape RED: two expected failures because atomic path/promotion helpers did
  not exist.
- Full Tape GREEN: seven focused tests passed.
- Massive B1Q RED: one expected failure because the atomic Parquet writer did
  not exist.
- Massive B1Q GREEN: two focused tests passed.
- Scoped Ruff: PASS.
- Scoped strict Mypy: PASS.

## Scientific boundary

No replication outcome, RV30 value, QLIKE result, prediction, or result sign was
read to diagnose or correct this storage behavior. The correction is strictly
operational and sign-agnostic.
