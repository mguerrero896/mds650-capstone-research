"""Gate 3: HAR intraday + HARQ ladder, development data only.

Pre-stated design:
- Features from the Gate 3 FMP bar acquisition; bar-label convention chosen by
  correlation of the reconstructed 30-minute RV against the frozen panel's
  ``b0_rv_30m_lag`` (shift 0 vs +1 minute — empirical A001 evidence, reported).
- Ladder: HAR, HARQ, HAR+B2, HARQ+B2 fitted by log-OLS with smearing on the
  common-complete development origins; expanding walk-forward (train on all
  sessions before each 10-session test block, first 30 sessions warm-up only).
- Winner rule (prespecified): lower pooled OOF QLIKE between HAR and HARQ
  becomes the preregistered base model of the prospective protocol (Gate 4).
- The B2 increment on the new baseline is HAR(Q) vs HAR(Q)+B2, evaluated with
  the Gate 1 studentized machinery. Development-only; no sealed reads.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from mds650 import har, inference
from mds650.metrics import qlike_losses

REPO = Path(__file__).resolve().parents[1]
DATA_ROOT = Path(os.environ.get("MDS650_EXTERNAL_ROOT", "D:/MDS650"))
BARS = DATA_ROOT / "data" / "fmp" / "gate3" / "underlying_1min_dev80.parquet"
PANEL = REPO / "artifacts" / "phase5" / "common_development_80d.parquet"
OUTPUT = REPO / "artifacts" / "gate3_har"

B2_FEATURES = [
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
WARMUP_SESSIONS = 30
TEST_BLOCK = 10


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _design(frame: pl.DataFrame, columns: list[str]) -> Any:
    matrix = frame.select(columns).to_numpy().astype(np.float64)
    return np.column_stack([np.ones(matrix.shape[0]), matrix])


def _evaluate_ladder(features: pl.DataFrame) -> tuple[pl.DataFrame, dict[str, Any]]:
    specs = {
        "har": list(har.HAR_COLUMNS),
        "harq": [*har.HAR_COLUMNS, har.HARQ_COLUMN],
        "har_b2": [*har.HAR_COLUMNS, *B2_FEATURES],
        "harq_b2": [*har.HAR_COLUMNS, har.HARQ_COLUMN, *B2_FEATURES],
    }
    sessions = sorted(features["session_date"].unique().to_list())
    folds: list[tuple[list[str], list[str]]] = []
    start = WARMUP_SESSIONS
    while start < len(sessions):
        test_block = sessions[start : start + TEST_BLOCK]
        folds.append(([str(s) for s in sessions[:start]], [str(s) for s in test_block]))
        start += TEST_BLOCK
    rows: list[pl.DataFrame] = []
    fold_summary: list[dict[str, float | int]] = []
    for train_sessions, test_sessions in folds:
        train_frame = features.filter(
            pl.col("session_date").cast(pl.Utf8).is_in(train_sessions)
        )
        test_frame = features.filter(
            pl.col("session_date").cast(pl.Utf8).is_in(test_sessions)
        )
        if train_frame.is_empty() or test_frame.is_empty():
            continue
        log_target = np.log(train_frame["rv30"].to_numpy().astype(np.float64))
        fold_entry: dict[str, float | int] = {
            "test_sessions": len(test_sessions),
            "train_rows": train_frame.height,
        }
        for name, columns in specs.items():
            fit = har.fit_log_ols(_design(train_frame, columns), log_target)
            forecast = har.predict_level(
                _design(test_frame, columns),
                np.asarray(fit["coefficients"]),
                float(fit["sigma2"]),
            )
            losses = qlike_losses(test_frame["rv30"].to_numpy().astype(np.float64), forecast)
            rows.append(
                test_frame.select("origin_id", "asset", "session_date").with_columns(
                    pl.lit(name).alias("model_role"),
                    pl.Series("qlike_loss", losses),
                )
            )
            fold_entry[f"{name}_qlike"] = float(losses.mean())
        fold_summary.append(fold_entry)
    return pl.concat(rows), {"folds": fold_summary}


def _contrast(oof: pl.DataFrame, base: str, expanded: str) -> dict[str, Any]:
    keys = ["origin_id", "asset", "session_date"]
    paired = (
        oof.filter(pl.col("model_role") == base)
        .select(*keys, pl.col("qlike_loss").alias("base_loss"))
        .join(
            oof.filter(pl.col("model_role") == expanded).select(
                *keys, pl.col("qlike_loss").alias("expanded_loss")
            ),
            on=keys,
            how="inner",
        )
        .with_columns((pl.col("base_loss") - pl.col("expanded_loss")).alias("difference"))
        .group_by("session_date")
        .agg(pl.col("difference").mean().alias("mean_difference"))
        .sort("session_date")
    )
    values = paired["mean_difference"].to_numpy()
    return {
        "cluster_t": inference.cluster_t_test(values),
        "newey_west": inference.newey_west_t_test(values),
        "wild_rademacher": inference.wild_cluster_bootstrap(values),
        "days": int(values.size),
    }


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    panel = pl.read_parquet(PANEL).filter(pl.col("common_complete"))
    bars = pl.read_parquet(BARS)
    origins = panel.select(
        "origin_id", "asset", "session_date", "forecast_origin_utc", "rv30", "b0_rv_30m_lag"
    ).with_columns(pl.col("session_date").cast(pl.Date))
    convention: dict[str, Any] = {}
    chosen_shift = 0
    best = -2.0
    for shift in (0, 1):
        candidate = har.build_har_features(
            bars, origins, label_shift_minutes=shift
        ).join(
            origins.select("origin_id", "b0_rv_30m_lag"), on="origin_id", how="inner"
        )
        correlation = float(
            np.corrcoef(
                np.log(candidate["rv_30m"].to_numpy()),
                np.log(np.maximum(candidate["b0_rv_30m_lag"].to_numpy(), 1e-12)),
            )[0, 1]
        )
        convention[f"shift_{shift}_log_corr_vs_b0_rv_30m_lag"] = correlation
        if correlation > best:
            best = correlation
            chosen_shift = shift
    convention["chosen_shift_minutes"] = chosen_shift
    features = har.build_har_features(bars, origins, label_shift_minutes=chosen_shift).join(
        panel.select("origin_id", "rv30", *B2_FEATURES), on="origin_id", how="inner"
    )
    oof, fold_info = _evaluate_ladder(features)
    pooled = {
        name: float(
            oof.filter(pl.col("model_role") == name)["qlike_loss"].to_numpy().mean()
        )
        for name in ("har", "harq", "har_b2", "harq_b2")
    }
    winner = "har" if pooled["har"] <= pooled["harq"] else "harq"
    results: dict[str, Any] = {
        "schema_version": "gate3-har-v1.0",
        "inputs": {
            "bars": {"path": str(BARS), "sha256": _sha256(BARS)},
            "panel": {"path": str(PANEL), "sha256": _sha256(PANEL)},
        },
        "label_convention": convention,
        "feature_rows": features.height,
        "feature_sessions": features["session_date"].n_unique(),
        "walk_forward": fold_info,
        "pooled_oof_qlike": pooled,
        "prespecified_winner_rule": "lower pooled OOF QLIKE between har and harq",
        "winner_base_model": winner,
        "contrasts": {
            "harq_vs_har": _contrast(oof, "har", "harq"),
            "har_vs_har_b2": _contrast(oof, "har", "har_b2"),
            "harq_vs_harq_b2": _contrast(oof, "harq", "harq_b2"),
        },
    }
    oof.write_parquet(OUTPUT / "oof_forecasts.parquet")
    payload = json.dumps(results, indent=1, sort_keys=True, default=str)
    (OUTPUT / "results.json").write_text(payload, encoding="utf-8")
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    (OUTPUT / "results.sha256").write_text(digest + "\n", encoding="utf-8")
    print(f"[gate3] winner={winner} pooled={pooled}")
    print(f"[gate3] wrote {OUTPUT / 'results.json'} sha256={digest[:16]}")


if __name__ == "__main__":
    main()
