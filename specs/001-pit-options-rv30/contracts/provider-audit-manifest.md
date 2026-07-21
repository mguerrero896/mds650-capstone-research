# Provider audit manifest contract v1.1

## Status and provenance

This is the contract for a future accepted provider audit. The existing
`artifacts/api_audit/exploratory_v0/provider_audit_manifest.json` is preserved byte-for-byte
and remains exploratory evidence; it is not rewritten or promoted to this contract.

The manifest is machine-readable, sanitized and accompanied by a human report. Raw licensed
responses remain immutable in restricted storage and are referenced only by SHA-256 hashes.
No connector, backfill or network request is authorized by this document.

## Top-level schema

```yaml
schema_version: "1.1"
run_id: "uuid"
generated_at_utc: "2026-07-20T00:00:00Z"
research_feature: "001-pit-options-rv30"
research_only: true
secrets_present: true
secret_values_emitted: false
provider_results: []
cross_provider_summary: {}
acceptance: {}
```

`secrets_present` is presence-only. Secret values, authorization headers, personal paths and
credential-bearing URLs are forbidden. The JSON Schema is
`provider-audit-manifest.schema.json`.

## Required provider-result identity and diagnostics

Each result MUST contain `request_id`, `provider`, `component`, `asset` (or `null` when a
component is not asset-specific), `request_start`, `request_end` and
`endpoint_fingerprint`. The unique key is:

```text
(run_id, provider, component, asset, request_start, request_end, endpoint_fingerprint)
```

The manifest validator MUST fail when this key repeats, including when the repeated records
have different response hashes. `record_key` is the pipe-joined serialization of the seven
identity fields above; the validator recomputes it rather than trusting caller input. The
schema/test harness uses that canonical form. `raw_sha256` repetition under distinct requests is a separate
idempotency warning/error and is never silently deduplicated.

Required state fields use these enums:

- `applicability`: `applicable`, `not_applicable`, `unsupported`, `invalid_response`;
- `pit_status`: `verified`, `not_verified`, `not_applicable`, `unsupported`,
  `invalid_response`;
- `authentication_diagnostic`, `endpoint_diagnostic`, `schema_diagnostic` and
  `entitlement_diagnostic`: separate objects with status, evidence and blocker fields.

## Provider-specific acceptance requirements

### FMP Ultimate

Probe one-minute OHLCV and structured earnings for all eight candidates. Record endpoint
fingerprint, request ID/window, HTTP status, raw schema fields/types, timestamp raw type/unit,
timezone and start/close semantics, rows by asset and session date, earliest/latest complete
date, exchange-calendar completeness, duplicates, critical nulls, rate-limit observations,
adjusted/unadjusted and split behavior, and a bandwidth-safe extraction strategy.

Completeness MUST use an official market calendar that handles weekends, holidays, early
closes, DST and identifiable halts; it MUST NOT use calendar-days multiplied by 390.
When the provider omits an entire official session, record it as `missing_session_dates`;
do not mislabel every minute in that session as a missing bar. Any
`regular_session_expected_rows`, `regular_session_observed_rows` and `completeness_ratio`
computed under a local minute-start assumption MUST carry that assumption explicitly and
cannot resolve the provider's start-versus-close semantics.
Validate winter, summer, DST transition, regular session and early-close dates, and locate
the missing minute in AMZN and TSLA. For earnings, require
`returned_symbol == requested_symbol`. ETF records SPY/QQQ are `not_applicable` unless a
corporate applicability contract is proven; mismatches are `invalid_response`. The v1.1
record may carry `requested_symbol`, `returned_symbol_set` and
`returned_symbol_matches_requested` so this check is machine-auditable without retaining
the full earnings payload in the manifest.

### Unusual Whales

Probe several pages, cursor/time-limit pagination, a recent window, an old window, a
high-activity asset and a valid empty response. Record no repeated pages, minimum observed
historical date, event density by asset, schema stability and all event fields required by
the research brief. `page_ids` may be retained as non-secret pagination evidence. The alias
map is `ivStart -> iv_start` and `ivEnd -> iv_end`.

Report `event_iv_fields_present` separately from `ordinary_option_state_pit_verified`.
Alert-level `iv_start`/`iv_end` do not prove an independently retrievable PIT IV, skew or term
structure series and cannot by themselves unlock B1. A successful historical state endpoint with
only a trading date is still `ordinary_option_state_pit_verified: false` until publication/
availability timing is proven. The manifest may additionally record
`ordinary_option_state_fields_present` and the exact `ordinary_option_state_endpoint`; these
describe field coverage only and never upgrade PIT status by themselves. Document `created_at`,
`start_time` and
`end_time` independently: raw type, unit, semantic meaning, timezone, conversion, relation
to the forecast origin and possible post-availability. Do not mention `executed_at` unless
the raw response contains it. Execution-side proxies are associations, never certain intent;
volume above OI is not confirmed opening activity.

### Massive Options Advanced

Use only contract identifiers returned by the event source. Probe reference data, directed
trades, directed quotes, timestamp precision, bid/ask, condition codes, pagination and empty
or illiquid windows around events. Record the bounded `contract_id`, host, authentication,
contract-format and entitlement diagnostics separately. Do not download the historical OPRA
quote market. Massive contract identifiers MUST preserve the provider's canonical OPRA ticker
format, including the `O:` prefix (for example, `O:AAPL211119C00085000`); a source-specific
identifier without that prefix is not a valid request identifier for the directed probe.

## Acceptance defaults

```yaml
all_eight_assets_tested: true
minimum_underlying_minute_completeness: 0.95
maximum_duplicate_rate: 0.0
required_null_rate: 0.0
minimum_common_overlap_days: null
minimum_quality_assets_for_freeze: 4
maximum_quality_assets_for_freeze: 6
pit_timestamp_required_for_b1: true
license_status_required: true
```

The overlap threshold is frozen only after the verified common calendar is observed. Any
authentication, entitlement, schema, licensing, pagination, timestamp or idempotency failure
is an explicit blocker and prevents downstream backfill or B1 claims.
