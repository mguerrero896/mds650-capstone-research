"""LightGBM gain/split importances for the nine B2 features (Gate 2 debt).

Refits the frozen-configuration LightGBM on the C6 training half (60 sessions)
and the C4c panel's first half, over the full B2 feature ladder, and records
gain and split importances for the nine B2 features — documenting WHY the
calibrated challenger assigns the activity block no value. Re-analysis of
already-read panels; EXPLORATORY_DESCRIPTIVE.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
from lightgbm import LGBMRegressor

REPO = Path(__file__).resolve().parents[1]
DATA_ROOT = Path(os.environ.get("MDS650_EXTERNAL_ROOT", "D:/MDS650"))
OUTPUT = REPO / "artifacts" / "lgbm_importances"

PANELS: dict[str, dict[str, Any]] = {
    "C6": {
        "path": DATA_ROOT / "b1v3_confirmation" / "evaluation" / "evaluation_panel.parquet",
        "features": [
            "b0v2_underlying_rv_5m",
            "b0v2_underlying_rv_30m",
            "b0v2_spy_rv_30m",
            "b0v2_qqq_rv_30m",
            "session_minute",
            "b1v3_log_atm_variance_30d",
            "b1v3_log_symmetric_skew_30d",
            "b1v3_log_atm_variance_change_5m",
            "b1v3_log_atm_variance_change_30m",
            "b2_log_trade_count",
            "b2_unique_contract_share",
            "b2_log_mean_trade_premium",
            "b2_log_max_trade_premium",
            "b2_call_put_premium_imbalance_scaled",
            "b2_execution_side_premium_imbalance",
            "b2_repeated_contract_premium_share",
            "b2_strike_concentration",
            "b2_expiry_concentration",
        ],
        "b2_prefix": "b2_",
    },
    "C4c": {
        "path": DATA_ROOT
        / "independent_replication_30"
        / "derived"
        / "pit_v2_evaluation"
        / "common_complete_90d_pit_v2.parquet",
        "features": [
            "b0v2_underlying_rv_5m",
            "b0v2_underlying_rv_30m",
            "b0v2_spy_rv_30m",
            "b0v2_qqq_rv_30m",
            "session_minute",
            "b1v2_atm_iv_30_60_dte",
            "b1v2_skew_symmetric_moneyness",
            "b1v2_atm_iv_change_5m",
            "b1v2_atm_iv_change_30m",
            "b2v2_z_log_trade_count",
            "b2v2_z_unique_contract_share",
            "b2v2_z_log_mean_trade_premium",
            "b2v2_z_log_max_trade_premium",
            "b2v2_deviation_call_put_premium_imbalance",
            "b2v2_deviation_execution_side_premium_imbalance",
            "b2v2_z_repeated_contract_premium_share",
            "b2v2_z_strike_concentration",
            "b2v2_z_expiry_concentration",
        ],
        "b2_prefix": "b2v2_",
    },
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    results: dict[str, Any] = {
        "schema_version": "lgbm-importances-v1.0",
        "label": "EXPLORATORY_DESCRIPTIVE (Gate 2 deferred deliverable)",
        "panels": {},
    }
    for name, spec in PANELS.items():
        frame = pl.read_parquet(Path(spec["path"]))
        features: list[str] = [c for c in spec["features"] if c in frame.columns]
        frame = frame.select("session_date", "rv30", *features).drop_nulls()
        sessions = sorted(frame["session_date"].cast(pl.Date).cast(pl.Utf8).unique().to_list())
        train_sessions = sessions[: len(sessions) // 2 or 1]
        train = frame.filter(
            pl.col("session_date").cast(pl.Date).cast(pl.Utf8).is_in(train_sessions)
        )
        x_train = train.select(features).to_numpy().astype(np.float64)
        y_train = np.log(np.maximum(train["rv30"].to_numpy().astype(np.float64), 1e-12))
        model = LGBMRegressor(
            n_estimators=200,
            learning_rate=0.05,
            num_leaves=31,
            min_child_samples=20,
            verbosity=-1,
            random_state=650,
        ).fit(x_train, y_train)
        gains = model.booster_.feature_importance(importance_type="gain")
        splits = model.booster_.feature_importance(importance_type="split")
        total_gain = float(gains.sum()) or 1.0
        rows: list[dict[str, Any]] = [
            {
                "feature": feature,
                "gain_share_pct": 100.0 * float(gain) / total_gain,
                "splits": int(split),
            }
            for feature, gain, split in zip(features, gains, splits, strict=True)
        ]
        table = sorted(rows, key=lambda row: -float(str(row["gain_share_pct"])))
        b2_share = sum(
            float(str(row["gain_share_pct"]))
            for row in table
            if str(row["feature"]).startswith(str(spec["b2_prefix"]))
        )
        results["panels"][name] = {
            "input_sha256": _sha256(Path(spec["path"])),
            "train_sessions": len(train_sessions),
            "importances": table,
            "b2_total_gain_share_pct": b2_share,
        }
        print(f"[lgbm-imp] {name}: B2 block gain share = {b2_share:.2f}%")
    payload = json.dumps(results, indent=1, sort_keys=True)
    (OUTPUT / "results.json").write_text(payload, encoding="utf-8")
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    (OUTPUT / "results.sha256").write_text(digest + "\n", encoding="utf-8")
    print(f"[lgbm-imp] wrote {OUTPUT / 'results.json'} sha256={digest[:16]}")


if __name__ == "__main__":
    main()
