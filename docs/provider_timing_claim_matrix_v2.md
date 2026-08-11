# Provider Timing Claim Matrix v2

This matrix separates provider documentation, local payload observations, conservative study rules, and unresolved claims. It contains no target, prediction, or performance result.

| Provider | Field or topic | Claim class | Evidence locator | Permitted conclusion |
|---|---|---|---|---|
| FMP | 1-minute chart endpoint | PROVIDER_DOCUMENTED | fmp_1min_endpoint | The endpoint provides one-minute OHLCV data and is described as real-time or historical. |
| FMP | raw date as bar start or close | UNVERIFIED | fmp_1min_endpoint_and_local_payload | Do not state that the provider documents whether the timestamp labels bar start or bar close. |
| FMP | 1-minute chart cycle time | PROVIDER_DOCUMENTED | fmp_cycle_times | The cycle-times page labels the 1-minute chart Real-Time, without a numeric completed-bar availability SLA. |
| FMP | primary bar availability | STUDY_CONSERVATIVE_RULE | study_contract_v2 | Use raw timestamp plus one minute only as a conservative study availability rule. |
| FMP | bar availability sensitivity | STUDY_CONSERVATIVE_RULE | study_contract_v2 | Use raw timestamp plus two minutes only as a prespecified conservative sensitivity. |
| FMP | raw date timestamp | PAYLOAD_OBSERVED | authenticated_audit_and_fixture | Acquired bars expose a naive YYYY-MM-DD HH:mm:ss raw date field. |
| FMP | raw date timestamp timezone | UNVERIFIED | fmp_1min_endpoint_and_local_payload | Do not state a provider-confirmed timezone for the naive raw date string. |
| Massive | last quote at or before forecast origin | STUDY_CONSERVATIVE_RULE | study_contract_v2 | Select the latest quote with sip_timestamp no later than the forecast origin. |
| Massive | cached query upper bound | PAYLOAD_OBSERVED | existing_massive_v4_cache | The audited v4 cache stores a sanitized timestamp.lte request bound. |
| Massive | REST response arrival | UNVERIFIED | massive_options_quotes | The quote source timestamp does not prove REST response or client-receipt time. |
| Massive | sequence_number | PROVIDER_DOCUMENTED | massive_options_quotes | The sequence number is increasing and unique per option ticker, but not necessarily sequential. |
| Massive | sip_timestamp | PROVIDER_DOCUMENTED | massive_options_quotes | The field is the nanosecond Unix timestamp when SIP received the quote from the exchange. |
| Unusual Whales | created_at | PROVIDER_DOCUMENTED | uw_option_trade | The field is the time the trade record was created in Unix milliseconds. |
| Unusual Whales | B2 eligibility cutoff | STUDY_CONSERVATIVE_RULE | study_contract_v2 | Use created_at only as an operational availability proxy with 60/120/300-second buffers. |
| Unusual Whales | executed_at | PROVIDER_DOCUMENTED | uw_option_trade | The field is the trade execution time in Unix milliseconds. |
| Unusual Whales | publication time and client receipt | UNVERIFIED | uw_option_trade | No historical publication-time or client-receipt field is established by this source. |
| Unusual Whales | created_at minus executed_at | PAYLOAD_OBSERVED | existing_full_tape | This derived quantity is record-creation lag; it is not provider publication or client-receipt latency. |
| Unusual Whales | persisted executed_at and created_at | PAYLOAD_OBSERVED | existing_full_tape | Acquired Full Tape persists both timestamp fields as UTC instants. |

## Official-source archive

- `fmp_1min_endpoint`: [1 Min Interval Stock Chart API](https://site.financialmodelingprep.com/developer/docs/stable/intraday-1-min)
- `fmp_cycle_times`: [Cycle Times - FMP API](https://site.financialmodelingprep.com/developer/docs/cycle-times-stable)
- `massive_options_quotes`: [Quotes \| Options REST API](https://massive.com/docs/rest/options/trades-quotes/quotes)
- `uw_option_trade`: [OptionTrade - Kafka Streaming](https://api.unusualwhales.com/docs/kafka/types/OptionTrade)
