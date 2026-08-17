"""Gate 10 (decision 56a): formalize the cross-family positive contrasts.

The registered story focused on the family-dependent B2-over-B1 increment. The
frozen artifacts also contain contrasts that were never formalized: in the 2024
blocks the B1a-over-B0 contrast and the TOTAL B0-to-B2 contrast are positive
across every model family. This runner computes, from the frozen forecasts
only, every {B0->B1, B1->B2, B0->B2} contrast per family per campaign with the
Gate-1 studentized machinery, plus a cross-family robustness count per cell.
Label: EXPLORATORY_DESCRIPTIVE. Signs are reported exactly as computed.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import polars as pl

from mds650 import inference

REPO = Path(__file__).resolve().parents[1]
DATA_ROOT = Path(os.environ.get("MDS650_EXTERNAL_ROOT", "D:/MDS650"))
EVIDENCE_ROOT = Path(os.environ.get("MDS650_EVIDENCE_ROOT", DATA_ROOT / "evidence_root"))
OUTPUT = REPO / "artifacts" / "gate10_positive_findings"

CAMPAIGNS: dict[str, dict[str, Any]] = {
    "C1_development_2026": {
        "path": REPO / "artifacts" / "phase5" / "development_forecasts.parquet",
        "model_column": "model_role",
        "sets": ("B0", "B1a", "B2"),
    },
    "C2_holdout_2026": {
        "path": EVIDENCE_ROOT / "artifacts" / "phase5" / "holdout_forecasts.parquet",
        "model_column": "model_role",
        "sets": ("B0", "B1a", "B2"),
    },
    "C4c_replication_2025": {
        "path": DATA_ROOT
        / "independent_replication_30"
        / "derived"
        / "pit_v2_evaluation"
        / "predictions_pit_v2.parquet",
        "model_column": "model_role",
        "sets": ("B0v2", "B1v2a", "B2v2"),
    },
    "C5_blocks_2024": {
        "path": REPO / "artifacts" / "b2_confirmation" / "frozen_evaluation_forecasts.parquet",
        "model_column": "model_name",
        "sets": ("B0", "B1a", "B2"),
        "block_column": "block_id",
    },
    "C6_b1v3_2024": {
        "path": DATA_ROOT / "b1v3_confirmation" / "evaluation" / "primary_forecasts.parquet",
        "model_column": "model_role",
        "sets": ("B0", "B1v3a", "B2"),
    },
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _stats(
    frame: pl.DataFrame, model_column: str, model: str, base: str, expanded: str
) -> dict[str, Any]:
    daily = inference.paired_daily_differences(
        frame,
        base_set=base,
        expanded_set=expanded,
        model=model,
        model_column=model_column,
    )
    values = daily["mean_difference"].to_numpy()
    entry: dict[str, Any] = dict(inference.cluster_t_test(values))
    entry["p_newey_west"] = inference.newey_west_t_test(values)["p_value"]
    entry["p_wild"] = inference.wild_cluster_bootstrap(values)["p_value"]
    return entry


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    results: dict[str, Any] = {
        "schema_version": "gate10-positive-findings-v1.0",
        "label": "EXPLORATORY_DESCRIPTIVE (decision 56a)",
        "campaigns": {},
    }
    for name, spec in CAMPAIGNS.items():
        frame = pl.read_parquet(Path(spec["path"]))
        if "timing_variant" in frame.columns:
            frame = frame.filter(pl.col("timing_variant") == "PRIMARY")
        blocks: list[tuple[str, pl.DataFrame]] = [("all", frame)]
        if "block_column" in spec:
            blocks = [
                (str(block), frame.filter(pl.col(spec["block_column"]) == block))
                for block in sorted(frame[spec["block_column"]].unique().to_list())
            ]
        model_column = str(spec["model_column"])
        base, middle, top = spec["sets"]
        campaign_entry: dict[str, Any] = {
            "input_sha256": _sha256(Path(spec["path"])),
            "blocks": {},
        }
        for block_name, block in blocks:
            models = sorted(block[model_column].unique().to_list())
            contrasts: dict[str, Any] = {}
            for model in models:
                contrasts[model] = {
                    f"{base}->{middle}": _stats(block, model_column, model, base, middle),
                    f"{middle}->{top}": _stats(block, model_column, model, middle, top),
                    f"{base}->{top}_total": _stats(block, model_column, model, base, top),
                }
            robustness: dict[str, dict[str, int]] = {}
            for contrast_name in (f"{base}->{middle}", f"{middle}->{top}", f"{base}->{top}_total"):
                positive = sum(
                    1
                    for model in models
                    if contrasts[model][contrast_name]["estimate"] > 0
                    and contrasts[model][contrast_name]["p_value"] < 0.05
                )
                negative = sum(
                    1
                    for model in models
                    if contrasts[model][contrast_name]["estimate"] < 0
                    and contrasts[model][contrast_name]["p_value"] < 0.05
                )
                robustness[contrast_name] = {
                    "families": len(models),
                    "significantly_positive": positive,
                    "significantly_negative": negative,
                }
            campaign_entry["blocks"][block_name] = {
                "contrasts": contrasts,
                "cross_family_robustness": robustness,
            }
        results["campaigns"][name] = campaign_entry
    payload = json.dumps(results, indent=1, sort_keys=True, default=str)
    (OUTPUT / "results.json").write_text(payload, encoding="utf-8")
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    (OUTPUT / "results.sha256").write_text(digest + "\n", encoding="utf-8")
    print(f"[gate10] wrote {OUTPUT / 'results.json'} sha256={digest[:16]}")


if __name__ == "__main__":
    main()
