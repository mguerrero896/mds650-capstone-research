# MDS650 observed data dictionary

This dictionary is derived from the sanitized v1r manifest and provider fixtures, not only
from provider documentation. Raw licensed values remain in restricted storage; this file
records field names, observed types/semantics and the acceptance state.

## Six component groups

| Component | Observed source fields | Type/semantic notes | Current status |
|---|---|---|---|
| Underlying 1-minute OHLCV | `date`, `open`, `high`, `low`, `close`, `volume` | `date` is a raw naive string such as `2026-07-17 09:30:00`; timezone and start/close meaning are not accepted yet | FMP partial; bar semantics blocked |
| Structured earnings | `symbol`, `date`, `epsActual`, `epsEstimated`, `revenueActual`, `revenueEstimated`, `lastUpdated` | `date` is date-only in the observed response; `lastUpdated` is retained as raw provider metadata, not release availability | FMP parsed; PIT release time unresolved |
| Unusual option events | `id`, `ticker`, `option_chain`, `start_time`, `end_time`, `created_at`, `total_premium`, `total_size`, `volume`, `open_interest`, `volume_oi_ratio`, `type`, `strike`, `expiry`, `price`, `bid`, `ask`, `has_sweep`, `has_floor`, `has_multileg`, `iv_start`, `iv_end` | Event times are epoch milliseconds; `iv_start`/`iv_end` are alert-window IV fields. No `executed_at` was present in the retained REST payload | Event fields present; PIT availability absent |
| Ordinary option state | `date`, `expiry`, `dte`, `ticker`, `volatility`, `implied_move`, `implied_move_perc`; skew `date`, `ticker`, `delta`, `risk_reversal` | `date` is trading date only; no independent publication timestamp was observed | Field coverage only; B1 blocked |
| Contract trades | `id`, `exchange`, `price`, `size`, `decimal_size`, `conditions`, `sip_timestamp`, `sequence_number` | `sip_timestamp` preserves nanosecond precision; condition codes remain uninterpreted source values | Massive directed probe passed |
| Consolidated contract quotes | `bid_price`, `ask_price`, `bid_size`, `ask_size`, `bid_exchange`, `ask_exchange`, `sip_timestamp`, `sequence_number` | Bid/ask nullability and provider pagination are preserved; empty windows are valid observations | Massive directed probe passed; broad history unverified |

## Canonical normalized fields

All normalized timestamps retain the raw value, UTC instant and `America/New_York` rendering.
`available_at_utc` is separate from event/market time and is mandatory for B1/B2 eligibility.
The target stores one origin close plus exactly thirty future closes, thirty log returns and
the formula version. Missing or ambiguous prices produce an invalid row; interpolation and
silent forward-fill are forbidden.

## Provenance and keys

Every row carries `run_id`, `source_provider`, `source_response_id`, `raw_sha256` and the
sanitized endpoint/request identity. Deduplication keys are defined in `data-model.md` and
manifest identity is `(run_id, provider, component, asset, request_start, request_end,
endpoint_fingerprint)`. A repeated key or a repeated raw hash under distinct requests fails
the audit rather than being silently deduplicated.
