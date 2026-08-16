# B2 feature contract — Pilot V2

## Panel and availability

The primary panel contains every valid five-minute origin for all eight candidates. For each
origin `t`, eligible Full Tape rows satisfy `created_at <= t - 60 seconds`. Sensitivity rows
use `created_at <= t - 15 seconds` and `created_at <= t`. `created_at` is an
`operational_availability_proxy`, not a publication-time claim.

`option_activity_present` is true when at least one eligible option trade exists. It is not an
unusualness label and does not require a matching no-operation origin. `unusual_event` remains
secondary and is `NOT_CALIBRATED` in Pilot V2.

## Continuous variables

Pilot V2 emits, per origin and availability specification: trade count, unique contracts,
total/max premium, total/max contract size, call/put premium and imbalance, ask/bid/midpoint
premium shares, multileg/sweep-equivalent shares, strike/expiry concentration, median DTE,
median absolute moneyness, repeated-contract count/premium, IV median/change, valid-trade
share and missing-IV share.

Provider cumulative fields (`volume`, `ask_vol`, `bid_vol`, `mid_vol`, `no_side_vol`) are not
predictors until their reset and availability semantics are proven. Internal sums are computed
only from eligible rows. `open_interest` is previous-session information unless independently
documented otherwise.

No call/put, ask-side, sweep, multileg or volume/OI field is interpreted as directional intent,
informed buying, opening activity or bullish/bearish information.
