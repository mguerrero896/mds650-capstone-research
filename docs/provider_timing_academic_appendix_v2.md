# Academic Appendix — Provider Timing and PIT Evidence v2

## Purpose

This appendix documents the timestamp contract used to prevent information entering a forecast origin after that origin. It is an engineering and provenance appendix; it does not report RV30, model, QLIKE or other predictive findings.

## Evidence taxonomy

1. **PROVIDER_DOCUMENTED** — an explicit statement on an official provider page.
2. **PAYLOAD_OBSERVED** — a field or relationship present in acquired, immutable local evidence.
3. **STUDY_CONSERVATIVE_RULE** — a deliberately stricter rule chosen by the study.
4. **UNVERIFIED** — not established by the reviewed official documentation and payloads.

## Provider-specific interpretation

- **FMP:** the one-minute endpoint scope is documented, but the raw timestamp's timezone, bar-start/bar-close semantics and numerical completed-bar API availability are unresolved. +1 and +2 minutes are therefore conservative study assumptions.
- **Unusual Whales:** `executed_at` describes execution and `created_at` describes creation of the trade record. The difference is record-creation lag. No source reviewed here establishes historical publication or this client's receipt time.
- **Massive:** `sip_timestamp` is an exchange-to-SIP source timestamp in nanoseconds and `sequence_number` provides a deterministic tie-breaker. Neither field establishes REST delivery to this client.

## Reproducible historical checks

- UW record-creation-lag CDF monotonic: `True`.
- Massive final selected quote future-free: `True`.
- This audit used existing acquired data only; it did not call a provider or create a new historical sample.

## Gates for future evidence

A new historical sample remains subject to a date-level PIT preflight. A prospective capture remains subject to a receipt logger that records provider event time, local request/receipt time, provider request ID where supplied, and clock discipline. Neither gate can be satisfied retroactively by relabelling `created_at` or `sip_timestamp`.

## Official sources

- [1 Min Interval Stock Chart API](https://site.financialmodelingprep.com/developer/docs/stable/intraday-1-min) — archived as compact metadata with source-record hash.
- [Cycle Times - FMP API](https://site.financialmodelingprep.com/developer/docs/cycle-times-stable) — archived as compact metadata with source-record hash.
- [Quotes \| Options REST API](https://massive.com/docs/rest/options/trades-quotes/quotes) — archived as compact metadata with source-record hash.
- [OptionTrade - Kafka Streaming](https://api.unusualwhales.com/docs/kafka/types/OptionTrade) — archived as compact metadata with source-record hash.
