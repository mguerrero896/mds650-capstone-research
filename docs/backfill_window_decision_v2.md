# Backfill window decision v2

No historical backfill was executed. The projection is based on 20 already
downloaded sessions and is preliminary. Evidence:
`artifacts/backfill/backfill_resource_projection_v2.json`.

## Resource projection

Latest telemetry snapshot in the artifact is environment-dependent because it
records the current disk state. The latest local run observed 423,272,148,992
bytes free; the value must be refreshed immediately before any future execution.
Observed raw Full Tape mean was 1,550,098,885 bytes/session and P95 was
1,740,968,640 bytes/session. ZIP member-size P95 (4,957,118,735 bytes/session)
is streamed and is not retained in the resident total. Filtered Parquet
mean/P95 were 253,016,069 / 298,356,335 bytes/session and Massive cache
mean/P95 were 132,673,396 / 170,673,206 bytes/session. P95 decompression was
317 seconds; observed download P95 was 171 seconds; aggregation was 4.51
seconds/session.

| Window | Raw P95 | Parquet P95 | Required with 30% reserve | Fits current snapshot? | Expected origins |
|---:|---:|---:|---:|---|---:|
| 60 sessions | 104.46 GB | 17.90 GB | 173.87 GB | Yes | 34,080 |
| 120 sessions | 208.92 GB | 35.80 GB | 346.25 GB | Yes | 68,160 |
| 180 sessions | 313.37 GB | 53.70 GB | 518.63 GB | No | 102,240 |

## Recommendation

`60_SESSIONS` is the single recommended window because it fits the measured
disk budget with the required reserve, is the shortest option that provides a
meaningful temporal design, and limits provider/licence and schedule risk. This
is a recommendation, not authorization. The 120-session scenario remains a
fallback only after storage and license review; 180 sessions is not feasible on
the current disk snapshot. Uncompressed ZIP members are streamed and excluded
from resident storage; retaining them would require a separate budget.

The license field in the artifact remains `provider license confirmation
required before retaining commercial raw`. No ZIP is downloaded by Phase 4A.

Status: **PARTIAL**. Engineering resource feasibility is demonstrated, but
provider entitlement/license and the scientific common-history gates remain open.
