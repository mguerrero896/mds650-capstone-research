# B2 feature contract (bounded pilot)

## Availability and timing

For every five-minute forecast origin `t`, Full Tape rows are filtered by event time `executed_at` in `[t-5 minutes, t]` and by vendor-record cutoff:

- primary: `created_at <= t - 60 seconds`;
- sensitivity 1: `created_at <= t - 15 seconds`;
- sensitivity 2: `created_at <= t`.

`executed_at` is never replaced by `start_time` or `end_time` from Flow Alerts. Flow Alerts are validation/sensitivity inputs only, not the primary B2 source.

## Level 1 variables

The pilot stores event count, unique contract count, total/max premium, total/max size, call/put premium totals and imbalance, explicitly tagged side-premium shares, multileg and sweep-equivalent shares, strike/moneyness summary, repeated-contract count, and an internal five-minute size sum. Final daily volume is excluded. `open_interest` is previous-session-only and is not used from the contemporaneous event row.

## Level 2 anomaly scores

Level 2 is not produced in this bounded run. The implementation contract is a rolling historical score using only origins strictly before `t`, with a configurable lookback and no same-day future rows. Training-only weighting/subsampling may not change validation or final-test prevalence.

## Interpretation constraints

Ask proximity, calls, sweeps, multileg labels, or high volume are not interpreted as bullish intent. Every feature row carries the availability specification and raw-source provenance. Missing data fails the contract; it is never silently interpolated.
