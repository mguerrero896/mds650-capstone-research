# Archived scripts

Dead one-off repair/backfill scripts kept for audit trail only (roadmap 2.5; housekeeping
2026-08-18). They target states of the store that no longer exist and must not be re-run.

- `fix_fmp_missing_window.py` — one-off FMP window repair, executed during Phase 5; the
  repaired windows are baked into the frozen panels.
- `run_phase5_b1q_missing_55.py` — one-off backfill of 55 missing B1Q sessions; artifacts
  live under `D:\MDS650\data\b1q\phase5_missing_55`.
- `materialize_backfill_from_raw.py` — superseded backfill materializer; the current
  acquisition path writes derived stores directly.
