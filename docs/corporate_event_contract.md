# Corporate event contract

## Frozen rules

- Individual equities use `instrument_type=equity` and may use only ex-ante FMP
  `date` plus BMO/AMC `time` when the timing is point-in-time verifiable.
- `epsActual`, `revenueActual` and published results are excluded from
  predictors.
- SPY and QQQ use `instrument_type=ETF` and
  `earnings_applicable=false`; both BMO/AMC indicators are zero and
  `days_to_next_earnings` is null.
- No ETF earnings event is synthesized. Dividends/distributions are never a
  substitute for earnings; they remain separate PIT inputs for IV inversion.
- Every dividend/distribution input records source, knowledge cutoff and yield
  method.

The executable guard is `mds650.events.earnings_instrument_contract` and ETF
earnings are rejected by `eligible_earnings_events`.
