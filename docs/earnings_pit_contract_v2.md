# Earnings PIT contract v2

Status: `PRIMARY_BENCHMARK_EXCLUDED_PENDING_PIT_INTEGRATION`

## Scope

Earnings controls may enter predictors only when the provider returns the requested
symbol, an event date, an ex-ante timing field (`bmo` or `amc`), and the project can
represent the release as available before the forecast origin. Actual EPS and revenue
values are never predictors.

## Instrument applicability

- `SPY`: `not_applicable`; no company earnings event is synthesized.
- `QQQ`: `not_applicable`; no company earnings event is synthesized.
- Equity candidates: `applicable` only when the symbol-specific response passes the
  requested/returned-symbol check and contains a usable timing value.
- A symbol with no event in the study window is `no_event_in_window`, not a failure.
- Provider schema or entitlement failures are `unsupported` or `invalid_response`.

## Point-in-time rule

The symbol-specific FMP probe at `/api/v3/historical/earning_calendar/{symbol}` observed
`date` and `time` fields and matching requested/returned symbols. This proves field
presence in the retained probe; it does not by itself prove the publication timestamp,
revision policy or parser integration for the primary pipeline.

Until those controls are integrated and tested, the primary B0/B1/B2 benchmark excludes
earnings predictors. The probe remains evidence for a later ex-ante integration task.

## Allowed derived variables after acceptance

- `earnings_bmo_today`
- `earnings_amc_today`
- `days_to_next_earnings`
- `first_session_after_earnings`

All joins must use only information known at or before the forecast origin. Date-only
earnings records remain excluded from PIT joins.

Evidence: `artifacts/pit/earnings_pit_probe_v2.json` and
`artifacts/pilot_v2/fmp_timestamp_validation_v2.json`.

