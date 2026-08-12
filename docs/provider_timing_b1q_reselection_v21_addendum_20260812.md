# Massive B1Q Reselection Sensitivity v2.1 — Technical Addendum

**Status:** `PASS` for target-blind cache-integrity and quote-selection checks only.
This addendum does not evaluate RV30, predictive performance, QLIKE, models, or
economic value.

## Bound artifact

The promoted, sanitized aggregate is
`artifacts/provider_timing_v21/massive_reselection_sensitivity_v21_recomputed_20260812.json`.

- Semantic self-hash: `2379d54838885a1a19014c434595b07da9796a1c5996ea08806c1bbd87a44bcd`
- File SHA-256: `62c0e6cd3444482f0d79348bcc812a77c7c66b0bfb2c26e989c4b9a4ae9bac3c`
- Contract: `specs/001-pit-options-rv30/contracts/massive-reselection-sensitivity-v21.schema.json`

The semantic hash is SHA-256 over deterministic compact JSON after removing
`recomputed_result_sha256`. The file hash binds the exact promoted bytes.

## Scope and method

The recomputation reads only the pre-existing target-free B1 IV-attempt table
and pre-existing Massive v4 cache envelopes. It performs no provider HTTP
request and reads no target, prediction, model, QLIKE, or out-of-sample result.

For every existing attempt, it selects the last cache quote ordered by
`(sip_timestamp, sequence_number)` at or before each cutoff: origin, origin
minus 60 seconds, and origin minus 300 seconds. The selected quote is never
replaced by an earlier quote merely because the later quote fails an NBBO,
spread, or IV-quality check.

Technical IV is recomputed from the reselected midpoint and existing
point-in-time inputs using the documented BSM approximation. This is a
mechanical availability diagnostic, not a claim that the option is European or
that the resulting IV is an economic forecast.

## Supersession of the legacy age-only diagnostic

`artifacts/provider_timing_v2/pit_timing_audit_v2.json` remains immutable as
historical evidence. Its `massive.iv_attempts.source_time_delay_sensitivity`
field is an age-threshold diagnostic on the quote originally selected at the
forecast origin: it counts whether that quote's age is at least the stated
delay. It does **not** reselect the last quote at `forecast_origin - delay`.

Consequently, it MUST NOT support any B1Q source-time-delay coverage,
availability, or latency claim. For the 0-, 60-, and 300-second cutoff
sensitivities, this v2.1 bound artifact is the controlling evidence because it
performs the required as-of reselection. Quote age relative to the original
origin and freshness relative to the delayed cutoff remain separate diagnostic
quantities. Neither quantity proves Massive REST publication or client receipt
latency.

## Integrity checks and observed counters

- 1,080 contiguous asset-day groups were streamed.
- 32,238 contract-day groups and 32,238 cache envelopes were processed: one
  envelope decode per contract-day group.
- The maximum in-memory pending attempt group was 2,160 rows.
- Cache and attempt identity-failure maps are empty.
- At all three cutoffs, no selected quote occurred after its applicable cutoff.
- The origin and 60-second cutoff each selected 2,308,176 cached quotes; the
  300-second cutoff selected 2,275,938 cached quotes.
- The only cache-scope notices concern conservative handling of early-close
  request bounds and removal of post-close observations where present.

`PASS` therefore means the bound artifact satisfies its cache identity,
pagination, as-of ordering, and monotonicity gates. It does not establish
provider publication semantics, complete historical market coverage, B1
feasibility, an edge, or approval to train/evaluate a model.

## Reproduction gate

Run the focused contract checks with:

```powershell
uv run pytest tests/unit/test_provider_timing_v21.py -q
uv run ruff check src/mds650/provider_timing_v21.py tests/unit/test_provider_timing_v21.py
uv run mypy src/mds650/provider_timing_v21.py
```

The contract test validates JSON Schema conformance, the semantic self-hash,
the exact file hash referenced above, cutoff ordering, per-asset cutoff
completeness, and absence of secret-like values or personal filesystem paths.
