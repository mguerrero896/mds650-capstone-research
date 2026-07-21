# Authenticated provider audit v1 summary

- Run: `790ec9ae-234b-40e3-bf80-5e83c1d9c92e`
- Generated: `2026-07-20T11:53:17.118862Z`
- Secret values emitted: `false`
- Raw payloads: restricted logical root `restricted://MDS650/raw`

## Gate status

- FMP minute probes: `8` assets; timestamp/PIT semantics remain gated.
- FMP earnings probes: `8` assets; ETF applicability is explicit.
- Unusual Whales event assets: `8`; event IV presence is separate from ordinary PIT state.
- Massive directed trades: `['200:1']`.
- Massive directed quotes: `['200:1']`.
- B1: `BLOCKED` until independent PIT IV/skew/term-structure coverage is proven.
- Backfill: `NOT_AUTHORIZED`.

## Explicit limitations

- FMP timestamp start/close semantics remain unresolved.
- FMP official calendar, adjustment and halt classification remain audit gates.
- Unusual Whales alert timestamps are not independent publication availability.
- Massive directed trade/quote access passed for one O:-prefixed event-returned contract; broader history and licensing remain unverified.
