# Target-Blind Common Predictor Panel v2.2

## Scope

This artefact is an offline, target-blind input layer. It joins one canonical
forecast-origin grid with B0, B1Q and corrected B2 predictors; it contains no
RV30, target count, forecast, QLIKE, prediction, model object, fitting result
or OOS outcome. It makes no provider request.

It is not a reconciliation of earlier sealed results. It is the only input
panel eligible for a **future**, separately frozen confirmation study under the
PIT v2.2 availability contract.

## Provenance and timing contract

| Information set | Input | Rule retained in this panel | Boundary |
|---|---|---|---|
| B0 | FMP one-minute bars | `available_at = timestamp_raw + 1 minute` | Conservative research assumption, not provider-confirmed bar semantics. The `+2`-minute rule remains a sensitivity. |
| B1Q | Massive B1Q source-state matrix | last SIP quote at or before the forecast origin; source quality filter maximum quote age 60 seconds | Massive source-time re-selection at origin-minus-60/300 seconds is a separate v2.1 sensitivity. It is not silently combined with the primary B1Q definition. |
| B2 | UW Full Tape-derived primary five-minute matrix | `created_at <= origin - 60 seconds` as an operational availability proxy | `created_at` is neither provider-proven publication time nor client receipt time. |

The builder derives B1 ATM-IV five- and thirty-minute changes only from earlier
same-session values. A missing earlier state stays missing; it is not set to
zero. B2 raw activity is normalized using only preceding sessions and requires
at least twenty earlier sessions.

## v2.2 availability handling

The immutable sidecar is applied before any common-completeness calculation.
Every primary B2 row with a delayed raw execution-window trade is made null and
is excluded from B2 completeness. It cannot be encoded as a zero-activity row.

For the 77,328-origin primary grid, the sidecar reports:

| Primary B2 availability state | Rows |
|---|---:|
| Eligible under the operational proxy | 76,877 |
| Explicitly excluded due to delayed raw execution-window trades | 451 |
| Corrected B2 rows with sufficient normalization history | 68,237 |

The 451 exclusions are a timing/data-quality classification, not a statement
about economic activity or predictive value.

## Target-free construction result

| Check | Rows | Rate |
|---|---:|---:|
| Canonical origins | 77,328 | 100.00% |
| B0 predictor-complete | 70,668 | 91.39% |
| B1a predictor-complete | 70,556 | 91.24% |
| B1b predictor-complete | 69,479 | 89.85% |
| B1c predictor-complete | 69,475 | 89.84% |
| B2 primary predictor-complete | 62,266 | 80.52% |
| Common B0/B1a/B2 predictor-complete | 62,266 | 80.52% |

The counts above are input-availability diagnostics only. They do not indicate
whether B1 improves B0 or B2 improves B1.

The origin-preserving panel and its common-complete subset are stored on the
data drive:

- `D:\MDS650\phase6\derived\target_blind_v22\target_blind_common_predictors_v22.parquet`
  (`d9f6c7690c5952a1c0e69087f9c8643c9b0496927fe863456d23648f268cd236`)
- `D:\MDS650\phase6\derived\target_blind_v22\target_blind_common_complete_v22.parquet`
  (`40aee9c6e6893de213d5358ac6b2d77af8c08db73b05a24d6374b1ecd6de79d2`)

The corresponding source, builder and output hashes are in
`artifacts/target_blind_v22/target_blind_common_predictor_manifest_v22.json`.

## Hard boundary

```text
TARGET_BLIND_COMMON_PREDICTOR_PANEL=PASS
SAFE_TO_RECONCILE_EXISTING_RESULTS=NO
SAFE_TO_OPEN_OR_EVALUATE_OOS=NO
MODEL_FIT_PERFORMED=NO
```

This panel does not repair, rerun, compare or reinterpret any pre-v2.2
prediction. A successor method freeze must bind this exact panel hash, the
temporal split, B0/B1/B2 contrasts, uncertainty procedure and multiplicity
policy before any outcome or OOS evaluation is accessed. The pre-method-freeze
seal is `artifacts/target_blind_v22/next_confirmation_preregistration_v2.json`.

## Reproduction

Run from the repository root without credentials:

```powershell
uv run python scripts/build_target_blind_common_panel_v22.py
uv run pytest -q tests/unit/test_target_blind_panel_v22.py tests/unit/test_b2_availability_v22.py
uv run ruff check src/mds650/target_blind_panel_v22.py scripts/build_target_blind_common_panel_v22.py
uv run mypy src/mds650/target_blind_panel_v22.py scripts/build_target_blind_common_panel_v22.py
uv run python -m jsonschema `
  -i artifacts/target_blind_v22/target_blind_common_predictor_manifest_v22.json `
  specs/001-pit-options-rv30/contracts/target-blind-common-predictor-manifest-v22.schema.json
uv run python scripts/create_target_blind_confirmation_prereg_v22.py
uv run python -m jsonschema `
  -i artifacts/target_blind_v22/next_confirmation_preregistration_v2.json `
  specs/001-pit-options-rv30/contracts/target-blind-confirmation-preregistration-v22.schema.json
```

Any source-hash or output-hash change is a stop condition. It requires a new
target-blind review, not selection of the more favorable run.
