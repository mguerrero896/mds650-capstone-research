# Next Confirmation Protocol v1 — READY_FOR_CONFIRMATION, Not Authorized Yet

## Purpose

This protocol specifies the minimum evidence required before a future research
goal can rebuild a corrected target-blind common B0/B1/B2 panel and freeze a
new method. It does not authorize opening, reconciling or evaluating sealed
OOS results. It does not authorize new provider acquisition, model training,
QLIKE, tuning or a method change.

## Current state

```text
B2_ZERO_CODING_REMEDIATED_UNDER_PROXY=YES
B2_CREATED_AT_PROVIDER_PUBLICATION_SEMANTICS=UNVERIFIED
CORRECTED_TARGET_BLIND_COMMON_PANEL=BUILT_TARGET_BLIND_V22
SAFE_TO_RECONCILE_EXISTING_RESULTS=NO
SAFE_TO_OPEN_OR_EVALUATE_OOS=NO
```

## Preconditions that must all pass

1. The immutable v2.2 sidecar hash and both v2.1 input hashes match the
   recorded manifest.
2. The v2.2 common-panel builder uses `eligible_for_corrected_pit_panel` as a
   filter, preserves the primary natural distribution and records every
   excluded origin by reason. Its source and output hashes must match the
   `target_blind_common_predictor_manifest_v22.json` manifest.
3. The new panel has a deterministic manifest; it contains no future B2 field,
   target, prediction, loss or result.
4. The Massive source-time as-of rules remain independently validated for the
   selected B1 route. A quote is selected by `(sip_timestamp, sequence_number)`
   at or before its registered cutoff, never by a later quote.
5. The FMP bar convention remains explicitly labelled as the conservative
   `timestamp_raw + 1 minute` assumption, with the registered `+2 minute`
   sensitivity; it must not be presented as provider-confirmed bar semantics.
6. The `created_at` rule remains labelled `OPERATIONAL_AVAILABILITY_PROXY`.
   A provider statement or prospective receipt logging is required before it is
   described as actual publication or client receipt timing.
7. A successor method-freeze/preregistration binds the new panel hash,
   predictor contract, temporal splits, registered contrasts, bootstrap and
   multiplicity treatment before any OOS payload is read.
8. A human explicitly accepts the proxy-limited claim boundary and authorizes
   the successor method freeze that binds the built panel. A separate
   authorization is required before any OOS evaluation.

## Exact preflight commands

Run from the repository root:

```powershell
uv run python scripts/build_b2_availability_v22.py `
  --event-root D:\MDS650\phase6\data\option_events `
  --matrix-root D:\MDS650\phase6\data\b2\raw_activity_by_session `
  --expected-origins-path D:\MDS650\phase6\data\b1q\phase6_b1_origins.parquet `
  --traceability-csv artifacts\provider_timing_v21\b2_canonical_traceability_v21.csv `
  --sidecar-output D:\MDS650\phase6\derived\provider_timing_v22\b2_row_availability_v22.parquet `
  --artifact-dir artifacts\provider_timing_v22

uv run pytest -q tests/unit/test_b2_availability_v22.py tests/unit/test_provider_timing_v21.py
uv run ruff check src/mds650/b2_availability_v22.py scripts/build_b2_availability_v22.py
uv run mypy src/mds650/b2_availability_v22.py scripts/build_b2_availability_v22.py
uv run python -m json.tool artifacts/provider_timing_v22/b2_availability_manifest_v22.json > $null

uv run python scripts/build_target_blind_common_panel_v22.py
uv run pytest -q tests/unit/test_target_blind_panel_v22.py tests/unit/test_b2_availability_v22.py
uv run ruff check src/mds650/target_blind_panel_v22.py scripts/build_target_blind_common_panel_v22.py
uv run mypy src/mds650/target_blind_panel_v22.py scripts/build_target_blind_common_panel_v22.py
uv run python -m jsonschema `
  -i artifacts/target_blind_v22/target_blind_common_predictor_manifest_v22.json `
  specs/001-pit-options-rv30/contracts/target-blind-common-predictor-manifest-v22.schema.json
```

The same command must reproduce the D-resident sidecar SHA-256 recorded in the
v2.2 manifest. A different hash is a stop condition, not an opportunity to
choose a more favorable result.

## Required next artefacts, outside this closure

- a target-blind common-panel manifest containing the v2.2 mask hash;
- a source-code and environment lock for that builder;
- an updated preregistration, self-hashed before OOS access;
- an access ledger showing zero OOS reads at freeze time;
- a provider-timing claim matrix that retains `PROXY_ONLY` where evidence is
  still incomplete.

The first three items are now present as
`artifacts/target_blind_v22/target_blind_common_predictor_manifest_v22.json`,
its builder-hash fields, and
`artifacts/target_blind_v22/next_confirmation_preregistration_v2.json`. The
new preregistration binds the corrected panel only; it intentionally remains a
pre-method-freeze seal and does not authorize OOS access.

## Decision

**READY_FOR_CONFIRMATION:** yes, for an explicitly authorized target-blind
common-panel rebuild under the proxy-limited contract.

**READY_FOR_RESULT_RECONCILIATION:** no.

**READY_FOR_OOS_OR_MODEL_EVALUATION:** no.
