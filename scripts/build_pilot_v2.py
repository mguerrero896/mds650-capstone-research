"""Build Pilot V2 continuous B2 features from existing filtered Parquet files."""
# ruff: noqa: E501

from __future__ import annotations

import json
from pathlib import Path

import polars as pl
from phase4b_common import WINDOW_SPECS

ROOT = Path(".")
IN = ROOT / "artifacts" / "pilot"
OUT = ROOT / "artifacts" / "pilot_v2"
SPECS = WINDOW_SPECS


def _fill(expr: pl.Expr, value: int | float = 0) -> pl.Expr:
    return expr.fill_null(value)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    origins = pl.read_parquet(IN / "b0_features.parquet").select([
        "origin_id", pl.col("asset").alias("underlying_symbol"), "session_date", "forecast_origin_utc", "spot"
    ])
    paths = sorted((IN / "option_events").glob("date=*/events.parquet"))
    if len(paths) != 5:
        raise RuntimeError(f"PILOT_V2_EXPECTED_FIVE_EVENT_PARQUETS:{len(paths)}")
    events = pl.concat(
        [
            pl.scan_parquet(path).with_columns(
                pl.lit(path.parts[-2].split("=", 1)[1]).alias("session_date")
            )
            for path in paths
        ],
        how="diagonal",
    )
    frames: list[pl.DataFrame] = []
    for spec, lag in SPECS.items():
        eligible = (
            events.with_columns(
                (
                    (pl.col("executed_at") + pl.duration(seconds=lag)).dt.truncate("5m")
                    + pl.duration(minutes=5)
                ).alias("_candidate_origin")
            )
            .join(
                origins.lazy(),
                left_on=["underlying_symbol", "session_date", "_candidate_origin"],
                right_on=["underlying_symbol", "session_date", "forecast_origin_utc"],
                how="inner",
            )
            .with_columns(pl.col("_candidate_origin").alias("forecast_origin_utc"))
            .filter(
                (pl.col("executed_at") >= pl.col("forecast_origin_utc") - pl.duration(seconds=lag) - pl.duration(minutes=5))
                & (pl.col("executed_at") < pl.col("forecast_origin_utc") - pl.duration(seconds=lag))
                & (pl.max_horizontal("executed_at", "created_at") <= pl.col("forecast_origin_utc") - pl.duration(seconds=lag))
            )
        )
        total_premium = pl.col("premium").fill_null(0).sum()
        contract_counts = eligible.group_by(["origin_id", "option_chain_id"]).agg([
            pl.len().alias("contract_trade_count"),
            pl.col("premium").fill_null(0).sum().alias("contract_premium"),
        ])
        repeated = contract_counts.filter(pl.col("contract_trade_count") > 1).group_by("origin_id").agg([
            pl.col("contract_trade_count").sum().alias("repeated_contract_trade_count"),
            pl.col("contract_premium").sum().alias("repeated_contract_premium"),
        ])
        strike_counts = eligible.filter(pl.col("strike").is_not_null()).group_by(["origin_id", "strike"]).len().group_by("origin_id").agg(
            (pl.col("len").max() / pl.col("len").sum()).alias("strike_concentration")
        )
        expiry_counts = eligible.filter(pl.col("expiry").is_not_null()).group_by(["origin_id", "expiry"]).len().group_by("origin_id").agg(
            (pl.col("len").max() / pl.col("len").sum()).alias("expiry_concentration")
        )
        summary = eligible.group_by(["origin_id", "underlying_symbol", "forecast_origin_utc", "spot"]).agg([
            pl.len().alias("option_trade_count_5m"),
            pl.col("option_chain_id").n_unique().alias("unique_contract_count_5m"),
            total_premium.alias("total_premium_5m"),
            pl.col("premium").max().fill_null(0).alias("max_trade_premium_5m"),
            pl.col("size").fill_null(0).sum().alias("total_contract_size_5m"),
            pl.col("size").max().fill_null(0).alias("max_contract_size_5m"),
            pl.when(pl.col("option_type").str.to_lowercase() == "call").then(pl.col("premium").fill_null(0)).otherwise(0).sum().alias("call_premium_5m"),
            pl.when(pl.col("option_type").str.to_lowercase() == "put").then(pl.col("premium").fill_null(0)).otherwise(0).sum().alias("put_premium_5m"),
            pl.when(pl.col("tags").fill_null("").str.contains("ask_side")).then(pl.col("premium").fill_null(0)).otherwise(0).sum().alias("_ask_premium"),
            pl.when(pl.col("tags").fill_null("").str.contains("bid_side")).then(pl.col("premium").fill_null(0)).otherwise(0).sum().alias("_bid_premium"),
            pl.when((pl.col("nbbo_bid") > 0) & (pl.col("nbbo_ask") > pl.col("nbbo_bid")) & (pl.col("price").is_not_null()) & ((pl.col("price") - (pl.col("nbbo_bid") + pl.col("nbbo_ask")) / 2).abs() <= ((pl.col("nbbo_bid") + pl.col("nbbo_ask")) / 2 * 0.01).clip(lower_bound=0.01))).then(pl.col("premium").fill_null(0)).otherwise(0).sum().alias("_midpoint_premium"),
            pl.when(pl.col("tags").fill_null("").str.contains("multileg")).then(1).otherwise(0).mean().alias("multileg_trade_share"),
            pl.when(pl.col("tags").fill_null("").str.contains("sweep")).then(1).otherwise(0).mean().alias("sweep_or_equivalent_share"),
            (pl.col("strike") / pl.col("spot") - 1).abs().median().alias("median_absolute_moneyness"),
            (pl.col("expiry").cast(pl.Int32) - pl.col("forecast_origin_utc").dt.date().cast(pl.Int32)).median().alias("median_days_to_expiry"),
            pl.col("implied_volatility").median().alias("implied_volatility_median"),
            (pl.col("implied_volatility").max() - pl.col("implied_volatility").min()).alias("within_bin_iv_change"),
            pl.col("implied_volatility").is_not_null().sum().alias("valid_iv_observation_count"),
            pl.when(pl.col("price").is_not_null() & pl.col("premium").is_not_null()).then(1).otherwise(0).mean().alias("valid_trade_share"),
            pl.col("implied_volatility").is_null().mean().alias("missing_iv_share"),
        ]).collect(engine="streaming")
        frame = origins.join(summary, on=["origin_id", "underlying_symbol", "forecast_origin_utc", "spot"], how="left")
        frame = frame.join(repeated.collect(engine="streaming"), on="origin_id", how="left")
        frame = frame.join(strike_counts.collect(engine="streaming"), on="origin_id", how="left")
        frame = frame.join(expiry_counts.collect(engine="streaming"), on="origin_id", how="left")
        frame = frame.with_columns([
            pl.lit(spec).alias("availability_spec"),
            _fill(pl.col("option_trade_count_5m")), _fill(pl.col("unique_contract_count_5m")),
            _fill(pl.col("total_premium_5m")), _fill(pl.col("max_trade_premium_5m")),
            _fill(pl.col("total_contract_size_5m")), _fill(pl.col("max_contract_size_5m")),
            _fill(pl.col("call_premium_5m")), _fill(pl.col("put_premium_5m")),
            _fill(pl.col("_ask_premium")), _fill(pl.col("_bid_premium")), _fill(pl.col("_midpoint_premium")),
            _fill(pl.col("multileg_trade_share")), _fill(pl.col("sweep_or_equivalent_share")),
            _fill(pl.col("repeated_contract_trade_count")), _fill(pl.col("repeated_contract_premium")),
            _fill(pl.col("strike_concentration")), _fill(pl.col("expiry_concentration")),
            _fill(pl.col("valid_trade_share")), _fill(pl.col("missing_iv_share")),
            pl.when(pl.col("valid_iv_observation_count").fill_null(0) >= 2)
            .then(pl.col("within_bin_iv_change"))
            .otherwise(None)
            .alias("within_bin_iv_change"),
            pl.col("option_trade_count_5m").fill_null(0).gt(0).alias("option_activity_present"),
            pl.lit("NOT_CALIBRATED").alias("unusual_event_status"),
            pl.lit("operational_availability_proxy").alias("availability_semantics"),
        ]).with_columns([
            (pl.col("call_premium_5m") - pl.col("put_premium_5m")).alias("call_put_premium_imbalance"),
            pl.when(pl.col("total_premium_5m") > 0).then(pl.col("_ask_premium") / pl.col("total_premium_5m")).otherwise(0).alias("ask_side_premium_share"),
            pl.when(pl.col("total_premium_5m") > 0).then(pl.col("_bid_premium") / pl.col("total_premium_5m")).otherwise(0).alias("bid_side_premium_share"),
            pl.when(pl.col("total_premium_5m") > 0).then(pl.col("_midpoint_premium") / pl.col("total_premium_5m")).otherwise(0).alias("midpoint_premium_share"),
        ]).drop(["spot", "_ask_premium", "_bid_premium", "_midpoint_premium"])
        frames.append(frame)
    output = pl.concat(frames, how="vertical").sort(["underlying_symbol", "forecast_origin_utc", "availability_spec"]).rename({"underlying_symbol": "asset"})
    output.write_parquet(OUT / "b2_features_v2.parquet")
    primary = output.filter(pl.col("availability_spec") == "primary_60s")
    coverage = {
        "status": "PILOT_V2_B2_CONTINUOUS_FEATURES",
        "origins": primary.height,
        "origins_with_option_activity": primary.filter(pl.col("option_activity_present")).height,
        "origins_without_option_activity": primary.filter(~pl.col("option_activity_present")).height,
        "natural_option_activity_prevalence": primary["option_activity_present"].mean(),
        "unusual_event_status": "NOT_CALIBRATED",
        "availability_specs": SPECS,
        "operational_availability_proxy": "created_at cutoff; not publication time",
        "provider_cumulative_fields_used": False,
        "artificial_balancing": False,
        "no_full_backfill": True,
    }
    (OUT / "b2_feature_coverage_v2.json").write_text(json.dumps(coverage, indent=2), encoding="utf-8")
    print(json.dumps({"rows": output.height, "origins": primary.height, "with_activity": coverage["origins_with_option_activity"], "without_activity": coverage["origins_without_option_activity"]}))


if __name__ == "__main__":
    main()
