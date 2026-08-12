# Data Model: Point-in-Time Options Activity for RV30 Forecasting

All timestamps are stored as UTC plus `America/New_York` rendering. Every entity includes a
source response identifier and an availability/provenance field when applicable. Raw values
are immutable; normalized values are versioned by transformation contract.

## ProviderAuditRun

| Field | Type | Rule |
|---|---|---|
| `run_id` | string | Unique per bounded audit run |
| `provider` | enum | `fmp`, `unusual_whales`, `massive` |
| `requested_at_utc` | timestamp | Time of request, never a market timestamp |
| `endpoint_label` | string | Sanitized endpoint identifier; no credential query strings |
| `http_status` | integer/null | Required when a response is received |
| `schema_fingerprint` | string/null | Hash of normalized field names/types |
| `pagination_status` | enum | `complete`, `partial`, `not_applicable`, `failed` |
| `rate_limit_observation` | object | Sanitized headers/behavior, no tokens |
| `license_status` | enum | `verified`, `pending`, `blocked` |
| `gate_status` | enum | `pass`, `fail`, `blocked` |
| `blocker` | string/null | Exact fail-closed blocker string |
| `request_id` | string | Provider request identifier or locally generated UUID |
| `request_start`, `request_end` | timestamp | UTC request window; required for uniqueness |
| `endpoint_fingerprint` | string | Hash of sanitized method/host/path/query shape |
| `applicability` | enum | `applicable`, `not_applicable`, `unsupported`, `invalid_response` |
| `pit_status` | enum | `verified`, `not_verified`, `not_applicable`, `unsupported`, `invalid_response` |
| `authentication_diagnostic` | object | Presence/auth status only; no credential material |
| `endpoint_diagnostic` | object | HTTP/route/parameter observations |
| `schema_diagnostic` | object | Raw fields, canonical aliases and fingerprint |
| `entitlement_diagnostic` | object | Plan/license/feature access state |

The manifest-level uniqueness key is `(run_id, provider, component, asset,
request_start, request_end, endpoint_fingerprint)`. Duplicate keys are a validation
failure, even if hashes or request identifiers differ.

## SourceResponse

| Field | Type | Rule |
|---|---|---|
| `source_response_id` | string | Stable local identifier |
| `raw_sha256` | string | Hash of immutable raw payload |
| `retrieved_at_utc` | timestamp | Retrieval time |
| `provider` | string | Provider name |
| `endpoint_label` | string | Sanitized endpoint label |
| `license_reference` | string/null | Contract/plan reference without secret |
| `payload_uri` | path/URI | Restricted persistent storage reference; personal absolute paths are forbidden in distributable manifests |
| `redaction_status` | enum | `raw_restricted`, `sanitized` |

## UnderlyingBar

| Field | Type | Rule |
|---|---|---|
| `asset` | string | One of the eight candidates |
| `bar_start_utc` | timestamp | Canonical minute start |
| `bar_close_utc` | timestamp/null | Resolved only after FMP start/close semantics are proven |
| `bar_start_ny` | timestamp | Rendering in `America/New_York` |
| `session_date_ny` | date | Exchange session date |
| `open`, `high`, `low`, `close` | decimal | Positive finite prices; `low <= high` |
| `volume` | decimal | Non-negative; null handling explicit |
| `source_response_id` | string | Trace to raw response |
| `quality_flags` | set | Regular-session, duplicate, null and calendar flags |

Deduplication key: `(asset, bar_start_utc)`.

## CorporateEvent

| Field | Type | Rule |
|---|---|---|
| `asset` | string | Candidate asset |
| `event_type` | enum | Earnings or other structured corporate event |
| `event_time_utc` | timestamp/null | Event time if provided |
| `available_at_utc` | timestamp/null | When the value was observable |
| `event_date_ny` | date/null | Date-only fallback, explicitly lower precision |
| `source_response_id` | string | Trace to source |
| `timestamp_quality` | enum | `point_in_time`, `date_only`, `unresolved` |

Deduplication key: `(asset, event_type, event_time_utc, event_date_ny, source_response_id)`.

## UnusualOptionEvent

| Field | Type | Rule |
|---|---|---|
| `event_id` | string | Provider event identifier where available |
| `asset` | string | Underlying candidate |
| `contract_id` | string | Provider contract identifier |
| `event_time_utc` | timestamp | Required; cannot be naive |
| `available_at_utc` | timestamp/null | Required for PIT feature eligibility |
| `premium`, `trade_price`, `size`, `volume`, `open_interest` | decimal/null | Non-negative where present |
| `volume_oi_ratio` | decimal/null | Derived only from same-origin OI semantics |
| `option_type` | enum | `call`, `put`, `unknown` |
| `strike`, `expiry` | decimal/date | Required when contract resolves |
| `moneyness`, `dte` | decimal/integer | Derived from origin-available underlying/expiry |
| `sweep`, `floor`, `multileg` | boolean/null | Source flags, not intent labels |
| `execution_proxy` | enum/null | Bid/ask proximity or source proxy only |
| `iv_change`, `iv`, `skew` | decimal/null | Optional, only when PIT validated |
| `source_response_id` | string | Trace to raw response |

Deduplication key: `(provider, event_id)` when stable; otherwise documented composite of
`(contract_id, event_time_utc, trade_price, size, source_response_id)`.

## OptionStateSnapshot

| Field | Type | Rule |
|---|---|---|
| `asset` | string | Candidate/frozen asset |
| `contract_or_surface_key` | string | Contract or surface coordinate |
| `observed_at_utc` | timestamp | Market observation timestamp |
| `available_at_utc` | timestamp | Must be no later than forecast origin |
| `iv`, `skew`, `term_structure_value` | decimal/null | Source values; no future interpolation |
| `interpolation_method` | enum/null | Must be recorded if interpolated |
| `coverage_flag` | enum | `observed`, `valid_interpolation`, `missing`, `blocked` |
| `source_response_id` | string | Trace to source |

## OptionTrade

| Field | Type | Rule |
|---|---|---|
| `contract_id` | string | Resolved from event source |
| `trade_time_utc` | timestamp | Preserves provider precision |
| `price`, `size` | decimal | Non-negative finite values |
| `condition_codes` | list[string] | Preserved without semantic invention |
| `source_response_id` | string | Trace to raw response |

Deduplication key: `(contract_id, trade_time_utc, price, size, condition_codes)` plus provider
sequence if supplied.

## OptionQuote

| Field | Type | Rule |
|---|---|---|
| `contract_id` | string | Same resolved contract as the directed event |
| `quote_time_utc` | timestamp | Preserves provider precision |
| `bid`, `ask` | decimal/null | Null means no quote; zero is not an absence proxy |
| `condition_codes` | list[string] | Preserved |
| `consolidation_scope` | string/null | Provider-reported scope |
| `source_response_id` | string | Trace to raw response |

## ForecastOrigin

| Field | Type | Rule |
|---|---|---|
| `origin_id` | string | Stable hash of asset and origin timestamp |
| `asset` | string | Candidate or frozen asset |
| `origin_start_utc` | timestamp | End of five-minute origin interval; exact origin close is `C(i,t)` |
| `origin_start_ny` | timestamp | NY rendering |
| `predictor_cutoff_utc` | timestamp | Latest admissible `available_at` |
| `option_activity_present` | boolean | At least one eligible trade; never an unusualness label |
| `source_trace_ids` | list[string] | All source response references |

Deduplication key: `(asset, origin_start_utc)`.

## RealizedVarianceTarget

| Field | Type | Rule |
|---|---|---|
| `origin_id` | string | Foreign key to ForecastOrigin |
| `horizon_minutes` | integer | Must equal 30 for primary target |
| `origin_close_count` | integer | Must equal 1 on valid rows |
| `future_close_count` | integer | Must equal 30 on valid rows |
| `rv_30m` | decimal | `Σ[j=1..30] (ln(C(i,t+j)/C(i,t+j-1)))²` |
| `log_rv_30m` | decimal | `log(rv_30m + epsilon)` with versioned epsilon |
| `origin_close_utc` | timestamp | Fully observed close used as `C(i,t)` |
| `future_close_start_utc`, `future_close_end_utc` | timestamp | `C(i,t+1)` through `C(i,t+30)` |
| `target_formula_version` | string | Reproducible formula identifier |
| `validity` | enum | `valid`, `missing_origin_close`, `missing_future_bars`, `invalid_price`, `outside_session`, `early_close`, `halt_unresolved`, `bar_semantics_unresolved` |

The contractual target sentence is: “The target MUST use the fully observed close at
forecast origin t and the next thirty consecutive one-minute closes, producing exactly
thirty one-minute log returns.” A row is invalid when any of the 31 prices is missing or
ambiguous. No interpolation, forward-fill or calendar-days-times-390 shortcut is allowed.

## BenchmarkRun

| Field | Type | Rule |
|---|---|---|
| `benchmark_id` | string | Frozen configuration identifier |
| `benchmark_level` | enum | `B0`, `B1a`, `B2`; `B1b`/`B1c` robustness only |
| `eligible_origin_hash` | string | Same origins across nested benchmarks |
| `split_definition` | object | Expanding chronological splits |
| `purge_minutes`, `embargo_minutes` | integer | Both at least 30 for primary target |
| `model_name`, `model_version` | string | Exact model specification |
| `primary_loss` | enum | `QLIKE` |
| `secondary_metrics` | list[string] | MAE and RMSE |
| `uncertainty_method` | string | Paired whole-day cluster bootstrap |
| `multiplicity_method` | enum | `holm_two_confirmatory_comparisons` |
| `model_role` | enum | `gamma_glm_confirmatory`, `lightgbm_robustness` |
| `effect_size_threshold` | decimal | Frozen before final test |
| `asset_regime_coverage` | object | Coverage and consistency results |
| `decision_status` | enum | `incremental`, `null`, `inconclusive`, `blocked` |

## ExecutionManifest

The manifest links the audit, pilot, benchmark, tests, configuration, package versions, raw
hashes, source folder status, secret-presence gate, licensing status and exact blocker strings.
It MUST be safe to share without provider tokens or raw licensed payloads.

## StudySessionManifest

| Field | Type | Rule |
|---|---|---|
| `calendar` | enum | `XNYS` |
| `development_sessions` | list[date] | Exactly 80 dates, 2026-03-24 through 2026-07-17 |
| `holdout_sessions` | list[date] | Exactly 10 dates, 2026-07-20 through 2026-07-31 |
| `reused_sessions` | list[date] | Exactly 25 hash-verified retained dates |
| `acquisition_sessions` | list[date] | Exactly 55 development dates absent from retained evidence |
| `disjoint` | boolean | Must be true |
| `manifest_sha256` | string | Lowercase 64-character SHA-256 |

Development and holdout arrays are ordered, unique and disjoint. A holdout date is never a
valid development acquisition input.

## PreregistrationManifest

| Field | Type | Rule |
|---|---|---|
| `status` | enum | `FROZEN_BEFORE_MODEL_OR_QLIKE`, then `METHOD_FROZEN` |
| `session_manifest_sha256` | string | Must match StudySessionManifest |
| `b2_feature_names` | list[string] | Exactly the nine names in FR-072 |
| `estimands` | object | Exact `Delta_B1` and `Delta_B2` definitions |
| `outer_folds` | list[object] | Exactly four ordered expanding folds |
| `models` | object | Frozen Gamma GLM and LightGBM roles/grids |
| `seed` | integer | 650 |
| `bootstrap_repetitions` | integer | 10,000 |
| `multiplicity` | enum | `holm_two_confirmatory_comparisons` |
| `holdout_reads` | integer | Zero before release |
| `preregistration_sha256` | string | Computed over canonical content excluding this field |

## CompactB2FeatureRow

| Field | Type | Rule |
|---|---|---|
| `origin_id` | string | Foreign key to ForecastOrigin |
| `window_start_utc`, `window_end_utc` | timestamp | Five-minute half-open window ending at origin minus delay |
| `delay_seconds` | enum | 60 primary; 120 and 300 sensitivity |
| `eligible_trade_count` | integer | Reconstructed locally |
| `b2_log_trade_count` | float | `log1p(eligible_trade_count)` |
| `b2_unique_contract_share` | float | Unique contracts divided by eligible trades |
| `b2_log_mean_trade_premium` | float | `log1p(total premium / eligible trades)` |
| `b2_log_max_trade_premium` | float | `log1p(maximum eligible premium)` |
| `b2_call_put_premium_imbalance_scaled` | float | Signed call/put premium ratio |
| `b2_execution_side_premium_imbalance` | float | Ask-side share minus bid-side share |
| `b2_repeated_contract_premium_share` | float | Repeated-contract premium divided by total premium |
| `b2_strike_concentration` | float | Maximum one-strike trade share |
| `b2_expiry_concentration` | float | Maximum one-expiry trade share |
| `source_hashes` | list[string] | Full Tape evidence hashes |

A zero denominator yields documented zero only when it represents no eligible activity; it
never masks missing provider data. RV30, loss and forecast fields are prohibited inputs.

## HoldoutAccessLedger

| Field | Type | Rule |
|---|---|---|
| `status` | enum | `SEALED_NOT_ACQUIRED`, `ACQUIRED_NOT_READ`, `READ_ONCE` |
| `holdout_sessions` | list[date] | Must match StudySessionManifest |
| `method_freeze_sha256` | string | Must match the frozen development method |
| `last_session_complete` | boolean | Must be true before read |
| `holdout_reads` | integer | Transition `0 -> 1` only |
| `authorized_at_utc` | timestamp/null | Recorded on the sole read |

Any early, mismatched or second analytical read fails closed.

## CorrectedDevelopmentRelease

| Field | Type | Rule |
|---|---|---|
| `release_id` | string | Deterministic identifier from source hashes and frozen method identity |
| `status` | enum | `TARGET_BLIND_READY`, `TARGET_BOUND_READY`, `EVALUATED_DEVELOPMENT_ONLY`, `BLOCKED` |
| `development_sessions` | list[date] | Exactly the 80 dates in `StudySessionManifest`; no holdout date permitted |
| `predictor_manifest_sha256` | string | Must bind the immutable target-blind v2.4 predictor manifest |
| `availability_sidecar_sha256` | string | Must bind the v2.2 B2 availability sidecar |
| `pit_gate_sha256` | string | Must bind the PIT v2.1 reconciliation gate without changing its legacy status |
| `massive_reselection_sha256` | string | Must bind the v2.1 as-of reselection evidence |
| `development_source_manifest_sha256` | string | Must bind the exact 80-session source manifest |
| `target_binding_sha256` | string/null | Populated only after the predictor-only release passes |
| `corrected_common_origin_count` | integer | Count of passing common rows after B2 exclusions |
| `b2_excluded_origin_count` | integer | Exclusions with all nine B2 fields null and an explicit reason |
| `safe_to_evaluate_corrected_development` | enum | `YES` only for the fixed development sample after all source and leakage gates pass |
| `safe_to_reconcile_existing_results` | enum | Always `NO` for legacy sealed results |
| `safe_to_open_or_evaluate_oos` | enum | Always `NO` in this release |
| `release_sha256` | string | Canonical content hash excluding this field |

`CorrectedDevelopmentRelease` is a new evidence object, not an update of a legacy result.
It rejects target-like input during predictor construction. Target binding and development
evaluation are successive, separately manifested states; neither can include a holdout date.
