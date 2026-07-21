# Authenticated provider audit v1 summary

- Run: `e7c7e6a9-1218-4732-b9c6-2ccec97dec21`
- Generated: `2026-07-20T12:02:29.509108Z`
- Secret values emitted: `false`
- Raw payloads: restricted logical root `restricted://MDS650/raw`

## Gate status

- FMP minute probes: `8` assets; timestamp/PIT semantics remain gated.
- FMP earnings probes: `8` assets; ETF applicability is explicit.
- Unusual Whales event assets: `8`; event IV presence is separate from ordinary PIT state.
- Unusual Whales ordinary-state field assets: `['AAPL', 'AMZN', 'META', 'MSFT', 'NVDA', 'QQQ', 'SPY', 'TSLA']`; valid empty records: `1`.
- Unusual Whales minimum event date observed: `2026-07-17`; oldest probes: `['uw-flow-oldest-accepted-aapl:200', 'uw-flow-oldest-rejected-aapl:403']`.
- Massive directed trades: `['200:1']`.
- Massive directed quotes: `['200:1']`.
- B1: `BLOCKED` until independent PIT IV/skew/term-structure coverage is proven.
- Backfill: `NOT_AUTHORIZED`.

## Explicit limitations

- FMP timestamp start/close semantics remain unresolved.
- FMP official calendar, adjustment and halt classification remain audit gates.
- Unusual Whales alert timestamps are not independent publication availability.
- Massive directed trade/quote access passed for one O:-prefixed event-returned contract; broader history and licensing remain unverified.
