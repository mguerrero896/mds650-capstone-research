# Pilot V2: preliminary backfill feasibility

This estimate uses the five existing Full Tape sessions (13–17 July 2026).
The ZIPs were reused; no duplicate download was performed. Values are
preliminary capacity estimates, not authorization for a historical backfill.

## Observed daily evidence

| Session | ZIP bytes | CSV rows | Rows retained | Parquet bytes | Decompression/count (s) |
|---|---:|---:|---:|---:|---:|
| 2026-07-13 | 1,446,379,218 | 10,867,794 | 4,680,362 | 253,212,165 | 17.082 |
| 2026-07-14 | 1,308,114,924 | 9,783,959 | 3,879,799 | 210,528,621 | 16.262 |
| 2026-07-15 | 1,553,487,942 | 11,720,014 | 5,142,043 | 277,871,439 | 20.757 |
| 2026-07-16 | 1,538,329,354 | 11,559,720 | 4,692,011 | 254,131,231 | 21.155 |
| 2026-07-17 | 1,740,679,927 | 12,993,186 | 5,201,517 | 284,325,138 | 20.399 |

Mean daily ZIP size is 1,517,398,273 bytes and mean daily Parquet size is
256,013,718.8 bytes. The observed maximum is used as a conservative P95 proxy
because only five sessions are available. Download, aggregation and peak
memory were not instrumented in V1; they remain uncertainty rather than
invented measurements.

## Extrapolation (approximately 21/63/126/252 sessions)

| Horizon | Sessions | Raw mean | Raw conservative | Parquet mean | Parquet conservative |
|---|---:|---:|---:|---:|---:|
| 3 months | 63 | 95.6 GB | 109.7 GB | 16.1 GB | 17.9 GB |
| 6 months | 126 | 191.2 GB | 219.3 GB | 32.3 GB | 35.8 GB |
| 12 months | 252 | 382.4 GB | 438.7 GB | 64.5 GB | 71.6 GB |

The conservative column multiplies the maximum observed daily footprint by the
session count. It does not model seasonality, provider changes, compression
drift, retries, or temporary working space. The prior V1 materialization reached
approximately 40 GB, while Pilot V2 peak memory was not instrumented.

## Decision

`BACKFILL = BLOCKED`. These figures support capacity planning only. A 20-session
extension may be proposed after Pilot V2 acceptance, usable B1a-or-better PIT
coverage, resumability, bounded memory, and verified free space. No full
backfill is authorized by this document.
