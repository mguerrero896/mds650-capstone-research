# Date-Level PIT Preflight v2.1: Current Status

`date_level_pit_preflight_status_v2` emits an immutable, sanitized status
record from the calendar plan, provider catalog and request budget. It is not a
transport runner and sends no provider request.

## What it verifies

- The versioned date-level plan, endpoint catalog and request budget remain
  schema-valid and source-bound.
- The initial plan is bounded to 119 logical operations and 343 total HTTP
  attempts if a future independent runner is ever authorized.
- FMP historical sessions (90/90 sampled) and Unusual Whales Full Tape file
  metadata (90/90 sampled) are recorded separately from PIT semantics.
- The registered deterministic Massive contract-selection rule is bound to the
  current plan. This removes only the stale “selection rule unresolved” block;
  it does not create a provider request or validate a returned contract.
- The remaining FMP, UW and Massive quote-timing evidence gaps still prevent
  all network transport; attempts reserved and sent are both zero.

## What it does not verify

It does not read secrets, free disk space, costs, provider endpoints, response
payloads, targets, RV30, QLIKE, models, predictions, OOS material or legacy
results. It cannot upgrade timestamp, publication or customer-receipt timing.

## Reproducible status command

Use the commit that introduced the v2.1 emitter. The command is idempotent
only while the bound source, schemas and inputs remain byte-identical.

```powershell
$commit = git rev-parse HEAD
uv run --offline python scripts/emit_date_level_pit_preflight_status_v2.py --source-commit $commit
```

The resulting `FAILED_CLOSED` record is positive evidence of controlled
readiness, not permission to acquire historical data or evaluate models. Before
network activity can be considered, these remaining contract evidence states
must change through admissible provider documentation or a separately validated
protocol; authorization, credentials or storage capacity do not override them:

- `FMP_DATE_BOUNDED_ONLY_NO_PIT_CLAIM`
- `UW_FULL_TAPE_ZIP_ROUTE_DOCUMENTED_EXECUTION_GATED`
- `MASSIVE_QUOTE_AS_OF_PARAMETERS_DOCUMENTED_LOCAL_SIP_CHECK_REQUIRED`

The current v2.1 immutable output is
`artifacts/preflight/date_level_pit_preflight_status_v2_1_current.json` (file
SHA-256 `9e246c6a167fc0a5ed5cb61cf83e6a747e6dee74901a4aa52f2ad76ab579e6db`,
semantic SHA-256
`sha256:a866b52ab7e6b8bbee38c6041c3935eb7fb329a7e1006674816d4008a71f6112`).
The sealed v2.0 record remains historical evidence at
`artifacts/preflight/revalidated_20260812/date_level_pit_preflight_status_v2_current.json`;
it is neither overwritten nor retroactively reclassified.

## Provider response intake

When a provider supplies a written clarification, first process a sanitized
record through
[`provider-timing-semantics-evidence-intake-v1`](provider_timing_semantics_evidence_intake_v1.md).
Its best possible outcome is review-ready evidence; it does not alter this
`FAILED_CLOSED` status. A separate technical review, an explicit gate
amendment and the bounded provider protocol remain required before any network
transport can be reconsidered.
