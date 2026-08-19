# B1 as a contemporaneous option-state snapshot

Frozen specification for the RP2-v3 B1 block. It replaces the lagged window RP2-v2 used.

## What changed and why

RP2-v2 ended B1's snapshot 1 920 seconds before the forecast origin so that no tape row
could appear in both B1 and B2. That bought row-disjointness at the cost of the thing B1
is for: it stopped being the state of the option market at `t` and became the state of the
option market half an hour earlier.

The disjointness was never required. The contrast is conditional —
`E[Y | B0, B1, B2]` against `E[Y | B0, B1]` — so B1 and B2 may be correlated, and indeed
must be allowed to be: an increment measured against a deliberately stale B1 credits flow
with information the surface already carried and simply was not asked for.

## Frozen parameters

```text
Forecast origin: t
Availability cutoff: t - 120 seconds
Maximum quote age: 30 minutes
Sensitivity maximum age: 60 minutes
Contract state: last available NBBO per contract
Primary source label: trade_sampled_contemporaneous_nbbo
Post-cutoff observations: forbidden
```

## Algorithm

For each origin `t`:

1. `c_t = t - 120 s`;
2. keep only rows with `created_at <= c_t`;
3. drop rows older than `c_t - 30 min`;
4. group by contract;
5. keep the last available observation of each contract;
6. build the surface from that snapshot.

Quote age is measured **against the forecast origin**, not against the cutoff, because the
age a reader cares about is how stale the state is at the moment the forecast is made.
The 120-second availability cutoff is therefore a floor on the reported age.

## B1-core

The primary information set carries only high-coverage features:

```text
b1_iv_7d
b1_iv_30d
b1_iv_60d
b1_term_slope
b1_smile_level
b1_risk_reversal_25
b1_median_relative_spread
b1_median_quote_age_s
b1_surface_coverage
b1_iv_minus_trailing_rv_30d
```

### Two of the ten are new

`b1_smile_level` is the fitted at-the-money level of the smile on the expiry bucket nearest
30 calendar days — the level the existing slope, curvature and butterfly features were all
measured *against* without ever being reported.

`b1_surface_coverage` is the share of four grid requirements the snapshot met at that
origin: at least three contracts, both wings spanned, and at least two expiries. It is a
scalar in `{0, 0.25, 0.5, 0.75, 1}`, so a model can condition on the quality of the state it
is reading rather than treating a thin surface and a full one as the same evidence.

## B1-rich

Kept, reported, and **not** part of the primary set:

```text
b1_implied_rate
b1_implied_dividend_yield
arbitrage diagnostics
low-coverage curvature diagnostics
```

A row is never discarded because implied rate or implied dividend yield failed to fit. A
failed rate is a missing diagnostic, not a missing origin.

## Targets

| Metric | RP2-v3 target |
| --- | ---: |
| B1-core coverage | > 90 % |
| Median quote age against the origin | < 900 s |
| P95 quote age | <= 1 800 s |
| Rows discarded for rate or dividend | 0 |
| Post-cutoff observations | 0 |
| Duplicate contracts per snapshot | 0 |

## What this does not buy

A contract enters the surface only because somebody traded it, so the *selection* of quotes
is still driven by flow. Moving the window forward removes a lag, not that selection.
Decision 77 measures the selection bias against an independent quote feed; that measurement
is a property of trade sampling and is unchanged by the window.
