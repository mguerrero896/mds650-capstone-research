# Fixture-only dataset preview

This artifact is deterministic fixture data, not historical provider data.
It is not a pilot acceptance and is not authorized for modeling or evaluation.

- Run: `fixture-preview-20260721`
- Candidates covered: 8
- Frozen assets (quality/coverage fixture gate): AAPL, AMZN, META, MSFT, NVDA, QQQ
- Valid RV30 targets: 16
- Excluded origins with missing future bars: 48
- RV30 contract: one fully observed anchor close plus 30 future closes = 30 log returns

## Table row counts

| table | rows |
|---|---:|
| `underlying_1min` | 320 |
| `corporate_events` | 8 |
| `unusual_option_events` | 8 |
| `option_state_snapshots` | 8 |
| `option_trades` | 8 |
| `option_quotes` | 8 |
| `forecast_origins` | 16 |
| `rv30_targets` | 16 |
| `row_trace` | 16 |

## Gate status

- `B1_NOT_AUTHORIZED`
- `COMMON_HISTORY_NOT_ESTABLISHED`
- `PROVIDER_FAILURES_PRESENT`
- `authorized_for_backfill=false`
