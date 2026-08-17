"""Gate 11 (decision 56b): era-information map 2024→2026.

Re-analyzes the four frozen feature panels with one fixed, prespecified ladder
per era: three model families (log-OLS, Ridge on log target, LightGBM on log
target; fixed hyperparameters, no tuning) over nested feature sets B0,
B0+B1, B0+B1+B2, evaluated with within-era expanding walk-forward (warm-up 40%
of sessions, 10-session test blocks) and studentized daily inference. Output:
the option-information content curve by era x family x contrast.
Label: EXPLORATORY_DESCRIPTIVE. Era feature definitions differ (stated);
within-era increments are internally consistent, and the cross-era object is
the increment, never the level.
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
from sklearn.linear_model import Ridge  # type: ignore[import-untyped]
from sklearn.preprocessing import StandardScaler  # type: ignore[import-untyped]

from mds650 import har, inference

REPO = Path(__file__).resolve().parents[1]
DATA_ROOT = Path(os.environ.get("MDS650_EXTERNAL_ROOT", "D:/MDS650"))
EVIDENCE_ROOT = Path(os.environ.get("MDS650_EVIDENCE_ROOT", DATA_ROOT / "evidence_root"))
OUTPUT = REPO / "artifacts" / "gate11_era_map"
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
    "b1v2_term_short_to_medium",
    "b1v2_atm_iv_change_5m",
    "b1v2_atm_iv_change_30m",
]
B1V3 = [
    "b1v3_log_atm_variance_30d",
    "b1v3_log_symmetric_skew_30d",
    "b1v3_log_forward_variance_short_medium",
    "b1v3_log_atm_variance_change_5m",
    "b1v3_log_atm_variance_change_30m",
]
B2_RAWNAME = [
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
B2_V2NAME = [
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
        "b2": B2_RAWNAME,
        "log_b0_rv": True,
    },
    "era_2025H1_c4cpanel": {
        "path": DATA_ROOT
        / "independent_replication_30"
        / "derived"
        / "pit_v2_evaluation"
        / "common_complete_90d_pit_v2.parquet",
        "b0": B0V2,
        "b1": B1V2,
        "b2": B2_V2NAME,
        "log_b0_rv": True,
    },
    "era_2025H2_2026Q1_p6panel": {
        "path": EVIDENCE_ROOT / "artifacts" / "phase6" / "common_panel.parquet",
        "b0": B0V2,
        "b1": B1V2,
        "b2": B2_V2NAME,
        "log_b0_rv": True,
    },
    "era_2026H1_devpanel": {
        "path": REPO / "artifacts" / "phase5" / "common_development_80d.parquet",
        "b0": ["b0_rv_5m_lag", "b0_rv_30m_lag", "b0_return_5m_lag", "b0_session_minute"],
        "b1": ["b1q_atm_iv"],
        "b2": B2_RAWNAME,
        "log_b0_rv": False,
        "complete_column": "common_complete",
        "log_columns": ["b0_rv_5m_lag", "b0_rv_30m_lag", "b1q_atm_iv"],
    },
}


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
    missing = [c for c in columns if c not in frame.columns]
    if missing:
        raise ValueError(f"GATE11_PANEL_COLUMNS_MISSING:{missing}")
    fully_null = [
        c for c in columns if c != "session_date" and frame[c].null_count() == frame.height
    ]
    if fully_null:
        # Reported, never silent: a feature absent from a panel era is excluded
        # from that era's ladder rather than emptying the panel via drop_nulls.
        spec["excluded_fully_null"] = fully_null
        for key in ("b0", "b1", "b2"):
            spec[key] = [c for c in spec[key] if c not in fully_null]
        columns = [c for c in columns if c not in fully_null]
    frame = (
        frame.select(columns)
        .with_columns(pl.col("session_date").cast(pl.Date).cast(pl.Utf8))
        .drop_nulls()
    )
    if spec.get("log_b0_rv"):
        frame = frame.with_columns(
            [
                pl.col(c).clip(lower_bound=FLOOR).log()
                for c in spec["b0"]
                if "rv" in c
            ]
        )
    for column in spec.get("log_columns", []):
        frame = frame.with_columns(pl.col(column).clip(lower_bound=FLOOR).log())
    return frame.filter(pl.col("rv30") > 0)


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
    if family == "ridge":
        scaler = StandardScaler().fit(x_train)
        model = Ridge(alpha=1.0).fit(scaler.transform(x_train), y_train)
        residuals = y_train - np.asarray(model.predict(scaler.transform(x_train)))
        sigma2 = float(residuals @ residuals / max(1, y_train.size - x_train.shape[1] - 1))
        prediction = np.asarray(model.predict(scaler.transform(x_test)), dtype=np.float64)
        return np.exp(prediction + sigma2 / 2.0)
    if family == "lightgbm":
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
    raise ValueError(f"GATE11_FAMILY_UNKNOWN:{family}")


def _qlike(actual: np.ndarray, forecast: np.ndarray) -> np.ndarray:
    ratio = actual / np.maximum(forecast, FLOOR)
    return np.asarray(ratio - np.log(ratio) - 1.0, dtype=np.float64)


def _era(spec: dict[str, Any]) -> dict[str, Any]:
    frame = _prepare(spec)
    sessions = sorted(str(s) for s in frame["session_date"].unique().to_list())
    warmup = max(10, math.ceil(len(sessions) * 0.4))
    ladders = {
        "B0": list(spec["b0"]),
        "B1": [*spec["b0"], *spec["b1"]],
        "B2": [*spec["b0"], *spec["b1"], *spec["b2"]],
    }
    rows: list[pl.DataFrame] = []
    start = warmup
    while start < len(sessions):
        train = frame.filter(pl.col("session_date").cast(pl.Utf8).is_in(sessions[:start]))
        test = frame.filter(
            pl.col("session_date").cast(pl.Utf8).is_in(sessions[start : start + 10])
        )
        start += 10
        if train.is_empty() or test.is_empty():
            continue
        actual = test["rv30"].to_numpy().astype(np.float64)
        for family in ("log_ols", "ridge", "lightgbm"):
            for ladder_name, columns in ladders.items():
                forecast = _fit_predict(family, train, test, columns)
                rows.append(
                    test.select("origin_id", "asset", "session_date").with_columns(
                        pl.lit(family).alias("family"),
                        pl.lit(ladder_name).alias("ladder"),
                        pl.Series("qlike_loss", _qlike(actual, forecast)),
                    )
                )
    oof = pl.concat(rows)
    entry: dict[str, Any] = {
        "sessions": len(sessions),
        "first_session": sessions[0],
        "last_session": sessions[-1],
        "oof_rows": oof.height,
        "warmup_sessions": warmup,
        "excluded_fully_null_features": spec.get("excluded_fully_null", []),
        "contrasts": {},
    }
    for family in ("log_ols", "ridge", "lightgbm"):
        family_oof = oof.filter(pl.col("family") == family)
        for base, expanded, name in (
            ("B0", "B1", "B0->B1"),
            ("B1", "B2", "B1->B2"),
            ("B0", "B2", "B0->B2_total"),
        ):
            daily = inference.paired_daily_differences(
                family_oof,
                base_set=base,
                expanded_set=expanded,
                model=family,
                model_column="family",
                set_column="ladder",
            )
            values = daily["mean_difference"].to_numpy()
            stats: dict[str, Any] = dict(inference.cluster_t_test(values))
            stats["p_wild"] = inference.wild_cluster_bootstrap(values)["p_value"]
            entry["contrasts"][f"{family}|{name}"] = stats
    return entry


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    results: dict[str, Any] = {
        "schema_version": "gate11-era-map-v1.0",
        "label": "EXPLORATORY_DESCRIPTIVE (decision 56b)",
        "design": "3 fixed families x nested B0/B1/B2, within-era walk-forward 40%/10",
        "eras": {},
        "inputs": {
            name: {"path": str(spec["path"]), "sha256": _sha256(Path(spec["path"]))}
            for name, spec in ERAS.items()
        },
    }
    for name, spec in ERAS.items():
        print(f"[gate11] {name}")
        results["eras"][name] = _era(spec)
    payload = json.dumps(results, indent=1, sort_keys=True, default=str)
    (OUTPUT / "results.json").write_text(payload, encoding="utf-8")
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    (OUTPUT / "results.sha256").write_text(digest + "\n", encoding="utf-8")
    print(f"[gate11] wrote {OUTPUT / 'results.json'} sha256={digest[:16]}")


if __name__ == "__main__":
    main()
