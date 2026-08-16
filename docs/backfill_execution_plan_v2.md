# Backfill execution plan v2 (not executed)

This runbook is a future, resumable plan for the recommended 60-session window
(resource estimate: 173,865,828,817 bytes including a 30% reserve; current disk
telemetry is environment-dependent and must be refreshed before execution).
It is deliberately not an authorization to download data.

1. Obtain human approval, provider licence confirmation and current disk check.
2. Freeze the exact session list with XNYS and write a configuration hash.
3. Process one session at a time: checksum Full Tape, stream ZIP members through
   a bounded workspace, filter to eight assets, write Parquet, and delete only
   temporary intermediates after checksum verification. Do not count streamed
   uncompressed members as retained resident storage.
4. Resolve Massive contracts by `as_of`/DTE/moneyness and cache each
   contract-day once; select quotes with `sip_timestamp <= origin` locally.
5. Build FMP B0 and RV30, UW B2, and B1Q in separate deterministic stages.
6. Write a checkpoint after every session containing input hashes, output hashes,
   row counts and schema version. Resume must be idempotent; corruption fails
   closed.
7. Run schema, duplicate, secret, PIT and disk gates before admitting a session.
8. Stop immediately on a provider schema/entitlement/license change; do not
   retry blocked ranges silently.

The controlled local restart test is
`artifacts/backfill/restart_dry_run_v1.json`: 13,240 input rows, 6,620-row
checkpoint, zero duplicate output rows, identical uninterrupted/resumed hashes,
corruption detected and partial-output cleanup true, with zero provider requests.

No model, QLIKE, final asset freeze or final test belongs in this runbook.
