# Backfill feasibility v3

Status: `DESCRIPTIVE_ONLY_FULL_BACKFILL_BLOCKED`

This report uses the measured twenty-session Full Tape telemetry. It does not authorize
a 3/6/12-month download, model run, QLIKE or a final test. ZIP inflate and CSV filtering
are measured as one streaming stage; calibration aggregation is reported separately by the
B2/B1 runners when those stages complete.

Observed sessions: 20; raw bytes total: 31001977709; Parquet bytes total: 5060321380.
Observed daily raw mean: 1550098885; empirical P95: 1744720132.
Observed daily Parquet mean: 253016069; empirical P95: 299134072.
Observed daily stream-filter mean seconds: 337.12; P95: 397.51.
Transfer time was observed for 17/20 sessions; reused raw checkpoints have no transfer timer and are excluded from that transfer statistic.
Observed process working-set maximum: 571527168 bytes across 20/20 sessions.
Free space at finalization: 475959099392 bytes; required margin is 30% over raw+Parquet P95.

## Descriptive projections

| Horizon | Sessions | Raw mean | Raw P95 | Parquet mean | Parquet P95 | P95 storage +30% | Duration P95 (s) |
|---|---:|---:|---:|---:|---:|---:|---:|
| 3_months | 62 | 96106130898 | 108172648172 | 15686996278 | 18546312445 | 164734648802 | 24646 |
| 6_months | 124 | 192212261796 | 216345296343 | 31373992556 | 37092624891 | 329469297604 | 49292 |
| 12_months | 252 | 390624919133 | 439669473214 | 63760049388 | 75381786068 | 669566637067 | 100174 |

The empirical P95 is interpolated from the twenty observed daily values, not treated as
a guarantee. Temporary SQLite dedup and provider variability can increase the working
set and duration. Projection duration is a lower bound where a reused raw checkpoint
did not retain its original transfer timer.
A future backfill requires a new authorization, a measured restart test
and a storage check against the P95 plus margin; this phase leaves `FULL_BACKFILL=BLOCKED`.

```json
{
  "free_bytes_at_finalize": 475959099392,
  "projections": {
    "12_months": {
      "duration_seconds_mean": 84953.14256646021,
      "duration_seconds_p95": 100173.76684307939,
      "parquet_bytes_mean": 63760049388.0,
      "parquet_bytes_p95": 75381786068.4,
      "raw_bytes_mean": 390624919133.4,
      "raw_bytes_p95": 439669473213.6,
      "sessions_approx": 252,
      "storage_p95_with_30_percent_margin": 669566637066.6
    },
    "3_months": {
      "duration_seconds_mean": 20901.169996510052,
      "duration_seconds_p95": 24645.92676297985,
      "parquet_bytes_mean": 15686996278.0,
      "parquet_bytes_p95": 18546312445.399998,
      "raw_bytes_mean": 96106130897.90001,
      "raw_bytes_p95": 108172648171.59999,
      "sessions_approx": 62,
      "storage_p95_with_30_percent_margin": 164734648802.1
    },
    "6_months": {
      "duration_seconds_mean": 41802.339993020105,
      "duration_seconds_p95": 49291.8535259597,
      "parquet_bytes_mean": 31373992556.0,
      "parquet_bytes_p95": 37092624890.799995,
      "raw_bytes_mean": 192212261795.80002,
      "raw_bytes_p95": 216345296343.19998,
      "sessions_approx": 124,
      "storage_p95_with_30_percent_margin": 329469297604.2
    }
  }
}
```
