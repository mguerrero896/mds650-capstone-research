# Authenticated provider audit v1 summary

- Run: `a07543c0-a790-4ef8-9abb-960603bd0b04`
- Generated: `2026-07-20T11:56:23.225703Z`
- Secret values emitted: `false`
- Raw payloads: restricted logical root `restricted://MDS650/raw`

## Gate status

- FMP minute probes: `8` assets; timestamp/PIT semantics remain gated.
- FMP earnings probes: `8` assets; ETF applicability is explicit.
- Unusual Whales event assets: `8`; event IV presence is separate from ordinary PIT state.
- Unusual Whales ordinary-state field assets: `['AAPL', 'AMZN', 'META', 'MSFT', 'NVDA', 'QQQ', 'SPY', 'TSLA']`; valid empty records: `1`.
- Massive directed trades: `['200:1']`.
- Massive directed quotes: `['200:1']`.
- B1: `BLOCKED` until independent PIT IV/skew/term-structure coverage is proven.
- Backfill: `NOT_AUTHORIZED`.

## Explicit limitations

- FMP timestamp start/close semantics remain unresolved.
- FMP official calendar, adjustment and halt classification remain audit gates.
- Unusual Whales alert timestamps are not independent publication availability.
- Massive directed trade/quote access passed for one O:-prefixed event-returned contract; broader history and licensing remain unverified.
