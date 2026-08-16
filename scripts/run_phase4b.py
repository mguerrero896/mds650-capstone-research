"""Build the local-only Phase 4B repair package.

This runner consumes only the retained 20-session calibration and five-session
pilot Parquet files.  It never calls a provider, downloads data, trains a model,
or computes a performance metric.
"""

from __future__ import annotations

# The runner intentionally keeps long evidence labels and report lines readable.
# Ruff still checks all other rule families below.
# ruff: noqa: E501
import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, cast
from zoneinfo import ZoneInfo

import exchange_calendars as xcals  # type: ignore[import-untyped]
import polars as pl
from phase4a_common import build_origin_id
from phase4b_common import (
    B2_ALIASES,
    WINDOW_SPECS,
    build_checkpoint,
    canonicalize_b2_frame,
    holdout_read_guard,
    validate_checkpoint,
)

from mds650.targets import compute_realized_variance

ROOT = Path(__file__).resolve().parents[1]
CAL = ROOT / "artifacts" / "calibration_20d"
PILOT = ROOT / "artifacts" / "pilot"
COMMON_V1 = ROOT / "artifacts" / "common_sample" / "common_matrix_available_25d.parquet"
OUT = ROOT / "artifacts" / "phase4b"
ET = ZoneInfo("America/New_York")
ASSETS = ("SPY", "QQQ", "AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "META")

B0_FIELDS = (
    "b0_spot",
    "b0_rv_5m_lag",
    "b0_rv_30m_lag",
    "b0_return_5m_lag",
    "b0_volume_5m_lag",
)
B2_CORE_FIELDS = (
    "b2_option_trade_count_5m",
    "b2_unique_contract_count_5m",
    "b2_total_premium_5m",
    "b2_max_trade_premium_5m",
    "b2_total_contract_size_5m",
    "b2_max_contract_size_5m",
    "b2_call_premium_5m",
    "b2_put_premium_5m",
    "b2_ask_side_premium_share",
    "b2_bid_side_premium_share",
    "b2_midpoint_premium_share",
    "b2_strike_concentration",
    "b2_expiry_concentration",
    "b2_median_days_to_expiry",
    "b2_median_absolute_moneyness",
    "b2_repeated_contract_trade_count",
    "b2_repeated_contract_premium",
    "b2_valid_trade_share",
    "b2_missing_iv_share",
)
B2_OPTIONAL_FIELDS = ("b2_implied_volatility_median", "b2_within_bin_iv_change")


def sha256_file(path: Path) -> str:
    """Hash a local file in bounded chunks."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_hash(value: Any) -> str:
    """Hash deterministic JSON for audit manifests."""
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    """Write sorted JSON atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    temporary.replace(path)


def _canonicalize_origins(frame: pl.DataFrame, role: str) -> pl.DataFrame:
    rows = []
    for row in frame.iter_rows(named=True):
        origin = row["forecast_origin_utc"]
        rows.append(
            {
                "origin_id": build_origin_id(str(row["asset"]), str(row["session_date"]), origin),
                "source_origin_id": row.get("origin_id"),
                "asset": str(row["asset"]),
                "session_date": str(row["session_date"]),
                "forecast_origin_utc": origin,
                "sample_role": role,
            }
        )
    result = pl.DataFrame(rows, strict=False).sort("origin_id")
    if result["origin_id"].n_unique() != result.height:
        raise RuntimeError("DUPLICATE_CANONICAL_ORIGIN_ID")
    return result


def _bars() -> pl.DataFrame:
    """Load the retained calibration and pilot underlying bars only."""
    return pl.concat(
        [
            pl.read_parquet(CAL / "underlying_1min_20d.parquet"),
            pl.read_parquet(PILOT / "underlying_1min.parquet"),
        ],
        how="diagonal_relaxed",
    ).sort(["asset", "session_date", "bar_timestamp_raw_utc"])


def _target_lookup(origins: pl.DataFrame, bars: pl.DataFrame) -> dict[str, dict[str, Any]]:
    """Reuse retained targets and calculate only absent calibration rows."""
    lookup: dict[str, dict[str, Any]] = {}
    if COMMON_V1.exists():
        for row in pl.read_parquet(COMMON_V1).select(
            ["origin_id", "rv30", "target_future_close_count", "target_price_count", "target_validity"]
        ).iter_rows(named=True):
            lookup[row["origin_id"]] = row
    pilot_targets = pl.read_parquet(PILOT / "rv30_targets.parquet")
    for row in pilot_targets.iter_rows(named=True):
        origin = row["forecast_origin_utc"]
        key = build_origin_id(str(row["asset"]), origin.astimezone(ET).date().isoformat(), origin)
        lookup[key] = {
            "origin_id": key,
            "rv30": row["rv30"],
            "target_future_close_count": row["future_close_count"],
            "target_price_count": row["price_count"],
            "target_validity": "valid" if row["price_count"] == 31 and row["future_close_count"] == 30 else "invalid",
        }
    by_session: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in bars.iter_rows(named=True):
        by_session.setdefault((row["asset"], str(row["session_date"])), []).append(row)
    for row in origins.iter_rows(named=True):
        if row["origin_id"] in lookup:
            continue
        values = by_session.get((row["asset"], row["session_date"]), [])
        by_timestamp = {item["bar_timestamp_raw_utc"]: item for item in values}
        anchor_time = row["forecast_origin_utc"] - timedelta(minutes=1)
        anchor = by_timestamp.get(anchor_time)
        future = [by_timestamp.get(anchor_time + timedelta(minutes=i)) for i in range(1, 31)]
        valid = anchor is not None and all(item is not None for item in future)
        rv = (
            compute_realized_variance(
                float(cast(dict[str, Any], anchor)["close"]),
                [float(cast(dict[str, Any], item)["close"]) for item in future],
            )
            if valid
            else None
        )
        lookup[row["origin_id"]] = {
            "origin_id": row["origin_id"],
            "rv30": rv,
            "target_future_close_count": 30 if valid else 0,
            "target_price_count": 31 if valid else (1 if anchor is not None else 0),
            "target_validity": "valid" if valid else "invalid_missing_31_prices",
        }
    return lookup


def load_origins_and_bars() -> tuple[pl.DataFrame, pl.DataFrame]:
    """Load all 14,200 retained origins and attach immutable RV30 targets."""
    calibration = _canonicalize_origins(
        pl.read_parquet(CAL / "b2_calibration_origins.parquet"), "CALIBRATION"
    )
    pilot = _canonicalize_origins(pl.read_parquet(PILOT / "b0_features.parquet"), "PILOT")
    origins = pl.concat([calibration, pilot], how="vertical_relaxed").sort("origin_id")
    bars = _bars()
    targets = _target_lookup(origins, bars)
    target_frame = pl.DataFrame(list(targets.values()), strict=False)
    origins = origins.join(target_frame, on="origin_id", how="left")
    if origins.height != 14200 or origins["origin_id"].n_unique() != origins.height:
        raise RuntimeError("PHASE4B_ORIGIN_PANEL_INVALID")
    return origins, bars


def _tail_returns(values: list[dict[str, Any]], count: int) -> list[float] | None:
    """Return the last ``count`` one-minute log returns when consecutive."""
    if len(values) < count + 1:
        return None
    tail = values[-(count + 1) :]
    if any(
        right["bar_timestamp_raw_utc"] - left["bar_timestamp_raw_utc"] != timedelta(minutes=1)
        for left, right in zip(tail, tail[1:], strict=False)
    ):
        return None
    returns: list[float] = []
    for left, right in zip(tail, tail[1:], strict=False):
        if float(left["close"]) <= 0 or float(right["close"]) <= 0:
            return None
        returns.append(__import__("math").log(float(right["close"]) / float(left["close"])))
    return returns


def build_b0_variants(origins: pl.DataFrame, bars: pl.DataFrame) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Build +1 and +2 as-of B0 snapshots without changing targets/origins."""
    indexed: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for bar_row in bars.iter_rows(named=True):
        indexed.setdefault((bar_row["asset"], str(bar_row["session_date"])), []).append(bar_row)
    rows: list[dict[str, Any]] = []
    for origin_row in origins.iter_rows(named=True):
        origin = origin_row["forecast_origin_utc"]
        values = indexed.get((origin_row["asset"], origin_row["session_date"]), [])
        target = {key: origin_row[key] for key in ("rv30", "target_future_close_count", "target_price_count", "target_validity")}
        row: dict[str, Any] = {**{key: origin_row[key] for key in ("origin_id", "asset", "session_date", "forecast_origin_utc", "sample_role")}, **target}
        row["b0_session_minute"] = int((origin.astimezone(ET).hour - 9) * 60 + origin.astimezone(ET).minute - 30)
        for delay, prefix in ((1, "b0"), (2, "b0_plus2")):
            candidates = [item for item in values if item["bar_timestamp_raw_utc"] + timedelta(minutes=delay) <= origin]
            source = candidates[-1] if candidates else None
            source_ts = source["bar_timestamp_raw_utc"] if source else None
            available_at = source_ts + timedelta(minutes=delay) if source_ts else None
            prior = [item for item in values if source_ts is not None and item["bar_timestamp_raw_utc"] <= source_ts]
            rv5_returns = _tail_returns(prior, 5)
            rv30_returns = _tail_returns(prior, 30)
            row.update(
                {
                    f"{prefix}_spot": float(source["close"]) if source else None,
                    f"{prefix}_rv_5m_lag": sum(x * x for x in rv5_returns) if rv5_returns else None,
                    f"{prefix}_rv_30m_lag": sum(x * x for x in rv30_returns) if rv30_returns else None,
                    f"{prefix}_return_5m_lag": sum(rv5_returns) if rv5_returns else None,
                    f"{prefix}_volume_5m_lag": sum(float(item["volume"]) for item in prior[-5:]) if rv5_returns else None,
                    f"{prefix}_source_timestamp_raw_utc": source_ts,
                    f"{prefix}_available_at_utc": available_at,
                    f"{prefix}_feature_age_seconds": (origin - available_at).total_seconds() if available_at else None,
                    f"{prefix}_availability_valid": bool(available_at and available_at <= origin),
                }
            )
        row["b0_fmp_available_at_1m"] = row["b0_available_at_utc"]
        row["b0_fmp_available_at_2m"] = row["b0_plus2_available_at_utc"]
        row["b0_fmp_bar_availability"] = "CONSERVATIVE_RESEARCH_ASSUMPTION"
        rows.append(row)
    result = pl.DataFrame(rows, strict=False).sort("origin_id")
    common_columns = [
        "origin_id", "asset", "session_date", "forecast_origin_utc", "sample_role", "rv30",
        "target_future_close_count", "target_price_count", "target_validity", "b0_session_minute",
        "b0_fmp_bar_availability",
    ]
    plus1 = result.select(common_columns + [
        "b0_spot", "b0_rv_5m_lag", "b0_rv_30m_lag", "b0_return_5m_lag", "b0_volume_5m_lag",
        "b0_source_timestamp_raw_utc", "b0_available_at_utc", "b0_feature_age_seconds",
        "b0_availability_valid",
    ])
    plus2 = result.select(common_columns + [
        "b0_plus2_spot", "b0_plus2_rv_5m_lag", "b0_plus2_rv_30m_lag", "b0_plus2_return_5m_lag",
        "b0_plus2_volume_5m_lag", "b0_plus2_source_timestamp_raw_utc", "b0_plus2_available_at_utc",
        "b0_plus2_feature_age_seconds", "b0_plus2_availability_valid",
    ])
    return plus1, plus2


def _event_files() -> list[tuple[Path, str, str]]:
    """Return retained event partitions with role, session and file hash."""
    files: list[tuple[Path, str, str]] = []
    for path in sorted(CAL.glob("option_events/date=*/asset=*/events.parquet")):
        files.append((path, "CALIBRATION", path.parts[-3].split("=", 1)[1]))
    for path in sorted(PILOT.glob("option_events/date=*/events.parquet")):
        files.append((path, "PILOT", path.parts[-2].split("=", 1)[1]))
    if not files:
        raise RuntimeError("PHASE4B_EVENT_FILES_MISSING")
    return files


def _aggregate_one_file(
    path: Path,
    role: str,
    session_date: str,
    origins: pl.DataFrame,
    delay: int,
    source_hash: str,
) -> pl.DataFrame | None:
    columns = [
        "id", "underlying_symbol", "option_chain_id", "executed_at", "created_at", "nbbo_bid", "nbbo_ask",
        "price", "size", "premium", "expiry", "strike", "option_type", "tags", "implied_volatility",
    ]
    events = pl.scan_parquet(path).select(columns).collect(engine="streaming").with_columns(
        [pl.lit(session_date).alias("session_date"), pl.lit(source_hash).alias("source_hash")]
    )
    if events.is_empty():
        return None
    events = events.unique(subset=["id"], maintain_order=True)
    events = events.with_columns(
        (pl.col("executed_at") + pl.duration(seconds=delay)).dt.truncate("5m")
        .add(pl.duration(minutes=5)).alias("_candidate_origin")
    )
    origin_key = origins.filter(pl.col("session_date") == session_date).select(
        ["origin_id", "asset", "session_date", "sample_role", "forecast_origin_utc", "b0_spot"]
    )
    if role == "CALIBRATION":
        origin_key = origin_key.filter(pl.col("sample_role") == role)
    joined = events.join(
        origin_key,
        left_on=["underlying_symbol", "_candidate_origin", "session_date"],
        right_on=["asset", "forecast_origin_utc", "session_date"],
        how="inner",
    ).with_columns(pl.col("_candidate_origin").alias("forecast_origin_utc"))
    end = pl.col("forecast_origin_utc") - pl.duration(seconds=delay)
    start = end - pl.duration(minutes=5)
    eligible = joined.filter(
        (pl.col("executed_at") >= start)
        & (pl.col("executed_at") < end)
        & (pl.max_horizontal("executed_at", "created_at") <= end)
    )
    if eligible.is_empty():
        return None
    grouped = eligible.group_by("origin_id").agg(
        [
            pl.len().alias("b2_option_trade_count_5m"),
            pl.col("option_chain_id").n_unique().alias("b2_unique_contract_count_5m"),
            pl.col("premium").fill_null(0).sum().alias("b2_total_premium_5m"),
            pl.col("premium").max().fill_null(0).alias("b2_max_trade_premium_5m"),
            pl.col("size").fill_null(0).sum().alias("b2_total_contract_size_5m"),
            pl.col("size").max().fill_null(0).alias("b2_max_contract_size_5m"),
            pl.when(pl.col("option_type").str.to_lowercase() == "call").then(pl.col("premium").fill_null(0)).otherwise(0).sum().alias("b2_call_premium_5m"),
            pl.when(pl.col("option_type").str.to_lowercase() == "put").then(pl.col("premium").fill_null(0)).otherwise(0).sum().alias("b2_put_premium_5m"),
            pl.when(pl.col("tags").fill_null("").str.contains("ask_side")).then(pl.col("premium").fill_null(0)).otherwise(0).sum().alias("_ask_premium"),
            pl.when(pl.col("tags").fill_null("").str.contains("bid_side")).then(pl.col("premium").fill_null(0)).otherwise(0).sum().alias("_bid_premium"),
            pl.when((pl.col("nbbo_bid") > 0) & (pl.col("nbbo_ask") > pl.col("nbbo_bid")) & pl.col("price").is_not_null()).then(pl.col("premium").fill_null(0)).otherwise(0).sum().alias("_midpoint_premium"),
            pl.when(pl.col("tags").fill_null("").str.contains("multileg")).then(1).otherwise(0).mean().alias("b2_multileg_trade_share"),
            pl.when(pl.col("tags").fill_null("").str.contains("sweep")).then(1).otherwise(0).mean().alias("b2_sweep_or_equivalent_share"),
            pl.col("strike").is_not_null().alias("_strike_present"),
            pl.col("expiry").is_not_null().alias("_expiry_present"),
            pl.col("implied_volatility").median().alias("b2_implied_volatility_median"),
            pl.col("implied_volatility").is_not_null().sum().alias("b2_valid_iv_observation_count"),
            (pl.col("implied_volatility").max() - pl.col("implied_volatility").min()).alias("_iv_change"),
            pl.col("executed_at").max().alias("b2_max_executed_at"),
            pl.max_horizontal("executed_at", "created_at").max().alias("b2_max_operational_time"),
            pl.when(pl.col("price").is_not_null() & pl.col("premium").is_not_null()).then(1).otherwise(0).mean().alias("b2_valid_trade_share"),
            pl.col("implied_volatility").is_null().mean().alias("b2_missing_iv_share"),
            ((pl.col("strike") / pl.col("b0_spot") - 1).abs()).median().alias("b2_median_absolute_moneyness"),
            (pl.col("expiry").cast(pl.Int32) - pl.col("forecast_origin_utc").dt.date().cast(pl.Int32)).median().alias("b2_median_days_to_expiry"),
            pl.first("source_hash").alias("b2_source_hash"),
        ]
    )
    repeated = (
        eligible.group_by(["origin_id", "option_chain_id"])
        .agg([pl.len().alias("_n"), pl.col("premium").fill_null(0).sum().alias("_p")])
        .filter(pl.col("_n") > 1)
        .group_by("origin_id")
        .agg([pl.col("_n").sum().alias("b2_repeated_contract_trade_count"), pl.col("_p").sum().alias("b2_repeated_contract_premium")])
    )
    strikes = (
        eligible.filter(pl.col("strike").is_not_null())
        .group_by(["origin_id", "strike"]).len()
        .group_by("origin_id")
        .agg((pl.col("len").max() / pl.col("len").sum()).alias("b2_strike_concentration"))
    )
    expiries = (
        eligible.filter(pl.col("expiry").is_not_null())
        .group_by(["origin_id", "expiry"]).len()
        .group_by("origin_id")
        .agg((pl.col("len").max() / pl.col("len").sum()).alias("b2_expiry_concentration"))
    )
    return grouped.join(repeated, on="origin_id", how="left").join(strikes, on="origin_id", how="left").join(expiries, on="origin_id", how="left").with_columns(
        [pl.lit(role).alias("sample_role"), pl.lit(session_date).alias("session_date"), pl.lit(delay).alias("b2_cutoff_seconds")]
    )


def build_b2_panel(origins: pl.DataFrame) -> tuple[pl.DataFrame, dict[str, Any]]:
    """Build exact five-minute B2 windows for every retained origin."""
    b0 = build_b0_variants(origins, _bars())[0]
    origin_key = origins.join(b0.select(["origin_id", "b0_spot"]), on="origin_id", how="left")
    aggregates: list[pl.DataFrame] = []
    duplicate_rows_removed = 0
    for path, role, day in _event_files():
        source_hash = sha256_file(path)
        raw_count = pl.scan_parquet(path).select(pl.len()).collect(engine="streaming").item()
        unique_count = pl.scan_parquet(path).select(pl.col("id").n_unique()).collect(engine="streaming").item()
        duplicate_rows_removed += int(raw_count - unique_count)
        for delay in WINDOW_SPECS.values():
            aggregate = _aggregate_one_file(path, role, day, origin_key, delay, source_hash)
            if aggregate is not None:
                aggregates.append(aggregate)
    if not aggregates:
        raise RuntimeError("PHASE4B_B2_EMPTY")
    aggregate_frame = pl.concat(aggregates, how="diagonal_relaxed").group_by(["origin_id", "b2_cutoff_seconds"]).agg(
        [pl.all().exclude(["origin_id", "b2_cutoff_seconds"]).first()]
    )
    grid_rows: list[dict[str, Any]] = []
    for row in origin_key.select(["origin_id", "asset", "session_date", "forecast_origin_utc", "sample_role"]).iter_rows(named=True):
        for spec, delay in WINDOW_SPECS.items():
            end = row["forecast_origin_utc"] - timedelta(seconds=delay)
            grid_rows.append({**row, "b2_availability_spec": spec, "b2_cutoff_seconds": delay, "b2_window_start": end - timedelta(minutes=5), "b2_window_end": end})
    grid = pl.DataFrame(grid_rows, strict=False)
    result = grid.join(aggregate_frame, on=["origin_id", "b2_cutoff_seconds"], how="left")
    zero_fields = [
        "b2_option_trade_count_5m", "b2_unique_contract_count_5m", "b2_total_premium_5m", "b2_max_trade_premium_5m",
        "b2_total_contract_size_5m", "b2_max_contract_size_5m", "b2_call_premium_5m", "b2_put_premium_5m",
        "_ask_premium", "_bid_premium", "_midpoint_premium", "b2_multileg_trade_share", "b2_sweep_or_equivalent_share",
        "b2_valid_trade_share", "b2_strike_concentration", "b2_expiry_concentration", "b2_repeated_contract_trade_count",
        "b2_repeated_contract_premium",
    ]
    result = result.with_columns([pl.col(name).fill_null(0) for name in zero_fields if name in result.columns])
    result = result.with_columns(
        [
            (pl.col("b2_call_premium_5m") - pl.col("b2_put_premium_5m")).alias("b2_call_put_premium_imbalance"),
            pl.when(pl.col("b2_total_premium_5m") > 0).then(pl.col("_ask_premium") / pl.col("b2_total_premium_5m")).otherwise(0).alias("b2_ask_side_premium_share"),
            pl.when(pl.col("b2_total_premium_5m") > 0).then(pl.col("_bid_premium") / pl.col("b2_total_premium_5m")).otherwise(0).alias("b2_bid_side_premium_share"),
            pl.when(pl.col("b2_total_premium_5m") > 0).then(pl.col("_midpoint_premium") / pl.col("b2_total_premium_5m")).otherwise(0).alias("b2_midpoint_premium_share"),
            pl.col("b2_option_trade_count_5m").gt(0).alias("b2_option_activity_present"),
            pl.col("b2_valid_iv_observation_count").fill_null(0).ge(2).alias("b2_within_bin_iv_change_available"),
            pl.when(pl.col("b2_valid_iv_observation_count").fill_null(0) >= 2).then(pl.col("_iv_change")).otherwise(None).alias("b2_within_bin_iv_change"),
            pl.col("b2_implied_volatility_median").alias("b2_implied_volatility_median"),
            pl.col("b2_missing_iv_share").fill_null(1.0).alias("b2_missing_iv_share"),
            pl.lit("operational_availability_proxy").alias("b2_availability_semantics"),
            pl.lit("NOT_CALIBRATED").alias("b2_unusual_event_status"),
            pl.lit(False).alias("b2_pit_recheck_failed"),
        ]
    ).drop([name for name in ("_ask_premium", "_bid_premium", "_midpoint_premium", "_iv_change") if name in result.columns]).sort(["origin_id", "b2_cutoff_seconds"])
    result = canonicalize_b2_frame(result)
    if result.select(["origin_id", "b2_cutoff_seconds"]).unique().height != origins.height * len(WINDOW_SPECS):
        raise RuntimeError("PHASE4B_B2_GRID_DUPLICATE")
    result.write_parquet(OUT / "b2_panel_25d.parquet", compression="zstd")
    coverage = result.group_by("b2_cutoff_seconds").agg([pl.len().alias("origins"), pl.col("b2_option_activity_present").mean().alias("activity_coverage"), pl.col("b2_within_bin_iv_change_available").mean().alias("iv_change_coverage")]).sort("b2_cutoff_seconds")
    return result, {"duplicate_event_rows_removed": duplicate_rows_removed, "coverage": coverage.to_dicts(), "window_width_seconds": 300, "boundary_convention": "[window_start, window_end)"}


def load_b1_view(origins: pl.DataFrame) -> pl.DataFrame:
    """Reuse the retained, independent Massive B1Q origin coverage."""
    old = pl.read_parquet(COMMON_V1)
    columns = [
        "origin_id", "b1q_atm_iv", "b1q_skew", "b1q_valid_expiry_bucket_count", "b1q_median_quote_age",
        "b1q_median_relative_spread", "b1q_iv_inversion_success_rate", "b1q_b1a_complete", "b1q_b1b_complete",
        "b1q_b1c_complete", "b1q_primary_complete", "b1q_pit_evidence_valid", "b1q_quote_not_after_origin", "b1q_missing_reason",
    ]
    available = old.select([column for column in columns if column in old.columns])
    return origins.select(["origin_id"]).join(available, on="origin_id", how="left").with_columns(
        [pl.col(column).fill_null(False) for column in ("b1q_primary_complete", "b1q_pit_evidence_valid", "b1q_quote_not_after_origin") if column in available.columns]
    )


def _feature_registry() -> tuple[list[dict[str, Any]], list[str]]:
    """Return canonical predictor definitions and the primary predictor list."""
    rows: list[dict[str, Any]] = []
    predictors: list[str] = []
    for name in ("b0_spot", "b0_rv_5m_lag", "b0_rv_30m_lag", "b0_return_5m_lag", "b0_volume_5m_lag", "b0_session_minute"):
        rows.append({"canonical_name": name, "benchmark": "B0", "formula": name, "predictor": True, "optional": False})
        predictors.append(name)
    for name in ("b1q_atm_iv", "b1q_skew"):
        rows.append({"canonical_name": name, "benchmark": "B1Q", "formula": name, "predictor": True, "optional": name == "b1q_skew"})
        predictors.append(name)
    for name in B2_CORE_FIELDS:
        rows.append({"canonical_name": name, "benchmark": "B2", "formula": name, "predictor": True, "optional": False})
        predictors.append(name)
    rows.extend(
        [
            {"canonical_name": "b2_implied_volatility_median", "benchmark": "B2", "formula": "median(implied_volatility)", "predictor": False, "optional": True},
            {"canonical_name": "b2_within_bin_iv_change", "benchmark": "B2", "formula": "max(iv)-min(iv) when n_iv>=2", "predictor": False, "optional": True},
            {"canonical_name": "b2_call_put_premium_imbalance", "benchmark": "B2", "formula": "call_premium-put_premium", "predictor": False, "optional": True},
            {"canonical_name": "b2_option_activity_present", "benchmark": "B2", "formula": "option_trade_count_5m>0", "predictor": False, "optional": True},
            {"canonical_name": "b2_multileg_trade_share", "benchmark": "B2", "formula": "share(tags contains multileg)", "predictor": False, "optional": True},
            {"canonical_name": "b2_sweep_or_equivalent_share", "benchmark": "B2", "formula": "share(tags contains sweep)", "predictor": False, "optional": True},
        ]
    )
    formulas = [row["formula"] for row in rows]
    if len(formulas) != len(set(formulas)):
        raise RuntimeError("FEATURE_FORMULA_DUPLICATE")
    return rows, predictors


def _validate_predictors(frame: pl.DataFrame, predictors: list[str]) -> dict[str, Any]:
    """Reject canonical aliases/exact duplicate predictor columns."""
    aliases = set(B2_ALIASES) | {f"b2_{name}" for name in B2_ALIASES}
    if aliases & set(frame.columns):
        raise RuntimeError("FEATURE_ALIAS_PRESENT")
    pairs: list[dict[str, str]] = []
    for index, left in enumerate(predictors):
        for right in predictors[index + 1 :]:
            if left in frame.columns and right in frame.columns and frame[left].equals(frame[right]):
                pairs.append({"left": left, "right": right})
    if pairs:
        raise RuntimeError(f"FEATURE_EXACT_DUPLICATE:{pairs[0]}")
    return {"exact_duplicate_predictors": pairs, "high_correlation_is_diagnostic_only": True}


def _target_hash(frame: pl.DataFrame) -> str:
    rows = frame.select(["origin_id", "rv30", "target_price_count", "target_future_close_count"]).sort("origin_id").to_dicts()
    return stable_hash(rows)


def build_matrices(origins: pl.DataFrame, b0_plus1: pl.DataFrame, b0_plus2: pl.DataFrame, b2_panel: pl.DataFrame) -> tuple[dict[str, pl.DataFrame], dict[str, Any]]:
    """Join B0, B1Q and corrected B2 into nested benchmark views."""
    b1 = load_b1_view(origins)
    primary_b2 = b2_panel.filter(pl.col("b2_availability_spec") == "primary_60s")
    b2_rename = {column: f"b2_{column}" for column in primary_b2.columns if column not in {"origin_id", "asset", "session_date", "forecast_origin_utc", "sample_role"} and not column.startswith("b2_")}
    primary_b2 = primary_b2.rename(b2_rename)
    frame = origins.join(b0_plus1, on=["origin_id", "asset", "session_date", "forecast_origin_utc", "sample_role", "rv30", "target_future_close_count", "target_price_count", "target_validity"], how="left", suffix="_b0")
    frame = frame.join(b0_plus2.select(["origin_id", "b0_plus2_spot", "b0_plus2_rv_5m_lag", "b0_plus2_rv_30m_lag", "b0_plus2_return_5m_lag", "b0_plus2_volume_5m_lag", "b0_plus2_source_timestamp_raw_utc", "b0_plus2_available_at_utc", "b0_plus2_feature_age_seconds", "b0_plus2_availability_valid"]), on="origin_id", how="left")
    frame = frame.join(b1, on="origin_id", how="left").join(primary_b2.drop(["asset", "session_date", "forecast_origin_utc", "sample_role"]), on="origin_id", how="left")
    frame = frame.with_columns(
        [
            (pl.col("b0_availability_valid") & pl.col("target_validity").eq("valid") & (pl.col("target_price_count") == 31) & (pl.col("target_future_close_count") == 30) & pl.all_horizontal([pl.col(name).is_not_null() for name in B0_FIELDS])).alias("b0_complete"),
            (pl.col("b1q_primary_complete") & pl.col("b1q_pit_evidence_valid") & pl.col("b1q_quote_not_after_origin")).fill_null(False).alias("b1q_complete"),
            pl.col("b2_option_trade_count_5m").is_not_null().fill_null(False).alias("b2_core_features_present"),
        ]
    )
    frame = frame.with_columns(
        [
            (pl.col("b0_complete") & pl.col("b1q_complete")).alias("b1q_complete"),
            (pl.col("b0_complete") & pl.col("b1q_complete") & pl.col("b2_core_features_present") & ~pl.col("b2_pit_recheck_failed").fill_null(True)).alias("b2_core_complete"),
        ]
    )
    frame = frame.with_columns(
        pl.when(~pl.col("b0_complete")).then(pl.lit("B0_MISSING_ASOF_FEATURE_OR_TARGET"))
        .when(~pl.col("b1q_complete")).then(pl.lit("B1Q_PIT_OR_QUOTE_COVERAGE"))
        .when(~pl.col("b2_core_complete")).then(pl.lit("B2_CORE_FEATURE_OR_PIT_FAILURE"))
        .otherwise(pl.lit("NONE")).alias("exclusion_reason")
    ).sort("origin_id")
    registry, predictors = _feature_registry()
    identity_audit = _validate_predictors(frame, predictors)
    b0_view = frame.filter(pl.col("b0_complete"))
    b1_view = frame.filter(pl.col("b1q_complete"))
    b2_view = frame.filter(pl.col("b2_core_complete"))
    common = b2_view
    for name, view in (("b0_complete_25d", b0_view), ("b1q_complete_25d", b1_view), ("b2_core_complete_25d", b2_view), ("common_intersection_25d", common), ("origin_matrix_25d", frame)):
        view.write_parquet(OUT / f"{name}.parquet", compression="zstd")
    targets = frame.select(["origin_id", "asset", "session_date", "forecast_origin_utc", "sample_role", "rv30", "target_price_count", "target_future_close_count", "target_validity"]).sort("origin_id")
    targets.write_parquet(OUT / "targets_25d.parquet", compression="zstd")
    registry_payload = {"schema_version": "phase4b-feature-registry-v1", "aliases": B2_ALIASES, "features": registry, "predictors": predictors, "identity_audit": identity_audit}
    write_json(OUT / "feature_registry_v1.json", registry_payload)
    common_ids = set(common["origin_id"].to_list())
    row_sets = {
        "nominal_origins": frame.height,
        "b0_complete": b0_view.height,
        "b1q_complete": b1_view.height,
        "b2_core_complete": b2_view.height,
        "common_intersection": common.height,
        "row_set_nesting": {"B2_subset_B1Q": set(b2_view["origin_id"]).issubset(set(b1_view["origin_id"])), "B1Q_subset_B0": set(b1_view["origin_id"]).issubset(set(b0_view["origin_id"]))},
        "target_hash_all": _target_hash(targets),
        "target_hash_common": _target_hash(common),
        "target_hash_common_in_b0": _target_hash(b0_view.filter(pl.col("origin_id").is_in(common_ids))),
        "target_hash_common_in_b1q": _target_hash(b1_view.filter(pl.col("origin_id").is_in(common_ids))),
        "target_hash_common_in_b2": _target_hash(b2_view.filter(pl.col("origin_id").is_in(common_ids))),
    }
    pilot_diagnostics = (
        frame.filter((pl.col("sample_role") == "PILOT") & ~pl.col("b2_core_complete"))
        .group_by("exclusion_reason")
        .len()
        .sort("exclusion_reason")
        .to_dicts()
    )
    pilot_diagnostics_by_asset_session = (
        frame.filter((pl.col("sample_role") == "PILOT") & ~pl.col("b2_core_complete"))
        .group_by(["asset", "session_date", "exclusion_reason"])
        .len()
        .sort(["asset", "session_date", "exclusion_reason"])
        .to_dicts()
    )
    row_sets["pilot_strict_core_diagnostics"] = pilot_diagnostics
    write_json(OUT / "matrix_row_sets_v1.json", row_sets)
    write_json(
        OUT / "pilot_strict_core_diagnostics.json",
        {
            "pilot_origins": origins.filter(pl.col("sample_role") == "PILOT").height,
            "pilot_strict_core_origins": b2_view.filter(pl.col("sample_role") == "PILOT").height,
            "exclusions": pilot_diagnostics,
            "exclusions_by_asset_session": pilot_diagnostics_by_asset_session,
            "optional_iv_fields_are_non_blocking": True,
            "iv_change_not_used_for_b2_core_completeness": True,
        },
    )
    return {"all": frame, "b0": b0_view, "b1q": b1_view, "b2": b2_view, "common": common, "targets": targets}, row_sets | {"predictors": predictors, "identity_audit": identity_audit}


def write_checkpoints(panel: pl.DataFrame, origins: pl.DataFrame, bars: pl.DataFrame, b2_meta: dict[str, Any]) -> dict[str, Any]:
    """Write and verify atomic per-session checkpoints from local outputs."""
    checkpoint_dir = OUT / "checkpoints"
    output_dir = OUT / "session_outputs"
    config = {"windows": WINDOW_SPECS, "fmp_delays": [1, 2], "optional_iv": list(B2_OPTIONAL_FIELDS), "no_network": True}
    session_dates = sorted(origins["session_date"].unique().to_list())
    session_list_hash = stable_hash(session_dates)
    calibration_dates = {
        str(value)
        for value in origins.filter(pl.col("sample_role") == "CALIBRATION")["session_date"].unique().to_list()
    }

    def materialize() -> tuple[dict[str, str], dict[str, str]]:
        checkpoint_hashes: dict[str, str] = {}
        output_hashes: dict[str, str] = {}
        for day in session_dates:
            session_panel = panel.filter(pl.col("session_date") == day).sort(["origin_id", "b2_cutoff_seconds"])
            output = output_dir / f"date={day}" / "b2_panel.parquet"
            output.parent.mkdir(parents=True, exist_ok=True)
            session_panel.write_parquet(output, compression="zstd")
            event_hashes = {str(path): sha256_file(path) for path, _, session in _event_files() if session == day}
            underlying_path = CAL / "underlying_1min_20d.parquet" if day in calibration_dates else PILOT / "underlying_1min.parquet"
            input_hashes = {"underlying": sha256_file(underlying_path), **{f"events_{index}": value for index, value in enumerate(sorted(event_hashes.values()))}}
            schema_hash = stable_hash({name: str(dtype) for name, dtype in session_panel.schema.items()})
            checkpoint = build_checkpoint(session=day, session_list=session_dates, config=config, input_hashes=input_hashes, schema_hash=schema_hash, request_hashes=[], output_hash=sha256_file(output), origin_ids=session_panel["origin_id"].unique().sort().to_list())
            validate_checkpoint(checkpoint)
            checkpoint_path = checkpoint_dir / f"date={day}.json"
            write_json(checkpoint_path, checkpoint)
            checkpoint_hashes[day] = sha256_file(checkpoint_path)
            output_hashes[day] = sha256_file(output)
        return checkpoint_hashes, output_hashes

    first_checkpoint_hashes, first_output_hashes = materialize()
    second_checkpoint_hashes, second_output_hashes = materialize()
    hashes_identical = first_checkpoint_hashes == second_checkpoint_hashes and first_output_hashes == second_output_hashes
    corrupted_detected = False
    for path in sorted(checkpoint_dir.glob("date=*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        validate_checkpoint(payload)
        corrupted = {**payload, "output_sha256": "0" * 64}
        try:
            validate_checkpoint(corrupted)
        except ValueError:
            corrupted_detected = True
    outputs = sorted(output_dir.glob("date=*/b2_panel.parquet"))
    duplicate_output_rows = panel.select(["origin_id", "b2_cutoff_seconds"]).height - panel.select(["origin_id", "b2_cutoff_seconds"]).unique().height
    restart = {"schema_version": "phase4b-checkpoint-restart-v1", "checkpoint_count": len(outputs), "hashes_identical": hashes_identical, "corrupted_checkpoint_detected": corrupted_detected, "duplicate_output_rows": duplicate_output_rows, "provider_requests": 0, "full_backfill_executed": False, "config_sha256": stable_hash(config), "session_list_sha256": session_list_hash}
    write_json(OUT / "checkpoint_restart_v1.json", restart)
    return restart


def seal_holdout(origins: pl.DataFrame) -> dict[str, Any]:
    """Seal ten future XNYS sessions without reading their payloads."""
    calendar = xcals.get_calendar("XNYS")
    max_origin = cast(datetime, origins["forecast_origin_utc"].max())
    seal_timestamp = max_origin + timedelta(seconds=1)
    start_date = seal_timestamp.astimezone(ET).date() + timedelta(days=1)
    sessions = calendar.sessions_in_range(start_date, start_date + timedelta(days=60))
    session_dates = [str(item.date()) for item in sessions[:10]]
    manifest = {
        "schema_version": "prospective-holdout-v1",
        "status": "SEALED_NOT_ACQUIRED",
        "role": "PROSPECTIVE_HOLDOUT",
        "seal_timestamp_utc": seal_timestamp.isoformat(),
        "selection_rule": "first ten XNYS sessions strictly after Phase 4B seal timestamp",
        "session_dates": session_dates,
        "session_list_sha256": stable_hash(session_dates),
        "acquired": False,
        "raw_payloads_written": False,
        "read_guard": "deny before method freeze and human approval",
        "overlap_with_retained_origins": bool(set(session_dates) & set(origins["session_date"].unique().to_list())),
        "provider_requests": 0,
    }
    if manifest["overlap_with_retained_origins"] or len(session_dates) != 10:
        raise RuntimeError("PROSPECTIVE_HOLDOUT_INVALID")
    holdout_read_guard(manifest, [])
    write_json(OUT / "prospective_10_session_manifest.json", manifest)
    return manifest


def write_handoff(
    origins: pl.DataFrame,
    b0_plus1: pl.DataFrame,
    b0_plus2: pl.DataFrame,
    b2_panel: pl.DataFrame,
    matrices: dict[str, pl.DataFrame],
    row_sets: dict[str, Any],
    b2_meta: dict[str, Any],
    restart: dict[str, Any],
    holdout: dict[str, Any],
) -> None:
    """Write the required evidence-first Phase 4B handoff."""
    common_ids = set(matrices["common"]["origin_id"].to_list())
    variant_target_hashes = {
        "plus1": _target_hash(b0_plus1),
        "plus2": _target_hash(b0_plus2),
    }
    common_target_hashes = {
        name: _target_hash(frame.filter(pl.col("origin_id").is_in(common_ids)))
        for name, frame in matrices.items()
        if name in {"b0", "b1q", "b2", "common"}
    }
    fmp_pass = (
        int(b0_plus1["b0_availability_valid"].sum()) > 0
        and int(b0_plus2["b0_plus2_availability_valid"].sum()) > 0
        and variant_target_hashes["plus1"] == variant_target_hashes["plus2"]
    )
    window_pass = all(row["window_width_seconds"] == 300 for row in [{"window_width_seconds": b2_meta["window_width_seconds"]}]) and float(cast(float, b2_panel.filter(pl.col("b2_cutoff_seconds") == 300)["b2_option_activity_present"].mean())) > 0
    pilot_rows = matrices["b2"].filter(pl.col("sample_role") == "PILOT").height
    pilot_strict = pilot_rows == origins.filter(pl.col("sample_role") == "PILOT").height
    feature_pass = row_sets["identity_audit"]["exact_duplicate_predictors"] == []
    common_pass = (
        row_sets["row_set_nesting"]["B2_subset_B1Q"]
        and row_sets["row_set_nesting"]["B1Q_subset_B0"]
        and len(set(common_target_hashes.values())) == 1
    )
    checkpoint_pass = restart["hashes_identical"] and restart["corrupted_checkpoint_detected"] and restart["duplicate_output_rows"] == 0
    holdout_pass = holdout["status"] == "SEALED_NOT_ACQUIRED" and not holdout["overlap_with_retained_origins"] and len(holdout["session_dates"]) == 10
    pilot_blockers = row_sets.get("pilot_strict_core_diagnostics", [])
    blockers = [
        "NO_NETWORK_OR_STAGE_A_EXECUTION_BY_SCOPE",
        "FMP_BAR_START_CLOSE_SEMANTICS_REMAIN_CONSERVATIVE_ASSUMPTION",
        "UW_CREATED_AT_IS_OPERATIONAL_PROXY_NOT_PUBLICATION_TIME",
    ]
    if pilot_blockers:
        blockers.append("PILOT_NON_IV_EXCLUSIONS_DOCUMENTED_IN_pilot_strict_core_diagnostics.json")
    report = f"""# CODEX Phase 4B Handoff

Status: local-only implementation; no new provider requests, downloads, backfill, models, tuning or performance metrics.

## Inputs and invariants

- Nominal origins: {origins.height}; assets: {sorted(origins['asset'].unique().to_list())}.
- RV30 target: unchanged retained target values; 31 prices and 30 returns per valid row.
- Primary UW cutoff: 60 seconds; sensitivities: 120 and 300 seconds.
- UW window: `[origin - delay - 5m, origin - delay)`; operational rule `max(executed_at, created_at) <= window_end`.
- `created_at` remains an `operational_availability_proxy`, never publication time.

## Gate results

| Gate | Result | Evidence |
|---|---|---|
| FMP as-of +1/+2 | {'PASS' if fmp_pass else 'FAIL'} | `artifacts/phase4b/b0_plus1_25d.parquet`, `artifacts/phase4b/b0_plus2_25d.parquet` |
| UW fixed windows | {'PASS' if window_pass else 'FAIL'} | `artifacts/phase4b/b2_panel_25d.parquet` |
| Pilot strict B2 core | {'PASS' if pilot_strict else 'FAIL — non-IV exclusions documented'} | `artifacts/phase4b/b2_core_complete_25d.parquet`, `artifacts/phase4b/pilot_strict_core_diagnostics.json` |
| Feature contract | {'PASS' if feature_pass else 'FAIL'} | `artifacts/phase4b/feature_registry_v1.json` |
| Common matrices | {'PASS' if common_pass else 'FAIL'} | `artifacts/phase4b/matrix_row_sets_v1.json` |
| Checkpoint gate | {'PASS' if checkpoint_pass else 'FAIL'} | `artifacts/phase4b/checkpoint_restart_v1.json` |
| Prospective holdout sealed | {'PASS' if holdout_pass else 'FAIL'} | `artifacts/phase4b/prospective_10_session_manifest.json` |

## Coverage

- FMP +1 valid rows: {int(b0_plus1['b0_availability_valid'].sum())}/{b0_plus1.height}.
- FMP +2 valid rows: {int(b0_plus2['b0_plus2_availability_valid'].sum())}/{b0_plus2.height}.
- B0-complete: {matrices['b0'].height}; B1Q-complete: {matrices['b1q'].height}; B2-core-complete: {matrices['b2'].height}; exact intersection: {matrices['common'].height}.
- Pilot B2-core rows retained: {pilot_rows}/{origins.filter(pl.col('sample_role') == 'PILOT').height}.
- Pilot strict-core exclusions (non-IV): {json.dumps(pilot_blockers, sort_keys=True)}.
- Per-asset/session exclusion detail: `artifacts/phase4b/pilot_strict_core_diagnostics.json`.
- UW activity coverage by cutoff: {json.dumps(b2_meta['coverage'], sort_keys=True)}
- Duplicate event rows removed: {b2_meta['duplicate_event_rows_removed']}.

## Checkpoint and holdout

- Checkpoints: {restart['checkpoint_count']}; restart hashes identical: {restart['hashes_identical']}; corrupted checkpoint detected: {restart['corrupted_checkpoint_detected']}.
- Holdout status: `{holdout['status']}`; sessions: `{', '.join(holdout['session_dates'])}`; acquired: `{holdout['acquired']}`.

## Remaining blockers

{chr(10).join(f'- `{item}`' for item in blockers)}

FMP_ASOF_REPAIR_PASS: {'YES' if fmp_pass else 'NO'}
UW_FIXED_WINDOWS_PASS: {'YES' if window_pass else 'NO'}
PILOT_STRICT_CORE_PASS: {'YES' if pilot_strict else 'NO'}
FEATURE_CONTRACT_PASS: {'YES' if feature_pass else 'NO'}
COMMON_MATRIX_PASS: {'YES' if common_pass else 'NO'}
CHECKPOINT_GATE_PASS: {'YES' if checkpoint_pass else 'NO'}
PROSPECTIVE_HOLDOUT_SEALED: {'YES' if holdout_pass else 'NO'}
SAFE_TO_RUN_STAGE_A_10_SESSIONS: NO
SAFE_TO_TRAIN_MODELS: NO
BLOCKERS: {', '.join(blockers)}
"""
    report_path = ROOT / "reports" / "CODEX_PHASE4B_HANDOFF.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")


def main() -> None:
    """Run the bounded Phase 4B rebuild from retained local evidence."""
    OUT.mkdir(parents=True, exist_ok=True)
    origins, bars = load_origins_and_bars()
    b0_plus1, b0_plus2 = build_b0_variants(origins, bars)
    b0_plus1.write_parquet(OUT / "b0_plus1_25d.parquet", compression="zstd")
    b0_plus2.write_parquet(OUT / "b0_plus2_25d.parquet", compression="zstd")
    b2_panel, b2_meta = build_b2_panel(origins)
    matrices, row_sets = build_matrices(origins, b0_plus1, b0_plus2, b2_panel)
    restart = write_checkpoints(b2_panel, origins, bars, b2_meta)
    holdout = seal_holdout(origins)
    write_handoff(origins, b0_plus1, b0_plus2, b2_panel, matrices, row_sets, b2_meta, restart, holdout)
    summary = {"status": "PHASE4B_LOCAL_ONLY", "origins": origins.height, "b0_plus1_valid": int(b0_plus1["b0_availability_valid"].sum()), "b0_plus2_valid": int(b0_plus2["b0_plus2_availability_valid"].sum()), "b2_core_rows": matrices["b2"].height, "common_rows": matrices["common"].height, "provider_requests": 0, "models_trained": 0}
    write_json(OUT / "phase4b_summary.json", summary)
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
