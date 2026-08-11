# Provider Timing Semantics Audit v1

## Scope and boundary

This is an offline audit of already-acquired, filtered Unusual Whales Full Tape data and a static review of official FMP documentation. It does not read RV30, QLIKE, model predictions or targets; it makes no provider HTTP request.

## FMP official documentation archive

Retrieved on: `2026-08-11`.

- [FMP 1 Min Interval Stock Chart API](https://site.financialmodelingprep.com/developer/docs/stable/intraday-1-min): The official page describes real-time or historical one-minute OHLCV data through the historical-chart/1min endpoint.
- [FMP official documentation index](https://site.financialmodelingprep.com/developer/docs): The official index lists the one-minute intraday chart endpoint and identifies open, high, low, close and volume for each minute.

The documentation confirms a one-minute OHLCV endpoint, but does **not** state the response timestamp timezone, whether it labels interval start or close, or the publication latency of a completed bar.

| Decision | Status | Consequence |
|---|---|---|
| FMP_BAR_LABEL_SEMANTICS | `UNVERIFIED` | Do not claim start or close labeling. |
| FMP_PROVIDER_CONFIRMED_LATENCY | `NOT_SUPPORTED` | Do not claim verified provider latency. |
| FMP_RESEARCH_AVAILABILITY_RULE | `SUPPORTED_CONSERVATIVE_ASSUMPTION` | Use `timestamp + 1 minute`; report `+2 minutes` as sensitivity. |
| FMP live probe | `PENDING_PROSPECTIVE_MEASUREMENT_NOT_BLOCKING` | Pending prospective measurement; not a current failure. |

`timestamp + 1 minute` is a conservative research rule, not a provider-confirmed publication timestamp.

## Unusual Whales historical Full Tape audit

Historical contract classification: `PROXY_ONLY`.

| Metric | Observed value |
|---|---:|
| Rows in scope | 819,602,983 |
| `executed_at` completeness | 100.0000% |
| `created_at` completeness | 100.0000% |
| Negative `created_at - executed_at` values | 0 |
| P1 latency seconds | 0.040132 |
| P5 latency seconds | 0.047493 |
| P50 latency seconds | 0.075686 |
| P90 latency seconds | 0.309733 |
| P95 latency seconds | 1.859337 |
| P99 latency seconds | 8.414490 |
| Maximum latency seconds | 23995.223140 |
| Within 60-second latency ceiling | 99.4532% |
| Within 120-second latency ceiling | 99.5303% |
| Within 300-second latency ceiling | 99.6199% |

Global, cohort and asset percentiles use a deterministic hash sample; each session uses its complete timestamp distribution. The associated CSV files retain the exact counts, field missingness, cutoff shares and the appropriate quantile method.

The audit demonstrates only the observed relationship between two provider fields. It does **not** demonstrate client receipt time, provider publication time, trader intent or informed trading. Therefore `created_at` remains an operational availability proxy, never a publication-time label.

## Cohort comparison

| Baseline | Comparison | |P50 difference| seconds | |P95 difference| seconds | |60s-share difference| |
|---|---|---:|---:|---:|
| independent_replication_30 | phase6 | 0.000310 | 0.288238 | 0.000177 |

Cohort comparisons describe stability of provider-field deltas only; they do not verify universal provider latency or client receipt time.

## Evidence files

- `artifacts/provider_timing/provider_timing_semantics_audit_v1.json`
- `artifacts/provider_timing/fmp_official_documentation_v1.json`
- `artifacts/provider_timing/uw_historical_latency_summary.csv`
- `artifacts/provider_timing/uw_historical_latency_by_session.csv`
- `artifacts/provider_timing/uw_historical_latency_by_asset.csv`
