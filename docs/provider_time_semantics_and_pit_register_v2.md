# Provider time semantics and PIT register v2

The machine-readable field register is
`artifacts/pit/provider_time_semantics_register_v2.json`. This document separates
provider statements, authenticated observations and research conventions.

## Field register summary

| Provider/field | Raw representation | Official/documented meaning | Observed evidence | Research availability | Status |
|---|---|---|---|---|---|
| FMP `date` / timestamp | `YYYY-MM-DD HH:mm:ss` string, naive | Intraday bar timestamp; start/close boundary is not contractually explicit in the consulted guide | Winter/summer/DST and normal/early-close probes; 78/78 five-minute labels consistent with starts | `raw + 1 minute` primary; `raw + 2 minutes` sensitivity | UNRESOLVED_LIMITATION + approved assumption |
| FMP OHLCV | numeric OHLCV | Bar values | 390 normal and 210 early-close observations; missing bars retained as exclusions | Only bars whose conservative availability is <= origin | AUTHENTICATED_EMPIRICAL_EVIDENCE |
| FMP dividends | date/numeric | Dividend record | Pre-origin filtering used in prior B1 evidence | Last known eligible record before origin | AUTHENTICATED_EMPIRICAL_EVIDENCE |
| FMP Treasury `month3` | numeric percent/date | Treasury rate observation | Latest record <= origin in B1 pipeline | No future rate | AUTHENTICATED_EMPIRICAL_EVIDENCE |
| FMP earnings `date/time` | date/string | Symbol-specific earnings calendar timing | `requested_symbol == returned_symbol`; BMO/AMC fields observed | Ex-ante timing only; excluded from primary | PARTIAL |
| Massive `sip_timestamp` | integer nanoseconds UTC | SIP quote event timestamp | Selected quote is the last quote <= origin after ns conversion | `sip_timestamp <= origin` | PASS for retained evidence |
| Massive `participant_timestamp` | integer timestamp | Participant/order timestamp metadata | Preserved as diagnostic, not used as cutoff | Not primary | PARTIAL |
| Massive `sequence_number` | integer | Ordering metadata | Used only to diagnose ordering | Not primary | PARTIAL |
| Massive `bid`,`ask`,`conditions` | numeric/code | Quote and condition fields | Accepted only for positive bid, ask>bid, age/spread limits | Midpoint only after quality filters | PASS for retained evidence |
| Massive contract `as_of`, expiry, strike, type | date/numeric/string | Historical contract reference | `as_of` contract selection in existing audit | Contract must exist on session date and expire after origin | PASS for retained evidence |
| UW `executed_at` | UTC datetime | Reported trade-event time | Used to assign the five-minute event bin | Event time, not availability | AUTHENTICATED_EMPIRICAL_EVIDENCE |
| UW `created_at` | UTC datetime | Record creation time in OptionTrade documentation | Compared with executed_at; publication/ingestion latency not established | `max(executed_at,created_at) <= origin - 60s` | UNVERIFIED; operational proxy only |
| UW event/contract identifiers | string | Trade/event and option-contract identifiers | Deduplication and exact asset mapping in retained Parquet | Required for B2 lineage | PASS for retained evidence |
| UW price/premium/size/bid/ask/type | numeric/string | Descriptive trade fields | Aggregated only from eligible rows | No intention or direction interpretation | PASS as descriptive features |
| UW sweep/multileg/floor/IV/OI | tags/numeric | Descriptive metadata | Shares/missingness preserved; OI treated as prior-session information | No informed-trading claim | PARTIAL |

Official references used in the register: FMP intraday guide,
`https://site.financialmodelingprep.com/how-to/how-to-get-stock-intraday-data-with-fmp-apis`;
Massive quotes and contracts,
`https://massive.com/docs/rest/options/quotes` and
`https://massive.com/docs/rest/options/contracts`; UW OptionTrade,
`https://api.unusualwhales.com/docs/kafka/types/OptionTrade`.

## Controlled checks

The JSON register records PASS or observed-exclusion results for winter,
summer, DST, 390-minute sessions, 210-minute early closes, duplicates,
out-of-order retained partitions, missing bars and origin-boundary checks.
The Phase 4A rebuild found 0 B0 predictors after origin, 0 Massive quotes after
origin, 0 panel-count mismatches and 0 duplicate canonical IDs in the
availability-aware matrix. It also found 0 UW recheck failures among 13,240
availability-aware rows.

These are local evidence checks, not a claim that either vendor guarantees a
publication timestamp. A provider response arriving with HTTP 200/206 does not
establish historical point-in-time availability.

## Operational rules

1. Parse raw timestamps and retain UTC plus `America/New_York`.
2. Apply `fmp_available_at = raw_timestamp + 1 minute` for primary B0 and +2
   minutes only for sensitivity.
3. Apply `uw_operational_base_time = max(executed_at, created_at)` and require
   the chosen cutoff. `created_at` is never called `publication_time`.
4. Select Massive quotes as-of origin; never use the first/last quote of a day.
5. Fail closed for missing, crossed, stale, duplicated or post-origin records.
