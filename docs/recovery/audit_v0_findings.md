# Exploratory provider audit v0 findings

Artifact: `artifacts/api_audit/exploratory_v0/provider_audit_manifest.json`.
Classification: exploratory only; preserved byte-for-byte from the prior snapshot.

## Observed evidence

- FMP one-minute OHLCV returned HTTP 200 with an array schema for all eight candidates in the
  bounded recent sample; recent sessions show 390 rows. The depth probe observed January 2015
  access, but does not establish the true minimum history.
- Sampled FMP rows reported zero duplicates and zero critical nulls. Timestamp values were
  naive `YYYY-MM-DD HH:mm:ss`; timezone and bar start/close semantics remain unresolved.
- Structured earnings returned five rows per candidate in the sample. Symbol equality and ETF
  applicability were not accepted by the exploratory artifact.
- Unusual Whales returned HTTP 200 flow-alert objects. The response fields are snake_case
  `iv_start` and `iv_end`, not camelCase `ivStart`/`ivEnd`. The v0 missing-field diagnostic is
  therefore a canonicalization defect. The sample is not a historical ordinary IV/skew/term
  structure series and cannot establish B1.
- The observed time fields requiring separate semantics are `created_at`, `start_time` and
  `end_time`. `executed_at` is not part of the observed field list and must not be claimed.
- Massive contract reference probes returned HTTP 200, while directed trade/quote probes
  returned 401/403 with blocker `MASSIVE_AUTH_OR_PLAN_UNAUTHORIZED`. Full historical OPRA
  quote download was not attempted.
- `underlying_1min_depth_probe` repeats for all eight assets. This is an idempotency defect of
  exploratory v0, not a reason to delete or collapse records.

## Recovery evidence handling

The v0 JSON remains byte-preserved at its original path and is not rewritten as a new audit.
For the authenticated v1 probe, raw response bytes were migrated to a restricted logical root
`restricted://MDS650/raw`; the distributable manifest contains hashes and logical references,
not personal filesystem paths. The v0 duplicate depth probes remain visible evidence and are
used as the idempotency regression fixture.

The later authenticated v1 run supersedes none of these observations: it is a separate run with
run-specific request IDs and hashes. It observed Massive contract reference HTTP 404 and directed
trades/quotes HTTP 403, so the earlier v0 reference HTTP 200 is retained as historical evidence
but cannot be treated as a current entitlement result.

## What v0 does not prove

It does not prove timezone, DST, early-close, halt, adjusted/split semantics, pagination or
true earliest history; it does not prove ordinary PIT option state; and it does not authorize
backfill, asset freeze, pilot construction or model evaluation.
