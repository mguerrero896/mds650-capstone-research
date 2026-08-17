"""Gate 4: effect-decay regression and decay-aware power for the Phase 8 read.

Pools the per-day Gamma-specific B2 loss differentials from every frozen
campaign, regresses them on calendar time (day-level pooled OLS with wild
cluster bootstrap on the slope, plus an inverse-variance campaign-level
meta-regression), extrapolates the expected effect at the Phase 8 holdout
midpoint, and computes the session count needed for 80% power at that effect
and at the equivalence bound. Everything is written down BEFORE the Phase 8
read (2026-08-29); nothing touches the frozen method hash 87c818be.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
from scipy import stats

from mds650 import inference

REPO = Path(__file__).resolve().parents[1]
DATA_ROOT = Path(os.environ.get("MDS650_EXTERNAL_ROOT", "D:/MDS650"))
EVIDENCE_ROOT = Path(os.environ.get("MDS650_EVIDENCE_ROOT", DATA_ROOT / "evidence_root"))
OUTPUT = REPO / "artifacts" / "gate4_decay_power"

GAMMA = "gamma_glm_confirmatory"
LGBM = "lightgbm_robustness"
EQUIVALENCE_BOUND = 0.005035
PHASE8_MIDPOINT = date(2026, 8, 8)
PHASE8_SESSIONS = 30

CAMPAIGNS: dict[str, dict[str, Any]] = {
    "C1_development": {
        "path": REPO / "artifacts" / "phase5" / "development_forecasts.parquet",
        "models": {GAMMA: GAMMA, LGBM: LGBM},
        "model_column": "model_role",
        "base": "B1a",
        "expanded": "B2",
    },
    "C2_holdout": {
        "path": EVIDENCE_ROOT / "artifacts" / "phase5" / "holdout_forecasts.parquet",
        "models": {GAMMA: GAMMA, LGBM: LGBM},
        "model_column": "model_role",
        "base": "B1a",
        "expanded": "B2",
    },
    "C4c_replication": {
        "path": DATA_ROOT
        / "independent_replication_30"
        / "derived"
        / "pit_v2_evaluation"
        / "predictions_pit_v2.parquet",
        "models": {GAMMA: GAMMA, LGBM: LGBM},
        "model_column": "model_role",
        "base": "B1v2a",
        "expanded": "B2v2",
    },
    "C5_blocks_2024": {
        "path": REPO / "artifacts" / "b2_confirmation" / "frozen_evaluation_forecasts.parquet",
        "models": {GAMMA: "gamma_glm", LGBM: "lightgbm"},
        "model_column": "model_name",
        "base": "B1a",
        "expanded": "B2",
    },
    "C6_b1v3": {
        "path": DATA_ROOT / "b1v3_confirmation" / "evaluation" / "primary_forecasts.parquet",
        "models": {GAMMA: GAMMA, LGBM: LGBM},
        "model_column": "model_role",
        "base": "B1v3a",
        "expanded": "B2",
    },
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _daily_series(role: str) -> pl.DataFrame:
    frames = []
    for name, spec in CAMPAIGNS.items():
        frame = pl.read_parquet(Path(spec["path"]))
        if "timing_variant" in frame.columns:
            frame = frame.filter(pl.col("timing_variant") == "PRIMARY")
        daily = inference.paired_daily_differences(
            frame,
            base_set=str(spec["base"]),
            expanded_set=str(spec["expanded"]),
            model=str(spec["models"][role]),
            model_column=str(spec["model_column"]),
        ).with_columns(pl.lit(name).alias("campaign"))
        frames.append(daily)
    return (
        pl.concat(frames)
        .with_columns(pl.col("session_date").cast(pl.Date))
        .sort("session_date")
    )


def _trend(daily: pl.DataFrame) -> dict[str, Any]:
    days = daily["session_date"].to_numpy()
    day_offsets = [
        (value - np.datetime64("2024-01-01")).astype("timedelta64[D]").astype(int)
        for value in days
    ]
    epoch = np.asarray(day_offsets, dtype=np.float64) / 365.25
    values = daily["mean_difference"].to_numpy().astype(np.float64)
    centered = epoch - epoch.mean()
    denominator = float(centered @ centered)
    slope = float(centered @ (values - values.mean()) / denominator)
    intercept = float(values.mean() - slope * epoch.mean())
    residuals = values - intercept - slope * epoch
    slope_se = float(
        math.sqrt((residuals @ residuals) / (values.size - 2) / denominator)
    )
    generator = np.random.default_rng(650)
    draws = generator.choice(np.asarray([-1.0, 1.0]), size=(9_999, values.size))
    boot = (residuals[None, :] * draws * centered[None, :]).sum(axis=1) / denominator
    p_slope = float(
        (np.count_nonzero(np.abs(boot) >= abs(slope)) + 1.0) / (9_999 + 1.0)
    )
    midpoint_years = (
        np.datetime64(PHASE8_MIDPOINT.isoformat()) - np.datetime64("2024-01-01")
    ).astype("timedelta64[D]").astype(int) / 365.25
    prediction = intercept + slope * float(midpoint_years)
    prediction_se = float(
        math.sqrt(
            (residuals @ residuals)
            / (values.size - 2)
            * (1.0 / values.size + (midpoint_years - epoch.mean()) ** 2 / denominator)
        )
    )
    return {
        "slope_per_year": slope,
        "slope_se": slope_se,
        "slope_wild_p": p_slope,
        "intercept": intercept,
        "days": int(values.size),
        "phase8_midpoint_prediction": prediction,
        "phase8_midpoint_prediction_se": prediction_se,
        "phase8_midpoint_prediction_ci95": [
            prediction - 1.96 * prediction_se,
            prediction + 1.96 * prediction_se,
        ],
    }


def _meta_regression(daily: pl.DataFrame) -> dict[str, Any]:
    rows = []
    for campaign, group in daily.group_by("campaign"):
        values = group["mean_difference"].to_numpy().astype(np.float64)
        dates = group["session_date"].to_numpy()
        midpoint = dates[len(dates) // 2]
        rows.append(
            {
                "campaign": str(campaign[0]),
                "midpoint": str(midpoint),
                "estimate": float(values.mean()),
                "se": float(values.std(ddof=1) / math.sqrt(values.size)),
                "days": int(values.size),
            }
        )
    rows.sort(key=lambda row: str(row["midpoint"]))
    estimates = np.asarray([row["estimate"] for row in rows])
    variances = np.asarray([row["se"] for row in rows]) ** 2
    weights = 1.0 / variances
    fixed = float((weights * estimates).sum() / weights.sum())
    q_statistic = float((weights * (estimates - fixed) ** 2).sum())
    dof = len(rows) - 1
    tau2 = max(
        0.0,
        (q_statistic - dof)
        / (weights.sum() - (weights**2).sum() / weights.sum()),
    )
    random_weights = 1.0 / (variances + tau2)
    random_effect = float((random_weights * estimates).sum() / random_weights.sum())
    random_se = float(math.sqrt(1.0 / random_weights.sum()))
    return {
        "campaigns": rows,
        "fixed_effect": fixed,
        "cochran_q": q_statistic,
        "q_p_value": float(stats.chi2.sf(q_statistic, df=dof)),
        "i_squared": max(0.0, (q_statistic - dof) / q_statistic) if q_statistic > 0 else 0.0,
        "tau2": tau2,
        "random_effect": random_effect,
        "random_effect_se": random_se,
        "random_effect_ci95": [
            random_effect - 1.96 * random_se,
            random_effect + 1.96 * random_se,
        ],
    }


def _power(daily_sd: float, effect: float, *, alpha: float = 0.05) -> dict[str, float]:
    if effect <= 0:
        return {"sessions_for_80_power": float("inf"), "daily_sd": daily_sd}
    z_alpha = float(stats.norm.ppf(1.0 - alpha / 2.0))
    z_beta = float(stats.norm.ppf(0.80))
    sessions = ((z_alpha + z_beta) * daily_sd / effect) ** 2
    return {"sessions_for_80_power": float(math.ceil(sessions)), "daily_sd": daily_sd}


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    results: dict[str, Any] = {
        "schema_version": "gate4-decay-power-v1.0",
        "written_before_phase8_read": True,
        "phase8": {
            "sessions": PHASE8_SESSIONS,
            "window_midpoint": PHASE8_MIDPOINT.isoformat(),
            "frozen_method_hash": "87c818be",
            "primary_model_family": "hist_gradient_boosting (tree family)",
            "equivalence_bound": EQUIVALENCE_BOUND,
        },
        "inputs": {
            name: {"path": str(spec["path"]), "sha256": _sha256(Path(spec["path"]))}
            for name, spec in CAMPAIGNS.items()
        },
        "models": {},
    }
    for role in (GAMMA, LGBM):
        daily = _daily_series(role)
        recent = daily.filter(pl.col("campaign").is_in(["C4c_replication", "C6_b1v3"]))
        recent_sd = float(recent["mean_difference"].to_numpy().std(ddof=1))
        trend = _trend(daily)
        predicted = float(trend["phase8_midpoint_prediction"])
        results["models"][role] = {
            "pooled_days": daily.height,
            "trend": trend,
            "meta_regression": _meta_regression(daily),
            "recent_daily_sd": recent_sd,
            "power_at_predicted_effect": _power(recent_sd, max(predicted, 0.0)),
            "power_at_equivalence_bound": _power(recent_sd, EQUIVALENCE_BOUND),
            "achieved_mde_at_30_sessions": float(
                (stats.norm.ppf(0.975) + stats.norm.ppf(0.80))
                * recent_sd
                / math.sqrt(PHASE8_SESSIONS)
            ),
        }
    payload = json.dumps(results, indent=1, sort_keys=True, default=str)
    (OUTPUT / "results.json").write_text(payload, encoding="utf-8")
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    (OUTPUT / "results.sha256").write_text(digest + "\n", encoding="utf-8")
    for role in (GAMMA, LGBM):
        model = results["models"][role]
        print(
            f"[gate4] {role}: slope={model['trend']['slope_per_year']:+.4f}/yr "
            f"(wild p={model['trend']['slope_wild_p']:.4g}) "
            f"pred@phase8={model['trend']['phase8_midpoint_prediction']:+.5f} "
            f"CI={model['trend']['phase8_midpoint_prediction_ci95']} "
            f"MDE@30={model['achieved_mde_at_30_sessions']:.5f}"
        )
    print(f"[gate4] wrote {OUTPUT / 'results.json'} sha256={digest[:16]}")


if __name__ == "__main__":
    main()
