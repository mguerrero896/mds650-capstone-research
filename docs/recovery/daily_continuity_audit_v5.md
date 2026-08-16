# Daily common-history continuity audit v5

Run date: 2026-07-22  
Window: `2025-07-21` inclusive through `2026-07-21` exclusive  
Calendar: XNYS  
Assets: SPY, QQQ, AAPL, MSFT, NVDA, TSLA, AMZN, META

## Scope and direct provider contracts

The audit made direct authenticated requests only. FMP used the documented
`/stable/historical-chart/1min` endpoint with exact `from`/`to` dates. Massive
used historical contracts with `as_of` and `GET /v3/quotes/{optionsTicker}`
with `timestamp.lte` in nanoseconds, descending timestamp order and `limit=1`.
Unusual Whales used a one-byte `Range: bytes=0-0` request for Full Tape file
metadata; it did not download ZIP contents and it does not establish PIT
publication availability.

Official references:

- FMP: https://site.financialmodelingprep.com/how-to/how-to-get-stock-intraday-data-with-fmp-apis
- UW Flow Alerts: https://api.unusualwhales.com/docs/operations/PublicApi.OptionTradeController.flow_alerts
- UW OptionTrade: https://api.unusualwhales.com/docs/kafka/types/OptionTrade
- Massive contracts: https://massive.com/docs/rest/options/contracts
- Massive quotes: https://massive.com/docs/rest/options/quotes

## Observed results

- 251 XNYS sessions and 2,008 asset-days were probed.
- 233 dates passed all three metadata/quote continuity components for all eight
  assets.
- Massive reference and quote requests were HTTP 200 for 2,008/2,008
  asset-days; every accepted quote had `sip_timestamp <= origin` in nanoseconds,
  with positive bid and ask greater than bid.
- Massive contract resolution recorded a provider-parameter behavior rather
  than hiding it: the initial documented `expired=true` request returned no
  candidate for each of the 2,008 asset-days, so the probe issued and recorded
  an explicit `expired=false` fallback with the same `as_of` and DTE bounds.
  This was not treated as silent substitution. The selected contract and
  quote remained subject to historical `as_of`, expiry, moneyness and
  `sip_timestamp <= origin` checks; the artifact preserves both sanitized
  requests and marks the behavior for follow-up entitlement/contract review.
- UW Full Tape metadata was HTTP 206 with `Content-Range` for 251/251 dates.
  `pit_claim=false` is retained for every record.
- FMP exact-session rates were AAPL/AMZN/META 98.80%, MSFT/NVDA/QQQ/SPY
  99.60%, and TSLA 97.61%.
- Nineteen FMP asset-days had one to three missing minute labels. A wider
  direct date-range request was run for each; all nineteen gaps persisted.
  Their cause remains `UNRESOLVED_PROVIDER_CALENDAR_OR_HALT`; no interpolation
  or silent substitution was performed.

## Gate interpretation

`OBSERVED_DAILY_PROVIDER_CONTINUITY_WITH_UW_PIT_UNVERIFIED` / `FAIL_CLOSED`.
The artifact establishes observed daily provider coverage and direct Massive
quote ordering, but not UW historical publication timing or FMP start-versus-
close bar semantics. It therefore does not authorize backfill, models, QLIKE,
tuning, asset freezing or final testing.

Evidence: `artifacts/api_audit/common_history_continuity_v5.json`  
Owner decisions: `docs/pit_gate_authorization_20260722.md`
