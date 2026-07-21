# Authenticated provider audit v1 summary

- Run: `76b40083-3db3-4034-942f-86e7048114f4`
- Generated: `2026-07-20T18:58:57.550362Z`
- Secret values emitted: `false`
- Raw payloads: restricted logical root `restricted://MDS650/raw`

## Gate status

- FMP minute probes: `8` assets; timestamp/PIT semantics remain gated.
- FMP earnings probes: `8` assets; ETF applicability is explicit.
- Unusual Whales event assets: `8`; event IV presence is separate from ordinary PIT state.
- Unusual Whales ordinary-state field assets: `['AAPL', 'AMZN', 'META', 'MSFT', 'NVDA', 'QQQ', 'SPY', 'TSLA']`; valid empty records: `1`.
- Unusual Whales minimum event date observed: `2026-07-20`; oldest probes: `['uw-flow-oldest-accepted-aapl:403', 'uw-flow-oldest-rejected-aapl:403']`.
- Massive directed trades: `['200:1']`.
- Massive directed quotes: `['200:3', '200:3', '200:3']`.
- B1: `BLOCKED` until independent PIT IV/skew/term-structure coverage is proven.
- Backfill: `NOT_AUTHORIZED`.

## Explicit limitations

- FMP timestamp start/close semantics remain unresolved.
- FMP calendar-match metrics assume local minute starts and are diagnostic only; official-calendar, adjustment and halt acceptance remain audit gates.
- Unusual Whales alert timestamps are not independent publication availability.
- Massive directed trade/quote access passed for one O:-prefixed event-returned contract; broader history and licensing remain unverified.
