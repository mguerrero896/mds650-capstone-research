# MDS650 provider audit summary

- Run: 512148a9-1459-476a-9a7f-9d01b09578bf
- Window: 2026-07-16 through 2026-07-18
- Secret values emitted: **false**
- Raw payloads: restricted to C:\Users\mguer\AppData\Local\Temp\mds650-provider-audit-20260720

## FMP

Eight assets returned HTTP 200 for both bounded one-minute and earnings probes. Each one-minute response contained 780 rows (390 per requested date), zero duplicate timestamps, and zero critical null OHLCV fields. The timestamp string was naive `YYYY-MM-DD HH:mm:ss`; timezone and point-in-time availability are not established.

## Unusual Whales

Eight bounded flow-alert probes returned HTTP 200 with one aggregate record each. The returned schema exposed option-chain, event-time, premium, size, volume/OI, sweep/floor/multileg, bid/ask, IV start/end and opening-trade classification fields. The endpoint returned aggregate alerts rather than individual trades; historical PIT retention and independent availability remain unverified.

## Massive Options Advanced

Eight contract-reference probes returned HTTP 200 and status `OK`. Directed trades and quotes using the option-chain identifiers returned by the event source returned HTTP 401 for all 16 probes; a bearer-header retry produced HTTP 403 on a bounded AAPL trade probe. This is a provider permission/plan blocker, not evidence of missing market data.

## Gate status

- FMP underlying/earnings bounded schema gate: **PASS for response availability; FAIL for timezone/PIT completion**.
- Unusual Whales bounded flow schema gate: **PASS for field availability; BLOCKED for historical PIT proof**.
- Massive directed contract trade/quote gate: **BLOCKED (`MASSIVE_AUTH_OR_PLAN_UNAUTHORIZED`)**.
- B1 construction: **BLOCKED** until historical ordinary option-state availability and timestamps are independently validated.
- Asset freeze/backfill/modeling: **NOT AUTHORIZED** by these results.


## FMP depth probe

A bounded 2015-01-05 through 2015-01-07 probe returned HTTP 200 for all eight assets. Six assets returned 1,170 rows (390 per session); AMZN and TSLA returned 1,169 rows, so the probe exposes a one-minute completeness exception. This establishes only that these dates are reachable, not the earliest recoverable date; timestamp strings remain naive and require timezone validation.

