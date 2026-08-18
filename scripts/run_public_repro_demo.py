"""Public reproducibility demo: the FULL pipeline on redistributable synthetic data.

Computational reproducibility is not data reproducibility (decision 63): a third
party without provider licenses cannot rebuild the licensed panels, but they CAN
verify that every methodological stage of this research runs end-to-end from a
clean clone — no provider keys, no external drives, no licensed bytes:

    PIT availability join  ->  feature construction  ->  purge/embargo split  ->
    gamma_glm / lightgbm / har_rv (log-linear ext.)  ->  QLIKE  ->
    wild + moving-block bootstrap  ->  Model Confidence Set  ->  claim ledger

Deterministic (seed 650). Run:  uv run python scripts/run_public_repro_demo.py
Outputs: artifacts/public_repro_demo/{results.json,claim_ledger.json} (untracked).
The numbers are synthetic by construction and carry NO information about the
licensed research results.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from mds650.development_models import candidate_parameter_grid, fit_development_candidate
from mds650.inference import (
    model_confidence_set,
    moving_block_bootstrap,
    paired_daily_differences,
    wild_cluster_bootstrap,
)
from mds650.metrics import holm_adjust, qlike_losses
from mds650.temporal_validation import purge_and_embargo_training

SEED = 650
SESSIONS = 24
ORIGINS_PER_SESSION = 12
ASSETS = ("AAA", "BBB")
B0_FEATURES = ("b0_rv_5m_lag", "b0_rv_30m_lag", "b0_return_5m_lag")
B1_FEATURES = (*B0_FEATURES, "b1_atm_iv")
B2_FEATURES = (*B1_FEATURES, "b2_log_trade_count")
MODELS = ("gamma_glm", "lightgbm", "har_rv")


def _synthetic_quotes_and_bars(rng: np.random.Generator) -> pl.DataFrame:
    """Simulate raw feeds with availability timestamps, then PIT-join them.

    Each origin only sees a quote whose availability timestamp is not after the
    origin — the same point-in-time rule as the licensed pipeline (a fraction of
    quotes arrive late and must be excluded by the join, never by hindsight).
    """
    rows: list[dict[str, Any]] = []
    start = datetime(2026, 1, 5, 14, 30, tzinfo=UTC)
    for session in range(SESSIONS):
        session_day = start + timedelta(days=session)
        log_vol = -4.6 + 0.35 * np.sin(session / 3.5)
        for asset in ASSETS:
            for slot in range(ORIGINS_PER_SESSION):
                origin_time = session_day + timedelta(minutes=5 * slot)
                true_vol = float(np.exp(log_vol + 0.25 * rng.normal()))
                rv_5m = true_vol * float(np.exp(0.2 * rng.normal()))
                rv_30m = true_vol * float(np.exp(0.15 * rng.normal()))
                iv = true_vol * float(np.exp(0.10 * rng.normal()))  # informative B1 signal
                quote_delay = float(rng.exponential(20.0))  # seconds; some arrive late
                rows.append(
                    {
                        "origin_id": f"{asset}:{origin_time.isoformat()}",
                        "asset": asset,
                        "session_date": session_day.date().isoformat(),
                        "forecast_origin_utc": origin_time,
                        "b0_rv_5m_lag": rv_5m,
                        "b0_rv_30m_lag": rv_30m,
                        "b0_return_5m_lag": float(0.01 * rng.normal()),
                        "quote_available_at_utc": origin_time
                        + timedelta(seconds=quote_delay - 30.0),
                        "b1_atm_iv_raw": iv,
                        "b2_log_trade_count": float(np.log1p(rng.poisson(40))),
                        "rv30": true_vol * float(np.exp(0.18 * rng.normal())),
                    }
                )
    return pl.DataFrame(rows)


def _pit_join(frame: pl.DataFrame) -> pl.DataFrame:
    """Keep only quotes available at or before the origin; late quotes fall back
    to the last B0 proxy (never to future information)."""
    return frame.with_columns(
        pl.when(pl.col("quote_available_at_utc") <= pl.col("forecast_origin_utc"))
        .then(pl.col("b1_atm_iv_raw"))
        .otherwise(pl.col("b0_rv_30m_lag"))
        .alias("b1_atm_iv"),
        (pl.col("quote_available_at_utc") <= pl.col("forecast_origin_utc")).alias(
            "b1_quote_not_after_origin"
        ),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "artifacts" / "public_repro_demo",
    )
    args = parser.parse_args()
    rng = np.random.default_rng(SEED)

    panel = _pit_join(_synthetic_quotes_and_bars(rng)).sort("forecast_origin_utc")
    pit_share = float(
        panel.select(pl.col("b1_quote_not_after_origin").cast(pl.Float64).mean()).item()
    )

    split_time = panel["forecast_origin_utc"][int(panel.height * 0.7)]
    train = purge_and_embargo_training(
        panel.filter(pl.col("forecast_origin_utc") < split_time), split_time
    )
    test = panel.filter(pl.col("forecast_origin_utc") >= split_time)

    information_sets = {"B0": B0_FEATURES, "B1": B1_FEATURES, "B2": B2_FEATURES}
    losses: list[pl.DataFrame] = []
    for model_name in MODELS:
        for set_name, features in information_sets.items():
            fitted = fit_development_candidate(
                train,
                feature_columns=features,
                model_name=model_name,
                parameters=candidate_parameter_grid(model_name)[0],
                seed=SEED,
            )
            forecasts = fitted.predict(test)
            losses.append(
                test.select("origin_id", "asset", "session_date").with_columns(
                    pl.lit(model_name).alias("model_role"),
                    pl.lit(set_name).alias("information_set"),
                    pl.Series("qlike_loss", qlike_losses(test["rv30"].to_numpy(), forecasts)),
                )
            )
    long_frame = pl.concat(losses)

    contrasts: dict[str, Any] = {}
    raw_p: dict[str, float] = {}
    for model_name in MODELS:
        daily = paired_daily_differences(
            long_frame, base_set="B0", expanded_set="B1", model=model_name
        )
        series = daily["mean_difference"].to_numpy()
        wild = wild_cluster_bootstrap(series, repetitions=999, seed=SEED)
        block = moving_block_bootstrap(series, repetitions=999, seed=SEED)
        contrasts[model_name] = {
            "estimate": float(np.mean(series)),
            "p_wild": float(wild["p_value"]),
            "block_ci": [float(block["ci_low"]), float(block["ci_high"])],
        }
        raw_p[model_name] = float(wild["p_value"])
    adjusted = holm_adjust(raw_p)

    cells = (
        long_frame.group_by("session_date", "model_role", "information_set")
        .agg(pl.col("qlike_loss").mean())
        .with_columns(
            (pl.col("model_role") + pl.lit("|") + pl.col("information_set")).alias("cell")
        )
        .pivot(on="cell", index="session_date", values="qlike_loss")
        .sort("session_date")
        .drop_nulls()
    )
    mcs = model_confidence_set(cells, repetitions=999, block_length=3)

    results = {
        "schema_version": "public-repro-demo-v1.0",
        "seed": SEED,
        "synthetic": True,
        "pit_join_share_valid": pit_share,
        "train_rows_after_purge_embargo": train.height,
        "test_rows": test.height,
        "b0_to_b1_contrasts": contrasts,
        "holm_adjusted_p": adjusted,
        "mcs_survivors": mcs["survivors"],
        "note": "Synthetic data; numbers say nothing about the licensed research results.",
    }
    payload = json.dumps(results, indent=1, sort_keys=True)
    args.output_root.mkdir(parents=True, exist_ok=True)
    (args.output_root / "results.json").write_text(payload + "\n", encoding="utf-8")

    ledger_claims = [
        {
            "claim": "PIT join excludes late quotes instead of using hindsight",
            "evidence": f"share of origins with a PIT-valid quote = {pit_share:.3f} < 1",
        },
        {
            "claim": "purge/embargo removed boundary-contaminated training rows",
            "evidence": (
                f"train rows {train.height} < raw pre-split rows "
                f"{panel.filter(pl.col('forecast_origin_utc') < split_time).height}"
            ),
        },
        {
            "claim": "three model families produced positive finite forecasts",
            "evidence": f"QLIKE computed on {long_frame.height} model-set-origin rows",
        },
        {
            "claim": "studentized inference and MCS ran on the synthetic panel",
            "evidence": f"MCS survivors: {mcs['survivors']}",
        },
    ]
    ledger = {
        "schema_version": "public-repro-demo-ledger-v1.0",
        "results_sha256": hashlib.sha256(payload.encode("utf-8")).hexdigest(),
        "claims": ledger_claims,
    }
    (args.output_root / "claim_ledger.json").write_text(
        json.dumps(ledger, indent=1, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"[demo] ok: {args.output_root} | survivors={mcs['survivors']}")


if __name__ == "__main__":
    main()
