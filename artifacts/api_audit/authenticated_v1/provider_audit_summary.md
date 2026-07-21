# Authenticated provider audit v1 summary

- Run: `08a704db-8fe3-41a9-aa74-776111e63936`
- Generated: `2026-07-20T11:30:30.256265Z`
- Secret values emitted: `false`
- Raw payloads: restricted logical root `restricted://MDS650/raw`

## Gate status

- FMP minute probes: `8` assets; timestamp/PIT semantics remain gated.
- FMP earnings probes: `8` assets; ETF applicability is explicit.
- Unusual Whales event assets: `8`; event IV presence is separate from ordinary PIT state.
- Massive directed trades: `['403:1']`.
- Massive directed quotes: `['403:1']`.
- B1: `BLOCKED` until independent PIT IV/skew/term-structure coverage is proven.
- Backfill: `NOT_AUTHORIZED`.

## Explicit limitations

- FMP timestamp start/close semantics remain unresolved.
- FMP official calendar, adjustment and halt classification remain audit gates.
- Unusual Whales alert timestamps are not independent publication availability.
- Massive directed trade/quote entitlement is not assumed from reference access.
