# Provider Timing PIT Contract v2

## Scope and invariant

This contract was built from official documentation and previously acquired, target-free provider evidence. It made no provider HTTP request, downloaded no market data, read no RV30/QLIKE/prediction/outcome field, and did not modify canonical research artifacts.

One forecast origin is an asset at a valid five-minute XNYS market-time origin. Each provider field is usable only under the evidence class below; a study rule is never represented as provider documentation.

## FMP one-minute OHLCV

- **Provider documentation:** [FMP 1-minute endpoint](https://site.financialmodelingprep.com/developer/docs/stable/intraday-1-min) documents one-minute OHLCV scope; [cycle times](https://site.financialmodelingprep.com/developer/docs/cycle-times-stable) labels the endpoint Real-Time.
- **Payload observation:** `Acquired bars expose a naive YYYY-MM-DD HH:mm:ss raw date field.`
- **Unresolved provider semantics:** FMP's raw timestamp timezone and whether it labels bar start or close are **not provider-documented** in the reviewed sources. The acquired audit records both as unresolved.
- **Study rule:** interpret the raw label under the existing XNYS/`America/New_York` research convention, then set **FMP +1 minute** as the primary `available_at` rule and **FMP +2 minutes** as the prespecified sensitivity. These are conservative study rules, not an FMP latency statement.
- **Calendar rule:** XNYS calendar logic controls regular sessions, DST transitions and early closes. This does not imply that FMP documents its bar-label semantics or its own calendar.

## Unusual Whales Full Tape / B2

- **Provider documentation:** [OptionTrade](https://api.unusualwhales.com/docs/kafka/types/OptionTrade) defines `executed_at` as execution time and `created_at` as trade-record creation time, both Unix milliseconds.
- **Payload observation:** Full Tape persists both fields as UTC instants. `created_at - executed_at` is named **record-creation lag** in this study; it is not publication time, feed-dispatch time or client-receipt time.
- **Study rule:** for buffer `d` in {60, 120, 300} seconds, B2 uses `[origin - d - 5 minutes, origin - d)` and requires `max(executed_at, created_at) <= origin - d`. The primary rule is `d=60`; 120 and 300 seconds are prespecified sensitivities.

### Record-creation-lag CDF (exact acquired scope)

| Buffer (seconds) | Within-buffer share | Interpretation |
|---:|---:|---|
| 60 | 99.3894% | Nested record-creation-lag CDF; monotonic by construction. |
| 120 | 99.4515% | Nested record-creation-lag CDF; monotonic by construction. |
| 300 | 99.4912% | Nested record-creation-lag CDF; monotonic by construction. |

### Exact B2 feature-window eligibility (existing origins)

| Buffer (seconds) | Candidate trades | Eligible trades | Eligibility retention | Note |
|---:|---:|---:|---:|---|
| 60 | 208,072,824 | 206,802,148 | 99.3893% | Windows shift with the buffer; this table is not a nested-CDF claim. |
| 120 | 207,674,156 | 206,379,715 | 99.3767% | Windows shift with the buffer; this table is not a nested-CDF claim. |
| 300 | 206,477,704 | 205,248,953 | 99.4049% | Windows shift with the buffer; this table is not a nested-CDF claim. |

### Extreme-tail audit

- Both timestamps observed: 224,672,292; negative record-creation lags: 0; lags over 300 seconds: 1,143,028; maximum observed lag: 23995.223140 seconds.

## Massive B1 quotes

- **Provider documentation:** [Massive Quotes](https://massive.com/docs/rest/options/trades-quotes/quotes) defines `sip_timestamp` as the nanosecond timestamp when SIP received a quote from the exchange. `sequence_number` is increasing and unique per option ticker, but need not be sequential.
- **Payload observation:** the existing v4 cache records sanitized `timestamp.lte`, `sort`, `order`, `limit`, `sip_timestamp`, `sequence_number`, bid and ask fields. The cache audit reports schema and request-upper-bound violations separately.
- **Study rule:** select the last `(sip_timestamp, sequence_number)` quote whose `sip_timestamp <= forecast_origin`. This source-time rule prevents a future SIP quote from entering an origin, but it does not establish when a Massive REST response reached this project.
- **Availability sensitivities:** source-time delays and maximum quote-age filters are conservative feasibility sensitivities. They are not labelled as measured Massive REST or client latency.

### Existing selected-quote evidence

| Check | Result |
|---|---:|
| B1 origin rows | 77,328 |
| Final selected future SIP timestamps | 0 |
| IV-attempt future SIP timestamps | 0 |
| Negative quote ages | 0 |
| Final selected quote future-free | True |
| Deterministic cache files schema-valid | 512 |
| Cache quotes after request upper bound | 0 |

## Gate map

| Gate | Status | Meaning |
|---|---|---|
| `EXISTING_FMP_EVIDENCE` | `CONDITIONAL_STUDY_RULE_ONLY` | Existing evidence is usable only under explicit study rules. |
| `EXISTING_MASSIVE_CACHE_SCHEMA_SAMPLE` | `PASS` | Sampled cache schema and request bounds were checked separately. |
| `EXISTING_MASSIVE_SELECTED_QUOTE_EVIDENCE` | `PASS` | Existing B1 source-time provenance has no future selected quote. |
| `EXISTING_UW_RECORD_CREATION_EVIDENCE` | `PASS_PROXY_ONLY` | Record creation supports a proxy-only eligibility rule. |
| `NEW_HISTORICAL_SAMPLE` | `REQUIRES_DATE_LEVEL_PIT_PREFLIGHT` | A date-level PIT preflight is required before any new historical sample. |
| `NEW_PROSPECTIVE_CAPTURE` | `REQUIRES_PROVIDER_RECEIPT_LOGGER` | A receipt logger is required before prospective latency claims. |
| `UNIVERSAL_PROVIDER_PUBLICATION_OR_RECEIPT_LATENCY` | `NOT_SUPPORTED` | Not established by existing documentation and payloads. |
