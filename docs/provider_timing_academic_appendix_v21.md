# Academic Appendix — Provider Timing PIT v2.1

## Session-asset timing incidents

| Session | Assets | Observed source state | Min lag (s) | Max lag (s) |
| --- | --- | --- | --- | --- |
| 2025-08-21 | 8 | RECORD_CREATION_DELAY_OBSERVED:8 | 0.031 | 758.275 |
| 2025-09-18 | 8 | RECORD_CREATION_DELAY_OBSERVED:1, SOURCE_AVAILABLE:7 | 0.031 | 3152.822 |
| 2025-10-20 | 8 | RECORD_CREATION_DELAY_OBSERVED:8 | 981.484 | 23995.223 |
| 2026-01-29 | 8 | RECORD_CREATION_DELAY_OBSERVED:2, SOURCE_AVAILABLE:6 | 0.030 | 468.831 |

`2025-10-20` is an observed Full Tape record-creation delay, not a documented
provider outage and not evidence of no option activity. Existing data do not
identify an upstream queue, export mechanism, or other provider-internal cause.

## Canonical B2 coding audit

The traceability sidecar has one row per canonical variant/session/asset. It
distinguishes numeric zero, numeric missingness, row absence, source state, and
the absence of an independent availability indicator. It makes no predictive or
economic inference.
