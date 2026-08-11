# PIT v2.1 Reconciliation Gate — Target-Blind Addendum

**Gate status:** `CONDITIONAL_NOT_CLOSED`.

This record consolidates only existing, sanitized timing evidence. It does not
read RV30, predictions, models, QLIKE, predictive results, or OOS artefacts; it
does not make a provider request. It contains no conclusion about an edge,
economic value, or model quality.

## Bound aggregate

The deterministic aggregate is
`artifacts/provider_timing_v21/pit_reconciliation_gate_v21_20260812.json`.
Its semantic self-hash is
`ba2afa8a5b6471561db0d363d47109393065f8a9f9c65e5a7f4c340abf303452`.
The JSON Schema contract is
`specs/001-pit-options-rv30/contracts/pit-reconciliation-gate-v21.schema.json`.

## Separate evidence states

1. **FMP bars:** `timestamp_raw + 1 minute` is the baseline conservative study
   rule and `timestamp_raw + 2 minutes` is its conservative sensitivity. Neither
   rule confirms FMP bar label, exact timezone, DST handling, or delivery
   latency semantics.

2. **Massive B1Q reselection:** the existing target-free cache reselection has
   `PASS` technical status. It validates cached as-of selection and identity
   controls; it does not prove historical REST delivery latency and does not
   establish a predictive effect.

3. **Legacy UW v2.1 raw coding diagnostic:**
   `FAIL_ZERO_CONFOUNDED_BY_OBSERVED_CREATED_AT_DELAY`. This means a legacy
   zero-coded B2 row cannot be read as confirmed absence of activity. It is not
   a permanent conclusion about B2 after correction.

4. **Corrected UW v2.2 availability sidecar:** `PASS_WITH_EXCLUSIONS`. The
   primary sidecar excludes 451 confounded rows and reports
   `PASS_MASK_READY_REQUIRES_NEW_TARGET_BLIND_PANEL_BUILD`. The sidecar is a
   mask for a new target-blind common panel, not a repair, rerun, or validation
   of sealed result artefacts.

## Enforced boundaries

`SAFE_TO_RECONCILE_EXISTING_RESULTS=NO`

`SAFE_TO_OPEN_OR_EVALUATE_OOS=NO`

The v2.2 corrected sidecar prevents a permanent-failure interpretation of the
legacy v2.1 diagnostic, but it does not authorize reconciliation. A newly built
target-blind common B0/B1/B2 panel must first apply the immutable sidecar mask,
receive its own hash, and pass no-leakage and provenance gates.

## Local verification

```powershell
uv run pytest tests/unit/test_pit_reconciliation_gate_v21.py -q
uv run ruff check src/mds650/pit_reconciliation_gate_v21.py scripts/aggregate_pit_reconciliation_gate_v21.py tests/unit/test_pit_reconciliation_gate_v21.py
uv run mypy src/mds650/pit_reconciliation_gate_v21.py scripts/aggregate_pit_reconciliation_gate_v21.py
uv run python scripts/aggregate_pit_reconciliation_gate_v21.py
```

The contract tests verify source self-hashes where source artefacts provide
them, the v2.1/v2.2 status split, schema conformance, deterministic aggregate
hashing, idempotent writing, and absence of secret-like values or personal
filesystem paths.
