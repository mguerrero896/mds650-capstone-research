# UW Full Tape Anomaly Evidence Addendum v2.1

## Purpose and scope

This addendum records a target-blind forensic check of how four preselected Unusual Whales Full Tape sessions are represented in the existing canonical B2 matrices. It is limited to `executed_at` and `created_at` timestamp fields in acquired Full Tape partitions, plus canonical B2 feature/provenance fields. It does not read RV30, QLIKE, predictions, models, outcomes, OOS artifacts, or market-value/trade-identifier columns; it makes no provider HTTP request.

The reproducible evidence is [uw_anomaly_evidence_v21.json](../artifacts/provider_timing_v21/uw_anomaly_evidence_v21.json), validated against [uw_anomaly_evidence_v21.schema.json](../schemas/uw_anomaly_evidence_v21.schema.json). Its self-hash is `83d0813dc6f9c809ca5c5eb247f737b13c7e4d8eefe3ac1fb5831fcd3889dc14`.

## Encoding contract

Each sanitised record has the grain `session_date × raw asset × canonical B2 variant`. It never serialises an origin identifier, trade identifier, quote, price, or an absolute filesystem path.

| Field | Meaning | Allowed interpretation |
|---|---|---|
| `canonical_value_coding = ZERO` | All B2 feature values in the affected canonical origin rows are numeric zero. | A coding fact only; it is not automatically no option activity. |
| `canonical_value_coding = MISSING` | At least one B2 feature value is null, or the matrix file is unavailable. | Missingness; never fill with zero. |
| `canonical_value_coding = EXCLUDED` | The Full Tape asset has no row in that canonical B2 variant/date file. | Observed exclusion from that matrix; no causal reason is asserted. |
| `availability_indicator_status = INDICATOR_ABSENT` | No recognised source-availability field is present in the B2 schema. | `b2v2_max_created_at_utc` is provenance of eligible activity, not an availability indicator. |
| `zero_interpretation = CONFOUNDED_BY_DELAY` | Numeric zeros coincide with a session-wide observed delay in Full Tape `created_at`. | Do not call the zeros no activity; flag or exclude them before a future B2 panel is assembled. |
| `zero_interpretation = SOURCE_UNAVAILABLE` | The raw partition is absent, empty, or invalid while a B2 value exists. | Fail closed; a zero cannot substitute for unavailable source evidence. |

`created_at` remains an operational availability proxy. The Full Tape REST/OpenAPI sources do not document its semantic identity merely because a Kafka message type uses the same field name. This addendum therefore reports an observed timestamp delay, not a provider-internal cause, publication time, receipt time, trader intention, or a conclusion about informed trading.

## Observed evidence

The forensic scope contains four dates (`2025-08-21`, `2025-09-18`, `2025-10-20`, `2026-01-29`), eight acquired Full Tape assets, five canonical B2 variants, 32 source incident records and 160 canonical-sidecar records. All 160 canonical records report `INDICATOR_ABSENT`; 120 have present canonical rows and 40 are observed exclusions of the two raw-only assets (`QQQ`, `SPY`) across the five variants.

The source temporal states are:

- `SESSION_WIDE_CREATED_AT_DELAY_OBSERVED`: 8 records, all eight acquired assets on `2025-10-20`.
- `LONG_CREATED_AT_DELAY_TAIL_OBSERVED`: 11 records across the other named dates.
- `SOURCE_AVAILABLE_NO_DELAY_TAIL_OBSERVED`: 13 records.

| Session | Observed source timing state by asset | Canonical B2 coding across five variants | Interpretation boundary |
|---|---|---|---|
| 2025-08-21 | Long `created_at` delay tail: all eight acquired assets. | 31 numeric-zero origins, 0 numeric-missing origins; 10 raw-only exclusions; remaining present records are mixed or nonzero. | The tail is observed; no provider-internal cause is identified. |
| 2025-09-18 | Long delay tail: NVDA only; the other seven source partitions have no >300-second tail. | 54 numeric-zero origins, 0 numeric-missing origins; 10 raw-only exclusions. | Numeric zero remains a coding fact, not a confirmation of no activity. |
| 2025-10-20 | Session-wide observed `created_at` delay: all eight acquired assets. | 2,160 numeric-zero origins: six canonical assets × 72 origins × five variants; 0 numeric-missing origins; 10 raw-only exclusions. | Zeros are `CONFOUNDED_BY_DELAY`; the availability gate fails. |
| 2026-01-29 | Long delay tail: META and MSFT; the other six source partitions have no >300-second tail. | 6 numeric-zero origins, 0 numeric-missing origins; 10 raw-only exclusions. | Preserve the tail indicator; do not infer a provider cause. |

On `2025-10-20`, the raw partitions are nonempty for all eight assets, but the observed `created_at` delays have medians between 16,811.440 and 19,633.134 seconds and P95 values between 22,380.171 and 23,541.098 seconds. In every canonical variant, each of the six canonical B2 assets has 72 numeric-zero origin rows, no numeric B2 nulls, and `zero_interpretation = CONFOUNDED_BY_DELAY`. The source is therefore present, but its timing condition makes the canonical zero encoding unsuitable as evidence of no activity.

The resulting `activity_availability_gate` is `FAIL` with the exact reason `ZERO_CONFOUNDED_BY_OBSERVED_CREATED_AT_DELAY`. This is a data-integrity gate, not a predictive result.

## Required downstream handling

Any future target-blind B2 matrix construction must join this sidecar before treating canonical feature rows as usable. A row with `CONFOUNDED_BY_DELAY`, `SOURCE_UNAVAILABLE`, `MISSING`, or `EXCLUDED` must remain explicitly flagged or excluded by a predeclared rule; it must not be silently converted to zero. A later implementation may expand the audit to other dates, but it cannot claim the existing canonical B2 zero semantics are closed while this incident remains unhandled.

## Reproduction

From the repository root, run:

```powershell
uv run python scripts/audit_uw_anomaly_evidence_v21.py
uv run pytest tests/unit/test_uw_anomaly_evidence_v21.py -q
uv run ruff check src/mds650/uw_anomaly_evidence_v21.py scripts/audit_uw_anomaly_evidence_v21.py tests/unit/test_uw_anomaly_evidence_v21.py
uv run mypy src/mds650/uw_anomaly_evidence_v21.py scripts/audit_uw_anomaly_evidence_v21.py
```

The CLI accepts local paths and explicit date/asset scope for fixture or forensic reruns, but it accepts no credentials and performs no network request.
