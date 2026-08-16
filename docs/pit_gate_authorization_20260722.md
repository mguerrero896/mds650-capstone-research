# PIT gate authorization — 2026-07-22

The project owner approved the following bounded decisions for the current run:

1. RV30 is the official target horizon. RV10 is not introduced.
2. FMP `available_at = timestamp_raw + 1 minute` is an explicit conservative research
   assumption, not a provider-confirmed bar-boundary claim.
3. UW `created_at <= forecast_origin - 60 seconds` may be used only as an
   `operational_availability_proxy`; it is not `publication_time` and does not prove
   historical publication availability.
4. A metadata-only daily continuity audit for the frozen 251 XNYS sessions is allowed.
   It must not download Full Tape ZIP contents or become a backfill.
5. Earnings remain excluded from the primary benchmark.

## Evidence boundary

The audit is recorded at
`artifacts/api_audit/common_history_continuity_v5.json`. It used direct documented
provider endpoints, retained no raw responses, downloaded no Full Tape ZIP, and sets
`pit_claim=false` for Unusual Whales file metadata. A successful Massive quote is
accepted only when the selected `sip_timestamp` is less than or equal to the direct
forecast-origin timestamp expressed in nanoseconds.

The official contracts consulted were:

- FMP intraday: https://site.financialmodelingprep.com/how-to/how-to-get-stock-intraday-data-with-fmp-apis
- UW Flow Alerts: https://api.unusualwhales.com/docs/operations/PublicApi.OptionTradeController.flow_alerts
- UW OptionTrade: https://api.unusualwhales.com/docs/kafka/types/OptionTrade
- Massive contracts: https://massive.com/docs/rest/options/contracts
- Massive quotes: https://massive.com/docs/rest/options/quotes

The authorization does not convert an assumption or operational proxy into provider
documentation. FMP start-vs-close semantics and UW historical publication semantics
remain separate evidence gates.
