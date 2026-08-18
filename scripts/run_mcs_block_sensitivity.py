"""MCS block-bootstrap sensitivity (reviewer correction, 2026-08-18).

The original Model Confidence Sets resampled days IID, which destroys the
serial dependence measured on the same daily series (rho_1 up to +0.62 where
the headline lives) and can make elimination too easy. This runner recomputes
every campaign's MCS under a circular moving-block bootstrap with block
lengths L in {ceil(T^(1/3)), 5, 10, 20} plus the IID baseline, drawing whole
days jointly across all model x information-set columns, and reports which
cells survive at every L. Re-analysis of frozen artifacts only.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any

import polars as pl

from mds650 import inference

REPO = Path(__file__).resolve().parents[1]
DATA_ROOT = Path(os.environ.get("MDS650_EXTERNAL_ROOT", "D:/MDS650"))
EVIDENCE_ROOT = Path(os.environ.get("MDS650_EVIDENCE_ROOT", DATA_ROOT / "evidence_root"))
OUTPUT = REPO / "artifacts" / "mcs_block_sensitivity"

CAMPAIGNS: dict[str, dict[str, Any]] = {
    "C1_development": {
        "path": REPO / "artifacts" / "phase5" / "development_forecasts.parquet",
        "model_column": "model_role",
    },
    "C2_holdout_prospective": {
        "path": EVIDENCE_ROOT / "artifacts" / "phase5" / "holdout_forecasts.parquet",
        "model_column": "model_role",
    },
    "C4c_replication_pit_v2": {
        "path": DATA_ROOT
        / "independent_replication_30"
        / "derived"
        / "pit_v2_evaluation"
        / "predictions_pit_v2.parquet",
        "model_column": "model_role",
    },
    "C5_blocks_2024_exploratory": {
        "path": REPO / "artifacts" / "b2_confirmation" / "frozen_evaluation_forecasts.parquet",
        "model_column": "model_name",
        "block_column": "block_id",
    },
    "C6_b1v3_confirmation": {
        "path": DATA_ROOT / "b1v3_confirmation" / "evaluation" / "primary_forecasts.parquet",
        "model_column": "model_role",
    },
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _cells(frame: pl.DataFrame, model_column: str) -> pl.DataFrame:
    return (
        frame.group_by("session_date", model_column, "information_set")
        .agg(pl.col("qlike_loss").mean())
        .with_columns(
            (
                pl.col(model_column).cast(pl.Utf8)
                + pl.lit("|")
                + pl.col("information_set").cast(pl.Utf8)
            ).alias("cell")
        )
        .pivot(on="cell", index="session_date", values="qlike_loss")
        .sort("session_date")
        .drop_nulls()
    )


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    results: dict[str, Any] = {
        "schema_version": "mcs-block-sensitivity-v1.0",
        "note": (
            "Circular moving-block MCS (whole days drawn jointly across all model "
            "columns) vs the legacy IID resampling; L=0 denotes IID."
        ),
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
        entry: dict[str, Any] = {"input_sha256": _sha256(Path(spec["path"])), "blocks": {}}
        for block_name, block in blocks:
            cells = _cells(block, str(spec["model_column"]))
            count = cells.height
            lengths: list[int | None] = [None, max(2, math.ceil(count ** (1.0 / 3.0))), 5, 10]
            if count > 20:
                lengths.append(20)
            per_length: dict[str, Any] = {}
            for length in lengths:
                mcs = inference.model_confidence_set(cells, block_length=length)
                per_length[f"L={0 if length is None else length}"] = {
                    "survivors": mcs["survivors"],
                    "mcs_p_values": mcs["mcs_p_values"],
                }
            entry["blocks"][block_name] = {"days": count, "by_block_length": per_length}
        results["campaigns"][name] = entry
        print(f"[mcs-block] {name} done")
    payload = json.dumps(results, indent=1, sort_keys=True, default=str)
    (OUTPUT / "results.json").write_text(payload, encoding="utf-8")
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    (OUTPUT / "results.sha256").write_text(digest + "\n", encoding="utf-8")
    print(f"[mcs-block] wrote {OUTPUT / 'results.json'} sha256={digest[:16]}")


if __name__ == "__main__":
    main()
