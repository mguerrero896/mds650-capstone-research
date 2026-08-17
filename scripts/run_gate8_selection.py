"""Gate 8: common-complete selection bias on the binding C6 sample.

Every registered contrast — including B0-vs-B1, which needs no B2 data — is
estimated only on origins where all three information sets are simultaneously
complete. This gate reconstructs the nominal origin grid (sessions x assets x
the union of grid times observed in the frozen forecasts), attaches
target-blind covariates from independently downloaded bars (lagged 30-minute
RV, session minute), fits a logistic inclusion model for
P(common_complete | covariates), and re-estimates the frozen contrasts with
stabilized inverse-probability weights. If IPW moves an estimate materially,
the unweighted number is conditioned on the three-provider join, not on the
market. C6 only (its bars are on disk from Gate 7); C4c deferred explicitly.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
from sklearn.linear_model import LogisticRegression  # type: ignore[import-untyped]

from mds650 import inference

REPO = Path(__file__).resolve().parents[1]
DATA_ROOT = Path(os.environ.get("MDS650_EXTERNAL_ROOT", "D:/MDS650"))
FORECASTS = DATA_ROOT / "b1v3_confirmation" / "evaluation" / "primary_forecasts.parquet"
BARS = DATA_ROOT / "data" / "fmp" / "gate7" / "underlying_1min_c6.parquet"
OUTPUT = REPO / "artifacts" / "gate8_selection"
GAMMA = "gamma_glm_confirmatory"
LGBM = "lightgbm_robustness"
WEIGHT_CLIP = 20.0


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _grid(forecasts: pl.DataFrame) -> pl.DataFrame:
    origins = forecasts.select(
        "origin_id", "asset", "session_date", "forecast_origin_utc"
    ).unique(subset=["origin_id"])
    times = (
        origins.with_columns(
            pl.col("forecast_origin_utc")
            .dt.convert_time_zone("America/New_York")
            .dt.time()
            .alias("grid_time")
        )["grid_time"]
        .unique()
        .sort()
    )
    sessions = origins["session_date"].unique().sort()
    assets = origins["asset"].unique().sort()
    grid = (
        pl.DataFrame({"session_date": sessions})
        .join(pl.DataFrame({"asset": assets}), how="cross")
        .join(pl.DataFrame({"grid_time": times}), how="cross")
        .with_columns(
            pl.col("session_date")
            .cast(pl.Date)
            .dt.combine(pl.col("grid_time"))
            .dt.replace_time_zone("America/New_York")
            .dt.convert_time_zone("UTC")
            .alias("forecast_origin_utc")
        )
    )
    included = origins.select(
        "asset", "session_date", "forecast_origin_utc", pl.lit(1).alias("included")
    )
    return grid.join(
        included, on=["asset", "session_date", "forecast_origin_utc"], how="left"
    ).with_columns(pl.col("included").fill_null(0))


def _covariates(grid: pl.DataFrame, bars: pl.DataFrame) -> pl.DataFrame:
    returns = (
        bars.sort("asset", "bar_start_utc")
        .with_columns(pl.col("bar_start_utc").dt.date().alias("bar_session"))
        .with_columns(
            (pl.col("close") / pl.col("close").shift(1).over("asset", "bar_session"))
            .log()
            .alias("log_return")
        )
        .drop_nulls("log_return")
        .with_columns((pl.col("log_return") ** 2).alias("squared"))
    )
    keyed = grid.with_columns(pl.col("session_date").cast(pl.Date).alias("bar_session"))
    window_start = pl.col("forecast_origin_utc").dt.offset_by("-30m")
    features = (
        returns.join(keyed, on=["asset", "bar_session"], how="inner")
        .filter(
            (pl.col("bar_start_utc") < pl.col("forecast_origin_utc"))
            & (pl.col("bar_start_utc") >= window_start)
        )
        .group_by("asset", "session_date", "forecast_origin_utc")
        .agg(pl.col("squared").sum().alias("rv_30m_lag"), pl.len().alias("window_bars"))
    )
    return (
        grid.join(features, on=["asset", "session_date", "forecast_origin_utc"], how="left")
        .with_columns(
            pl.col("rv_30m_lag").fill_null(1e-12).clip(lower_bound=1e-12),
            pl.col("window_bars").fill_null(0),
            (
                pl.col("forecast_origin_utc")
                .dt.convert_time_zone("America/New_York")
                .dt.hour()
                * 60
                + pl.col("forecast_origin_utc")
                .dt.convert_time_zone("America/New_York")
                .dt.minute()
                - 570
            ).alias("session_minute"),
        )
        .with_columns(pl.col("rv_30m_lag").log().alias("log_rv_30m_lag"))
    )


def _fit_inclusion(frame: pl.DataFrame) -> tuple[pl.DataFrame, dict[str, Any]]:
    assets = sorted(frame["asset"].unique().to_list())
    design_columns = ["session_minute", "log_rv_30m_lag"]
    matrix = [frame[column].to_numpy().astype(np.float64) for column in design_columns]
    for asset in assets[1:]:
        matrix.append((frame["asset"] == asset).to_numpy().astype(np.float64))
    design = np.column_stack(matrix)
    included = frame["included"].to_numpy().astype(int)
    model = LogisticRegression(max_iter=2000)
    model.fit(design, included)
    probability = model.predict_proba(design)[:, 1]
    marginal = float(included.mean())
    weights = np.clip(marginal / np.maximum(probability, 1e-6), 0.0, WEIGHT_CLIP)
    scored = frame.with_columns(
        pl.Series("inclusion_probability", probability),
        pl.Series("ipw_weight", weights),
    )
    summary = {
        "marginal_inclusion": marginal,
        "auc_proxy_mean_p_included": float(probability[included == 1].mean()),
        "auc_proxy_mean_p_excluded": float(probability[included == 0].mean()),
        "probability_p1": float(np.quantile(probability, 0.01)),
        "probability_p99": float(np.quantile(probability, 0.99)),
        "weight_max": float(weights[included == 1].max()),
        "coefficients": {
            name: float(value)
            for name, value in zip(
                design_columns + [f"asset_{asset}" for asset in assets[1:]],
                model.coef_[0],
                strict=True,
            )
        },
    }
    return scored, summary


def _weighted_contrast(
    forecasts: pl.DataFrame,
    weights: pl.DataFrame,
    model: str,
    base: str,
    expanded: str,
) -> dict[str, Any]:
    keys = ["origin_id", "asset", "session_date"]
    sides = {
        label: forecasts.filter(
            (pl.col("model_role") == model) & (pl.col("information_set") == label)
        ).select(*keys, pl.col("qlike_loss").alias(f"loss_{label}"))
        for label in (base, expanded)
    }
    paired = (
        sides[base]
        .join(sides[expanded], on=keys, how="inner")
        .join(
            weights.select(*keys[1:], "forecast_origin_utc", "ipw_weight"),
            on=keys[1:],
            how="inner",
        )
        .with_columns((pl.col(f"loss_{base}") - pl.col(f"loss_{expanded}")).alias("difference"))
    )
    daily = (
        paired.group_by("session_date")
        .agg(
            (pl.col("difference") * pl.col("ipw_weight")).sum().alias("weighted_sum"),
            pl.col("ipw_weight").sum().alias("weight_sum"),
            pl.col("difference").mean().alias("unweighted_mean"),
        )
        .with_columns((pl.col("weighted_sum") / pl.col("weight_sum")).alias("weighted_mean"))
        .sort("session_date")
    )
    return {
        "unweighted": inference.cluster_t_test(daily["unweighted_mean"].to_numpy()),
        "ipw_weighted": inference.cluster_t_test(daily["weighted_mean"].to_numpy()),
        "ipw_wild": inference.wild_cluster_bootstrap(daily["weighted_mean"].to_numpy()),
    }


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    forecasts = pl.read_parquet(FORECASTS)
    bars = pl.read_parquet(BARS)
    grid = _grid(forecasts)
    covariates = _covariates(grid, bars)
    scored, summary = _fit_inclusion(covariates)
    weights = (
        scored.filter(pl.col("included") == 1)
        .with_columns(pl.col("session_date").cast(pl.Utf8))
        .select("asset", "session_date", "forecast_origin_utc", "ipw_weight")
    )
    forecasts_keyed = forecasts.with_columns(pl.col("session_date").cast(pl.Utf8))
    results: dict[str, Any] = {
        "schema_version": "gate8-selection-v1.0",
        "inputs": {
            "forecasts_sha256": _sha256(FORECASTS),
            "bars_sha256": _sha256(BARS),
        },
        "grid_origins": grid.height,
        "included_origins": int(grid["included"].sum()),
        "inclusion_model": summary,
        "contrasts": {},
        "deferred": {"C4c": "bars for its sessions not on local disk; same design applies"},
    }
    for model in (GAMMA, LGBM):
        results["contrasts"][model] = {
            "B1v3a_vs_B0": _weighted_contrast(forecasts_keyed, weights, model, "B1v3a", "B0"),
            "B2_vs_B1v3a": _weighted_contrast(forecasts_keyed, weights, model, "B1v3a", "B2"),
        }
    payload = json.dumps(results, indent=1, sort_keys=True, default=str)
    (OUTPUT / "results.json").write_text(payload, encoding="utf-8")
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    (OUTPUT / "results.sha256").write_text(digest + "\n", encoding="utf-8")
    print(
        f"[gate8] inclusion={results['included_origins']}/{results['grid_origins']}"
        f" marginal={summary['marginal_inclusion']:.3f}"
    )
    print(f"[gate8] wrote {OUTPUT / 'results.json'} sha256={digest[:16]}")


if __name__ == "__main__":
    main()
