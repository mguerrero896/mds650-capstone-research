"""Gate 12: does the option-state positive survive HAR-class baselines?

Hardening test demanded by the 2026-08-18 investigation: the decision-56
positive (option information helps, mostly via option state) was never tested
against the one baseline family that killed B2 in Gate 3. Two designs:

A. All four era panels, panel-only HAR augmentation (target-blind daily and
   weekly RV components derived from each panel's own lagged 5-minute RVs):
   ladder B0+HAR vs B0+HAR+B1 vs B0+HAR+B2, families log-OLS and LightGBM
   (Ridge dropped: numerically duplicates log-OLS).
B. Development era, true HARQ from 1-minute bars (Gate 3 machinery):
   HARQ vs HARQ+B1 vs HARQ+B2.

Label: EXPLORATORY_DESCRIPTIVE (decision 56 follow-up). Signs reported exactly
as computed, per the citation rule in docs/positive_findings_v1.md.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
from lightgbm import LGBMRegressor

from mds650 import har, inference

REPO = Path(__file__).resolve().parents[1]
DATA_ROOT = Path(os.environ.get("MDS650_EXTERNAL_ROOT", "D:/MDS650"))
EVIDENCE_ROOT = Path(os.environ.get("MDS650_EVIDENCE_ROOT", DATA_ROOT / "evidence_root"))
OUTPUT = REPO / "artifacts" / "gate12_harq_hardening"
FLOOR = 1e-12

B0V2 = [
    "b0v2_underlying_rv_5m",
    "b0v2_underlying_rv_30m",
    "b0v2_spy_rv_30m",
    "b0v2_qqq_rv_30m",
    "session_minute",
]
B1V2 = [
    "b1v2_atm_iv_30_60_dte",
    "b1v2_skew_symmetric_moneyness",
    "b1v2_atm_iv_change_5m",
    "b1v2_atm_iv_change_30m",
]
B1V3 = [
    "b1v3_log_atm_variance_30d",
    "b1v3_log_symmetric_skew_30d",
    "b1v3_log_atm_variance_change_5m",
    "b1v3_log_atm_variance_change_30m",
]
B2_RAW = [
    "b2_log_trade_count",
    "b2_unique_contract_share",
    "b2_log_mean_trade_premium",
    "b2_log_max_trade_premium",
    "b2_call_put_premium_imbalance_scaled",
    "b2_execution_side_premium_imbalance",
    "b2_repeated_contract_premium_share",
    "b2_strike_concentration",
    "b2_expiry_concentration",
]
B2_V2 = [
    "b2v2_z_log_trade_count",
    "b2v2_z_unique_contract_share",
    "b2v2_z_log_mean_trade_premium",
    "b2v2_z_log_max_trade_premium",
    "b2v2_deviation_call_put_premium_imbalance",
    "b2v2_deviation_execution_side_premium_imbalance",
    "b2v2_z_repeated_contract_premium_share",
    "b2v2_z_strike_concentration",
    "b2v2_z_expiry_concentration",
]

ERAS: dict[str, dict[str, Any]] = {
    "era_2024H2_c6panel": {
        "path": DATA_ROOT / "b1v3_confirmation" / "evaluation" / "evaluation_panel.parquet",
        "b0": B0V2,
        "b1": B1V3,
        "b2": B2_RAW,
        "rv5_column": "b0v2_underlying_rv_5m",
    },
    "era_2025H1_c4cpanel": {
        "path": DATA_ROOT
        / "independent_replication_30"
        / "derived"
        / "pit_v2_evaluation"
        / "common_complete_90d_pit_v2.parquet",
        "b0": B0V2,
        "b1": B1V2,
        "b2": B2_V2,
        "rv5_column": "b0v2_underlying_rv_5m",
    },
    "era_2025H2_2026Q1_p6panel": {
        "path": EVIDENCE_ROOT / "artifacts" / "phase6" / "common_panel.parquet",
        "b0": B0V2,
        "b1": B1V2,
        "b2": B2_V2,
        "rv5_column": "b0v2_underlying_rv_5m",
    },
    "era_2026H1_devpanel": {
        "path": REPO / "artifacts" / "phase5" / "common_development_80d.parquet",
        "b0": ["b0_rv_5m_lag", "b0_rv_30m_lag", "b0_return_5m_lag", "b0_session_minute"],
        "b1": ["b1q_atm_iv"],
        "b2": B2_RAW,
        "rv5_column": "b0_rv_5m_lag",
        "complete_column": "common_complete",
        "log_columns": ["b0_rv_5m_lag", "b0_rv_30m_lag", "b1q_atm_iv"],
    },
}
DEV_BARS = DATA_ROOT / "data" / "fmp" / "gate3" / "underlying_1min_dev80.parquet"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _prepare(spec: dict[str, Any]) -> pl.DataFrame:
    frame = pl.read_parquet(Path(spec["path"]))
    if "complete_column" in spec:
        frame = frame.filter(pl.col(spec["complete_column"]))
    columns = ["origin_id", "asset", "session_date", "rv30", *spec["b0"], *spec["b1"], *spec["b2"]]
    fully_null = [
        c
        for c in columns
        if c != "session_date" and c in frame.columns and frame[c].null_count() == frame.height
    ]
    for key in ("b0", "b1", "b2"):
        spec[key] = [c for c in spec[key] if c not in fully_null]
    columns = [c for c in columns if c not in fully_null and c in frame.columns]
    frame = (
        frame.select(columns)
        .with_columns(pl.col("session_date").cast(pl.Date).cast(pl.Utf8))
        .drop_nulls()
        .filter(pl.col("rv30") > 0)
    )
    rv5 = spec["rv5_column"]
    daily = (
        frame.group_by("asset", "session_date")
        .agg(pl.col(rv5).sum().alias("session_rv_proxy"))
        .sort("asset", "session_date")
        .with_columns(
            pl.col("session_rv_proxy").shift(1).over("asset").alias("har_rv_day"),
            pl.col("session_rv_proxy")
            .shift(1)
            .rolling_mean(5)
            .over("asset")
            .alias("har_rv_week"),
        )
        .drop("session_rv_proxy")
    )
    return (
        frame.join(daily, on=["asset", "session_date"], how="inner")
        .drop_nulls(["har_rv_day", "har_rv_week"])
        .with_columns(
            pl.col("har_rv_day").clip(lower_bound=FLOOR).log(),
            pl.col("har_rv_week").clip(lower_bound=FLOOR).log(),
            *[
                pl.col(c).clip(lower_bound=FLOOR).log()
                for c in spec.get("log_columns", [])
                if c in frame.columns
            ],
        )
    )


def _fit_predict(
    family: str, train: pl.DataFrame, test: pl.DataFrame, columns: list[str]
) -> np.ndarray:
    x_train = train.select(columns).to_numpy().astype(np.float64)
    x_test = test.select(columns).to_numpy().astype(np.float64)
    y_train = np.log(train["rv30"].to_numpy().astype(np.float64))
    medians = np.nanmedian(x_train, axis=0)
    x_train = np.where(np.isfinite(x_train), x_train, medians)
    x_test = np.where(np.isfinite(x_test), x_test, medians)
    if family == "log_ols":
        design = np.column_stack([np.ones(x_train.shape[0]), x_train])
        fit = har.fit_log_ols(design, y_train)
        return har.predict_level(
            np.column_stack([np.ones(x_test.shape[0]), x_test]),
            np.asarray(fit["coefficients"]),
            float(fit["sigma2"]),
        )
    model = LGBMRegressor(
        n_estimators=200,
        learning_rate=0.05,
        num_leaves=31,
        min_child_samples=20,
        verbosity=-1,
        random_state=650,
    ).fit(x_train, y_train)
    residuals = y_train - np.asarray(model.predict(x_train))
    sigma2 = float(residuals.var())
    prediction = np.asarray(model.predict(x_test), dtype=np.float64)
    return np.exp(prediction + sigma2 / 2.0)


def _qlike(actual: np.ndarray, forecast: np.ndarray) -> np.ndarray:
    ratio = actual / np.maximum(forecast, FLOOR)
    return np.asarray(ratio - np.log(ratio) - 1.0, dtype=np.float64)


def _walk(
    frame: pl.DataFrame, ladders: dict[str, list[str]], families: tuple[str, ...]
) -> pl.DataFrame:
    sessions = sorted(frame["session_date"].unique().to_list())
    warmup = max(10, math.ceil(len(sessions) * 0.4))
    rows: list[pl.DataFrame] = []
    start = warmup
    while start < len(sessions):
        train = frame.filter(pl.col("session_date").is_in(sessions[:start]))
        test = frame.filter(pl.col("session_date").is_in(sessions[start : start + 10]))
        start += 10
        if train.is_empty() or test.is_empty():
            continue
        actual = test["rv30"].to_numpy().astype(np.float64)
        for family in families:
            for ladder_name, columns in ladders.items():
                forecast = _fit_predict(family, train, test, columns)
                rows.append(
                    test.select("origin_id", "asset", "session_date").with_columns(
                        pl.lit(family).alias("family"),
                        pl.lit(ladder_name).alias("ladder"),
                        pl.Series("qlike_loss", _qlike(actual, forecast)),
                    )
                )
    return pl.concat(rows)


def _contrast(oof: pl.DataFrame, family: str, base: str, expanded: str) -> dict[str, Any]:
    daily = inference.paired_daily_differences(
        oof.filter(pl.col("family") == family),
        base_set=base,
        expanded_set=expanded,
        model=family,
        model_column="family",
        set_column="ladder",
    )
    values = daily["mean_difference"].to_numpy()
    entry: dict[str, Any] = dict(inference.cluster_t_test(values))
    entry["p_wild"] = inference.wild_cluster_bootstrap(values)["p_value"]
    return entry


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    results: dict[str, Any] = {
        "schema_version": "gate12-harq-hardening-v1.0",
        "label": "EXPLORATORY_DESCRIPTIVE (decision 56 follow-up)",
        "inputs": {
            name: {"path": str(spec["path"]), "sha256": _sha256(Path(spec["path"]))}
            for name, spec in ERAS.items()
        },
        "design_a_panel_har": {},
        "design_b_true_harq_dev": {},
    }
    for name, spec in ERAS.items():
        print(f"[gate12] A: {name}")
        frame = _prepare(spec)
        ladders = {
            "B0HAR": [*spec["b0"], "har_rv_day", "har_rv_week"],
            "B1": [*spec["b0"], "har_rv_day", "har_rv_week", *spec["b1"]],
            "B2": [*spec["b0"], "har_rv_day", "har_rv_week", *spec["b1"], *spec["b2"]],
        }
        oof = _walk(frame, ladders, ("log_ols", "lightgbm"))
        entry: dict[str, Any] = {"rows": frame.height}
        for family in ("log_ols", "lightgbm"):
            entry[family] = {
                "B0HAR->B1": _contrast(oof, family, "B0HAR", "B1"),
                "B1->B2": _contrast(oof, family, "B1", "B2"),
                "B0HAR->B2_total": _contrast(oof, family, "B0HAR", "B2"),
            }
        results["design_a_panel_har"][name] = entry
    print("[gate12] B: true HARQ (dev)")
    dev_spec = {
        "path": ERAS["era_2026H1_devpanel"]["path"],
        "b1": ["b1q_atm_iv"],
        "b2": B2_RAW,
    }
    panel = pl.read_parquet(Path(dev_spec["path"])).filter(pl.col("common_complete"))
    panel = panel.filter(pl.col("b1q_atm_iv").is_not_null()).with_columns(
        pl.col("b1q_atm_iv").clip(lower_bound=1e-6).log()
    )
    bars = pl.read_parquet(DEV_BARS)
    origins = panel.select("origin_id", "asset", "session_date", "forecast_origin_utc")
    features = har.build_har_features(bars, origins).join(
        panel.select("origin_id", "rv30", "b1q_atm_iv", *B2_RAW), on="origin_id", how="inner"
    ).with_columns(pl.col("session_date").cast(pl.Date).cast(pl.Utf8))
    harq_columns = [*har.HAR_COLUMNS, har.HARQ_COLUMN]
    ladders_b = {
        "HARQ": harq_columns,
        "B1": [*harq_columns, "b1q_atm_iv"],
        "B2": [*harq_columns, "b1q_atm_iv", *B2_RAW],
    }
    oof_b = _walk(features, ladders_b, ("log_ols",))
    results["design_b_true_harq_dev"] = {
        "rows": features.height,
        "log_ols": {
            "HARQ->B1": _contrast(oof_b, "log_ols", "HARQ", "B1"),
            "B1->B2": _contrast(oof_b, "log_ols", "B1", "B2"),
            "HARQ->B2_total": _contrast(oof_b, "log_ols", "HARQ", "B2"),
        },
    }
    payload = json.dumps(results, indent=1, sort_keys=True, default=str)
    (OUTPUT / "results.json").write_text(payload, encoding="utf-8")
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    (OUTPUT / "results.sha256").write_text(digest + "\n", encoding="utf-8")
    print(f"[gate12] wrote {OUTPUT / 'results.json'} sha256={digest[:16]}")


if __name__ == "__main__":
    main()
