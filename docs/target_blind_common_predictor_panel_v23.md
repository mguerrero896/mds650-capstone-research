# Target-Blind Common Predictor Panel v2.3

## Purpose and boundary

Version 2.3 constructs a new, predictor-only B0/B1Q/B2 matrix after the UW
availability correction. It is an engineering artefact, not an evaluation
artefact: it must not read RV30, predictions, QLIKE, model objects, losses, or
OOS results. It does not reconcile any result generated before the correction.

`SAFE_TO_RECONCILE_EXISTING_RESULTS=NO`

`SAFE_TO_OPEN_OR_EVALUATE_OOS=NO`

## Immutable provenance preflight

Before any predictor Parquet is opened, the v2.3 command validates:

1. the B2 sidecar bytes against the v2.2 manifest;
2. the origin-grid bytes against the same v2.2 manifest;
3. the promoted Massive recomputation self-hash and technical target-blind
   contract;
4. the PIT v2.1 gate schema and self-hash;
5. the gate binding of both the promoted Massive record and the v2.2 B2
   manifest.

The B1Q primary state remains `SIP_ASOF_ORIGIN_MAX_AGE_60S`. The 60- and
300-second Massive re-selections are documented sensitivities; they are not
silently mixed into the primary state.

The B2 primary variant is `primary_5m_60s`. Its 451 affected rows are kept in
the origin grid but have null B2 features and an explicit exclusion status;
they are never treated as zero activity.

## Output and replay policy

The constructor uses explicit B0/B1/B2 output allowlists, so unregistered
source metadata cannot propagate into the predictor matrix. Outcome-like,
loss-like, model-like, metric-like, and unregistered forecast-like columns are
rejected. An excluded B2 row carrying a numeric B2 feature fails closed.

All outputs use write-if-new-or-byte-identical semantics. A different existing
file is never overwritten.

The builder, its local runtime modules, and its locked environment files must
be committed before a build begins. This prevents a manifest from presenting a
commit identity that does not contain the code or dependency lock which
generated it. Unrelated user-owned worktree changes, including Graphify, are
outside this narrow builder-source check.

## Precommit run retained but not accepted

`D:/MDS650/phase6/derived/target_blind_v23/` and
`artifacts/target_blind_v23/` contain a preliminary local build made before the
builder-source commitment rule existed. Its predictor payload was target-blind,
but its `source_commit` cannot identify the uncommitted builder code. It is
retained for forensic traceability and is **invalid for acceptance**. It must
not be overwritten, reconciled, or used for evaluation.

The first acceptable replay is written only after a committed build under:

`D:/MDS650/phase6/derived/target_blind_v23_committed_20260812/`

and its repository artefacts under:

`artifacts/target_blind_v23_committed_20260812/`.

## Verification

```powershell
uv run pytest -q tests/unit/test_target_blind_panel_v22.py tests/unit/test_target_blind_provenance_v23.py tests/unit/test_build_target_blind_common_panel_v23.py
uv run ruff check src/mds650/target_blind_panel_v22.py src/mds650/target_blind_provenance_v23.py scripts/build_target_blind_common_panel_v23.py
uv run mypy src/mds650/target_blind_panel_v22.py src/mds650/target_blind_provenance_v23.py scripts/build_target_blind_common_panel_v23.py
uv run python scripts/build_target_blind_common_panel_v23.py
```

The last command remains a data-engineering operation only. Passing it does not
authorize model fitting, QLIKE, OOS access, or a claim that B1 or B2 has an
edge.
