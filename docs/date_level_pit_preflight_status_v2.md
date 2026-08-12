# Date-Level PIT Preflight v2: Current Status

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
- The current FMP, UW and Massive evidence gaps still prevent all network
  transport; attempts reserved and sent are both zero.

## What it does not verify

It does not read secrets, free disk space, costs, provider endpoints, response
payloads, targets, RV30, QLIKE, models, predictions, OOS material or legacy
results. It cannot upgrade timestamp, publication or customer-receipt timing.

## Reproducible status command

Use the commit that introduced the status emitter. The command is idempotent
only while the bound source, schemas and inputs remain byte-identical.

```powershell
$commit = 'd1c4efcccd415227db7856f477e9f278b666b772'
uv run --offline python scripts/emit_date_level_pit_preflight_status_v2.py --source-commit $commit
```

The resulting `FAILED_CLOSED` record is positive evidence of controlled
readiness, not permission to acquire historical data or evaluate models. Before
network activity can be considered, the four listed contract evidence states
must change through admissible provider documentation or a separately validated
protocol; authorization, credentials or storage capacity do not override them.

The current immutable output is
`artifacts/preflight/date_level_pit_preflight_status_v2_current.json` (file
SHA-256 `945908ba718bea18fe85f3cb4297495d08e7e2b3158619c1bc4ae5b543642683`,
semantic SHA-256
`sha256:f7089333dba0dd65d5a901f8fdfb64983fc5d976afd856594426b6918de5943d`).
