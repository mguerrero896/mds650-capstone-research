"""Gate 9: signal localization — ablation, earnings conditioning, horizons.

Exploratory, development-data-only (plus stratification of already-read frozen
daily differentials). Three questions:

9.1 WHERE does the B2 gain live? Grouped ablation of the nine B2 features
    (volume / premium size / direction-concentration) under a smooth-family
    log-OLS pipeline (proxy for the Gamma lineage; stated) with the same
    walk-forward as Gate 3.
9.2 WHEN does it live? Earnings-proximity stratification (sessions t−1, t,
    t+1 vs others) of the frozen C6 and C4c Gamma differentials, using
    date-only FMP earnings dates (target-blind).
9.3 AT WHAT HORIZON? RV15 / RV30 / RV60 term structure of the B2 increment on
    the HARQ baseline, development sessions only.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from mds650 import har, inference
from mds650.metrics import qlike_losses
from mds650.providers.fmp import FMPProvider, parse_earnings_payload

REPO = Path(__file__).resolve().parents[1]
DATA_ROOT = Path(os.environ.get("MDS650_EXTERNAL_ROOT", "D:/MDS650"))
PANEL = REPO / "artifacts" / "phase5" / "common_development_80d.parquet"
DEV_BARS = DATA_ROOT / "data" / "fmp" / "gate3" / "underlying_1min_dev80.parquet"
C6_FORECASTS = DATA_ROOT / "b1v3_confirmation" / "evaluation" / "primary_forecasts.parquet"
C4C_FORECASTS = (
    DATA_ROOT / "independent_replication_30" / "derived" / "pit_v2_evaluation"
    / "predictions_pit_v2.parquet"
)
OUTPUT = REPO / "artifacts" / "gate9_localization"
ASSETS = ("AAPL", "AMZN", "META", "MSFT", "NVDA", "TSLA")
GAMMA = "gamma_glm_confirmatory"

BASE_FEATURES = [
    "b0_rv_5m_lag",
    "b0_rv_30m_lag",
    "b0_return_5m_lag",
    "b0_session_minute",
    "b1q_atm_iv",
]
GROUPS = {
    "volume": ["b2_log_trade_count", "b2_unique_contract_share"],
    "premium": [
        "b2_log_mean_trade_premium",
        "b2_log_max_trade_premium",
        "b2_repeated_contract_premium_share",
    ],
    "direction_concentration": [
        "b2_call_put_premium_imbalance_scaled",
        "b2_execution_side_premium_imbalance",
        "b2_strike_concentration",
        "b2_expiry_concentration",
    ],
}
ALL_B2 = [feature for group in GROUPS.values() for feature in group]
WARMUP, BLOCK = 30, 10


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _walk_forward_qlike(
    frame: pl.DataFrame, target_column: str, specs: dict[str, list[str]]
) -> pl.DataFrame:
    sessions = sorted(str(s) for s in frame["session_date"].unique().to_list())
    rows: list[pl.DataFrame] = []
    start = WARMUP
    while start < len(sessions):
        train = frame.filter(
            pl.col("session_date").cast(pl.Utf8).is_in(sessions[:start])
        )
        test = frame.filter(
            pl.col("session_date").cast(pl.Utf8).is_in(sessions[start : start + BLOCK])
        )
        start += BLOCK
        if train.is_empty() or test.is_empty():
            continue
        log_target = np.log(train[target_column].to_numpy().astype(np.float64))
        for name, columns in specs.items():
            train_design = np.column_stack(
                [np.ones(train.height), train.select(columns).to_numpy()]
            )
            test_design = np.column_stack(
                [np.ones(test.height), test.select(columns).to_numpy()]
            )
            fit = har.fit_log_ols(train_design, log_target)
            forecast = har.predict_level(
                test_design, np.asarray(fit["coefficients"]), float(fit["sigma2"])
            )
            losses = qlike_losses(test[target_column].to_numpy().astype(np.float64), forecast)
            rows.append(
                test.select("origin_id", "asset", "session_date").with_columns(
                    pl.lit(name).alias("spec"), pl.Series("qlike_loss", losses)
                )
            )
    return pl.concat(rows)


def _contrast(oof: pl.DataFrame, base: str, expanded: str) -> dict[str, Any]:
    keys = ["origin_id", "asset", "session_date"]
    paired = (
        oof.filter(pl.col("spec") == base)
        .select(*keys, pl.col("qlike_loss").alias("base_loss"))
        .join(
            oof.filter(pl.col("spec") == expanded).select(
                *keys, pl.col("qlike_loss").alias("expanded_loss")
            ),
            on=keys,
            how="inner",
        )
        .with_columns((pl.col("base_loss") - pl.col("expanded_loss")).alias("difference"))
        .group_by("session_date")
        .agg(pl.col("difference").mean())
        .sort("session_date")
    )
    values = paired["difference"].to_numpy()
    result = inference.cluster_t_test(values)
    result["wild_p"] = float(inference.wild_cluster_bootstrap(values)["p_value"])
    return result


def _earnings_sessions(api_key: str) -> dict[str, set[str]]:
    provider = FMPProvider(api_key)
    flags: dict[str, set[str]] = {}
    try:
        for asset in ASSETS:
            response = provider.earnings(asset)
            events = parse_earnings_payload(
                response.payload,
                run_id="gate9_earnings",
                source_response_id=f"gate9:{asset}",
            )
            flags[asset] = {
                event.event_date_ny.isoformat()
                for event in events
                if event.event_date_ny is not None
            }
            time.sleep(0.15)
    finally:
        provider.close()
    return flags


def _earnings_strata(
    forecasts_path: Path, base: str, expanded: str, earnings: dict[str, set[str]]
) -> dict[str, Any]:
    frame = pl.read_parquet(forecasts_path)
    if "timing_variant" in frame.columns:
        frame = frame.filter(pl.col("timing_variant") == "PRIMARY")
    keys = ["origin_id", "asset", "session_date"]
    sides = {
        label: frame.filter(
            (pl.col("model_role") == GAMMA) & (pl.col("information_set") == label)
        ).select(*keys, pl.col("qlike_loss").alias(f"loss_{label}"))
        for label in (base, expanded)
    }
    paired = (
        sides[base]
        .join(sides[expanded], on=keys, how="inner")
        .with_columns((pl.col(f"loss_{base}") - pl.col(f"loss_{expanded}")).alias("difference"))
    )
    sessions = sorted(str(s) for s in paired["session_date"].unique().to_list())
    index = {session: position for position, session in enumerate(sessions)}
    near: dict[str, set[str]] = {asset: set() for asset in ASSETS}
    for asset in ASSETS:
        for event_day in earnings.get(asset, set()):
            if event_day in index:
                position = index[event_day]
                for offset in (-1, 0, 1):
                    if 0 <= position + offset < len(sessions):
                        near[asset].add(sessions[position + offset])
    flagged = paired.with_columns(
        pl.struct("asset", "session_date")
        .map_elements(
            lambda row: str(row["session_date"]) in near.get(str(row["asset"]), set()),
            return_dtype=pl.Boolean,
        )
        .alias("near_earnings")
    )
    out: dict[str, Any] = {}
    for label, condition in (("near_earnings", True), ("other_sessions", False)):
        subset = (
            flagged.filter(pl.col("near_earnings") == condition)
            .group_by("session_date")
            .agg(pl.col("difference").mean())
            .sort("session_date")
        )
        values = subset["difference"].to_numpy()
        if values.size >= 3:
            entry = inference.cluster_t_test(values)
            entry["wild_p"] = float(inference.wild_cluster_bootstrap(values)["p_value"])
            out[label] = entry
        else:
            out[label] = {"days": int(values.size), "note": "insufficient strata days"}
    return out


def main() -> None:
    api_key = os.environ.get("FMP_API_KEY")
    if not api_key:
        raise SystemExit("GATE9_FMP_KEY_MISSING")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    panel = pl.read_parquet(PANEL).filter(pl.col("common_complete"))
    panel = panel.filter(pl.col("b1q_atm_iv").is_not_null()).with_columns(
        pl.col("b0_rv_5m_lag").clip(lower_bound=1e-12).log(),
        pl.col("b0_rv_30m_lag").clip(lower_bound=1e-12).log(),
        pl.col("b1q_atm_iv").clip(lower_bound=1e-6).log(),
    )
    specs: dict[str, list[str]] = {"base": BASE_FEATURES, "base_all_b2": BASE_FEATURES + ALL_B2}
    for group_name, group_features in GROUPS.items():
        specs[f"base_plus_{group_name}"] = BASE_FEATURES + group_features
        specs[f"base_all_minus_{group_name}"] = BASE_FEATURES + [
            feature for feature in ALL_B2 if feature not in group_features
        ]
    oof = _walk_forward_qlike(panel, "rv30", specs)
    ablation: dict[str, Any] = {
        "all_nine_vs_base": _contrast(oof, "base", "base_all_b2"),
    }
    for group_name in GROUPS:
        ablation[f"alone_{group_name}"] = _contrast(oof, "base", f"base_plus_{group_name}")
        ablation[f"drop_{group_name}"] = _contrast(
            oof, f"base_all_minus_{group_name}", "base_all_b2"
        )
    earnings = _earnings_sessions(api_key)
    strata = {
        "C6": _earnings_strata(C6_FORECASTS, "B1v3a", "B2", earnings),
        "C4c": _earnings_strata(C4C_FORECASTS, "B1v2a", "B2v2", earnings),
    }
    bars = pl.read_parquet(DEV_BARS)
    origins = panel.select("origin_id", "asset", "session_date", "forecast_origin_utc")
    features = har.build_har_features(bars, origins).join(
        panel.select("origin_id", "rv30", *ALL_B2), on="origin_id", how="inner"
    )
    horizon_results: dict[str, Any] = {}
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
    keyed = features.select(
        "origin_id", "asset", "session_date", "forecast_origin_utc"
    ).with_columns(pl.col("session_date").cast(pl.Date).alias("bar_session"))
    for horizon in (15, 30, 60):
        window_end = pl.col("forecast_origin_utc").dt.offset_by(f"{horizon}m")
        targets = (
            returns.join(keyed, on=["asset", "bar_session"], how="inner")
            .filter(
                (pl.col("bar_start_utc") > pl.col("forecast_origin_utc"))
                & (pl.col("bar_start_utc") <= window_end)
            )
            .group_by("origin_id")
            .agg(pl.col("squared").sum().alias("rv_h"), pl.len().alias("bars"))
            .filter(pl.col("bars") == horizon)
            .with_columns(pl.col("rv_h").clip(lower_bound=1e-12))
        )
        merged = features.join(targets.select("origin_id", "rv_h"), on="origin_id", how="inner")
        horizon_specs = {
            "harq": [*har.HAR_COLUMNS, har.HARQ_COLUMN],
            "harq_b2": [*har.HAR_COLUMNS, har.HARQ_COLUMN, *ALL_B2],
        }
        horizon_oof = _walk_forward_qlike(merged, "rv_h", horizon_specs)
        horizon_results[f"rv{horizon}"] = {
            "origins": merged.height,
            "b2_increment": _contrast(horizon_oof, "harq", "harq_b2"),
        }
    results: dict[str, Any] = {
        "schema_version": "gate9-localization-v1.0",
        "label": "EXPLORATORY_DEVELOPMENT_ONLY (9.2 stratifies already-read frozen deltas)",
        "inputs": {
            "panel_sha256": _sha256(PANEL),
            "dev_bars_sha256": _sha256(DEV_BARS),
            "c6_sha256": _sha256(C6_FORECASTS),
            "c4c_sha256": _sha256(C4C_FORECASTS),
        },
        "smooth_family_proxy_note": (
            "ablation uses log-OLS as the smooth-family proxy for the Gamma lineage"
        ),
        "ablation": ablation,
        "earnings_strata": strata,
        "horizon_term_structure": horizon_results,
    }
    payload = json.dumps(results, indent=1, sort_keys=True, default=str)
    (OUTPUT / "results.json").write_text(payload, encoding="utf-8")
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    (OUTPUT / "results.sha256").write_text(digest + "\n", encoding="utf-8")
    print(f"[gate9] wrote {OUTPUT / 'results.json'} sha256={digest[:16]}")


if __name__ == "__main__":
    main()
