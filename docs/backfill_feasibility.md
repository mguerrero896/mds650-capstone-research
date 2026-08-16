# Backfill feasibility after the bounded pilot

Backfill remains blocked by the authorization scope and by unresolved acceptance gates. The five-session pilot processed 7.586991365 GB of compressed Full Tape archives and retained 23,595,732 rows for the eight candidates. Daily Parquet artifacts are written per session, so the raw archive is never loaded into memory as a whole.

The first B2 implementation was stopped after its Python materialization reached approximately 40 GB resident memory. It was replaced with a lazy Polars/columnar aggregation and rerun successfully. This is an engineering gate, not evidence to extrapolate a production backfill.

| Horizon | Status | Feasibility basis |
|---|---|---|
| 3 months | Not authorized | Requires resumable checkpoints, storage budget, and accepted PIT/B1/B2 contracts. |
| 6 months | Not authorized | Same gates; estimate only after a representative multi-month byte/row probe. |
| 12 months | Not authorized | No extrapolation from five sessions is accepted for capacity or cost decisions. |

Before any horizon is authorized, add resumable per-day manifests, bounded memory telemetry, raw SHA-256, Parquet row counts, storage quota checks, and a stop-on-schema-drift policy. No asset freeze, model, QLIKE, or final test is permitted from this pilot.
