"""Gate 7: noise-robust RV30 target sensitivity on the frozen C6 forecasts.

Trade-price RV is upward-biased and serially contaminated by bid-ask bounce;
Patton (2011) shows QLIKE rankings are proxy-robust only for conditionally
unbiased proxies. This gate (a) measures per-asset 1-minute return AC(1) and
the implied Zhou/Hansen-Lunde noise bias, and (b) recomputes the registered C6
contrasts against an AC(1)-corrected target RV30* = max(RV30 + 2·Σ rₜrₜ₊₁,
floor) built from freshly downloaded bars, with the uncorrected reconstruction
validated against the frozen panel target before anything else is trusted.
Model forecasts stay frozen; only the evaluation proxy changes. No sealed
reads; the C6 outcomes were already read.
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

from mds650 import inference
from mds650.metrics import qlike_losses
from mds650.providers.fmp import FMPProvider, parse_minute_payload

REPO = Path(__file__).resolve().parents[1]
DATA_ROOT = Path(os.environ.get("MDS650_EXTERNAL_ROOT", "D:/MDS650"))
BARS_STORE = DATA_ROOT / "data" / "fmp" / "gate7"
FORECASTS = DATA_ROOT / "b1v3_confirmation" / "evaluation" / "primary_forecasts.parquet"
OUTPUT = REPO / "artifacts" / "gate7_noise_robust"
ASSETS = ("AAPL", "AMZN", "META", "MSFT", "NVDA", "TSLA")
GAMMA = "gamma_glm_confirmatory"
LGBM = "lightgbm_robustness"
FLOOR = 1e-12


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _acquire_bars(sessions: list[str]) -> Path:
    output = BARS_STORE / "underlying_1min_c6.parquet"
    if output.exists() and output.stat().st_size > 1_000_000:
        return output
    api_key = os.environ.get("FMP_API_KEY")
    if not api_key:
        raise SystemExit("GATE7_FMP_KEY_MISSING")
    BARS_STORE.mkdir(parents=True, exist_ok=True)
    provider = FMPProvider(api_key)
    frames: list[pl.DataFrame] = []
    try:
        for asset in ASSETS:
            for session in sessions:
                response = provider.minute_bars(asset, from_date=session, to_date=session)
                bars = parse_minute_payload(
                    response.payload,
                    asset=asset,
                    run_id="gate7_c6_bars",
                    source_response_id=f"gate7:{asset}:{session}",
                    source_timezone="America/New_York",
                )
                if bars:
                    frames.append(
                        pl.DataFrame(
                            {
                                "asset": [bar.asset for bar in bars],
                                "bar_start_utc": [bar.bar_start_utc for bar in bars],
                                "close": [bar.close for bar in bars],
                            }
                        )
                    )
                time.sleep(0.15)
            print(f"[gate7] bars {asset}: {sum(f.height for f in frames)} rows")
    finally:
        provider.close()
    combined = (
        pl.concat(frames)
        .unique(subset=["asset", "bar_start_utc"], keep="first")
        .sort("asset", "bar_start_utc")
    )
    combined.write_parquet(output)
    return output


def _targets(bars: pl.DataFrame, origins: pl.DataFrame) -> pl.DataFrame:
    returns = (
        bars.sort("asset", "bar_start_utc")
        .with_columns(pl.col("bar_start_utc").dt.date().alias("bar_session"))
        .with_columns(
            (pl.col("close") / pl.col("close").shift(1).over("asset", "bar_session"))
            .log()
            .alias("log_return")
        )
        .drop_nulls("log_return")
    )
    keyed = origins.select(
        "origin_id", "asset", "session_date", "forecast_origin_utc"
    ).with_columns(pl.col("session_date").cast(pl.Date).alias("bar_session"))
    window_end = pl.col("forecast_origin_utc").dt.offset_by("30m")
    joined = (
        returns.join(keyed, on=["asset", "bar_session"], how="inner")
        .filter(
            (pl.col("bar_start_utc") > pl.col("forecast_origin_utc"))
            & (pl.col("bar_start_utc") <= window_end)
        )
        .sort("origin_id", "bar_start_utc")
        .with_columns(
            (pl.col("log_return") * pl.col("log_return").shift(-1).over("origin_id")).alias(
                "adjacent_product"
            )
        )
        .group_by("origin_id")
        .agg(
            (pl.col("log_return") ** 2).sum().alias("rv30_reconstructed"),
            pl.col("adjacent_product").drop_nulls().sum().alias("cross_sum"),
            pl.len().alias("target_bars"),
        )
        .filter(pl.col("target_bars") == 30)
        .with_columns(
            (pl.col("rv30_reconstructed") + 2.0 * pl.col("cross_sum"))
            .clip(lower_bound=FLOOR)
            .alias("rv30_ac1"),
        )
    )
    return joined


def _delta(frame: pl.DataFrame, model: str, base: str, expanded: str, loss: str) -> dict[str, Any]:
    keys = ["origin_id", "asset", "session_date"]
    side = {
        label: frame.filter(
            (pl.col("model_role") == model) & (pl.col("information_set") == label)
        ).select(*keys, pl.col(loss).alias(f"loss_{label}"))
        for label in (base, expanded)
    }
    paired = side[base].join(side[expanded], on=keys, how="inner")
    daily = (
        paired.with_columns(
            (pl.col(f"loss_{base}") - pl.col(f"loss_{expanded}")).alias("difference")
        )
        .group_by("session_date")
        .agg(pl.col("difference").mean())
        .sort("session_date")
    )
    values = daily["difference"].to_numpy()
    return {
        "cluster_t": inference.cluster_t_test(values),
        "newey_west": inference.newey_west_t_test(values),
        "wild_rademacher": inference.wild_cluster_bootstrap(values),
        "days": int(values.size),
    }


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    forecasts = pl.read_parquet(FORECASTS)
    sessions = sorted(str(value) for value in forecasts["session_date"].unique().to_list())
    bars_path = _acquire_bars(sessions)
    bars = pl.read_parquet(bars_path)
    origins = forecasts.select(
        "origin_id", "asset", "session_date", "forecast_origin_utc", "rv30"
    ).unique(subset=["origin_id"])
    targets = _targets(bars, origins)
    merged = origins.join(targets, on="origin_id", how="inner")
    reconstruction_corr = float(
        np.corrcoef(
            np.log(merged["rv30"].to_numpy()),
            np.log(np.maximum(merged["rv30_reconstructed"].to_numpy(), FLOOR)),
        )[0, 1]
    )
    diagnostics: dict[str, Any] = {}
    returns = (
        bars.sort("asset", "bar_start_utc")
        .with_columns(pl.col("bar_start_utc").dt.date().alias("bar_session"))
        .with_columns(
            (pl.col("close") / pl.col("close").shift(1).over("asset", "bar_session"))
            .log()
            .alias("log_return")
        )
        .drop_nulls("log_return")
    )
    for asset, group in returns.group_by("asset"):
        series = group["log_return"].to_numpy()
        ac1 = float(np.corrcoef(series[:-1], series[1:])[0, 1])
        rv = float((series**2).sum())
        cross = float((series[:-1] * series[1:]).sum())
        diagnostics[str(asset[0])] = {
            "ac1_1min_returns": ac1,
            "implied_noise_bias_share": -2.0 * cross / rv,
        }
    evaluation = forecasts.join(
        targets.select("origin_id", "rv30_ac1"), on="origin_id", how="inner"
    ).with_columns(
        pl.Series(
            "qlike_ac1",
            qlike_losses(
                pl.read_parquet(FORECASTS)
                .join(targets.select("origin_id", "rv30_ac1"), on="origin_id", how="inner")[
                    "rv30_ac1"
                ]
                .to_numpy(),
                pl.read_parquet(FORECASTS)
                .join(targets.select("origin_id", "rv30_ac1"), on="origin_id", how="inner")[
                    "forecast"
                ]
                .to_numpy(),
            ),
        )
    )
    results: dict[str, Any] = {
        "schema_version": "gate7-noise-robust-v1.0",
        "inputs": {
            "forecasts_sha256": _sha256(FORECASTS),
            "bars_sha256": _sha256(bars_path),
        },
        "reconstruction_log_corr_vs_frozen_rv30": reconstruction_corr,
        "matched_origins": merged.height,
        "per_asset_noise_diagnostics": diagnostics,
        "contrasts": {},
    }
    for model in (GAMMA, LGBM):
        results["contrasts"][model] = {
            "frozen_target": _delta(evaluation, model, "B1v3a", "B2", "qlike_loss"),
            "ac1_corrected_target": _delta(evaluation, model, "B1v3a", "B2", "qlike_ac1"),
        }
    payload = json.dumps(results, indent=1, sort_keys=True, default=str)
    (OUTPUT / "results.json").write_text(payload, encoding="utf-8")
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    (OUTPUT / "results.sha256").write_text(digest + "\n", encoding="utf-8")
    print(f"[gate7] reconstruction_corr={reconstruction_corr:.6f}")
    print(f"[gate7] wrote {OUTPUT / 'results.json'} sha256={digest[:16]}")


if __name__ == "__main__":
    main()
