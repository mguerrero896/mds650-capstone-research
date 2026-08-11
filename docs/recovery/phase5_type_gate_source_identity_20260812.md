# Phase 5 type-gate source identity remediation

## Status

`LEGACY_PHASE5_METHOD_FREEZE_NOT_EXECUTABLE_WITH_REMEDIATED_SOURCE`

## Why this record exists

The Phase 5 holdout runner rejects any source-code hash that differs from its
method-freeze manifest. The strict Mypy remediation changes two paths in the
frozen Phase 5 source set:

- `scripts/run_phase4b.py`;
- `scripts/run_phase5_holdout.py`.

The changes improve type narrowing and third-party typing boundaries only. They
do not authorize, read, write, train on, or evaluate the holdout. Nevertheless,
the legacy method freeze must remain immutable and cannot be used with the
remediated source tree.

## Evidence and boundary

- The legacy source baseline is commit
  `cb8448de7281540e7efdec7fa94c3fa5ebed3248`.
- `src/mds650/holdout.py` includes both paths in
  `FROZEN_PHASE5_SOURCE_PATHS`.
- `scripts/run_phase5_holdout.py` validates every frozen source hash before its
  one permitted holdout read.
- The remediation was validated with `uv run mypy`, which now checks
  `src/mds650` and `scripts` by default.

## Required future action

Do not overwrite or amend the legacy Phase 5 freeze. Only after the PIT gate is
closed may a separately reviewed, source-bound method-freeze artifact be
created for the remediated sources. Until then, any holdout execution must fail
closed on the source-hash mismatch.
