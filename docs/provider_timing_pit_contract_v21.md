# Provider Timing PIT Contract v2.1

**Status:** `CONDITIONAL_NOT_CLOSED`

## Scope

This amendment is target-blind. It reads official documentation and already
acquired Full Tape, B2, B1 provenance, and Massive cache data only. It does not
read RV30, QLIKE, forecasts, predictions, model outputs, or outcomes. It does
not train a model or download provider data.

## FMP one-minute bars

FMP's FAQ documents intraday timezone convention at the exchange-country/region
level. `timestamp_raw + 1 minute` remains a conservative study rule. Exact IANA
implementation, DST handling, bar-start/bar-close label, and completed-bar
latency are unresolved provider facts.

## Unusual Whales Full Tape

The REST/OpenAPI sources document a date-specific ZIP. Kafka documentation
defines Kafka timestamps; Full Tape field-name and UTC concordance are payload
observations only. Neither source establishes historical publication time or
client receipt. `created_at` remains an operational availability proxy.

## B2 activity availability

Canonical B2 matrices lack an independent provider-availability field.
`b2v2_max_created_at_utc` is activity provenance, not a health indicator. The
coding sidecar counts are `{'NUMERIC_NONZERO_FEATURE_VALUES': 5339, 'ZERO_CODING_POTENTIALLY_CONFOUNDED': 61}`.

**Gate:** `FAIL_ZERO_ACTIVITY_NOT_DISAMBIGUATED`. A source record-creation delay paired with an all-zero
B2 row cannot be called genuine zero activity. The B2 activity-availability
contract is **not closed** until a future consumer applies the sidecar state.

**Existing-results reconciliation:**
`SAFE_TO_RECONCILE_EXISTING_RESULTS=NO`.
Reasons: `B2_ACTIVITY_AVAILABILITY_GATE_NOT_CLOSED`.
This rendering does not read, alter, or reinterpret any sealed predictive result.

## Massive shifted as-of sensitivity

At every delay, the audit reselects the last cached quote satisfying
`sip_timestamp <= forecast_origin - delay`; it does not filter a quote selected
at the original origin. IV is recalculated from the new midpoint and existing
target-free PIT inputs. This does not prove customer-side REST receipt latency.

**Forecast-origin session gate:** `PASS`.
The audit reports `0`
origins before the official open and
`0` after the
official close, including early-close sessions.

**Massive cache-identity gate:** `PASS`. A failed identity or
monotonicity check keeps this contract conditional even if the B2 gate later
becomes passable.

**Massive request-scope warnings:** `{'OK_EARLY_CLOSE_POST_CLOSE_QUOTES_EXCLUDED': 31, 'OK_EARLY_CLOSE_REQUEST_OVEREXTENDED': 329}`. An early-close
request extended to the nominal 16:00 close is always reported separately,
rather than silently treated as an exact session request. If it contains a SIP
record after the actual close, the audit removes that record before every
as-of join and records `OK_EARLY_CLOSE_POST_CLOSE_QUOTES_EXCLUDED`; it never
permits such a record to be selected. The forecast-origin table is separately
constrained to the actual session close.

| Cutoff | Quote coverage | Median quote age from origin (s) | IV available |
| --- | --- | --- | --- |
| origin - 0s | 1.000000 | 1.1496710495 | 0.998856 |
| origin - 60s | 1.000000 | 61.115299468 | 0.998628 |
| origin - 300s | 0.986033 | 301.14915498949995 | 0.982856 |

## Official source archive

| Source | Status | Body SHA-256 | Support | Boundary |
| --- | --- | --- | --- | --- |
| fmp_faq_intraday_timezone | HTTP 200 | 9f396b9e8b98b82af4c5a04a937ff72037f1022993cc7bf36cf8333b707e43d6 | FMP states that endpoint time zones correspond to the country or region of the exchange; the intraday endpoint follows the same convention. | The FAQ does not establish exact IANA zone handling, DST implementation, bar start/close labels, or completed-bar latency. |
| uw_full_tape_rest | HTTP 200 | c435e35c7f4b7708923fa941a92ef160fc9d1e8a3ea44707503691fff0fca16f | The REST operation downloads all option transactions for a required market date and returns an application/zip response. | The operation page does not define the semantics of executed_at or created_at fields inside a historical ZIP payload. |
| uw_kafka_option_trade | HTTP 200 | e1940f9ac46154a54c71ac5b367ba0b26cc98e1bb2a2dda45619fedd18647513 | Kafka OptionTrade documents executed_at as execution time and created_at as trade-record creation time, in Unix milliseconds. | Kafka documentation does not establish publication time, client receipt time, or identical semantics for a historical Full Tape ZIP. |
| uw_openapi_full_tape | HTTP 200 | 0f975cca5bebcd6d2d06c327756ca6f740e325641ecf176bccec3f5285260240 | OpenAPI describes GET /api/option-trades/full-tape/{date} as a full option-transaction ZIP for a market date. | The OpenAPI response declaration does not define historical field-level created_at or executed_at semantics. |
