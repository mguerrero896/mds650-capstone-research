# Twenty-session calibration decision v3

Decision: `AUTHORIZE_METHOD_FREEZE_AND_BACKFILL_PLAN`

This is a planning authorization only. It does not authorize a larger download, model training,
tuning, QLIKE, final testing, definitive asset freeze, Word/PowerPoint changes, publication or
email.

## Evidence disposition

- Spec Kit: `PASS_WITH_RESEARCH_GATE`; no critical contradiction.
- Authorized sessions: 20/20, exactly 2026-06-11 through 2026-07-10; Pilot V2 dates excluded.
- Raw evidence: 20 unique SHA-256 hashes, stable schema, CRC PASS, 160 readable Parquet
  partitions, zero duplicate event IDs.
- B2: 11,360 origins, 96 parameter groups, primary cutoff 60 seconds, natural prevalence,
  `unusual_event` retained as `CALIBRATED_SECONDARY_EXPLORATORY` only in the Pilot application.
- B1Q: B1a 91.14%, B1b 59.95%, B1c 18.81%; IV inversion success 85.13%; nested invariants PASS
  globally and by asset/date/session segment/instrument type.
- FMP: 160/160 HTTP 200 requests with 390 exact-session bars after local date filtering.
- Literature ledger: ten rows; four full-text, three abstract-only and three publisher-metadata-only
  rows. Claims for the six limited rows are explicitly bounded and are not used as strong evidence.
- Sensitivity quantiles: p90, p95 and p97.5 are calculated with the requested empirical quantile;
  the percentile-regression test passes.

## Provisional quality universe (not frozen)

AAPL, AMZN, META, MSFT, NVDA and TSLA meet the declared data-only B1a/segment/IV gates. SPY and
QQQ remain B0 market controls because their early-session and IV coverage fail the same options-state
gate. NVDA may move from diagnostic to eligible target candidate at a later recorded freeze. B1b and
B1c remain enriched/robustness states; B1c is not forced as the primary benchmark.

## Conditions before any larger backfill

1. Record the method freeze and exact asset universe in a new configuration change.
2. Validate daily continuity beyond the sampled common-history points; the current all-assets probe
   explicitly reports `daily_continuity_established=false`.
3. Preserve the B1a PIT/coverage gates and the bounded literature claims.
4. Run a restart/storage gate against the measured P95 plus 30% margin.
5. Obtain a separate authorization before downloading any range larger than the twenty sessions.
