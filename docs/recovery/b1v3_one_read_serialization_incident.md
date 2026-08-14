# B1v3 one-read serialization incident

**Date:** 2026-08-14

**Scope:** registered B1v3 confirmation finalization

**Scientific sample:** unchanged

## Incident

The one-read runner durably consumed
`artifacts/b1v3_confirmation/access_authorization_consumed.json`, read the thirty registered
confirmation sessions once, fitted no confirmation-selected parameters, computed the registered
forecast and inference objects, and wrote these three immutable Parquet outputs:

- `MDS650_B1V3_DATA_ROOT/evaluation/evaluation_panel.parquet` — SHA-256
  `d688000d86d5752ab5d553d4616f7ea94f301f7e148b81c1aa2044e16db6d3dd`;
- `MDS650_B1V3_DATA_ROOT/evaluation/primary_forecasts.parquet` — SHA-256
  `a3fd362db6b34cf53225b76f37132174298a421afa754dff4563422b552a496c`;
- `MDS650_B1V3_DATA_ROOT/evaluation/timing_forecasts.parquet` — SHA-256
  `96b8fde4b23eab8de35e6700c5a70788d610a271140f4b446222803971b67e2d`.

The process then failed before writing `result.json`. The exact exception was
`B1V3_CONFIRMATION_OUTPUT_HYGIENE_INVALID`.

## Root cause

The sanitizer prohibited the generic byte sequence `authorization`. The schema-valid result
necessarily contains the non-secret provenance field
`consumed_authorization_manifest_sha256`; consequently, every legitimate result was rejected.
This was a deterministic false positive in output serialization, not a data, model, provider,
target or inference failure.

## Recovery control

The runner was **not rerun** and the source target was **not read a second time**. A tested
`--finalize-sealed-outputs` path was added with these fail-closed requirements:

1. the frozen and consumed ledgers must reproduce the exact registered `0 -> 1` transition;
2. the three derived Parquet outputs must already exist;
3. no final JSON, report or evidence index may exist;
4. the evaluation-panel and prediction target identities must match exactly;
5. registered inference is recomputed only from the sealed forecast cube;
6. FMP bars, provider payloads, common predictors and training inputs are not accepted inputs;
7. all final files retain exclusive-create behavior.

The sanitizer now rejects actual `Authorization:` headers, JSON `"authorization":` secrets,
Bearer values, API-key patterns and personal/local data paths while permitting provenance field
names. Regression tests cover both the legitimate result and actual secret-header rejection.

## Outcome

Finalization succeeded with zero stderr. The final result is
`artifacts/b1v3_confirmation/result.json`, semantic SHA-256
`c80977d6128e403a308f0ad4552050083c3d79a0593af7dc94d97aecab740ced`.
The scientific signs were not altered, selected or filtered during recovery.
