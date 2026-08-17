"""Economic-significance appendix (roadmap 5.4, decision-56 era).

Translates the abstract QLIKE deltas into interpretable units from the frozen
forecast parquets, per campaign and model family, for the B1->B2 and B0->B2
contrasts: (a) annualized-volatility forecast RMSE and its percentage
reduction; (b) a toy delta-hedging cost proxy - the mean absolute error in
annualized variance units times a 100k USD vega-style notional - labeled TOY:
no execution, no prices, no profitability claim (research illustration only).
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

REPO = Path(__file__).resolve().parents[1]
DATA_ROOT = Path(os.environ.get("MDS650_EXTERNAL_ROOT", "D:/MDS650"))
EVIDENCE_ROOT = Path(os.environ.get("MDS650_EVIDENCE_ROOT", DATA_ROOT / "evidence_root"))
OUTPUT = REPO / "artifacts" / "economic_significance"
WINDOWS_PER_YEAR = 13.0 * 252.0
TOY_NOTIONAL_USD = 100_000.0

CAMPAIGNS: dict[str, dict[str, Any]] = {
    "C5_blocks_2024": {
        "path": REPO / "artifacts" / "b2_confirmation" / "frozen_evaluation_forecasts.parquet",
        "model_column": "model_name",
        "models": ["gamma_glm", "lightgbm", "har_rv"],
        "sets": ("B0", "B1a", "B2"),
    },
    "C4c_replication_2025": {
        "path": DATA_ROOT
        / "independent_replication_30"
        / "derived"
        / "pit_v2_evaluation"
        / "predictions_pit_v2.parquet",
        "model_column": "model_role",
        "models": ["gamma_glm_confirmatory", "lightgbm_robustness"],
        "sets": ("B0v2", "B1v2a", "B2v2"),
    },
    "C6_b1v3_2024": {
        "path": DATA_ROOT / "b1v3_confirmation" / "evaluation" / "primary_forecasts.parquet",
        "model_column": "model_role",
        "models": ["gamma_glm_confirmatory", "lightgbm_robustness"],
        "sets": ("B0", "B1v3a", "B2"),
    },
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _vol_annual(rv30: np.ndarray) -> np.ndarray:
    return np.asarray(np.sqrt(np.maximum(rv30, 0.0) * WINDOWS_PER_YEAR), dtype=np.float64)


def _metrics(frame: pl.DataFrame) -> dict[str, float]:
    actual = frame["rv30"].to_numpy().astype(np.float64)
    forecast = frame["forecast"].to_numpy().astype(np.float64)
    vol_error = _vol_annual(forecast) - _vol_annual(actual)
    variance_mae_annual = float(
        np.mean(np.abs(forecast - actual)) * WINDOWS_PER_YEAR
    )
    return {
        "vol_rmse_annual_points": float(np.sqrt(np.mean(vol_error**2)) * 100.0),
        "vol_mae_annual_points": float(np.mean(np.abs(vol_error)) * 100.0),
        "toy_hedge_cost_usd_per_window": variance_mae_annual * TOY_NOTIONAL_USD / WINDOWS_PER_YEAR,
        "median_actual_vol_annual_points": float(np.median(_vol_annual(actual)) * 100.0),
    }


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    results: dict[str, Any] = {
        "schema_version": "economic-significance-v1.0",
        "label": "TOY / DESCRIPTIVE - no execution, prices, costs, or profitability claim",
        "annualization_windows_per_year": WINDOWS_PER_YEAR,
        "toy_notional_usd": TOY_NOTIONAL_USD,
        "campaigns": {},
    }
    for name, spec in CAMPAIGNS.items():
        frame = pl.read_parquet(Path(spec["path"]))
        if "timing_variant" in frame.columns:
            frame = frame.filter(pl.col("timing_variant") == "PRIMARY")
        base, middle, top = spec["sets"]
        entry: dict[str, Any] = {"input_sha256": _sha256(Path(spec["path"])), "models": {}}
        for model in spec["models"]:
            model_frame = frame.filter(pl.col(spec["model_column"]) == model)
            cells = {
                label: _metrics(
                    model_frame.filter(pl.col("information_set") == label)
                )
                for label in (base, middle, top)
                if not model_frame.filter(pl.col("information_set") == label).is_empty()
            }
            if len(cells) < 3:
                continue
            improvement = {
                "vol_rmse_reduction_B1_to_B2_pct": 100.0
                * (cells[middle]["vol_rmse_annual_points"] - cells[top]["vol_rmse_annual_points"])
                / cells[middle]["vol_rmse_annual_points"],
                "vol_rmse_reduction_B0_to_B2_pct": 100.0
                * (cells[base]["vol_rmse_annual_points"] - cells[top]["vol_rmse_annual_points"])
                / cells[base]["vol_rmse_annual_points"],
                "toy_hedge_saving_usd_per_window_B1_to_B2": (
                    cells[middle]["toy_hedge_cost_usd_per_window"]
                    - cells[top]["toy_hedge_cost_usd_per_window"]
                ),
            }
            entry["models"][model] = {"cells": cells, "improvement": improvement}
        results["campaigns"][name] = entry
    payload = json.dumps(results, indent=1, sort_keys=True)
    (OUTPUT / "results.json").write_text(payload, encoding="utf-8")
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    (OUTPUT / "results.sha256").write_text(digest + "\n", encoding="utf-8")
    for name, campaign_entry in results["campaigns"].items():
        for model, model_entry in campaign_entry["models"].items():
            imp = model_entry["improvement"]
            print(
                f"[econ] {name}/{model}: "
                f"B1->B2 vol-RMSE {imp['vol_rmse_reduction_B1_to_B2_pct']:+.2f}% "
                f"B0->B2 {imp['vol_rmse_reduction_B0_to_B2_pct']:+.2f}% "
                f"toy saving ${imp['toy_hedge_saving_usd_per_window_B1_to_B2']:+.2f}/window"
            )
    print(f"[econ] wrote {OUTPUT / 'results.json'} sha256={digest[:16]}")


if __name__ == "__main__":
    main()
