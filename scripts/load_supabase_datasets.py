"""Load the gated research datasets into the private Supabase Postgres tables.

Streams each frozen parquet into its table via PostgREST CSV inserts (service-role
key). Idempotent by count: a table whose server row count already equals the parquet
row count is skipped; a partial load is wiped and reloaded. The repo parquets remain
the source of truth — these tables are a queryable private view, never an editing
surface (RLS enabled, no policies: service-role only).

Run:  $env:SUPABASE_SERVICE_KEY set, then  uv run python scripts/load_supabase_datasets.py
"""

from __future__ import annotations

import io
import os
from pathlib import Path

import httpx
import polars as pl
import polars.selectors as cs

REPO = Path(__file__).resolve().parents[1]
PROJECT_REF = "eqpyjikcewqaegnbaemf"
REST = f"https://{PROJECT_REF}.supabase.co/rest/v1"
BATCH_CELLS = 200_000  # rows per batch scaled by column count; wide tables get smaller batches

DATASETS: dict[str, str] = {
    "dev_training_all_origins": "artifacts/phase5/development_all_origins_80d.parquet",
    "dev_training_common": "artifacts/phase5/common_development_80d.parquet",
    "c1_development_forecasts": "artifacts/phase5/development_forecasts.parquet",
    "c5_frozen_evaluation_forecasts": (
        "artifacts/b2_confirmation/frozen_evaluation_forecasts.parquet"
    ),
    "b1v3_features": "artifacts/b1v3_target_blind/b1v3_features.parquet",
    "b2_mechanism_forecasts": "artifacts/methodology/b2_mechanism_forecasts.parquet",
}


def _server_count(client: httpx.Client, table: str) -> int:
    response = client.head(
        f"{REST}/{table}",
        params={"select": "*"},
        headers={"Prefer": "count=exact", "Range-Unit": "items", "Range": "0-0"},
    )
    content_range = response.headers.get("content-range", "/0")
    return int(content_range.rsplit("/", 1)[-1])


def main() -> None:
    key = os.environ.get("SUPABASE_SERVICE_KEY")
    if not key:
        raise SystemExit("SUPABASE_SERVICE_KEY missing (User env var; see DATA_ACCESS.md).")
    headers = {"Authorization": f"Bearer {key}", "apikey": key}
    with httpx.Client(timeout=300, headers=headers) as client:
        for table, rel_path in DATASETS.items():
            frame = pl.read_parquet(REPO / rel_path)
            existing = _server_count(client, table)
            if existing == frame.height:
                print(f"[load] {table}: already complete ({existing:,} rows), skipped")
                continue
            if existing:
                print(f"[load] {table}: partial ({existing:,}/{frame.height:,}), wiping")
                wipe = client.delete(f"{REST}/{table}", params={"origin_id": "neq."})
                if wipe.status_code not in (200, 204):
                    raise SystemExit(f"WIPE_FAILED {table}: {wipe.status_code} {wipe.text[:200]}")
            sent = 0
            batch_rows = max(2_000, BATCH_CELLS // frame.width)
            for offset in range(0, frame.height, batch_rows):
                chunk = frame.slice(offset, batch_rows).with_columns(
                    cs.float().fill_nan(None)
                )
                buffer = io.BytesIO()
                chunk.write_json(buffer)
                payload = buffer.getvalue()
                for attempt in range(4):
                    try:
                        response = client.post(
                            f"{REST}/{table}",
                            content=payload,
                            headers={"Content-Type": "application/json"},
                        )
                    except httpx.HTTPError:
                        response = None
                    if response is not None and response.status_code in (200, 201):
                        break
                    if attempt == 3:
                        detail = (
                            f"{response.status_code} {response.text[:300]}"
                            if response is not None
                            else "transport error"
                        )
                        raise SystemExit(f"LOAD_FAILED {table} offset {offset}: {detail}")
                sent += chunk.height
                if sent % 100_000 < batch_rows:
                    print(f"[load] {table}: {sent:,}/{frame.height:,}", flush=True)
            final = _server_count(client, table)
            if final != frame.height:
                raise SystemExit(
                    f"COUNT_MISMATCH {table}: server {final} != parquet {frame.height}"
                )
            print(f"[load] {table}: OK, {final:,} rows verified")
    print("[load] done")


if __name__ == "__main__":
    main()
