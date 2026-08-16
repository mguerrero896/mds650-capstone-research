"""Frozen calendar and methodological contract for the Phase 6 replication."""

from __future__ import annotations

import math
import statistics
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import exchange_calendars as xcals  # type: ignore[import-untyped]
import polars as pl

from mds650.phase5_features import RAW_B2_COLUMNS, add_compact_b2_features
from mds650.phase5_storage import Phase5StorageConfig, storage_preflight
from mds650.study_design import B2_FEATURE_NAMES, canonical_sha256
from mds650.targets import compute_realized_variance

PHASE6_BLOCKS: tuple[tuple[str, str, str, int], ...] = (
    ("warmup", "2025-07-07", "2025-08-01", 20),
    ("initial_train", "2025-08-04", "2025-10-27", 60),
    ("oos_fold_1", "2025-10-28", "2025-11-24", 20),
    ("oos_fold_2", "2025-11-25", "2025-12-23", 20),
    ("oos_fold_3", "2025-12-24", "2026-01-23", 20),
    ("oos_fold_4", "2026-01-26", "2026-02-23", 20),
    ("oos_fold_5", "2026-02-24", "2026-03-23", 20),
)

OUTCOME_ASSETS: tuple[str, ...] = ("AAPL", "AMZN", "META", "MSFT", "NVDA", "TSLA")
MARKET_CONTROLS: tuple[str, ...] = ("SPY", "QQQ")

B0V2_FEATURES: tuple[str, ...] = (
    "b0v2_log_spot",
    "b0v2_underlying_return_5m",
    "b0v2_underlying_rv_5m",
    "b0v2_underlying_rv_30m",
    "b0v2_log_dollar_volume_5m",
    "b0v2_spy_return_5m",
    "b0v2_spy_rv_30m",
    "b0v2_qqq_return_5m",
    "b0v2_qqq_rv_30m",
    "b0v2_session_sine",
    "b0v2_session_cosine",
    "b0v2_asset_identity",
)

B1V2A_FEATURES: tuple[str, ...] = (
    "b1v2_atm_iv_30_60_dte",
    "b1v2_atm_iv_change_5m",
    "b1v2_atm_iv_change_30m",
)
B1V2B_FEATURES: tuple[str, ...] = (
    "b1v2_skew_symmetric_moneyness",
    "b1v2_skew_change_30m",
)
B1V2C_FEATURES: tuple[str, ...] = (
    "b1v2_term_short_to_medium",
    "b1v2_term_medium_to_long",
    "b1v2_term_short_to_medium_change_30m",
    "b1v2_term_medium_to_long_change_30m",
)

B2V2_FEATURES: tuple[str, ...] = (
    "b2v2_z_log_trade_count",
    "b2v2_z_unique_contract_share",
    "b2v2_z_log_mean_trade_premium",
    "b2v2_z_log_max_trade_premium",
    "b2v2_deviation_call_put_premium_imbalance",
    "b2v2_deviation_execution_side_premium_imbalance",
    "b2v2_z_repeated_contract_premium_share",
    "b2v2_z_strike_concentration",
    "b2v2_z_expiry_concentration",
)


def build_phase6_common_panel(
    origins: pl.DataFrame,
    b0: pl.DataFrame,
    b1: pl.DataFrame,
    b2: pl.DataFrame,
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Join B0v2, B1v2a and B2v2 on one auditable set of forecast origins."""
    key_columns = (
        "origin_id",
        "asset",
        "session_date",
        "forecast_origin_utc",
    )
    required = {
        "origins": (*key_columns, "role"),
        "b0": (
            *key_columns,
            "target_price_count",
            "target_return_count",
            "rv30",
            "max_predictor_available_at_utc",
            "drop_reason",
            *B0V2_FEATURES,
        ),
        "b1": (
            *key_columns,
            "forecast_origin_ns",
            "max_sip_timestamp_ns",
            *B1V2A_FEATURES,
            *B1V2B_FEATURES,
            *B1V2C_FEATURES,
            "b1v2a_complete",
            "b1v2b_complete",
            "b1v2c_complete",
        ),
        "b2": (
            *key_columns,
            *B2V2_FEATURES,
            "b2v2_complete",
            "b2v2_cutoff_utc",
            "b2v2_max_created_at_utc",
        ),
    }
    frames = {"origins": origins, "b0": b0, "b1": b1, "b2": b2}
    canonical_keys: pl.DataFrame | None = None
    for name, frame in frames.items():
        missing = set(required[name]) - set(frame.columns)
        if missing:
            raise ValueError(f"PHASE6_REQUIRED_COLUMNS_MISSING:{name}:{','.join(sorted(missing))}")
        if frame["origin_id"].null_count() or frame["origin_id"].n_unique() != frame.height:
            raise ValueError(f"PHASE6_DUPLICATE_ORIGIN:{name}")
        keys = frame.select(key_columns).sort("origin_id")
        if canonical_keys is None:
            canonical_keys = keys
        elif not keys.equals(canonical_keys):
            raise ValueError(f"PHASE6_ORIGIN_KEY_MISMATCH:{name}")

    if b0.filter(pl.col("max_predictor_available_at_utc") > pl.col("forecast_origin_utc")).height:
        raise ValueError("PHASE6_B0_AFTER_ORIGIN")
    if b1.filter(
        pl.col("max_sip_timestamp_ns").is_not_null()
        & (pl.col("max_sip_timestamp_ns") > pl.col("forecast_origin_ns"))
    ).height:
        raise ValueError("PHASE6_B1_AFTER_ORIGIN")
    if b2.filter(pl.col("b2v2_cutoff_utc") > pl.col("forecast_origin_utc")).height:
        raise ValueError("PHASE6_B2_CUTOFF_AFTER_ORIGIN")
    if b2.filter(
        pl.col("b2v2_max_created_at_utc").is_not_null()
        & (pl.col("b2v2_max_created_at_utc") > pl.col("b2v2_cutoff_utc"))
    ).height:
        raise ValueError("PHASE6_B2_AFTER_CUTOFF")
    if (
        b1.filter(pl.col("b1v2c_complete") & ~pl.col("b1v2b_complete")).height
        or b1.filter(pl.col("b1v2b_complete") & ~pl.col("b1v2a_complete")).height
    ):
        raise ValueError("PHASE6_B1_NESTED_INVARIANT_FAILURE")

    panel = origins
    for frame in (b0, b1, b2):
        additions = [
            column
            for column in frame.columns
            if column == "origin_id" or column not in panel.columns
        ]
        panel = panel.join(frame.select(additions), on="origin_id", how="left", validate="1:1")
    numeric_b0 = [name for name in B0V2_FEATURES if name != "b0v2_asset_identity"]
    target_complete = (
        (pl.col("target_price_count") == 31)
        & (pl.col("target_return_count") == 30)
        & pl.col("rv30").is_finite()
        & (pl.col("rv30") > 0)
    )
    b0_complete = target_complete & pl.all_horizontal(
        [pl.col(name).is_finite() for name in numeric_b0]
        + [
            pl.col("drop_reason").is_null(),
            pl.col("b0v2_asset_identity").is_not_null(),
            pl.col("b0v2_asset_identity") != "",
            pl.col("max_predictor_available_at_utc").is_not_null(),
        ]
    )
    b1_complete = b0_complete & pl.all_horizontal(
        [pl.col(name).is_finite() for name in B1V2A_FEATURES]
        + [
            pl.col("b1v2a_complete"),
            pl.col("max_sip_timestamp_ns").is_not_null(),
            pl.col("max_sip_timestamp_ns") <= pl.col("forecast_origin_ns"),
        ]
    )
    common_complete = b1_complete & pl.all_horizontal(
        [pl.col(name).is_finite() for name in B2V2_FEATURES]
        + [
            pl.col("b2v2_complete"),
            pl.col("b2v2_cutoff_utc").is_not_null(),
            pl.col("b2v2_cutoff_utc") <= pl.col("forecast_origin_utc"),
            pl.col("b2v2_max_created_at_utc").is_null()
            | (pl.col("b2v2_max_created_at_utc") <= pl.col("b2v2_cutoff_utc")),
        ]
    )
    panel = panel.with_columns(
        target_complete.fill_null(False).alias("target_complete"),
        b0_complete.fill_null(False).alias("b0v2_complete"),
        b1_complete.fill_null(False).alias("b1v2a_common_complete"),
        common_complete.fill_null(False).alias("common_complete"),
    ).with_columns(
        pl.when(~pl.col("target_complete"))
        .then(pl.lit("TARGET_INVALID_OR_MISSING_31_PRICES"))
        .when(~pl.col("b0v2_complete"))
        .then(pl.lit("B0V2_MISSING_OR_PIT_FAILURE"))
        .when(~pl.col("b1v2a_common_complete"))
        .then(pl.lit("B1V2A_MISSING_OR_PIT_FAILURE"))
        .when(~pl.col("common_complete"))
        .then(pl.lit("B2V2_MISSING_OR_PIT_FAILURE"))
        .otherwise(pl.lit("NONE"))
        .alias("exclusion_reason")
    )
    return panel, panel.filter(pl.col("common_complete"))


def b2_activity_checkpoint_valid(path: Path, *, expected_rows: int) -> bool:
    """Return whether a cached B2 activity day carries auditable PIT evidence."""
    try:
        scan = pl.scan_parquet(path)
        if not {
            "origin_id",
            "b2v2_cutoff_utc",
            "b2v2_max_created_at_utc",
        } <= set(scan.collect_schema().names()):
            return False
        frame = scan.select("origin_id", "b2v2_cutoff_utc", "b2v2_max_created_at_utc").collect()
    except (OSError, pl.exceptions.PolarsError):
        return False
    return bool(
        frame.height == expected_rows
        and frame["origin_id"].n_unique() == expected_rows
        and frame["b2v2_cutoff_utc"].null_count() == 0
        and frame.filter(
            pl.col("b2v2_max_created_at_utc").is_not_null()
            & (pl.col("b2v2_max_created_at_utc") > pl.col("b2v2_cutoff_utc"))
        ).is_empty()
    )


_PROVENANCE_KEYS = {
    "branch",
    "repository_commit",
    "python_version",
    "uv_lock_sha256",
    "design_sha256",
    "spec_sha256",
    "plan_sha256",
    "tasks_sha256",
    "analysis_sha256",
    "phase6_source_sha256",
    "schema_sha256",
    "worktree_dirty",
}
_HASH_KEYS = {
    "uv_lock_sha256",
    "design_sha256",
    "spec_sha256",
    "plan_sha256",
    "tasks_sha256",
    "analysis_sha256",
    "phase6_source_sha256",
    "schema_sha256",
}

_NEW_YORK = ZoneInfo("America/New_York")


def _robust_scale(values: Sequence[float]) -> tuple[float, str]:
    """Return the preregistered robust scale and its diagnostic label."""
    if not values:
        return 0.0, "CONSTANT_PRIOR_HISTORY"
    median = statistics.median(values)
    mad = statistics.median(abs(value - median) for value in values)
    if mad > 0:
        return 1.4826 * mad, "MAD_1_4826"
    if len(values) >= 2:
        quartiles = statistics.quantiles(values, n=4, method="inclusive")
        iqr = quartiles[2] - quartiles[0]
        if iqr > 0:
            return iqr / 1.349, "IQR_DIV_1_349"
    return 0.0, "CONSTANT_PRIOR_HISTORY"


def robust_prior_deviation(
    values: Sequence[float],
    current: float,
    *,
    asset_values: Sequence[float] = (),
) -> tuple[float, str]:
    """Standardize one value using only prior observations.

    The location always comes from the matching asset/time band. Scale falls
    back from MAD to IQR and then to prior asset-wide history. Constant prior
    history yields a documented zero deviation.
    """
    center, scale, label = _robust_parameters(values, asset_values)
    if scale == 0:
        return 0.0, "CONSTANT_PRIOR_HISTORY"
    return (float(current) - center) / scale, label


def _robust_parameters(
    values: Sequence[float], asset_values: Sequence[float] = ()
) -> tuple[float, float, str]:
    """Fit target-free robust location and scale from prior observations."""
    prior = [float(value) for value in values]
    if not prior:
        return 0.0, 0.0, "CONSTANT_PRIOR_HISTORY"
    center = statistics.median(prior)
    scale, label = _robust_scale(prior)
    if scale == 0 and asset_values:
        scale, _ = _robust_scale([float(value) for value in asset_values])
        if scale > 0:
            label = "PRIOR_ASSET"
    return center, scale, label


def _phase6_band(origin: datetime) -> str:
    """Return the frozen thirty-minute New York band for one origin."""
    local = origin.astimezone(_NEW_YORK)
    minute = local.hour * 60 + local.minute - (9 * 60 + 30)
    return f"B30_{minute // 30:02d}"


def aggregate_b2_activity(
    trades: pl.DataFrame,
    origins: pl.DataFrame,
    window_minutes: int = 5,
    delay_seconds: int = 60,
) -> pl.DataFrame:
    """Aggregate eligible individual trades into per-origin activity inputs.

    ``created_at`` must precede the origin by the configured registered delay.
    ``executed_at`` assigns the trade to the immediately preceding window.
    """
    if window_minutes not in {5, 15, 30}:
        raise ValueError("B2V2_WINDOW_NOT_REGISTERED")
    if delay_seconds not in {60, 120, 300}:
        raise ValueError("B2V2_DELAY_NOT_REGISTERED")
    if any(
        column.lower() in {"rv30", "qlike", "target"} or column.lower().startswith("rv30_")
        for column in trades.columns
    ):
        raise ValueError("B2V2_TARGET_COLUMN_FORBIDDEN")
    required = {
        "underlying_symbol",
        "session_date",
        "executed_at",
        "created_at",
        "option_chain_id",
        "premium",
        "option_type",
        "tags",
        "strike",
        "expiry",
    }
    missing = required - set(trades.columns)
    if missing:
        raise ValueError(f"B2V2_TRADE_COLUMNS_MISSING:{','.join(sorted(missing))}")
    origin_key = origins.select(
        "origin_id",
        "asset",
        "session_date",
        "forecast_origin_utc",
    ).with_columns(
        (pl.col("forecast_origin_utc") - pl.duration(seconds=delay_seconds)).alias(
            "b2v2_cutoff_utc"
        )
    )
    eligible = (
        trades.with_columns(
            (
                (pl.col("executed_at") + pl.duration(seconds=delay_seconds)).dt.truncate("5m")
                + pl.duration(minutes=5)
            ).alias("_first_candidate_origin")
        )
        .with_columns(
            pl.concat_list(
                pl.col("_first_candidate_origin") + pl.duration(minutes=offset)
                for offset in range(0, window_minutes, 5)
            ).alias("_candidate_origin")
        )
        .explode("_candidate_origin", empty_as_null=True)
        .join(
            origin_key,
            left_on=[
                "underlying_symbol",
                "session_date",
                "_candidate_origin",
            ],
            right_on=["asset", "session_date", "forecast_origin_utc"],
            how="inner",
        )
        .with_columns(pl.col("_candidate_origin").alias("forecast_origin_utc"))
        .filter(
            (
                pl.col("executed_at")
                >= pl.col("forecast_origin_utc")
                - pl.duration(seconds=delay_seconds, minutes=window_minutes)
            )
            & (
                pl.col("executed_at")
                < pl.col("forecast_origin_utc") - pl.duration(seconds=delay_seconds)
            )
            & (
                pl.col("created_at")
                <= pl.col("forecast_origin_utc") - pl.duration(seconds=delay_seconds)
            )
        )
        .with_columns(
            pl.col("premium").is_null().alias("_premium_was_null"),
            (pl.col("premium") < 0.0).fill_null(value=False).alias("_premium_was_negative"),
            pl.col("premium").fill_null(0.0).clip(0.0).alias("_premium"),
        )
    )
    counts = eligible.group_by("origin_id").agg(
        pl.col("created_at").max().alias("b2v2_max_created_at_utc"),
        pl.col("_premium_was_null").sum().cast(pl.Float64).alias("null_premium_count_5m"),
        pl.col("_premium_was_negative").sum().cast(pl.Float64).alias("negative_premium_count_5m"),
        pl.len().cast(pl.Float64).alias("option_trade_count_5m"),
        pl.col("option_chain_id").n_unique().cast(pl.Float64).alias("unique_contract_count_5m"),
        pl.col("_premium").sum().alias("total_premium_5m"),
        pl.col("_premium").max().alias("max_trade_premium_5m"),
        pl.when(pl.col("option_type").str.to_lowercase() == "call")
        .then(pl.col("_premium"))
        .otherwise(0.0)
        .sum()
        .alias("call_premium_5m"),
        pl.when(pl.col("option_type").str.to_lowercase() == "put")
        .then(pl.col("_premium"))
        .otherwise(0.0)
        .sum()
        .alias("put_premium_5m"),
        pl.when(pl.col("tags").fill_null("").str.contains("ask_side"))
        .then(pl.col("_premium"))
        .otherwise(0.0)
        .sum()
        .alias("_ask_premium"),
        pl.when(pl.col("tags").fill_null("").str.contains("bid_side"))
        .then(pl.col("_premium"))
        .otherwise(0.0)
        .sum()
        .alias("_bid_premium"),
    )
    repeated = (
        eligible.group_by("origin_id", "option_chain_id")
        .agg(pl.len().alias("_n"), pl.col("_premium").sum().alias("_premium"))
        .filter(pl.col("_n") > 1)
        .group_by("origin_id")
        .agg(pl.col("_premium").sum().alias("repeated_contract_premium"))
    )
    strikes = (
        eligible.filter(pl.col("strike").is_not_null())
        .group_by("origin_id", "strike")
        .len()
        .group_by("origin_id")
        .agg((pl.col("len").max() / pl.col("len").sum()).alias("strike_concentration"))
    )
    expiries = (
        eligible.filter(pl.col("expiry").is_not_null())
        .group_by("origin_id", "expiry")
        .len()
        .group_by("origin_id")
        .agg((pl.col("len").max() / pl.col("len").sum()).alias("expiry_concentration"))
    )
    activity = (
        origin_key.join(counts, on="origin_id", how="left", validate="1:1")
        .join(repeated, on="origin_id", how="left", validate="1:1")
        .join(strikes, on="origin_id", how="left", validate="1:1")
        .join(expiries, on="origin_id", how="left", validate="1:1")
        .with_columns(
            pl.col(column).fill_null(0.0)
            for column in (
                "option_trade_count_5m",
                "unique_contract_count_5m",
                "null_premium_count_5m",
                "negative_premium_count_5m",
                "total_premium_5m",
                "max_trade_premium_5m",
                "call_premium_5m",
                "put_premium_5m",
                "_ask_premium",
                "_bid_premium",
                "repeated_contract_premium",
                "strike_concentration",
                "expiry_concentration",
            )
        )
        .with_columns(
            pl.when(pl.col("total_premium_5m") > 0)
            .then(pl.col("_ask_premium") / pl.col("total_premium_5m"))
            .otherwise(0.0)
            .alias("ask_side_premium_share"),
            pl.when(pl.col("total_premium_5m") > 0)
            .then(pl.col("_bid_premium") / pl.col("total_premium_5m"))
            .otherwise(0.0)
            .alias("bid_side_premium_share"),
        )
        .drop("_ask_premium", "_bid_premium")
    )
    return activity


def build_b2v2_features(
    trades: pl.DataFrame,
    origins: pl.DataFrame,
    window_minutes: int = 5,
) -> pl.DataFrame:
    """Construct normalized B2v2 features from individual Full Tape rows."""
    return build_b2v2_from_activity(aggregate_b2_activity(trades, origins, window_minutes), origins)


def build_b2v2_from_activity(
    activity: pl.DataFrame,
    origins: pl.DataFrame,
) -> pl.DataFrame:
    """Build the nine target-blind B2v2 features from per-origin activity.

    Only the most recent sixty strictly prior sessions are eligible. At least
    twenty prior sessions are required; warm-up rows remain explicitly
    incomplete and may only contribute to later history.
    """
    forbidden = {
        column
        for column in (*activity.columns, *origins.columns)
        if column.lower() in {"rv30", "qlike", "target"} or column.lower().startswith("rv30_")
    }
    if forbidden:
        raise ValueError("B2V2_TARGET_COLUMN_FORBIDDEN")
    required_origins = {
        "origin_id",
        "asset",
        "session_date",
        "forecast_origin_utc",
    }
    if not required_origins <= set(origins.columns):
        raise ValueError("B2V2_ORIGIN_COLUMNS_MISSING")
    if origins["origin_id"].n_unique() != origins.height:
        raise ValueError("B2V2_ORIGIN_ID_DUPLICATE")
    missing_raw = RAW_B2_COLUMNS - set(activity.columns)
    if missing_raw:
        raise ValueError(f"B2_RAW_FEATURES_MISSING:{','.join(sorted(missing_raw))}")
    if activity["origin_id"].n_unique() != activity.height:
        raise ValueError("B2V2_ACTIVITY_ORIGIN_DUPLICATE")

    evidence_columns = [
        column
        for column in ("b2v2_cutoff_utc", "b2v2_max_created_at_utc")
        if column in activity.columns
    ]
    raw = origins.select(sorted(required_origins)).join(
        activity.select("origin_id", *sorted(RAW_B2_COLUMNS), *evidence_columns),
        on="origin_id",
        how="left",
        validate="1:1",
    )
    raw = raw.with_columns(pl.col(column).fill_null(0.0) for column in sorted(RAW_B2_COLUMNS))
    compact = add_compact_b2_features(raw)
    source_to_output = dict(zip(B2_FEATURE_NAMES, B2V2_FEATURES, strict=True))
    records = (
        compact.select(
            "origin_id",
            "asset",
            "session_date",
            "forecast_origin_utc",
            *B2_FEATURE_NAMES,
            *evidence_columns,
        )
        .sort(["asset", "session_date", "forecast_origin_utc"])
        .to_dicts()
    )
    for row in records:
        row["_band"] = _phase6_band(row["forecast_origin_utc"])

    dates_by_asset: dict[str, list[str]] = {}
    rows_by_asset_date: dict[tuple[str, str], list[dict[str, Any]]] = {}
    rows_by_asset_band_date: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    current_groups: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for row in records:
        asset, day, band = row["asset"], row["session_date"], row["_band"]
        rows_by_asset_date.setdefault((asset, day), []).append(row)
        rows_by_asset_band_date.setdefault((asset, band, day), []).append(row)
        current_groups.setdefault((asset, band, day), []).append(row)
    for asset in {row["asset"] for row in records}:
        dates_by_asset[asset] = sorted(
            day for candidate, day in rows_by_asset_date if candidate == asset
        )

    output: list[dict[str, Any]] = []
    for (asset, band, day), current_rows in sorted(current_groups.items()):
        date_index = dates_by_asset[asset].index(day)
        prior_dates = dates_by_asset[asset][max(0, date_index - 60) : date_index]
        complete = len(prior_dates) >= 20
        parameters: dict[str, tuple[float, float, str]] = {}
        for source, destination in source_to_output.items():
            if not complete:
                continue
            band_values = [
                float(row[source])
                for prior_day in prior_dates
                for row in rows_by_asset_band_date.get((asset, band, prior_day), [])
            ]
            asset_values = [
                float(row[source])
                for prior_day in prior_dates
                for row in rows_by_asset_date.get((asset, prior_day), [])
            ]
            parameters[destination] = _robust_parameters(band_values, asset_values)
        for current in current_rows:
            result = {
                key: current[key]
                for key in (
                    "origin_id",
                    "asset",
                    "session_date",
                    "forecast_origin_utc",
                    *evidence_columns,
                )
            }
            labels: list[str] = []
            for source, destination in source_to_output.items():
                if not complete:
                    result[destination] = 0.0
                    labels.append("INSUFFICIENT_PRIOR_SESSIONS")
                    continue
                center, scale, label = parameters[destination]
                result[destination] = (float(current[source]) - center) / scale if scale else 0.0
                labels.append(label)
            result["b2v2_complete"] = complete
            result["b2v2_history_sessions"] = len(prior_dates)
            result["b2v2_normalization_labels"] = ";".join(sorted(set(labels)))
            output.append(result)
    return pl.DataFrame(output, infer_schema_length=None).sort(
        ["asset", "session_date", "forecast_origin_utc"]
    )


def build_phase6_origins(
    session_dates: Sequence[str],
    *,
    assets: Sequence[str] = OUTCOME_ASSETS,
) -> pl.DataFrame:
    """Create every five-minute origin with room for a full RV30 target.

    Parameters
    ----------
    session_dates:
        Ordered XNYS dates from the frozen Phase 6 allow-list.
    assets:
        Outcome assets to materialize; defaults to the six registered assets.

    Returns
    -------
    polars.DataFrame
        Deterministically ordered origins from open plus five minutes through
        close minus thirty minutes, inclusive. Early closes use their actual
        XNYS close.

    Raises
    ------
    ValueError
        If a date or asset is outside the frozen contract.
    """
    contract = {row["session_date"]: row["role"] for row in phase6_sessions()}
    if len(session_dates) != len(set(session_dates)):
        raise ValueError("PHASE6_ORIGIN_SESSION_DUPLICATE")
    if any(day not in contract for day in session_dates):
        raise ValueError("PHASE6_ORIGIN_SESSION_NOT_AUTHORIZED")
    if not assets or any(asset not in OUTCOME_ASSETS for asset in assets):
        raise ValueError("PHASE6_ORIGIN_ASSET_NOT_AUTHORIZED")

    calendar = xcals.get_calendar("XNYS")
    rows: list[dict[str, Any]] = []
    for day_text in session_dates:
        day = date.fromisoformat(day_text)
        session_open = calendar.session_open(day).to_pydatetime()
        session_close = calendar.session_close(day).to_pydatetime()
        last_origin = session_close - timedelta(minutes=30)
        origin = session_open + timedelta(minutes=5)
        while origin <= last_origin:
            minute = int((origin - session_open).total_seconds() // 60)
            segment = "first" if minute < 130 else "middle" if minute < 260 else "last"
            for asset in assets:
                rows.append(
                    {
                        "origin_id": f"{asset}:{origin.isoformat()}",
                        "asset": asset,
                        "session_date": day_text,
                        "forecast_origin_utc": origin,
                        "forecast_origin_ny": origin.astimezone(_NEW_YORK),
                        "session_minute": minute,
                        "session_tercile": segment,
                        "role": contract[day_text],
                    }
                )
            origin += timedelta(minutes=5)
    return pl.DataFrame(rows, infer_schema_length=None).sort(
        ["session_date", "forecast_origin_utc", "asset"]
    )


def _exact_bar_window(
    index: Mapping[datetime, Mapping[str, Any]],
    *,
    end: datetime,
    return_count: int,
) -> list[Mapping[str, Any]] | None:
    """Return consecutive one-minute bars ending at ``end``."""
    timestamps = [end - timedelta(minutes=offset) for offset in range(return_count, -1, -1)]
    rows = [index.get(timestamp) for timestamp in timestamps]
    return None if any(row is None for row in rows) else [row for row in rows if row]


def _log_returns(rows: Sequence[Mapping[str, Any]]) -> list[float]:
    """Calculate log returns after enforcing finite, positive closes."""
    closes = [float(row["close"]) for row in rows]
    if any(not math.isfinite(value) or value <= 0 for value in closes):
        raise ValueError("B0V2_CLOSE_NOT_POSITIVE")
    return [
        math.log(current / previous) for previous, current in zip(closes, closes[1:], strict=False)
    ]


def build_b0v2_features(
    bars: pl.DataFrame,
    origins: pl.DataFrame,
    *,
    delay_minutes: int = 1,
    include_target: bool = True,
) -> pl.DataFrame:
    """Build causal B0v2 predictors and exact RV30 targets.

    Parameters
    ----------
    bars:
        Exact-session FMP one-minute bars for outcome assets, SPY and QQQ.
        ``available_at_utc`` must encode the registered conservative delay.
    origins:
        Unique asset/session five-minute forecast origins.
    delay_minutes:
        Conservative predictor availability delay, registered as one or two
        minutes.
    include_target:
        Whether to read the thirty-one closes needed for RV30.  Set to
        ``False`` for target-free timing sensitivities; predictor construction
        remains identical and no future closes are inspected.

    Returns
    -------
    polars.DataFrame
        One traceable row per input origin. Invalid targets remain present with
        ``rv30=null`` and an explicit ``drop_reason``; prices are never filled.

    Raises
    ------
    ValueError
        If schemas, uniqueness or point-in-time availability are violated.

    Examples
    --------
    ``build_b0v2_features(bars, origins).select("origin_id", "rv30")``
    returns the immutable origin key and its exact 30-return target.
    """
    required_bars = {
        "asset",
        "session_date",
        "bar_timestamp_raw_utc",
        "available_at_utc",
        "close",
        "volume",
    }
    required_origins = {
        "origin_id",
        "asset",
        "session_date",
        "forecast_origin_utc",
    }
    if delay_minutes not in {1, 2}:
        raise ValueError("B0V2_DELAY_NOT_REGISTERED")
    if not required_bars.issubset(bars.columns):
        raise ValueError("B0V2_BAR_SCHEMA_INVALID")
    if not required_origins.issubset(origins.columns):
        raise ValueError("B0V2_ORIGIN_SCHEMA_INVALID")
    if origins["origin_id"].n_unique() != origins.height:
        raise ValueError("B0V2_DUPLICATE_ORIGIN")

    indexed: dict[tuple[str, str], dict[datetime, Mapping[str, Any]]] = {}
    for row in bars.iter_rows(named=True):
        key = (str(row["asset"]), str(row["session_date"]))
        timestamp = row["bar_timestamp_raw_utc"]
        if not isinstance(timestamp, datetime):
            raise ValueError("B0V2_BAR_TIMESTAMP_INVALID")
        session = indexed.setdefault(key, {})
        if timestamp in session:
            raise ValueError("B0V2_DUPLICATE_BAR")
        session[timestamp] = row

    output: list[dict[str, Any]] = []
    for origin_row in origins.sort("origin_id").iter_rows(named=True):
        origin = origin_row["forecast_origin_utc"]
        if not isinstance(origin, datetime) or origin.tzinfo is None:
            raise ValueError("B0V2_ORIGIN_TIMESTAMP_INVALID")
        asset = str(origin_row["asset"])
        session_date = str(origin_row["session_date"])
        anchor_timestamp = origin - timedelta(minutes=1)
        predictor_anchor_timestamp = origin - timedelta(minutes=delay_minutes)
        asset_index = indexed.get((asset, session_date), {})
        anchor = asset_index.get(anchor_timestamp)
        predictor_anchor = asset_index.get(predictor_anchor_timestamp)
        base: dict[str, Any] = {
            "origin_id": str(origin_row["origin_id"]),
            "asset": asset,
            "session_date": session_date,
            "forecast_origin_utc": origin,
            "anchor_timestamp_raw_utc": anchor_timestamp,
            "predictor_anchor_timestamp_raw_utc": predictor_anchor_timestamp,
            "role": origin_row.get("role"),
            "session_minute": origin_row.get("session_minute"),
            "session_tercile": origin_row.get("session_tercile"),
            "target_price_count": 0,
            "target_return_count": 0,
            "rv30": None,
            "max_predictor_available_at_utc": None,
            "drop_reason": None,
            **{feature: None for feature in B0V2_FEATURES},
        }
        if anchor is None:
            output.append({**base, "drop_reason": "RV30_ORIGIN_CLOSE_MISSING"})
            continue
        target_price_count = 0
        target_return_count = 0
        rv30: float | None = None
        target_drop_reason: str | None = None
        if include_target:
            target_timestamps = [
                anchor_timestamp + timedelta(minutes=offset) for offset in range(31)
            ]
            target_rows = [asset_index.get(timestamp) for timestamp in target_timestamps]
            target_price_count = sum(row is not None for row in target_rows)
            target_drop_reason = "RV30_CONSECUTIVE_CLOSE_MISSING"
            if target_price_count == 31:
                target_closes = [float(row["close"]) for row in target_rows if row]
                rv30 = compute_realized_variance(target_closes[0], target_closes[1:])
                target_return_count = 30
                target_drop_reason = None
        base.update(
            {
                "target_price_count": target_price_count,
                "target_return_count": target_return_count,
                "rv30": rv30,
            }
        )
        if predictor_anchor is None:
            output.append({**base, "drop_reason": "B0V2_PREDICTOR_ANCHOR_MISSING"})
            continue
        if predictor_anchor["available_at_utc"] > origin:
            raise ValueError("B0V2_ORIGIN_CLOSE_NOT_AVAILABLE")

        underlying_30 = _exact_bar_window(
            asset_index,
            end=predictor_anchor_timestamp,
            return_count=30,
        )
        if underlying_30 is None:
            output.append({**base, "drop_reason": "B0V2_UNDERLYING_HISTORY_MISSING"})
            continue
        if any(row["available_at_utc"] > origin for row in underlying_30):
            raise ValueError("B0V2_FUTURE_PREDICTOR")
        underlying_returns_30 = _log_returns(underlying_30)
        underlying_returns_5 = underlying_returns_30[-5:]

        control_values: dict[str, float] = {}
        predictor_rows: list[Mapping[str, Any]] = list(underlying_30)
        controls_valid = True
        for control in MARKET_CONTROLS:
            control_30 = _exact_bar_window(
                indexed.get((control, session_date), {}),
                end=predictor_anchor_timestamp,
                return_count=30,
            )
            if control_30 is None:
                controls_valid = False
                break
            if any(row["available_at_utc"] > origin for row in control_30):
                raise ValueError("B0V2_FUTURE_PREDICTOR")
            returns = _log_returns(control_30)
            prefix = control.lower()
            control_values[f"b0v2_{prefix}_return_5m"] = sum(returns[-5:])
            control_values[f"b0v2_{prefix}_rv_30m"] = sum(value * value for value in returns)
            predictor_rows.extend(control_30)
        if not controls_valid:
            output.append({**base, "drop_reason": "B0V2_MARKET_CONTROL_MISSING"})
            continue

        recent_underlying = underlying_30[-5:]
        dollar_volume = sum(float(row["close"]) * float(row["volume"]) for row in recent_underlying)
        if not math.isfinite(dollar_volume) or dollar_volume <= 0:
            output.append({**base, "drop_reason": "B0V2_DOLLAR_VOLUME_NOT_POSITIVE"})
            continue
        minute = (
            origin.astimezone(_NEW_YORK).hour * 60
            + origin.astimezone(_NEW_YORK).minute
            - (9 * 60 + 30)
        )
        angle = 2.0 * math.pi * minute / 390.0

        max_available = max(row["available_at_utc"] for row in predictor_rows)
        output.append(
            {
                **base,
                "target_price_count": target_price_count,
                "target_return_count": target_return_count,
                "rv30": rv30,
                "max_predictor_available_at_utc": max_available,
                "drop_reason": target_drop_reason,
                "b0v2_log_spot": math.log(float(predictor_anchor["close"])),
                "b0v2_underlying_return_5m": sum(underlying_returns_5),
                "b0v2_underlying_rv_5m": sum(value * value for value in underlying_returns_5),
                "b0v2_underlying_rv_30m": sum(value * value for value in underlying_returns_30),
                "b0v2_log_dollar_volume_5m": math.log(dollar_volume),
                **control_values,
                "b0v2_session_sine": math.sin(angle),
                "b0v2_session_cosine": math.cos(angle),
                "b0v2_asset_identity": asset,
            }
        )
    return pl.DataFrame(output, infer_schema_length=None, strict=False)


def _b1_atm_iv(rows: Sequence[Mapping[str, Any]]) -> float | None:
    """Return ATM IV, interpolating across the nearest surrounding strikes."""
    if not rows:
        return None
    below = sorted(
        (row for row in rows if float(row["moneyness"]) <= 1.0),
        key=lambda row: 1.0 - float(row["moneyness"]),
    )
    above = sorted(
        (row for row in rows if float(row["moneyness"]) >= 1.0),
        key=lambda row: float(row["moneyness"]) - 1.0,
    )
    if below and above:
        low, high = below[0], above[0]
        low_m, high_m = float(low["moneyness"]), float(high["moneyness"])
        if low["contract"] == high["contract"] or low_m == high_m:
            return float(low["implied_volatility"])
        weight = (1.0 - low_m) / (high_m - low_m)
        return float(low["implied_volatility"]) + weight * (
            float(high["implied_volatility"]) - float(low["implied_volatility"])
        )
    closest = min(rows, key=lambda row: abs(float(row["moneyness"]) - 1.0))
    return float(closest["implied_volatility"])


def _b1_skew(rows: Sequence[Mapping[str, Any]]) -> float | None:
    """Return same-expiry symmetric-moneyness put-minus-call IV skew."""
    by_expiry: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        by_expiry.setdefault(str(row["expiry"]), []).append(row)
    candidates: list[tuple[float, float]] = []
    for expiry_rows in by_expiry.values():
        puts = [
            row
            for row in expiry_rows
            if str(row["option_type"]).lower() == "put" and float(row["moneyness"]) <= 0.99
        ]
        calls = [
            row
            for row in expiry_rows
            if str(row["option_type"]).lower() == "call" and float(row["moneyness"]) >= 1.01
        ]
        if not puts or not calls:
            continue
        put = min(puts, key=lambda row: abs(float(row["moneyness"]) - 0.975))
        call = min(calls, key=lambda row: abs(float(row["moneyness"]) - 1.025))
        distance = abs(float(put["moneyness"]) - 0.975) + abs(float(call["moneyness"]) - 1.025)
        candidates.append(
            (
                distance,
                float(put["implied_volatility"]) - float(call["implied_volatility"]),
            )
        )
    return min(candidates)[1] if candidates else None


def _b1_level_summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, float | None]:
    """Summarize valid contract states into registered B1v2 levels."""
    buckets = {
        "short": [row for row in rows if 7 <= int(row["dte"]) <= 21],
        "medium": [row for row in rows if 30 <= int(row["dte"]) <= 60],
        "long": [row for row in rows if 90 <= int(row["dte"]) <= 180],
    }
    atm = {name: _b1_atm_iv(values) for name, values in buckets.items()}
    return {
        "b1v2_atm_iv_30_60_dte": atm["medium"],
        "b1v2_skew_symmetric_moneyness": _b1_skew(buckets["medium"]),
        "b1v2_term_short_to_medium": (
            atm["medium"] - atm["short"]
            if atm["short"] is not None and atm["medium"] is not None
            else None
        ),
        "b1v2_term_medium_to_long": (
            atm["long"] - atm["medium"]
            if atm["medium"] is not None and atm["long"] is not None
            else None
        ),
    }


def _b1_change(
    current: Mapping[str, Any],
    previous: Mapping[str, Any] | None,
    feature: str,
) -> float | None:
    """Return an exact-lag level change without filling missing history."""
    current_value = current.get(feature)
    prior_value = previous.get(feature) if previous else None
    return (
        float(current_value) - float(prior_value)
        if current_value is not None and prior_value is not None
        else None
    )


def build_b1v2_features(
    origins: pl.DataFrame,
    option_states: pl.DataFrame,
) -> pl.DataFrame:
    """Build nested ordinary-option-state features at each forecast origin.

    ``option_states`` contains quote/IV candidates already tied to an origin.
    The latest quote per contract with SIP time at or before that origin is
    selected locally. Quotes must satisfy the preregistered 60-second age and
    25-percent relative-spread filters. No missing component is imputed.

    Parameters
    ----------
    origins:
        Unique Phase 6 forecast origins.
    option_states:
        Per-origin contract candidates with historical SIP timestamps and IV.

    Returns
    -------
    polars.DataFrame
        One row per origin with B1v2 levels, changes, diagnostics and nested
        completion flags.

    Raises
    ------
    ValueError
        If schemas, timestamps, origin keys or nested PIT invariants fail.
    """
    required_origins = {
        "origin_id",
        "asset",
        "session_date",
        "forecast_origin_utc",
        "session_tercile",
    }
    required_states = {
        "origin_id",
        "contract",
        "expiry",
        "option_type",
        "dte",
        "moneyness",
        "sip_timestamp_ns",
        "bid",
        "ask",
        "implied_volatility",
    }
    if not required_origins.issubset(origins.columns):
        raise ValueError("B1V2_ORIGIN_SCHEMA_INVALID")
    if not required_states.issubset(option_states.columns):
        raise ValueError("B1V2_OPTION_STATE_SCHEMA_INVALID")
    if origins["origin_id"].n_unique() != origins.height:
        raise ValueError("B1V2_DUPLICATE_ORIGIN")

    origin_ids = set(str(value) for value in origins["origin_id"].to_list())
    candidates: dict[str, dict[str, list[Mapping[str, Any]]]] = {}
    for row in option_states.iter_rows(named=True):
        origin_id = str(row["origin_id"])
        if origin_id not in origin_ids:
            raise ValueError("B1V2_UNKNOWN_ORIGIN")
        candidates.setdefault(origin_id, {}).setdefault(str(row["contract"]), []).append(row)

    levels: list[dict[str, Any]] = []
    for origin_row in origins.sort(["asset", "session_date", "forecast_origin_utc"]).iter_rows(
        named=True
    ):
        origin = origin_row["forecast_origin_utc"]
        if not isinstance(origin, datetime) or origin.tzinfo is None:
            raise ValueError("B1V2_ORIGIN_TIMESTAMP_INVALID")
        origin_ns = int(origin.timestamp() * 1_000_000_000)
        selected: list[Mapping[str, Any]] = []
        valid: list[dict[str, Any]] = []
        for rows in candidates.get(str(origin_row["origin_id"]), {}).values():
            eligible = [
                row
                for row in rows
                if isinstance(row["sip_timestamp_ns"], int)
                and int(row["sip_timestamp_ns"]) <= origin_ns
            ]
            if not eligible:
                continue
            quote = max(eligible, key=lambda row: int(row["sip_timestamp_ns"]))
            selected.append(quote)
            try:
                bid, ask = float(quote["bid"]), float(quote["ask"])
                iv = float(quote["implied_volatility"])
            except (TypeError, ValueError):
                continue
            midpoint = (bid + ask) / 2.0
            age = (origin_ns - int(quote["sip_timestamp_ns"])) / 1e9
            spread = (ask - bid) / midpoint if midpoint > 0 else math.inf
            if (
                bid > 0
                and ask > bid
                and age <= 60.0
                and spread <= 0.25
                and math.isfinite(iv)
                and iv > 0
            ):
                valid.append({**quote, "midpoint": midpoint})
        summary = _b1_level_summary(valid)
        timestamps = [int(row["sip_timestamp_ns"]) for row in selected]
        midpoints = sorted(float(row["bid"] + row["ask"]) / 2.0 for row in valid)
        levels.append(
            {
                **origin_row,
                "forecast_origin_ns": origin_ns,
                "max_sip_timestamp_ns": max(timestamps) if timestamps else None,
                "selected_midpoint": (midpoints[len(midpoints) // 2] if midpoints else None),
                "valid_contract_count": len(valid),
                **summary,
            }
        )

    by_time = {
        (str(row["asset"]), str(row["session_date"]), row["forecast_origin_utc"]): row
        for row in levels
    }
    output: list[dict[str, Any]] = []
    for row in levels:
        origin = row["forecast_origin_utc"]
        key = (str(row["asset"]), str(row["session_date"]))
        previous_5 = by_time.get((*key, origin - timedelta(minutes=5)))
        previous_30 = by_time.get((*key, origin - timedelta(minutes=30)))

        enriched = {
            **row,
            "b1v2_atm_iv_change_5m": _b1_change(row, previous_5, "b1v2_atm_iv_30_60_dte"),
            "b1v2_atm_iv_change_30m": _b1_change(row, previous_30, "b1v2_atm_iv_30_60_dte"),
            "b1v2_skew_change_30m": _b1_change(row, previous_30, "b1v2_skew_symmetric_moneyness"),
            "b1v2_term_short_to_medium_change_30m": _b1_change(
                row, previous_30, "b1v2_term_short_to_medium"
            ),
            "b1v2_term_medium_to_long_change_30m": _b1_change(
                row, previous_30, "b1v2_term_medium_to_long"
            ),
        }
        enriched["b1v2a_complete"] = all(
            enriched.get(feature) is not None for feature in B1V2A_FEATURES
        )
        enriched["b1v2b_complete"] = bool(enriched["b1v2a_complete"]) and all(
            enriched.get(feature) is not None for feature in B1V2B_FEATURES
        )
        enriched["b1v2c_complete"] = bool(enriched["b1v2b_complete"]) and all(
            enriched.get(feature) is not None for feature in B1V2C_FEATURES
        )
        enriched["b1v2_missing_reason"] = (
            None if enriched["b1v2a_complete"] else "B1V2A_HISTORY_OR_STATE_MISSING"
        )
        output.append(enriched)

    frame = pl.DataFrame(output, infer_schema_length=None, strict=False)
    if frame.filter(
        pl.col("max_sip_timestamp_ns").is_not_null()
        & (pl.col("max_sip_timestamp_ns") > pl.col("forecast_origin_ns"))
    ).height:
        raise ValueError("B1V2_FUTURE_QUOTE")
    if frame.filter(pl.col("b1v2c_complete") & ~pl.col("b1v2b_complete")).height:
        raise ValueError("B1V2_NESTED_INVARIANT_FAILURE")
    if frame.filter(pl.col("b1v2b_complete") & ~pl.col("b1v2a_complete")).height:
        raise ValueError("B1V2_NESTED_INVARIANT_FAILURE")
    return frame


def b1v2_coverage_status(frame: pl.DataFrame) -> str:
    """Apply the preregistered B1v2a global, asset and tercile gates."""
    required = {"asset", "session_tercile", "b1v2a_complete"}
    if frame.is_empty() or not required.issubset(frame.columns):
        return "REVISE_B1V2"
    global_coverage_value = frame["b1v2a_complete"].mean()
    asset_min_value = (
        frame.group_by("asset")
        .agg(pl.col("b1v2a_complete").mean().alias("coverage"))["coverage"]
        .min()
    )
    tercile_min_value = (
        frame.group_by("session_tercile")
        .agg(pl.col("b1v2a_complete").mean().alias("coverage"))["coverage"]
        .min()
    )
    if (
        not isinstance(global_coverage_value, int | float)
        or not isinstance(asset_min_value, int | float)
        or not isinstance(tercile_min_value, int | float)
    ):
        return "REVISE_B1V2"
    global_coverage = float(global_coverage_value)
    asset_min = float(asset_min_value)
    tercile_min = float(tercile_min_value)
    return (
        "PASS_B1V2A_COVERAGE"
        if global_coverage >= 0.80 and asset_min >= 0.65 and tercile_min >= 0.60
        else "REVISE_B1V2"
    )


def continuity_verdict(rows: Sequence[Mapping[str, object]], expected_dates: set[str]) -> str:
    """Return the fail-closed provider-continuity decision.

    Parameters
    ----------
    rows:
        One provider-status record per asset and expected session.
    expected_dates:
        Exact frozen session allow-list.

    Returns
    -------
    str
        Stable PASS or blocker code.
    """
    expected_keys = {
        (day, asset) for day in expected_dates for asset in (*OUTCOME_ASSETS, *MARKET_CONTROLS)
    }
    observed_keys = [(str(row.get("date", "")), str(row.get("asset", ""))) for row in rows]
    if len(observed_keys) != len(set(observed_keys)):
        return "REPLICATION_CONTINUITY_DUPLICATE"
    if set(observed_keys) != expected_keys:
        return "REPLICATION_SESSION_ALLOWLIST_INCOMPLETE"
    required_passes = (
        "fmp_provider_available",
        "uw_file_metadata_pass",
        "massive_quote_pass",
    )
    if any(row.get(field) is not True for row in rows for field in required_passes):
        return "PROVIDER_CONTINUITY_FAILURE"
    return "PASS_PHASE6_CONTINUITY"


def phase6_storage_preflight(
    config: Phase5StorageConfig, session_count: int = 180
) -> dict[str, object]:
    """Run the existing storage gate and add a Phase 6 status code.

    Parameters
    ----------
    config:
        Existing validated storage configuration.
    session_count:
        Exact authorized session count.

    Returns
    -------
    dict[str, object]
        Sanitized storage evidence with a stable Phase 6 status.
    """
    if len(config.sessions) != session_count:
        return {"status": "REPLICATION_SESSION_ALLOWLIST_INCOMPLETE"}
    try:
        evidence = storage_preflight(config)
    except RuntimeError as error:
        status = (
            "STORAGE_FLOOR_BREACH"
            if str(error) == "PROJECTED_MINIMUM_FREE_SPACE_BELOW_FLOOR"
            else str(error)
        )
        return {"status": status}
    return {"status": "PASS_PHASE6_STORAGE", **evidence}


def phase6_sessions() -> list[dict[str, str]]:
    """Return the exact ordered Phase 6 XNYS session allow-list.

    Returns
    -------
    list[dict[str, str]]
        One date/role record for each of 180 sessions.

    Raises
    ------
    ValueError
        If a registered boundary is not an XNYS session or its count drifts.
    """
    calendar = xcals.get_calendar("XNYS")
    rows: list[dict[str, str]] = []
    for role, start_text, end_text, expected_count in PHASE6_BLOCKS:
        sessions = calendar.sessions_in_range(
            date.fromisoformat(start_text),
            date.fromisoformat(end_text),
        )
        dates = [value.date().isoformat() for value in sessions]
        if (
            len(dates) != expected_count
            or not dates
            or dates[0] != start_text
            or dates[-1] != end_text
        ):
            raise ValueError(f"PHASE6_SESSION_BLOCK_INVALID:{role}")
        rows.extend({"session_date": session_date, "role": role} for session_date in dates)

    unique_dates = {row["session_date"] for row in rows}
    if len(rows) != 180 or len(unique_dates) != 180:
        raise ValueError("PHASE6_SESSION_ALLOWLIST_INVALID")
    return rows


def phase6_folds() -> list[dict[str, object]]:
    """Build the five frozen expanding Phase 6 folds.

    Returns
    -------
    list[dict[str, object]]
        Five records with past-only training dates and twenty test dates.

    Raises
    ------
    ValueError
        If fold counts, ordering or disjointness drift.
    """
    rows = phase6_sessions()
    initial_train = [row["session_date"] for row in rows if row["role"] == "initial_train"]
    previous_tests: list[str] = []
    folds: list[dict[str, object]] = []
    for fold_number in range(1, 6):
        test_dates = [
            row["session_date"] for row in rows if row["role"] == f"oos_fold_{fold_number}"
        ]
        train_dates = [*initial_train, *previous_tests]
        if (
            len(train_dates) != 60 + 20 * (fold_number - 1)
            or len(test_dates) != 20
            or set(train_dates) & set(test_dates)
            or max(train_dates) >= min(test_dates)
        ):
            raise ValueError(f"PHASE6_FOLD_INVALID:{fold_number}")
        folds.append(
            {
                "fold": fold_number,
                "train_dates": train_dates,
                "test_dates": test_dates,
                "train_count": len(train_dates),
                "test_count": len(test_dates),
            }
        )
        previous_tests.extend(test_dates)
    return folds


def _validate_provenance(provenance: Mapping[str, Any]) -> None:
    """Validate exact preregistration provenance without exposing source content."""
    if set(provenance) != _PROVENANCE_KEYS:
        raise ValueError("PHASE6_PROVENANCE_INVALID")
    if not isinstance(provenance["branch"], str) or not provenance["branch"]:
        raise ValueError("PHASE6_PROVENANCE_INVALID")
    commit = provenance["repository_commit"]
    if not isinstance(commit, str) or len(commit) != 40 or set(commit) - set("0123456789abcdef"):
        raise ValueError("PHASE6_PROVENANCE_INVALID")
    if not isinstance(provenance["python_version"], str) or not str(
        provenance["python_version"]
    ).startswith("3.12."):
        raise ValueError("PHASE6_PROVENANCE_INVALID")
    if not isinstance(provenance["worktree_dirty"], bool):
        raise ValueError("PHASE6_PROVENANCE_INVALID")
    for key in _HASH_KEYS:
        value = provenance[key]
        if not isinstance(value, str) or len(value) != 64 or set(value) - set("0123456789abcdef"):
            raise ValueError("PHASE6_PROVENANCE_INVALID")


def build_phase6_preregistration(provenance: Mapping[str, Any]) -> dict[str, Any]:
    """Build the outcome-blind Phase 6 preregistration.

    Parameters
    ----------
    provenance:
        Exact branch/runtime and governing-file hash record.

    Returns
    -------
    dict[str, Any]
        Self-hashed calendar, feature, model and inference contract.

    Raises
    ------
    ValueError
        If provenance or the derived session/fold contract is invalid.
    """
    _validate_provenance(provenance)
    sessions = phase6_sessions()
    folds = phase6_folds()
    session_payload = {"calendar": "XNYS", "sessions": sessions}
    manifest: dict[str, Any] = {
        "schema_version": "phase6-preregistration-1.0",
        "status": "FROZEN_BEFORE_OOS",
        "approved_on": "2026-08-01",
        "target": {
            "name": "RV30",
            "price_count": 31,
            "return_count": 30,
            "horizon_minutes": 30,
        },
        "session_manifest_sha256": canonical_sha256(session_payload),
        "sessions": sessions,
        "session_counts": {"warmup": 20, "initial_train": 60, "oos": 100, "total": 180},
        "folds": folds,
        "outcome_assets": list(OUTCOME_ASSETS),
        "market_controls": list(MARKET_CONTROLS),
        "information_sets": {
            "B0v2": list(B0V2_FEATURES),
            "B1v2a_addition": list(B1V2A_FEATURES),
            "B1v2b_addition": list(B1V2B_FEATURES),
            "B1v2c_addition": list(B1V2C_FEATURES),
            "B2v2_addition": list(B2V2_FEATURES),
        },
        "b2v2_feature_names": list(B2V2_FEATURES),
        "feature_design_outcome_blind": True,
        "timing": {
            "fmp_primary_delay_minutes": 1,
            "fmp_sensitivity_delay_minutes": 2,
            "uw_primary_delay_seconds": 60,
            "uw_sensitivity_delay_seconds": [120, 300],
            "b2_primary_window_minutes": 5,
            "b2_sensitivity_window_minutes": [15, 30],
            "created_at_semantics": "OPERATIONAL_AVAILABILITY_PROXY_NOT_PUBLICATION_TIME",
        },
        "b2v2_normalization": {
            "grouping": ["asset", "new_york_30_minute_band"],
            "history_sessions_max": 60,
            "history_sessions_min": 20,
            "history_rule": "PRIOR_SESSIONS_ONLY",
            "scale_fallback": ["MAD_1_4826", "IQR_DIV_1_349", "PRIOR_ASSET", "CONSTANT_ZERO"],
            "forbidden_inputs": ["RV30", "QLIKE", "MODEL_RESIDUAL", "OOS_RESULT"],
        },
        "b1v2_coverage": {
            "B1v2a": {"global_min": 0.80, "asset_min": 0.65, "session_tercile_min": 0.60},
            "B1v2b_B1v2c": {
                "global_min": 0.70,
                "asset_min": 0.50,
                "session_tercile_min": 0.40,
            },
            "failure_status": "REVISE_B1V2",
            "b2_vs_b0_fallback": False,
        },
        "models": {
            "confirmatory": {
                "name": "GammaRegressor",
                "link": "log_fixed_by_estimator",
                "alpha_grid": [0.0, 0.01, 0.1, 1.0],
                "max_iter": 2000,
                "tolerance": 1e-8,
            },
            "robustness": {
                "name": "LGBMRegressor",
                "objective": "gamma",
                "grid": {
                    "learning_rate": [0.03, 0.05],
                    "max_depth": [3, 5],
                    "min_child_samples": [50],
                    "n_estimators": [200, 500],
                    "num_leaves": [7, 15],
                    "reg_lambda": [1.0],
                },
            },
            "purge_embargo_minutes": 30,
            "selection": "CHRONOLOGICAL_TRAINING_ONLY",
        },
        "estimands": {
            "delta_b1v2": "QLIKE(B0v2)-QLIKE(B1v2a)",
            "delta_b2v2": "QLIKE(B1v2a)-QLIKE(B2v2)",
            "primary": "delta_b2v2",
            "key_secondary": "delta_b1v2",
            "positive_direction": "EXPANDED_INFORMATION_SET_BETTER",
        },
        "inference": {
            "primary_metric": "QLIKE",
            "descriptive_metrics": ["MAE", "RMSE"],
            "bootstrap_repetitions": 10_000,
            "bootstrap_cluster": "XNYS_SESSION_DATE_WITH_ALL_ASSETS",
            "multiplicity": "Holm",
            "global_holm_family": ["delta_b1v2", "delta_b2v2"],
            "targeted_holm_family": ["META", "MSFT", "last_session_tercile"],
            "mde": "TRAINING_ONLY_FROZEN_BEFORE_OOS",
            "seed": 650,
        },
        "stability": [
            "asset",
            "session_tercile",
            "training_defined_volatility_regime",
            "fmp_delay_1_vs_2_minutes",
            "uw_delay_60_120_300_seconds",
            "b2_window_5_15_30_minutes",
        ],
        "success_rules": {
            "positive_gamma_estimate": True,
            "bootstrap_lower_bound_above_zero": True,
            "holm_adjusted_p_below": 0.05,
            "effect_at_least_training_mde": True,
            "lightgbm_positive_sign": True,
            "positive_asset_estimates_min": 4,
            "materially_negative_asset_intervals_max": 1,
            "material_timing_reversal_allowed": False,
        },
        "stop_states": [
            "CRITICAL_SPEC_KIT_CONTRADICTION",
            "REPLICATION_SESSION_ALLOWLIST_INCOMPLETE",
            "STORAGE_FLOOR_BREACH",
            "REVISE_B1V2",
            "PIT_VIOLATION",
            "SCHEMA_DRIFT",
            "SECRET_LEAK",
            "HASH_MISMATCH",
        ],
        "outcome_reporting": "RETAIN_ALL_POSITIVE_NEGATIVE_AND_NULL_RESULTS",
        "oos_read_count": 0,
        "provenance": dict(provenance),
    }
    manifest["manifest_sha256"] = canonical_sha256(manifest)
    return manifest
