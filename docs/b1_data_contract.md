# B1 data contract: B1Q and B1T

## Scope

This contract covers the controlled feasibility phase for the 2,840 Pilot V2
forecast origins. It does not authorize a backfill, final benchmark evaluation
or twenty-session download.

## Routes

| Route | Source | Role | Independence |
|---|---|---|---|
| B1Q | Massive historical quotes | Primary ordinary option state | Independent of trade occurrence |
| B1T | Existing UW Full Tape rows | Fallback/sensitivity | Dependent on the B2 source |

## Quote selection

For each asset-date, resolve contracts with `as_of`, cache the contract-day
response, and locally select the last quote satisfying:

`sip_timestamp <= forecast_origin`

Primary filters: `bid > 0`, `ask > bid`, quote age <= 60 seconds and relative
spread <= 25%. Sensitivities use 300 seconds and 50%. A missing result is
classified as no quote, temporal filter error, inactive contract, nanosecond
error, pagination issue, invalid spread or stale quote; it is never replaced by
zero.

Contracts are selected in short (7–21), medium (30–60) and long (90–180) DTE
buckets at moneyness targets 0.95, 0.975, 1.00, 1.025 and 1.05.

## Per-origin fields

Each route emits B1a ATM IV, B1b skew, B1c term structure, interpolation flags,
contract/quote counts, expiry-bucket and moneyness counts, median quote age,
median relative spread, IV attempts/successes, failure reason and source request
hash. B1T rows additionally carry the Full Tape operational availability proxy
and are not independent of B2.

Black–Scholes–Merton is an approximation for American options. Inputs must be
known no later than the origin: midpoint, FMP spot, strike, expiry, option type,
last prior Treasury rate and prior-known dividends. Future rates, dividends,
EPS, revenue and invalid/crossed quotes are prohibited.
