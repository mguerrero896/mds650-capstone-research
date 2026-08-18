"""Sync the research catalog tables in Supabase from the repo's frozen artifacts.

Idempotent upserts (PostgREST, service-role key) of aggregates only — no licensed
provider values ever leave the repo through this script:

    campaigns          <- artifacts/gate1_inference/results.json
    contrast_results   <- artifacts/gate1_inference/results.json
    mcs_cells          <- artifacts/mcs_block_sensitivity/results.json
    gated_files        <- data/GATED_DATA_POINTERS.json

Run:  $env:SUPABASE_SERVICE_KEY set, then  uv run python scripts/sync_supabase_catalog.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import httpx

REPO = Path(__file__).resolve().parents[1]
PROJECT_REF = "eqpyjikcewqaegnbaemf"
REST = f"https://{PROJECT_REF}.supabase.co/rest/v1"


def _upsert(client: httpx.Client, table: str, rows: list[dict[str, Any]], conflict: str) -> None:
    if not rows:
        return
    response = client.post(
        f"{REST}/{table}",
        params={"on_conflict": conflict},
        json=rows,
        headers={"Prefer": "resolution=merge-duplicates"},
    )
    if response.status_code not in (200, 201):
        raise SystemExit(f"UPSERT_FAILED {table}: {response.status_code} {response.text[:300]}")
    print(f"[sync] {table}: {len(rows)} rows upserted")


def main() -> None:
    key = os.environ.get("SUPABASE_SERVICE_KEY")
    if not key:
        raise SystemExit("SUPABASE_SERVICE_KEY missing (User env var; see DATA_ACCESS.md).")

    gate1 = json.loads((REPO / "artifacts" / "gate1_inference" / "results.json").read_text())
    mcs = json.loads((REPO / "artifacts" / "mcs_block_sensitivity" / "results.json").read_text())
    pointers = json.loads((REPO / "data" / "GATED_DATA_POINTERS.json").read_text())

    campaigns: list[dict[str, Any]] = []
    contrasts: list[dict[str, Any]] = []
    for campaign_id, campaign in gate1["campaigns"].items():
        campaigns.append(
            {
                "campaign_id": campaign_id,
                "sessions": campaign.get("sessions"),
                "row_count": campaign.get("rows"),
                "input_sha256": campaign["input_sha256"],
                "note": gate1.get("note"),
            }
        )
        for block_id, block in campaign["blocks"].items():
            for contrast_key, entry in block["contrasts"].items():
                model_role, _, contrast = contrast_key.partition(":")
                contrasts.append(
                    {
                        "campaign_id": campaign_id,
                        "block_id": block_id,
                        "model_role": model_role,
                        "contrast": contrast,
                        "estimate": entry["cluster_t"]["estimate"],
                        "cluster_t": entry["cluster_t"]["statistic"],
                        "p_cluster": entry["cluster_t"]["p_value"],
                        "p_newey_west": entry.get("newey_west", {}).get("p_value"),
                        "p_wild": entry.get("wild_bootstrap", {}).get("p_value"),
                        "rho1": (entry.get("acf") or [None])[0],
                        "ljung_box_p": entry.get("ljung_box", {}).get("p_value"),
                    }
                )

    cells: list[dict[str, Any]] = []
    for campaign_id, campaign in mcs["campaigns"].items():
        for block_id, block in campaign["blocks"].items():
            for length_key, result in block["by_block_length"].items():
                length = int(length_key.removeprefix("L="))
                survivors = set(result["survivors"])
                for cell, p_value in result["mcs_p_values"].items():
                    cells.append(
                        {
                            "campaign_id": campaign_id,
                            "block_id": block_id,
                            "block_length": length,
                            "cell": cell,
                            "mcs_p": p_value,
                            "survivor": cell in survivors,
                        }
                    )

    gated = [
        {
            "path": entry["path"],
            "sha256": entry["sha256"],
            "bytes": entry["bytes"],
            "bucket_object": entry["bucket_object"],
        }
        for entry in pointers["files"]
    ]

    headers = {"Authorization": f"Bearer {key}", "apikey": key}
    with httpx.Client(timeout=120, headers=headers) as client:
        _upsert(client, "campaigns", campaigns, "campaign_id")
        _upsert(client, "contrast_results", contrasts, "campaign_id,block_id,model_role,contrast")
        _upsert(client, "mcs_cells", cells, "campaign_id,block_id,block_length,cell")
        _upsert(client, "gated_files", gated, "path")
    print("[sync] done")


if __name__ == "__main__":
    main()
