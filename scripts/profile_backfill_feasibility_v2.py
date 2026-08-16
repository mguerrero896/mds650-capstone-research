"""Estimate storage from the five retained sessions without downloading anything."""
# ruff: noqa: E501,E702

from __future__ import annotations

import json
import statistics
import time
import zipfile
from pathlib import Path

RAW = Path("artifacts/raw/full_tape")
EVENT = Path("artifacts/pilot/option_events")
DATES = [f"2026-07-{d:02d}" for d in range(13, 18)]


def count_csv_rows(path: Path) -> tuple[int, float]:
    started = time.perf_counter()
    with zipfile.ZipFile(path) as archive, archive.open(archive.namelist()[0]) as source:
        count = 0
        for chunk in iter(lambda: source.read(8 * 1024 * 1024), b""):
            count += chunk.count(b"\n")
    return max(0, count - 1), time.perf_counter() - started


def main() -> None:
    rows: list[dict[str, object]] = []
    raw_sizes: list[int] = []
    parquet_sizes: list[int] = []
    for day in DATES:
        zip_path = RAW / day / f"full_tape_{day}.zip"
        parquet_path = EVENT / f"date={day}" / "events.parquet"
        total_rows, scan_seconds = count_csv_rows(zip_path)
        retained_rows = int(__import__("polars").scan_parquet(parquet_path).select(__import__("polars").len()).collect().item())
        raw_sizes.append(zip_path.stat().st_size)
        parquet_sizes.append(parquet_path.stat().st_size)
        rows.append({"date": day, "zip_bytes": zip_path.stat().st_size, "csv_rows_total": total_rows,
                     "retained_rows": retained_rows, "parquet_bytes": parquet_path.stat().st_size,
                     "decompress_and_count_seconds": round(scan_seconds, 3),
                     "download_seconds": None, "filter_seconds": None, "aggregation_seconds": None,
                     "peak_memory_bytes": None})
    sessions = {"3_months": 63, "6_months": 126, "12_months": 252}
    estimates: dict[str, dict[str, int | str]] = {}
    for horizon, n in sessions.items():
        estimates[horizon] = {"sessions": n, "raw_mean_bytes": round(statistics.mean(raw_sizes) * n),
                              "raw_p95_bytes": round(max(raw_sizes) * n), "parquet_mean_bytes": round(statistics.mean(parquet_sizes) * n),
                              "parquet_p95_bytes": round(max(parquet_sizes) * n), "duration_basis": "not_authorized; no production extrapolation"}
    output = {"status": "PRELIMINARY_ONLY_BACKFILL_BLOCKED", "sessions_observed": rows,
              "daily_mean_zip_bytes": statistics.mean(raw_sizes), "daily_p95_zip_bytes": max(raw_sizes),
              "daily_mean_parquet_bytes": statistics.mean(parquet_sizes), "daily_p95_parquet_bytes": max(parquet_sizes),
              "estimates": estimates, "memory_note": "V1 Python materialization reached ~40 GB; V2 peak was not instrumented; backfill remains blocked.",
              "free_space_bytes": None, "uncertainty": "five-session sample; P95 uses sample maximum, not a population quantile.", "secret_values_emitted": False}
    Path("artifacts/pilot_v2/backfill_feasibility_v2.json").write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(json.dumps({"days": len(rows), "raw_mean_gb": statistics.mean(raw_sizes) / 1e9, "raw_p95_gb": max(raw_sizes) / 1e9}))


if __name__ == "__main__":
    main()
