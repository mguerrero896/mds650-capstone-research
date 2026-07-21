# Pilot dataset contract

## Recovery status

This contract is defined now but its implementation and dataset construction are deferred.
No connector, normalization or pilot run is authorized in the recovery iteration.

The target MUST use the fully observed close at forecast origin t and the next thirty consecutive one-minute closes, producing exactly thirty one-minute log returns.

## Required tables

The pilot exports six component tables, a forecast-origin table, and the target
table. The six components are underlying one-minute OHLCV, structured corporate
events, unusual option events, point-in-time option state, contract trades, and
consolidated contract quotes.

Every table includes `run_id`, `source_provider`, `source_response_id`,
`observed_at_utc`, and `observed_at_ny`. Raw source payloads remain immutable
outside normalized tables and are linked by SHA-256 digest.

## Temporal invariants

- `observed_at_utc` is timezone-aware and is the canonical ordering field.
- `observed_at_ny` is the same instant represented in `America/New_York`.
- Forecast origins are aligned to five-minute boundaries within validated
  regular-market sessions.
- Predictors are restricted to records with proven `available_at <= origin_time`; event time
  alone is insufficient.
- The target uses the fully observed close at origin `C(i,t)` and the next thirty consecutive
  one-minute closes `C(i,t+1)...C(i,t+30)`, producing exactly thirty log returns:
  `r(i,t+j)=ln[C(i,t+j)/C(i,t+j-1)]`, `j=1,...,30`, and
  `RV(i,t:t+30)=Σ[j=1..30]{r(i,t+j)}²`.
- The exact FMP bar start/close convention, origin close, last valid regular/early-close
  origin, missing 31-price behavior and halt classification must be frozen before any pilot.
  Missing prices are invalid and are never silently interpolated.
- Corporate earnings intervals are joined by release timestamp and are never
  forward-filled from a later observation.

## Keys and quality rules

Deduplication keys are documented per table in `data-model.md`. Duplicate keys,
unexpected schema changes, non-monotone timestamps, invalid OHLC relationships,
or missing required target closes cause an explicit failure. Missing option
quotes are retained as missing observations with a quality flag; they are not
imputed silently.

The pilot must contain event and no-event origins for all eight candidates while preserving
their natural prevalence. If the configured window has too few events, the extraction window
is widened by a recorded configuration change; assets are not selected by preliminary model
performance. Any training-only subsampling or weighting must be documented, and validation
and final testing must preserve the natural distribution.

## Required outputs

```yaml
pilot_manifest.json
pilot_profile.html
pilot_row_trace.jsonl
pilot_tables/*.parquet
```

The manifest reports row counts, coverage, missingness, duplicate counts,
timezone checks, target construction counts, event/no-event counts, asset
quality scores, and the frozen asset set (4–6 assets selected only by coverage
and quality). The row trace maps a normalized forecast origin to source hashes,
predictor cutoff, future close timestamps, and realized-variance calculation. Every valid row
must contain one origin-close timestamp, thirty future-close timestamps, immutable references
to all 31 prices, the formula version and a deterministic target hash. Missing or ambiguous
closes produce a non-valid status rather than an imputed row.
