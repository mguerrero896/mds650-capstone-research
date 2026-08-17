"""Gate 2: calibration-vs-information on the binding frozen samples.

Pre-stated design (recorded before any delta below was computed):

- Mincer-Zarnowitz (log scale) per model x information set x campaign.
- Recalibration coefficients are fitted strictly out of the evaluation half:
  C6 Gamma uses the frozen training OOF forecasts; every other cell uses the
  first half of evaluation sessions (fit) vs the second half (score), labeled
  ``split_sample``. Corrected forecasts use the lognormal smearing term.
- Primary estimand: symmetric recalibrated Delta(B2) = daily mean
  QLIKE(recal base) - QLIKE(recal B2). Secondary: base-only recalibration.
- Interpretation rule: if the C6 symmetric recalibrated Gamma Delta(B2) falls
  below the frozen MDE 0.013040, the Gamma-specific B2 effect is reported as a
  calibration artifact; if it stays above with wild-bootstrap p < 0.05 it
  survives objection R-020. C4c rule uses MDE 0.005035. C5 is exploratory.
- Diagnostic 2.2: per-day regression of the raw Gamma B2 daily differential on
  the day's mean baseline log-bias ln(actual / forecast_base).

Re-analysis of already-read artifacts only; decision-52 compliant.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from mds650 import calibration, inference
from mds650.metrics import qlike_losses

REPO = Path(__file__).resolve().parents[1]
DATA_ROOT = Path(os.environ.get("MDS650_EXTERNAL_ROOT", "D:/MDS650"))
OUTPUT = REPO / "artifacts" / "gate2_calibration"

GAMMA = "gamma_glm_confirmatory"
LGBM = "lightgbm_robustness"

RULES = {
    "C6_b1v3_confirmation": {"mde": 0.013040, "binding": True},
    "C4c_replication_pit_v2": {"mde": 0.005035, "binding": True},
    "C5_blocks_2024_exploratory": {"mde": 0.005035, "binding": False},
}

CAMPAIGNS: dict[str, dict[str, Any]] = {
    "C6_b1v3_confirmation": {
        "eval_path": DATA_ROOT / "b1v3_confirmation" / "evaluation" / "primary_forecasts.parquet",
        "train_path": DATA_ROOT
        / "b1v3_confirmation"
        / "evaluation"
        / "training_oof_forecasts.parquet",
        "model_column": "model_role",
        "models": [GAMMA, LGBM],
        "sets": ["B0", "B1v3a", "B2"],
        "base": "B1v3a",
        "expanded": "B2",
    },
    "C4c_replication_pit_v2": {
        "eval_path": DATA_ROOT
        / "independent_replication_30"
        / "derived"
        / "pit_v2_evaluation"
        / "predictions_pit_v2.parquet",
        "model_column": "model_role",
        "models": [GAMMA, LGBM],
        "sets": ["B0v2", "B1v2a", "B2v2"],
        "base": "B1v2a",
        "expanded": "B2v2",
    },
    "C5_blocks_2024_exploratory": {
        "eval_path": REPO / "artifacts" / "b2_confirmation" / "frozen_evaluation_forecasts.parquet",
        "model_column": "model_name",
        "models": ["gamma_glm", "lightgbm", "har_rv", "ridge", "elastic_net"],
        "sets": ["B0", "B1a", "B2"],
        "base": "B1a",
        "expanded": "B2",
        "block_column": "block_id",
    },
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fit_cell(frame: pl.DataFrame) -> dict[str, float | int]:
    return calibration.mincer_zarnowitz(
        frame["rv30"].to_numpy(), frame["forecast"].to_numpy()
    )


def _corrected(frame: pl.DataFrame, fit: dict[str, float | int]) -> pl.DataFrame:
    corrected = calibration.recalibrate(
        frame["forecast"].to_numpy(),
        intercept=float(fit["intercept"]),
        slope=float(fit["slope"]),
        sigma2=float(fit["sigma2"]),
    )
    losses = qlike_losses(frame["rv30"].to_numpy(), corrected)
    return frame.with_columns(
        pl.Series("forecast_recal", corrected), pl.Series("qlike_recal", losses)
    )


def _daily_delta(
    base: pl.DataFrame,
    expanded: pl.DataFrame,
    column: str,
    *,
    expanded_column: str | None = None,
) -> pl.DataFrame:
    keys = ["origin_id", "asset", "session_date"]
    paired = base.select(*keys, pl.col(column).alias("base_loss")).join(
        expanded.select(*keys, pl.col(expanded_column or column).alias("expanded_loss")),
        on=keys,
        how="inner",
    )
    if paired.height != base.height or paired.height != expanded.height:
        raise ValueError("GATE2_UNPAIRED_ORIGINS")
    return (
        paired.with_columns((pl.col("base_loss") - pl.col("expanded_loss")).alias("difference"))
        .group_by("session_date")
        .agg(pl.col("difference").mean().alias("mean_difference"), pl.len().alias("origin_count"))
        .sort("session_date")
    )


def _stats(daily: pl.DataFrame) -> dict[str, Any]:
    values = daily["mean_difference"].to_numpy()
    return {
        "cluster_t": inference.cluster_t_test(values),
        "newey_west": inference.newey_west_t_test(values),
        "wild_rademacher": inference.wild_cluster_bootstrap(values),
        "days": int(values.size),
    }


def _bias_regression(base: pl.DataFrame, expanded: pl.DataFrame) -> dict[str, float]:
    delta = _daily_delta(base, expanded, "qlike_loss")
    bias = (
        base.with_columns((pl.col("rv30") / pl.col("forecast")).log().alias("log_bias"))
        .group_by("session_date")
        .agg(pl.col("log_bias").mean())
        .sort("session_date")
    )
    joined = delta.join(bias, on="session_date", how="inner")
    y = joined["mean_difference"].to_numpy()
    x = joined["log_bias"].to_numpy()
    x_centered = x - x.mean()
    denominator = float(np.dot(x_centered, x_centered))
    slope = float(np.dot(x_centered, y - y.mean()) / denominator)
    intercept = float(y.mean() - slope * x.mean())
    residuals = y - intercept - slope * x
    dof = y.size - 2
    slope_se = float(np.sqrt(np.dot(residuals, residuals) / dof / denominator))
    total = float(np.dot(y - y.mean(), y - y.mean()))
    return {
        "slope": slope,
        "slope_t": slope / slope_se if slope_se > 0 else float("inf"),
        "r_squared": 1.0 - float(np.dot(residuals, residuals)) / total if total > 0 else 0.0,
        "days": float(y.size),
    }


def _campaign(name: str, spec: dict[str, Any]) -> dict[str, Any]:
    eval_path = Path(spec["eval_path"])
    frame = pl.read_parquet(eval_path)
    if "timing_variant" in frame.columns:
        frame = frame.filter(pl.col("timing_variant") == "PRIMARY")
    train_frame: pl.DataFrame | None = None
    if "train_path" in spec:
        train_frame = pl.read_parquet(Path(spec["train_path"]))
    blocks: list[tuple[str, pl.DataFrame]] = [("all", frame)]
    if "block_column" in spec:
        blocks = [
            (str(block), frame.filter(pl.col(spec["block_column"]) == block))
            for block in sorted(frame[spec["block_column"]].unique().to_list())
        ]
    model_column = str(spec["model_column"])
    result: dict[str, Any] = {
        "input_path": str(eval_path),
        "input_sha256": _sha256(eval_path),
        "blocks": {},
    }
    if train_frame is not None:
        result["train_path"] = str(spec["train_path"])
        result["train_sha256"] = _sha256(Path(spec["train_path"]))
    for block_name, block in blocks:
        sessions = sorted(block["session_date"].unique().to_list())
        midpoint = len(sessions) // 2
        fit_sessions, score_sessions = sessions[:midpoint], sessions[midpoint:]
        entry: dict[str, Any] = {
            "mincer_zarnowitz": {},
            "recalibrated": {},
            "bias_regression": {},
            "split": {
                "fit_sessions": len(fit_sessions),
                "score_sessions": len(score_sessions),
            },
        }
        cells: dict[tuple[str, str], dict[str, Any]] = {}
        for model in spec["models"]:
            for info_set in spec["sets"]:
                cell = block.filter(
                    (pl.col(model_column) == model) & (pl.col("information_set") == info_set)
                )
                if cell.is_empty():
                    continue
                entry["mincer_zarnowitz"][f"{model}|{info_set}"] = _fit_cell(cell)
                if (
                    train_frame is not None
                    and model in train_frame[model_column].unique().to_list()
                ):
                    fit_source = train_frame.filter(
                        (pl.col(model_column) == model)
                        & (pl.col("information_set") == info_set)
                    )
                    method = "training_oof"
                    score = cell
                else:
                    fit_source = cell.filter(pl.col("session_date").is_in(fit_sessions))
                    method = "split_sample"
                    score = cell.filter(pl.col("session_date").is_in(score_sessions))
                fit = _fit_cell(fit_source)
                cells[(model, info_set)] = {
                    "method": method,
                    "fit": fit,
                    "scored": _corrected(score, fit),
                    "raw_scored": score,
                }
                if method == "training_oof":
                    split_fit = _fit_cell(
                        cell.filter(pl.col("session_date").is_in(fit_sessions))
                    )
                    split_score = cell.filter(pl.col("session_date").is_in(score_sessions))
                    cells[(f"{model}#split", info_set)] = {
                        "method": "split_sample_sensitivity",
                        "fit": split_fit,
                        "scored": _corrected(split_score, split_fit),
                        "raw_scored": split_score,
                    }
        contrast_models = list(spec["models"]) + [
            f"{model}#split"
            for model in spec["models"]
            if (f"{model}#split", str(spec["base"])) in cells
        ]
        for model in contrast_models:
            base_cell = cells.get((model, str(spec["base"])))
            expanded_cell = cells.get((model, str(spec["expanded"])))
            if base_cell is None or expanded_cell is None:
                continue
            if base_cell["method"] != expanded_cell["method"]:
                raise ValueError("GATE2_METHOD_MISMATCH")
            symmetric = _daily_delta(
                base_cell["scored"], expanded_cell["scored"], "qlike_recal"
            )
            base_only = _daily_delta(
                base_cell["scored"],
                expanded_cell["raw_scored"],
                "qlike_recal",
                expanded_column="qlike_loss",
            )
            raw = _daily_delta(base_cell["raw_scored"], expanded_cell["raw_scored"], "qlike_loss")
            entry["recalibrated"][model] = {
                "method": base_cell["method"],
                "raw_delta_scored_half": _stats(raw),
                "symmetric_recalibrated_delta": _stats(symmetric),
                "base_only_recalibrated_delta": _stats(base_only),
            }
        gamma_model = spec["models"][0]
        base_cell = cells.get((gamma_model, str(spec["base"])))
        expanded_cell = cells.get((gamma_model, str(spec["expanded"])))
        if base_cell is not None and expanded_cell is not None:
            entry["bias_regression"][gamma_model] = _bias_regression(
                base_cell["raw_scored"], expanded_cell["raw_scored"]
            )
        for cell_entry in cells.values():
            cell_entry.pop("scored", None)
            cell_entry.pop("raw_scored", None)
        result["blocks"][block_name] = entry
    return result


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    results: dict[str, Any] = {
        "schema_version": "gate2-calibration-v1.0",
        "prestated_rules": RULES,
        "smearing": True,
        "seed": 650,
        "deferred": {
            "lightgbm_importances": "requires model refits; folded into Gate 9 ablation",
            "ols_on_log_rv_benchmark": "requires feature panels; folded into Gate 3 ladder",
        },
        "campaigns": {},
    }
    for name, spec in CAMPAIGNS.items():
        print(f"[gate2] {name}")
        results["campaigns"][name] = _campaign(name, spec)
    payload = json.dumps(results, indent=1, sort_keys=True, default=str)
    (OUTPUT / "results.json").write_text(payload, encoding="utf-8")
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    (OUTPUT / "results.sha256").write_text(digest + "\n", encoding="utf-8")
    print(f"[gate2] wrote {OUTPUT / 'results.json'} sha256={digest[:16]}")


if __name__ == "__main__":
    main()
