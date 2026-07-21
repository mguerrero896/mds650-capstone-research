# Authenticated provider audit v1 summary

- Run: `f4f54d90-4979-4b7b-9384-09c964e36c80`
- Generated: `2026-07-21T02:19:43.628832Z`
- Secret values emitted: `false`
- Raw payloads: restricted logical root `restricted://MDS650/raw`

## Gate status

- FMP minute probes: `8` assets; timestamp/PIT semantics remain gated.
- FMP earnings probes: `8` assets; ETF applicability is explicit.
- Unusual Whales event assets: `8`; event IV presence is separate from ordinary PIT state.
- Unusual Whales ordinary-state field assets: `['AAPL', 'AMZN', 'META', 'MSFT', 'NVDA', 'QQQ', 'SPY', 'TSLA']`; valid empty records: `1`.
- Unusual Whales minimum event date observed: `2024-08-02`; oldest probes: `['uw-flow-oldest-accepted-aapl:200', 'uw-flow-oldest-rejected-aapl:403']`.
- Massive directed trades: `['200:1']`.
- Massive directed quotes: `['200:3', '200:3', '200:3']`.
- Massive empty quote windows: `['200:0']`.
- B1: `INFEASIBLE`; fallback: `B2-vs-B0`.
- Backfill audit status: `NOT_AUTHORIZED`; pilot approval remains a separate downstream gate.

## Explicit limitations

- FMP timestamp start/close semantics remain unresolved.
- FMP calendar-match metrics assume local minute starts and are diagnostic only; official-calendar, adjustment and halt acceptance remain audit gates.
- Unusual Whales alert timestamps are not independent publication availability.
- Massive directed reference/trades/quotes, one followed quotes page, bid/ask and trade-condition fields passed for one O:-prefixed event-returned contract; an empty historical quote window was valid, while broader history and licensing remain unverified.
