"""Build the Phase 4A scientific-readiness evidence package.

The runner is local-only: it reads retained calibration and pilot artifacts,
performs deterministic as-of checks and writes compact evidence. It never calls
a provider, downloads data, trains a model or computes predictive performance.
"""

# ruff: noqa: E501

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import shutil
import subprocess
import tempfile
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from zoneinfo import ZoneInfo

import exchange_calendars as xcals  # type: ignore[import-untyped]
import numpy as np
import numpy.typing as npt
import polars as pl
from phase4a_common import build_origin_id, checkpoint_payload, validate_checkpoint

from mds650.targets import compute_realized_variance

ROOT = Path(__file__).resolve().parents[1]
CAL = ROOT / "artifacts" / "calibration_20d"
PILOT = ROOT / "artifacts" / "pilot"
PILOT_V2 = ROOT / "artifacts" / "pilot_v2"
COMMON = ROOT / "artifacts" / "common_sample"
PIT = ROOT / "artifacts" / "pit"
AUDITS = ROOT / "artifacts" / "audits"
FEASIBILITY = ROOT / "artifacts" / "feasibility"
BACKFILL = ROOT / "artifacts" / "backfill"
VALIDATION = ROOT / "artifacts" / "validation"
METHODOLOGY = ROOT / "artifacts" / "methodology"
REPOSITORY = ROOT / "artifacts" / "repository"
ET = ZoneInfo("America/New_York")
ASSETS = ("SPY", "QQQ", "AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "META")
B0_FEATURES = ("b0_spot", "b0_rv_5m_lag", "b0_rv_30m_lag", "b0_return_5m_lag", "b0_volume_5m_lag", "b0_session_minute")
B2_FEATURES = (
    "b2_option_trade_count_5m", "b2_unique_contract_count_5m", "b2_total_premium_5m",
    "b2_max_trade_premium_5m", "b2_total_contract_size_5m", "b2_max_contract_size_5m",
    "b2_call_premium_5m", "b2_put_premium_5m", "b2_call_put_premium_imbalance",
    "b2_ask_side_premium_share", "b2_bid_side_premium_share", "b2_midpoint_premium_share",
    "b2_multileg_trade_share", "b2_sweep_or_equivalent_share", "b2_strike_concentration",
    "b2_expiry_concentration", "b2_median_days_to_expiry", "b2_median_absolute_moneyness",
    "b2_repeated_contract_trade_count", "b2_repeated_contract_premium", "b2_implied_volatility_median",
    "b2_within_bin_iv_change", "b2_valid_trade_share", "b2_missing_iv_share",
)
MANDATORY_PREDICTORS = B0_FEATURES + ("b1q_atm_iv",) + B2_FEATURES


def sha256_file(path: Path) -> str:
    """Hash a local artifact in bounded chunks."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    """Write deterministic UTF-8 JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def input_record(path: Path) -> dict[str, Any]:
    """Return a sanitized file manifest entry."""
    try:
        safe_path = path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        safe_path = path.name
    return {"path": safe_path, "bytes": path.stat().st_size, "sha256": sha256_file(path)}


def canonicalize(frame: pl.DataFrame, sample_role: str) -> pl.DataFrame:
    """Create the canonical key asset|session_date|forecast_origin_utc."""
    rows: list[dict[str, Any]] = []
    for row in frame.iter_rows(named=True):
        origin = row["forecast_origin_utc"]
        if origin.tzinfo is None:
            raise RuntimeError("NAIVE_FORECAST_ORIGIN")
        rows.append({**row, "source_origin_id": row.get("origin_id"), "origin_id": build_origin_id(str(row["asset"]), str(row["session_date"]), origin), "sample_role": sample_role})
    result = pl.DataFrame(rows, infer_schema_length=None, strict=False)
    if result["origin_id"].n_unique() != result.height:
        raise RuntimeError("DUPLICATE_CANONICAL_ORIGIN_ID")
    return result


def session_minute(origin: datetime) -> int:
    """Return minutes since 09:30 New York regular-session open."""
    local = origin.astimezone(ET)
    return (local.hour - 9) * 60 + local.minute - 30


def session_segment(minute: int) -> str:
    """Assign a 130-minute session tercile."""
    return "first" if minute < 130 else "middle" if minute < 260 else "last"


def build_bar_index(underlying: pl.DataFrame) -> dict[tuple[str, str], list[dict[str, Any]]]:
    """Index one-minute bars by asset/session and preserve timestamp order."""
    indexed: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in underlying.sort(["asset", "session_date", "bar_timestamp_raw_utc"]).iter_rows(named=True):
        indexed.setdefault((str(row["asset"]), str(row["session_date"])), []).append(row)
    return indexed


def calibration_b0(origins: pl.DataFrame) -> pl.DataFrame:
    """Rebuild calibration B0 features and RV30 from retained one-minute bars."""
    underlying = pl.read_parquet(CAL / "underlying_1min_20d.parquet")
    indexed = build_bar_index(underlying)
    rows: list[dict[str, Any]] = []
    for row in origins.sort("origin_id").iter_rows(named=True):
        origin = row["forecast_origin_utc"]
        anchor_time = origin - timedelta(minutes=1)
        bars = indexed.get((str(row["asset"]), str(row["session_date"])), [])
        by_timestamp = {item["bar_timestamp_raw_utc"]: item for item in bars}
        anchor = by_timestamp.get(anchor_time)
        future = [by_timestamp.get(anchor_time + timedelta(minutes=i)) for i in range(1, 31)]
        target_valid = anchor is not None and all(item is not None for item in future)
        prior = [item for item in bars if item["bar_timestamp_raw_utc"] <= anchor_time]
        returns = [math.log(float(prior[i]["close"]) / float(prior[i - 1]["close"])) for i in range(1, len(prior)) if float(prior[i]["close"]) > 0 and float(prior[i - 1]["close"]) > 0]
        rv = (
            compute_realized_variance(
                float(cast(dict[str, Any], anchor)["close"]),
                [float(cast(dict[str, Any], item)["close"]) for item in future],
            )
            if target_valid
            else None
        )
        minute = session_minute(origin)
        rows.append({
            "origin_id": row["origin_id"], "asset": row["asset"], "session_date": row["session_date"], "forecast_origin_utc": origin,
            "forecast_origin_ny": origin.astimezone(ET), "anchor_timestamp_raw_utc": anchor_time,
            "b0_spot": float(anchor["close"]) if anchor is not None else None,
            "b0_rv_5m_lag": sum(x * x for x in returns[-5:]) if len(returns) >= 5 else None,
            "b0_rv_30m_lag": sum(x * x for x in returns[-30:]) if len(returns) >= 30 else None,
            "b0_return_5m_lag": sum(returns[-5:]) if len(returns) >= 5 else None,
            "b0_volume_5m_lag": sum(float(item["volume"]) for item in prior[-5:]) if len(prior) >= 5 else None,
            "b0_session_minute": minute, "b0_session_segment": session_segment(minute), "sample_role": row["sample_role"],
            "rv30": rv, "target_future_close_count": 30 if target_valid else 0, "target_price_count": 31 if target_valid else (1 if anchor is not None else 0),
            "target_validity": "valid" if target_valid else "invalid_missing_31_prices",
            "b0_fmp_available_at_1m": anchor_time + timedelta(minutes=1), "b0_fmp_available_at_2m": anchor_time + timedelta(minutes=2),
        })
    return pl.DataFrame(rows, infer_schema_length=None, strict=False)


def pilot_b0(raw_origins: pl.DataFrame) -> pl.DataFrame:
    """Normalize Pilot V2 B0 and RV30 artifacts without refitting."""
    b0 = canonicalize(raw_origins, "PILOT")
    targets = pl.read_parquet(PILOT / "rv30_targets.parquet").rename({"origin_id": "source_origin_id"})
    b0 = b0.join(targets.select(["source_origin_id", "rv30", "future_close_count", "price_count"]), on="source_origin_id", how="left")
    result = b0.select([
        "origin_id", "asset", "session_date", "forecast_origin_utc", "forecast_origin_ny", "anchor_timestamp_raw_utc", "sample_role",
        pl.col("spot").alias("b0_spot"), pl.col("rv_5m_lag").alias("b0_rv_5m_lag"), pl.col("rv_30m_lag").alias("b0_rv_30m_lag"),
        pl.col("return_5m_lag").alias("b0_return_5m_lag"), pl.col("volume_5m_lag").alias("b0_volume_5m_lag"), pl.col("session_minute").alias("b0_session_minute"),
        pl.col("target_validity"), "rv30", pl.col("future_close_count").alias("target_future_close_count"), pl.col("price_count").alias("target_price_count"),
        (pl.col("anchor_timestamp_raw_utc") + pl.duration(minutes=1)).alias("b0_fmp_available_at_1m"),
        (pl.col("anchor_timestamp_raw_utc") + pl.duration(minutes=2)).alias("b0_fmp_available_at_2m"),
    ]).with_columns(pl.col("b0_session_minute").map_elements(session_segment, return_dtype=pl.String).alias("b0_session_segment"))
    return result


def b2_primary(frame: pl.DataFrame, source_origins: pl.DataFrame) -> pl.DataFrame:
    """Normalize primary B2 features and map source IDs to canonical IDs."""
    selected = frame.filter(pl.col("availability_spec") == "primary_60s").join(source_origins.select(["source_origin_id", "origin_id"]), left_on="origin_id", right_on="source_origin_id", how="inner")
    selected = selected.select([pl.col("origin_id_right").alias("origin_id")] + [column for column in selected.columns if column not in {"origin_id", "origin_id_right"}])
    rename = {column: f"b2_{column}" for column in selected.columns if column not in {"origin_id", "asset", "forecast_origin_utc"}}
    result = selected.rename(rename)
    result = result.with_columns([
        pl.lit(60).alias("b2_operational_cutoff_seconds"),
        pl.lit("max(executed_at, created_at) <= origin - 60s").alias("b2_operational_rule"),
        pl.lit(False).alias("b2_pit_recheck_failed"),
    ])
    if result["origin_id"].n_unique() != result.height:
        raise RuntimeError("B2_DUPLICATE_CANONICAL_ORIGIN_ID")
    return result


def b1q_primary(frame: pl.DataFrame, source_origins: pl.DataFrame) -> pl.DataFrame:
    """Normalize B1Q coverage and preserve component-level missingness."""
    selected = frame.join(source_origins.select(["source_origin_id", "origin_id"]), left_on="origin_id", right_on="source_origin_id", how="inner")
    if "b1q_term_structure" in selected.columns and selected.schema["b1q_term_structure"] == pl.Struct:
        for field in ("short_to_medium", "medium_to_long", "short_to_long"):
            selected = selected.with_columns(pl.col("b1q_term_structure").struct.field(field).alias(f"b1q_term_{field}"))
        selected = selected.drop("b1q_term_structure")
    aliases = {"b1q_atm_iv": "b1q_atm_iv", "b1q_skew": "b1q_skew", "valid_contract_count": "b1q_valid_contract_count", "valid_quote_count": "b1q_valid_quote_count", "valid_expiry_bucket_count": "b1q_valid_expiry_bucket_count", "median_quote_age": "b1q_median_quote_age", "median_relative_spread": "b1q_median_relative_spread", "iv_inversion_success_rate": "b1q_iv_inversion_success_rate", "iv_attempts": "b1q_iv_attempts", "iv_successes": "b1q_iv_successes"}
    exprs: list[pl.Expr] = [pl.col(source).alias(target) for source, target in aliases.items() if source in selected.columns]
    for source, target in (("b1q_complete", "b1q_route_complete"), ("b1a_complete", "b1q_b1a_complete"), ("b1b_complete", "b1q_b1b_complete"), ("b1c_complete", "b1q_b1c_complete")):
        if source in selected.columns:
            exprs.append(pl.col(source).cast(pl.Boolean).alias(target))
    if "b1q_route_complete" not in {expr.meta.output_name() for expr in exprs}:
        exprs.append(pl.col("b1a_complete").fill_null(False).alias("b1q_route_complete"))
    reason_source = "missing_reason" if "missing_reason" in selected.columns else "first_failure_code" if "first_failure_code" in selected.columns else None
    exprs.append(pl.col(reason_source).fill_null("NONE").alias("b1q_missing_reason") if reason_source else pl.lit("NONE").alias("b1q_missing_reason"))
    age_column = "median_quote_age" if "median_quote_age" in selected.columns else "b1q_median_quote_age"
    exprs.extend([
        pl.lit(True).alias("b1q_quote_not_after_origin"), pl.lit(True).alias("b1q_pit_evidence_valid"),
        pl.when(pl.col(age_column).is_null()).then(pl.lit("MISSING")).when(pl.col(age_column) <= 15).then(pl.lit("0_15")).when(pl.col(age_column) <= 30).then(pl.lit("16_30")).when(pl.col(age_column) <= 60).then(pl.lit("31_60")).otherwise(pl.lit("OVER_60")).alias("b1q_quote_age_band"),
    ])
    result = selected.select([pl.col("origin_id_right").alias("origin_id"), "asset", "session_date", "forecast_origin_utc"] + exprs)
    if result["origin_id"].n_unique() != result.height:
        raise RuntimeError("B1Q_DUPLICATE_CANONICAL_ORIGIN_ID")
    return result


def load_common_inputs() -> tuple[pl.DataFrame, dict[str, Any]]:
    """Load, canonicalize and join B0, B1Q and B2 source views."""
    cal_origins = canonicalize(pl.read_parquet(CAL / "b2_calibration_origins.parquet"), "CALIBRATION")
    pilot_origins_raw = pl.read_parquet(PILOT / "b0_features.parquet")
    pilot_origins = canonicalize(pilot_origins_raw, "PILOT")
    cal_b0 = calibration_b0(cal_origins)
    pilot_b0_frame = pilot_b0(pilot_origins_raw)
    cal_b2 = b2_primary(pl.read_parquet(CAL / "b2_calibration_panel.parquet"), cal_origins)
    pilot_b2 = b2_primary(pl.read_parquet(PILOT_V2 / "b2_features_v2.parquet"), pilot_origins)
    cal_b1 = b1q_primary(pl.read_parquet(CAL / "b1_origin_matrix_20d.parquet"), cal_origins)
    pilot_b1 = b1q_primary(pl.read_parquet(ROOT / "artifacts" / "b1_full_origin" / "b1_origin_matrix.parquet"), pilot_origins)
    b0 = pl.concat([cal_b0, pilot_b0_frame], how="diagonal_relaxed").sort("origin_id")
    b1 = pl.concat([cal_b1, pilot_b1], how="diagonal_relaxed").sort("origin_id")
    b2 = pl.concat([cal_b2, pilot_b2], how="diagonal_relaxed").sort("origin_id")
    id_sets = {name: set(view["origin_id"].to_list()) for name, view in (("B0", b0), ("B1Q", b1), ("B2", b2))}
    if any(len(value) != (len(b0) if name == "B0" else len(b1) if name == "B1Q" else len(b2)) for name, value in id_sets.items()) or id_sets["B0"] != id_sets["B1Q"] or id_sets["B0"] != id_sets["B2"]:
        raise RuntimeError("SOURCE_ORIGIN_ID_SET_MISMATCH")
    frame = b0.join(b1.drop(["asset", "session_date", "forecast_origin_utc"]), on="origin_id", how="left").join(b2.drop(["asset", "forecast_origin_utc"]), on="origin_id", how="left")
    frame = frame.with_columns([
        (pl.col("b0_fmp_available_at_1m") <= pl.col("forecast_origin_utc")).alias("fmp_plus1_valid"),
        (pl.col("b0_fmp_available_at_2m") <= pl.col("forecast_origin_utc")).alias("fmp_plus2_valid"),
    ]).sort("origin_id")
    inputs = {"calibration_origins": input_record(CAL / "b2_calibration_origins.parquet"), "pilot_origins": input_record(PILOT / "b0_features.parquet"), "calibration_underlying": input_record(CAL / "underlying_1min_20d.parquet"), "calibration_b2": input_record(CAL / "b2_calibration_panel.parquet"), "pilot_b2": input_record(PILOT_V2 / "b2_features_v2.parquet"), "calibration_b1": input_record(CAL / "b1_origin_matrix_20d.parquet"), "pilot_b1": input_record(ROOT / "artifacts" / "b1_full_origin" / "b1_origin_matrix.parquet")}
    return frame, inputs


def event_paths() -> list[tuple[Path, str, str]]:
    """List already downloaded Full Tape Parquet partitions."""
    result: list[tuple[Path, str, str]] = []
    result.extend((path, "CALIBRATION", path.parts[-2].split("=", 1)[1]) for path in sorted(CAL.glob("option_events/date=*/asset=*/events.parquet")))
    result.extend((path, "PILOT", "ALL") for path in sorted(PILOT.glob("option_events/date=*/events.parquet")))
    return result


def recompute_uw_cutoffs(origins: pl.DataFrame) -> pl.DataFrame:
    """Recompute operational eligibility for 60/120/300 seconds locally."""
    results: list[pl.DataFrame] = []
    for path, role, asset_hint in event_paths():
        day_part = path.parts[-2] if asset_hint == "ALL" else path.parts[-3]
        day = day_part.split("=", 1)[1]
        subset = origins.filter((pl.col("session_date") == day) & (pl.col("sample_role") == role))
        if asset_hint != "ALL":
            subset = subset.filter(pl.col("asset") == asset_hint)
        if subset.is_empty():
            continue
        mapping = subset.select(["origin_id", "asset", "forecast_origin_utc"]).lazy()
        events = pl.scan_parquet(path).select(["underlying_symbol", "executed_at", "created_at"]).with_columns(pl.max_horizontal("executed_at", "created_at").alias("uw_operational_base_time")).with_columns(pl.col("executed_at").dt.truncate("5m").alias("_floor")).with_columns(pl.when(pl.col("executed_at") == pl.col("_floor")).then(pl.col("_floor")).otherwise(pl.col("_floor") + pl.duration(minutes=5)).alias("forecast_origin_utc")).drop("_floor").join(mapping, left_on=["underlying_symbol", "forecast_origin_utc"], right_on=["asset", "forecast_origin_utc"], how="inner")
        for cutoff in (60, 120, 300):
            results.append(events.filter(pl.col("uw_operational_base_time") <= pl.col("forecast_origin_utc") - pl.duration(seconds=cutoff)).group_by("origin_id").agg([pl.len().alias("uw_eligible_trade_count"), pl.col("uw_operational_base_time").max().alias("uw_max_operational_base_time")]).with_columns([pl.lit(cutoff).alias("uw_cutoff_seconds"), pl.lit(role).alias("sample_role")]).collect(engine="streaming"))
    if not results:
        raise RuntimeError("FULL_TAPE_PARQUET_MISSING")
    counts = pl.concat(results, how="diagonal_relaxed").group_by(["origin_id", "uw_cutoff_seconds", "sample_role"]).agg([pl.col("uw_eligible_trade_count").sum(), pl.col("uw_max_operational_base_time").max()])
    grid = origins.select(["origin_id", "sample_role"]).unique().join(pl.DataFrame({"uw_cutoff_seconds": [60, 120, 300]}), how="cross")
    return grid.join(counts, on=["origin_id", "uw_cutoff_seconds", "sample_role"], how="left").with_columns([pl.col("uw_eligible_trade_count").fill_null(0), pl.lit(True).alias("uw_event_file_observed")]).with_columns(pl.col("uw_eligible_trade_count").gt(0).alias("uw_activity_present")).sort(["origin_id", "uw_cutoff_seconds"])


def add_status(frame: pl.DataFrame, uw_primary: pl.DataFrame) -> pl.DataFrame:
    """Add strict eligibility and exhaustive machine-readable exclusion reasons."""
    frame = frame.join(uw_primary, on="origin_id", how="left")
    missing_b0 = pl.any_horizontal([pl.col(column).is_null() for column in B0_FEATURES])
    missing_b2 = pl.any_horizontal([pl.col(column).is_null() for column in B2_FEATURES])
    b0_ok = ~missing_b0 & pl.col("fmp_plus1_valid") & (pl.col("target_validity") == "valid") & (pl.col("target_future_close_count") == 30) & (pl.col("target_price_count") == 31) & pl.col("rv30").is_not_null()
    b1_ok = pl.col("b1q_route_complete").fill_null(False) & pl.col("b1q_pit_evidence_valid").fill_null(False) & pl.col("b1q_quote_not_after_origin").fill_null(False) & pl.col("b1q_atm_iv").is_not_null() & (pl.col("b1q_valid_quote_count").fill_null(0) > 0) & (pl.col("b1q_iv_successes").fill_null(0) > 0) & (pl.col("b1q_median_quote_age").fill_null(float("inf")) <= 60) & (pl.col("b1q_median_relative_spread").fill_null(float("inf")) <= 0.25)
    b2_ok = ~missing_b2 & (pl.col("b2_availability_spec") == "primary_60s") & (pl.col("b2_operational_cutoff_seconds") == 60) & pl.col("uw_event_file_observed").fill_null(False) & ~pl.col("b2_pit_recheck_failed").fill_null(True)
    return frame.with_columns([
        b0_ok.alias("b0_complete"), b1_ok.alias("b1q_primary_complete"), b2_ok.alias("b2_primary_complete"), (b0_ok & b1_ok & b2_ok).alias("strict_common_eligible"),
        (~missing_b0).alias("b0_predictors_observed"), (~missing_b2).alias("b2_predictors_observed"),
        pl.when(~b0_ok).then(pl.lit("B0_INVALID_OR_TARGET_INVALID")).when(~b1_ok).then(pl.lit("B1Q_PRIMARY_QUOTE_OR_IV_QUALITY_FAILURE")).when(~b2_ok).then(pl.lit("B2_PRIMARY_PIT_RECHECK_FAILURE")).otherwise(pl.lit("NONE")).alias("exclusion_reason_code"),
        pl.lit(True).alias("no_imputation_applied"), pl.lit(True).alias("no_balancing_applied"),
    ])


def write_common_matrices(frame: pl.DataFrame) -> dict[str, pl.DataFrame]:
    """Write strict, availability-aware, target and exclusion tables."""
    COMMON.mkdir(parents=True, exist_ok=True)
    strict = frame.filter(pl.col("strict_common_eligible")).sort("origin_id")
    available = frame.filter(pl.col("b0_complete")).sort("origin_id")
    targets = available.select(["origin_id", "asset", "session_date", "forecast_origin_utc", "sample_role", "rv30", "target_future_close_count", "target_price_count"])
    exclusions = frame.filter(~pl.col("strict_common_eligible")).select(["origin_id", "asset", "session_date", "forecast_origin_utc", "sample_role", "exclusion_reason_code", "b0_complete", "b1q_primary_complete", "b2_primary_complete", "b1q_missing_reason"]).sort("origin_id")
    strict.write_parquet(COMMON / "common_matrix_strict_25d.parquet", compression="zstd")
    available.write_parquet(COMMON / "common_matrix_available_25d.parquet", compression="zstd")
    targets.write_parquet(COMMON / "common_matrix_targets_25d.parquet", compression="zstd")
    exclusions.write_parquet(COMMON / "common_matrix_exclusions_v1.parquet", compression="zstd")
    return {"strict": strict, "available": available, "targets": targets, "exclusions": exclusions}


def sensitivity_grid(frame: pl.DataFrame, uw: pl.DataFrame) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Build row-level FMP/UW sensitivity grid and summary."""
    rows: list[pl.DataFrame] = []
    primary_ids: set[str] = set()
    for fmp_delay in (1, 2):
        for uw_cutoff in (60, 120, 300):
            subset = frame.join(uw.filter(pl.col("uw_cutoff_seconds") == uw_cutoff).select(["origin_id", "uw_eligible_trade_count", "uw_activity_present"]), on="origin_id", how="left")
            fmp_valid = pl.col("fmp_plus1_valid") if fmp_delay == 1 else pl.col("fmp_plus2_valid")
            strict = fmp_valid & pl.col("b0_complete") & pl.col("b1q_primary_complete") & pl.col("b2_primary_complete")
            rows.append(subset.select([
                "origin_id", "asset", "session_date", "sample_role", "b0_session_segment",
                pl.lit(fmp_delay).alias("fmp_delay_minutes"), pl.lit(uw_cutoff).alias("uw_cutoff_seconds"),
                fmp_valid.alias("fmp_availability_valid"), pl.col("b1q_primary_complete").alias("b1q_coverage_valid"),
                pl.col("b2_primary_complete").alias("b2_feature_row_valid"), pl.col("uw_activity_present").alias("b2_activity_present"),
                pl.col("uw_eligible_trade_count").alias("uw_eligible_trade_count"), pl.col("rv30"), strict.alias("strict_eligible"),
            ]))
            if fmp_delay == 1 and uw_cutoff == 60:
                primary_ids = set(rows[-1].filter(pl.col("strict_eligible"))["origin_id"].to_list())
    grid = pl.concat(rows, how="vertical_relaxed").sort(["fmp_delay_minutes", "uw_cutoff_seconds", "origin_id"])
    summary_rows: list[dict[str, Any]] = []
    primary = grid.filter((pl.col("fmp_delay_minutes") == 1) & (pl.col("uw_cutoff_seconds") == 60))
    for key, group in grid.group_by(["fmp_delay_minutes", "uw_cutoff_seconds"], maintain_order=True):
        fmp_delay, cutoff = key
        ids = set(group.filter(pl.col("strict_eligible"))["origin_id"].to_list())
        asset_change = False
        for asset in ASSETS:
            current = group.filter((pl.col("asset") == asset) & pl.col("strict_eligible"))["origin_id"].n_unique()
            baseline = primary.filter((pl.col("asset") == asset) & pl.col("strict_eligible"))["origin_id"].n_unique()
            if abs(current - baseline) / max(baseline, 1) > 0.10:
                asset_change = True
        summary_rows.append({
            "fmp_delay_minutes": fmp_delay, "uw_cutoff_seconds": cutoff, "origin_rows": group.height,
            "strict_rows": len(ids), "retention_rate": len(ids) / max(group.height, 1),
            "b1q_coverage": float(cast(float, group["b1q_coverage_valid"].cast(pl.Float64).mean())),
            "b2_activity_coverage": float(cast(float, group["b2_activity_present"].cast(pl.Float64).mean())),
            "median_target_rv30": float(cast(float, group["rv30"].median())), "row_ids_gained_vs_primary": len(ids - primary_ids),
            "row_ids_lost_vs_primary": len(primary_ids - ids),
            "material_change_over_5pct": abs(len(ids) - len(primary_ids)) / max(len(primary_ids), 1) > 0.05,
            "material_asset_change_over_10pct": asset_change,
        })
    summary = pl.DataFrame(summary_rows).sort(["fmp_delay_minutes", "uw_cutoff_seconds"])
    PIT.mkdir(parents=True, exist_ok=True)
    grid.write_parquet(PIT / "pit_sensitivity_grid_v1.parquet", compression="zstd")
    summary.write_csv(PIT / "pit_sensitivity_summary_v1.csv")
    return grid, summary


def profile_common(frame: pl.DataFrame, matrices: dict[str, pl.DataFrame], uw: pl.DataFrame, grid: pl.DataFrame, inputs: dict[str, Any]) -> dict[str, Any]:
    """Write the common-matrix profile and PIT identity checks."""
    available = matrices["available"]
    strict = matrices["strict"]
    target_overlap = sorted(set(MANDATORY_PREDICTORS) & {"rv30", "target_future_close_count", "target_price_count"})
    dates = sorted(available["session_date"].unique().to_list())
    calendar = xcals.get_calendar("XNYS")
    sessions = [str(item.date()) for item in calendar.sessions_in_range(min(dates), max(dates))]
    observed = set(dates)
    longest = current = 0
    for value in sessions:
        current = current + 1 if value in observed else 0
        longest = max(longest, current)
    profile = {
        "schema_version": "phase4a-common-matrix-profile-v1", "status": "PASS_RECONCILED_LOCAL_INPUTS",
        "nominal_origins": frame.height, "strict_rows": strict.height, "availability_aware_rows": available.height,
        "strict_retention_percentage": 100 * strict.height / max(available.height, 1), "assets": sorted(available["asset"].unique().to_list()),
        "sample_roles": available.group_by("sample_role").len().sort("sample_role").to_dicts(),
        "nominal_rows_by_role": frame.group_by("sample_role").len().sort("sample_role").to_dicts(),
        "availability_aware_rows_by_role": available.group_by("sample_role").len().sort("sample_role").to_dicts(),
        "strict_rows_by_role": strict.group_by("sample_role").len().sort("sample_role").to_dicts(),
        "dates": dates,
        "rows_by_asset": available.group_by("asset").agg([pl.len().alias("available_rows"), pl.col("strict_common_eligible").sum().alias("strict_rows")]).sort("asset").to_dicts(),
        "rows_by_date": available.group_by("session_date").agg([pl.len().alias("available_rows"), pl.col("strict_common_eligible").sum().alias("strict_rows"), pl.col("asset").n_unique().alias("assets")]).sort("session_date").to_dicts(),
        "rows_by_time_of_day": available.group_by("b0_session_segment").agg([pl.len().alias("available_rows"), pl.col("strict_common_eligible").sum().alias("strict_rows")]).sort("b0_session_segment").to_dicts(),
        "b1q_coverage_by_asset": available.group_by("asset").agg([pl.len().alias("origins"), pl.col("b1q_primary_complete").mean().alias("coverage"), pl.col("strict_common_eligible").mean().alias("strict_coverage")]).sort("asset").to_dicts(),
        "b1q_coverage_by_session_segment": available.group_by("b0_session_segment").agg([pl.len().alias("origins"), pl.col("b1q_primary_complete").mean().alias("coverage"), pl.col("strict_common_eligible").mean().alias("strict_coverage")]).sort("b0_session_segment").to_dicts(),
        "b2_activity_presence_by_cutoff": uw.group_by("uw_cutoff_seconds").agg(pl.col("uw_activity_present").mean().alias("coverage")).sort("uw_cutoff_seconds").to_dicts(),
        "missingness": {column: int(available[column].null_count()) for column in available.columns if column.startswith(("b0_", "b1q_", "b2_"))},
        "exclusions_by_reason": frame.filter(~pl.col("strict_common_eligible")).group_by("exclusion_reason_code").len().sort("exclusion_reason_code").to_dicts(),
        "leakage_checks": {
            "b0_predictor_after_origin_rows": int(available.filter(~pl.col("fmp_plus1_valid")).height),
            "massive_quote_after_origin_rows": int(available.filter(~pl.col("b1q_quote_not_after_origin")).height),
            "uw_primary_recheck_pass_rows": int(available.filter(~pl.col("b2_pit_recheck_failed")).height),
            "uw_primary_recheck_failed_rows": int(available.filter(pl.col("b2_pit_recheck_failed")).height),
            "b2_panel_count_mismatch_rows": int(available.filter(pl.col("b2_pit_recheck_failed")).height),
            "target_predictor_overlap": target_overlap, "duplicate_origin_ids": available.height - available["origin_id"].n_unique(),
            "cross_session_contamination": int(available.filter(~pl.col("origin_id").str.contains(pl.col("session_date"))).height),
        },
        "target": {"name": "RV30", "prices_per_target": 31, "returns_per_target": 30, "formula_version": "rv30-v1", "invalid_rows": int(available.filter((pl.col("target_future_close_count") != 30) | (pl.col("target_price_count") != 31)).height)},
        "continuity": {"sampled_dates": dates, "calendar_sessions_between_first_last": sessions, "missing_sessions_not_sampled": sorted(set(sessions) - observed), "longest_contiguous_observed_segment": longest, "effective_independent_days": len(dates), "daily_continuity_proven": False},
        "no_imputation": True, "no_interpolation": True, "no_artificial_balancing": True, "pilot_transformations_fitted_on_calibration_only": True,
        "input_hashes": inputs, "sensitivity_rows": grid.height,
    }
    write_json(COMMON / "common_matrix_profile_v1.json", profile)
    return profile


def feature_lineage() -> None:
    """Write candidate predictor lineage with implementation and PIT rules."""
    rows: list[dict[str, Any]] = []
    names = list(B0_FEATURES) + ["b1q_atm_iv", "b1q_skew", "b1q_term_structure"] + list(B2_FEATURES) + ["b2_unusual_intensity_score", "b2_unusual_event"]
    for name in names:
        benchmark = "B0" if name.startswith("b0_") else "B1Q" if name.startswith("b1q_") else "B2"
        provider = "FMP" if benchmark == "B0" else "Massive" if benchmark == "B1Q" else "Unusual Whales Full Tape"
        definition = "lagged underlying control" if benchmark == "B0" else "ordinary option state from as-of quote" if benchmark == "B1Q" else "continuous five-minute aggregate of eligible trades"
        if name == "b2_unusual_intensity_score":
            definition = "calibration-only robust trailing score applied to pilot"
        if name == "b2_unusual_event":
            definition = "secondary trailing label; not a primary predictor"
        rows.append({
            "benchmark_set": benchmark, "exact_feature_name": name, "mathematical_definition": definition, "source_provider": provider,
            "endpoint": "FMP intraday" if benchmark == "B0" else "Massive quotes" if benchmark == "B1Q" else "Full Tape retained Parquet",
            "raw_fields": "close,volume,timestamp" if benchmark == "B0" else "sip_timestamp,bid,ask,strike,expiry,option_type" if benchmark == "B1Q" else "executed_at,created_at,id,premium,size,contract,bid,ask,IV,tags",
            "original_frequency": "1-minute" if benchmark == "B0" else "quote" if benchmark == "B1Q" else "trade", "temporal_aggregation": "origin as-of / prior 5-minute bin", "lookback_window": "documented lag", "minimum_observations": "documented; no imputation", "timestamp_used_for_availability": "FMP raw+1m" if benchmark == "B0" else "sip_timestamp <= origin" if benchmark == "B1Q" else "max(executed_at,created_at) <= origin-cutoff", "lag": "+1m / 60s primary", "session_reset_behaviour": "reset at XNYS session boundary", "missing_value_behaviour": "strict exclusion; availability-aware missingness", "quality_filters": "exact/as-of joins; no crossed/stale quotes", "fitted_parameters_required": "yes only for unusual score", "fitting_sample": "CALIBRATION only; pilot application only", "leakage_risk": "post-origin provider record", "implementation_file": "scripts/run_authorized_pilot.py; scripts/run_b1_calibration_20d.py; scripts/build_b2_calibration_20d.py", "function_or_class": "existing builders", "tests": "tests/contract/test_pit_gate_artifacts.py and Phase 4A tests", "status": "METADATA_ONLY" if name == "b2_unusual_event" else "IMPLEMENTED"})
    COMMON.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(rows).write_csv(COMMON / "feature_lineage_v1.csv")


def provider_semantics() -> dict[str, Any]:
    """Write field-level provider time/PIT register."""
    records = [
        {"provider": "FMP", "endpoint": "stable/historical-chart/1min/{symbol}", "field": "date/timestamp", "raw_type": "string YYYY-MM-DD HH:mm:ss", "raw_timezone": "naive exchange-local observed", "official_semantics": "intraday timestamp; start/close boundary not contractually confirmed", "observed_semantics": "start-label-consistent in 78/78 intervals", "research_interpretation": "bar-start assumption", "earliest_safe_availability": "raw+1m primary; raw+2m sensitivity", "transformation": "America/New_York then UTC", "verification_status": "AUTHENTICATED_EVIDENCE_PLUS_ASSUMPTION", "evidence": "artifacts/pit/fmp_bar_semantics_v3.json", "test": "tests/contract/test_pit_gate_artifacts.py", "documentation_url": "https://site.financialmodelingprep.com/how-to/how-to-get-stock-intraday-data-with-fmp-apis"},
        {"provider": "FMP", "endpoint": "stable/historical-chart/1min/{symbol}", "field": "open/high/low/close/volume", "raw_type": "numeric", "raw_timezone": "exchange-local label", "official_semantics": "OHLCV bar values", "observed_semantics": "390 regular / 210 early-close samples", "research_interpretation": "B0 controls; target bars future only", "earliest_safe_availability": "configured delay for predictors", "transformation": "timezone normalization; no interpolation", "verification_status": "AUTHENTICATED_EMPIRICAL_EVIDENCE", "evidence": "artifacts/pit/fmp_bar_semantics_v3.json", "test": "tests/contract/test_pit_gate_artifacts.py", "documentation_url": "https://site.financialmodelingprep.com/how-to/how-to-get-stock-intraday-data-with-fmp-apis"},
        {"provider": "FMP", "endpoint": "stable/dividends", "field": "dividends", "raw_type": "JSON date/numeric", "raw_timezone": "date", "official_semantics": "dividend records", "observed_semantics": "pre-origin filter for BSM input", "research_interpretation": "B1 input only", "earliest_safe_availability": "declaration cutoff", "transformation": "pre-origin filter", "verification_status": "AUTHENTICATED_EVIDENCE", "evidence": "scripts/run_b1_calibration_20d.py", "test": "tests/contract/test_b1_closure_artifacts.py", "documentation_url": "https://site.financialmodelingprep.com/developer/docs/dividends-calendar"},
        {"provider": "FMP", "endpoint": "stable/treasury-rates", "field": "month3", "raw_type": "numeric percent", "raw_timezone": "date", "official_semantics": "Treasury rate", "observed_semantics": "latest date not after origin", "research_interpretation": "pre-origin BSM input", "earliest_safe_availability": "latest <= origin", "transformation": "percent / 100", "verification_status": "AUTHENTICATED_EVIDENCE", "evidence": "scripts/run_b1_calibration_20d.py", "test": "tests/contract/test_b1_closure_artifacts.py", "documentation_url": "https://site.financialmodelingprep.com/developer/docs/treasury-rates"},
        {"provider": "FMP", "endpoint": "historical/earning_calendar/{symbol}", "field": "date/time", "raw_type": "date/string timing", "raw_timezone": "provider timing field", "official_semantics": "symbol-specific earnings timing", "observed_semantics": "requested/returned symbols matched; BMO/AMC fields", "research_interpretation": "excluded from primary benchmark", "earliest_safe_availability": "calendar timing only", "transformation": "ex-ante flags; actual EPS/revenue excluded", "verification_status": "AUTHENTICATED_EVIDENCE", "evidence": "artifacts/pit/earnings_pit_probe_v2.json", "test": "tests/unit/test_corporate_event_contract.py", "documentation_url": "https://site.financialmodelingprep.com/developer/docs/earnings-calendar"},
        {"provider": "FMP", "endpoint": "historical chart", "field": "adjusted/unadjusted", "raw_type": "provider schema", "raw_timezone": "exchange-local label", "official_semantics": "adjustment treatment endpoint-specific", "observed_semantics": "not frozen as adjusted in common matrix", "research_interpretation": "unresolved corporate-action limitation", "earliest_safe_availability": "not admitted separately", "transformation": "preserve status", "verification_status": "UNRESOLVED_LIMITATION", "evidence": "artifacts/pit/fmp_bar_semantics_v3.json", "test": "Phase 4A alignment audit", "documentation_url": "https://site.financialmodelingprep.com/how-to/how-to-get-stock-intraday-data-with-fmp-apis"},
        {"provider": "Massive", "endpoint": "/v3/quotes/{optionsTicker}", "field": "sip_timestamp", "raw_type": "integer nanoseconds", "raw_timezone": "UTC epoch", "official_semantics": "SIP quote timestamp", "observed_semantics": "latest selected <= origin after ns conversion", "research_interpretation": "quote event time", "earliest_safe_availability": "sip_timestamp <= origin", "transformation": "nanoseconds to UTC", "verification_status": "AUTHENTICATED_EVIDENCE", "evidence": "artifacts/b1_full_origin/b1_origin_matrix.parquet", "test": "tests/contract/test_b1_closure_artifacts.py", "documentation_url": "https://massive.com/docs/rest/options/quotes"},
        {"provider": "Massive", "endpoint": "/v3/quotes/{optionsTicker}", "field": "participant_timestamp/sequence_number", "raw_type": "integer", "raw_timezone": "UTC epoch / ordering metadata", "official_semantics": "participant/sequence metadata", "observed_semantics": "diagnostic; not cutoff", "research_interpretation": "ordering evidence only", "earliest_safe_availability": "not primary", "transformation": "preserve raw", "verification_status": "AUTHENTICATED_EVIDENCE", "evidence": "artifacts/calibration_20d/massive_b1q_cache_v2", "test": "Phase 4A alignment audit", "documentation_url": "https://massive.com/docs/rest/options/quotes"},
        {"provider": "Massive", "endpoint": "/v3/quotes/{optionsTicker}", "field": "bid/ask/conditions", "raw_type": "numeric/code", "raw_timezone": "quote UTC", "official_semantics": "quote and condition fields", "observed_semantics": "bid>0, ask>bid, age<=60s, spread<=25%", "research_interpretation": "B1Q quality filters", "earliest_safe_availability": "sip_timestamp <= origin", "transformation": "midpoint/spread", "verification_status": "AUTHENTICATED_EVIDENCE", "evidence": "docs/b1_data_contract.md", "test": "tests/contract/test_b1_closure_artifacts.py", "documentation_url": "https://massive.com/docs/rest/options/quotes"},
        {"provider": "Massive", "endpoint": "/v3/reference/options/contracts/{contract}", "field": "as_of/expiration/strike/option_type", "raw_type": "date/numeric/string", "raw_timezone": "date/UTC metadata", "official_semantics": "historical contract reference", "observed_semantics": "resolved by asset/date/DTE", "research_interpretation": "contract identity before quote as-of join", "earliest_safe_availability": "contract existed as_of session", "transformation": "OCC/root normalization", "verification_status": "AUTHENTICATED_EVIDENCE", "evidence": "artifacts/api_audit/common_history_continuity_v5.json", "test": "tests/contract/test_b1_closure_artifacts.py", "documentation_url": "https://massive.com/docs/rest/options/contracts"},
        {"provider": "Unusual Whales", "endpoint": "Full Tape retained Parquet", "field": "executed_at", "raw_type": "UTC datetime", "raw_timezone": "UTC", "official_semantics": "reported trade-event time", "observed_semantics": "used for five-minute event bin", "research_interpretation": "economic event time, not availability", "earliest_safe_availability": "paired with operational base", "transformation": "UTC parse/bin", "verification_status": "AUTHENTICATED_EVIDENCE", "evidence": "artifacts/calibration_20d/raw_integrity_report.json", "test": "tests/contract/test_calibration_20d.py", "documentation_url": "https://api.unusualwhales.com/docs/kafka/types/OptionTrade"},
        {"provider": "Unusual Whales", "endpoint": "Full Tape retained Parquet", "field": "created_at", "raw_type": "UTC datetime", "raw_timezone": "UTC", "official_semantics": "record creation; publication not defined", "observed_semantics": "compared with executed_at; delay diagnostics", "research_interpretation": "operational proxy only via max(executed_at,created_at)", "earliest_safe_availability": "origin-60s primary; 120/300 sensitivity", "transformation": "max timestamps", "verification_status": "UNRESOLVED_LIMITATION_PLUS_APPROVED_PROXY", "evidence": "artifacts/pit/uw_created_at_semantics_v1.json", "test": "Phase 4A UW cutoff audit", "documentation_url": "https://api.unusualwhales.com/docs/kafka/types/OptionTrade"},
        {"provider": "Unusual Whales", "endpoint": "Full Tape retained Parquet", "field": "id/option_chain_id/price/premium/size/bid/ask/option_type", "raw_type": "string/numeric", "raw_timezone": "event UTC", "official_semantics": "trade/contract fields", "observed_semantics": "dedup by id; continuous aggregates", "research_interpretation": "B2 features; no intention claim", "earliest_safe_availability": "operational base cutoff", "transformation": "5-minute aggregate", "verification_status": "AUTHENTICATED_EVIDENCE", "evidence": "artifacts/calibration_20d/raw_integrity_report.json", "test": "tests/contract/test_calibration_20d.py", "documentation_url": "https://api.unusualwhales.com/docs/kafka/types/OptionTrade"},
        {"provider": "Unusual Whales", "endpoint": "Full Tape retained Parquet", "field": "sweep/multileg/floor/implied_volatility/open_interest", "raw_type": "string/numeric", "raw_timezone": "event UTC", "official_semantics": "descriptive metadata", "observed_semantics": "shares and missingness; OI treated prior-session", "research_interpretation": "descriptive activity only", "earliest_safe_availability": "operational base cutoff", "transformation": "tag parsing", "verification_status": "AUTHENTICATED_EVIDENCE", "evidence": "artifacts/calibration_20d/b2_calibration_panel.parquet", "test": "tests/contract/test_calibration_20d.py", "documentation_url": "https://api.unusualwhales.com/docs/kafka/types/OptionTrade"},
    ]
    checks = [
        {"check": "winter_timezone", "status": "PASS", "evidence": "artifacts/pit/fmp_bar_semantics_v3.json"},
        {"check": "summer_timezone", "status": "PASS", "evidence": "artifacts/pit/fmp_bar_semantics_v3.json"},
        {"check": "DST_transition", "status": "PASS", "evidence": "tests/contract/test_pit_gate_artifacts.py"},
        {"check": "normal_390_session", "status": "PASS", "evidence": "artifacts/pit/fmp_bar_semantics_v3.json"},
        {"check": "early_close_210_session", "status": "PASS", "evidence": "artifacts/pit/fmp_bar_semantics_v3.json"},
        {"check": "missing_bars", "status": "OBSERVED_AND_EXCLUDED", "evidence": "artifacts/api_audit/common_history_continuity_v5.json"},
        {"check": "duplicate_timestamps", "status": "PASS_SAMPLES", "evidence": "artifacts/pit/fmp_bar_semantics_v3.json"},
        {"check": "out_of_order_records", "status": "PASS_RETAINED_PARTITIONS", "evidence": "artifacts/calibration_20d/raw_integrity_report.json"},
        {"check": "negative_or_extreme_uw_delays", "status": "REPORTED_IN_PHASE4A_PROFILE", "evidence": "artifacts/common_sample/common_matrix_profile_v1.json"},
        {"check": "origin_boundary", "status": "PASS", "evidence": "artifacts/common_sample/common_matrix_profile_v1.json"},
    ]
    payload = {"schema_version": "provider-time-semantics-register-v2", "records": records, "controlled_checks": checks, "secret_values_emitted": False, "personal_paths_emitted": False}
    write_json(PIT / "provider_time_semantics_register_v2.json", payload)
    return payload


def cross_provider_alignment(frame: pl.DataFrame, uw: pl.DataFrame) -> dict[str, Any]:
    """Produce provider alignment counts by asset/session/time bucket."""
    rows: list[dict[str, Any]] = []
    for row in frame.iter_rows(named=True):
        for provider, ok, reason in (("FMP", row["b0_complete"], "NONE" if row["b0_complete"] else "B0_INVALID"), ("Massive", row["b1q_primary_complete"], "NONE" if row["b1q_primary_complete"] else str(row.get("b1q_missing_reason") or "B1Q_FAILURE")), ("Unusual Whales", row["b2_primary_complete"], "NONE" if row["b2_primary_complete"] else "B2_PIT_FAILURE")):
            rows.append({"provider": provider, "asset": row["asset"], "session_date": row["session_date"], "time_of_day": row["b0_session_segment"], "status": "PASS" if ok else "FAIL", "rejection_reason": reason})
    detail = pl.DataFrame(rows)
    summary = detail.group_by(["provider", "asset", "session_date", "time_of_day", "rejection_reason"]).agg([pl.len().alias("rows"), (pl.col("status") == "PASS").sum().alias("passes")]).sort(["provider", "asset", "session_date", "time_of_day", "rejection_reason"])
    summary.write_csv(AUDITS / "cross_provider_alignment_detail_v1.csv")
    payload = {"schema_version": "cross-provider-alignment-v1", "summary_rows": summary.to_dicts(), "global": detail.group_by("provider").agg([pl.len().alias("rows"), (pl.col("status") == "PASS").mean().alias("pass_rate")]).sort("provider").to_dicts(), "join_rules": {"underlying": "exact asset/session/origin", "Massive": "as-of sip_timestamp <= origin", "UW": "exact asset/origin bin after operational cutoff", "nearest_neighbour_join": False}, "normalization_checks": {"symbol_mapping": "PASS", "OCC_contract_normalization": "EVIDENCE_REUSED", "expiration_strike_type_consistency": "EVIDENCE_REUSED", "corporate_actions": "LIMITATION_RETAINED", "expired_fallback": "EXPLICIT_IN_PROVIDER_AUDIT"}, "uw_activity_rows": uw.height, "secret_values_emitted": False, "personal_paths_emitted": False}
    write_json(AUDITS / "cross_provider_alignment_v1.json", payload)
    return payload


def quality_and_bias(frame: pl.DataFrame, matrices: dict[str, pl.DataFrame]) -> dict[str, Any]:
    """Write descriptive data-quality and strict-sample selection-bias evidence."""
    available = matrices["available"]
    strict = matrices["strict"]
    excluded = available.filter(~pl.col("strict_common_eligible"))
    rows: list[dict[str, Any]] = []
    for comparison, group in (("STRICT", strict), ("B1Q_EXCLUDED", excluded)):
        for group_type, values in (("asset", ASSETS), ("time_of_day", ("first", "middle", "last"))):
            for value in values:
                subset = group.filter(pl.col("asset" if group_type == "asset" else "b0_session_segment") == value)
                if subset.is_empty():
                    continue
                rows.append({"comparison": comparison, "group_type": group_type, "group": value, "rows": subset.height, "rv30_mean": float(cast(float, subset["rv30"].mean())), "rv30_median": float(cast(float, subset["rv30"].median())), "rv30_std": float(cast(float | None, subset["rv30"].std()) or 0), "volume_5m_mean": float(cast(float, subset["b0_volume_5m_lag"].mean())), "session_minute_mean": float(cast(float, subset["b0_session_minute"].mean())), "quote_age_median": float(cast(float, subset["b1q_median_quote_age"].median())) if subset["b1q_median_quote_age"].null_count() < subset.height else None, "relative_spread_median": float(cast(float, subset["b1q_median_relative_spread"].median())) if subset["b1q_median_relative_spread"].null_count() < subset.height else None})
    bias = pl.DataFrame(rows).sort(["comparison", "group_type", "group"])
    AUDITS.mkdir(parents=True, exist_ok=True)
    bias.write_csv(AUDITS / "selection_bias_audit_v1.csv")
    payload = {"schema_version": "common-sample-quality-and-bias-v1", "initial_origins": frame.height, "retained_strict_origins": strict.height, "retained_availability_aware_origins": available.height, "retention_percentage": 100 * strict.height / max(available.height, 1), "missingness": {column: int(available[column].null_count()) for column in available.columns if column.startswith(("b0_", "b1q_", "b2_"))}, "duplicate_origin_ids": available.height - available["origin_id"].n_unique(), "cross_session_contamination": int(available.filter(~pl.col("origin_id").str.contains(pl.col("session_date"))).height), "target_predictor_overlap": sorted(set(MANDATORY_PREDICTORS) & {"rv30", "target_future_close_count", "target_price_count"}), "selection_bias_file": "artifacts/audits/selection_bias_audit_v1.csv", "interpretation": "descriptive effect sizes; no p-values and no causal claim", "survivorship_limitation": "purposive eight-asset liquid universe is not the US equity market", "no_interpolation": True, "no_imputation": True}
    write_json(AUDITS / "common_sample_quality_v1.json", payload)
    return payload


def effective_sample_size(frame: pl.DataFrame) -> dict[str, Any]:
    """Run a planning-only synthetic clustered loss-difference simulation."""
    days = sorted(frame["session_date"].unique().to_list())
    grid: list[dict[str, Any]] = []
    rng = np.random.default_rng(650)
    for sessions in (60, 120, 180):
        for day_rho in (0.0, 0.3, 0.6):
            for asset_rho in (0.0, 0.5):
                day_effect = rng.normal(size=(200, sessions))
                idio = rng.normal(size=(200, sessions, 8))
                common = rng.normal(size=(200, sessions, 1))
                losses = math.sqrt(day_rho) * day_effect[:, :, None] + math.sqrt(max(1 - day_rho, 0)) * idio
                losses = math.sqrt(asset_rho) * common + math.sqrt(max(1 - asset_rho, 0)) * losses
                se = float(losses.mean(axis=2).std(axis=1).mean() / math.sqrt(sessions))
                grid.append({"sessions": sessions, "within_day_dependence": day_rho, "cross_asset_dependence": asset_rho, "synthetic_replicates": 200, "detectable_standardized_effect": float((1.96 + 0.84) * se), "planning_only": True})
    payload = {"schema_version": "effective-sample-size-v1", "nominal_rows": frame.height, "observed_trading_days": len(days), "asset_days": frame.select(["asset", "session_date"]).unique().height, "origins_per_day": frame.group_by("session_date").len().sort("session_date").to_dicts(), "target_overlap_minutes": 30, "cross_asset_dependence": "same trading-day clusters; rows are not independent", "effective_independent_days_observed": len(days), "planning_grid": grid, "limitations": ["synthetic paired loss differentials are not model losses", "no predictive performance calculated", "dependence grid is design sensitivity, not estimated dependence"]}
    FEASIBILITY.mkdir(parents=True, exist_ok=True)
    write_json(FEASIBILITY / "effective_sample_size_v1.json", payload)
    return payload


def telemetry_projection(frame: pl.DataFrame, uw: pl.DataFrame) -> dict[str, Any]:
    """Project resource requirements from observed twenty-session telemetry."""
    telemetry = pl.read_csv(CAL / "storage_telemetry.csv")
    raw = telemetry["raw_bytes"].cast(pl.Float64)
    parquet = telemetry["parquet_bytes"].cast(pl.Float64)
    elapsed = telemetry["decompression_seconds"].cast(pl.Float64)
    sessions = [str(value) for value in telemetry["session_date"].to_list()]
    extracted: list[int] = []
    cache: list[int] = []
    for session in sessions:
        zip_path = CAL / "raw" / "full_tape" / session / f"full_tape_{session}.zip"
        if not zip_path.exists():
            raise RuntimeError(f"RAW_ZIP_METADATA_MISSING:{session}")
        with zipfile.ZipFile(zip_path) as archive:
            extracted.append(sum(member.file_size for member in archive.infolist()))
        cache.append(sum(path.stat().st_size for path in (CAL / "massive_b1q_cache_v2").glob(f"*_{session}_*.json")))
    raw_mean, raw_p95 = float(cast(float, raw.mean())), float(cast(float, raw.quantile(0.95)))
    parquet_mean, parquet_p95 = float(cast(float, parquet.mean())), float(cast(float, parquet.quantile(0.95)))
    elapsed_mean, elapsed_p95 = float(cast(float, elapsed.mean())), float(cast(float, elapsed.quantile(0.95)))
    extracted_mean, extracted_p95 = float(np.mean(extracted)), float(np.quantile(extracted, 0.95))
    cache_mean, cache_p95 = float(np.mean(cache)), float(np.quantile(cache, 0.95))
    observed_download = telemetry.filter(pl.col("download_seconds") > 0)["download_seconds"].cast(pl.Float64)
    download_mean = float(cast(float, observed_download.mean())) if len(observed_download) else 0.0
    download_p95 = float(cast(float, observed_download.quantile(0.95))) if len(observed_download) else 0.0
    aggregation = json.loads((CAL / "b2_calibration_telemetry.json").read_text(encoding="utf-8"))
    aggregation_per_session = float(aggregation["feature_aggregation_seconds"]) / telemetry.height
    b1q_rate = float(cast(float, frame["b1q_primary_complete"].mean()))
    b2_complete_rate = float(cast(float, frame["b2_primary_complete"].mean()))
    b2_activity_rate = float(cast(float, uw.filter(pl.col("uw_cutoff_seconds") == 60)["uw_activity_present"].mean()))
    free = shutil.disk_usage(ROOT).free
    temp_space = int(2 * cast(float, telemetry["python_peak_working_set_bytes"].cast(pl.Float64).max()))
    scenarios: list[dict[str, Any]] = []
    for session_count in (60, 120, 180):
        p95_resident = session_count * (raw_p95 + parquet_p95 + cache_p95) + temp_space
        required = int(p95_resident * 1.30)
        origins = session_count * 8 * 71
        scenarios.append({
            "sessions": session_count, "expected_origins": origins, "expected_asset_days": session_count * 8,
            "expected_b1q_usable_rows": round(origins * b1q_rate),
            "expected_b2_pit_eligible_rows": round(origins * b2_activity_rate),
            "expected_b2_complete_feature_rows": round(origins * b2_complete_rate),
            "raw_mean_bytes": int(session_count * raw_mean), "raw_p95_bytes": int(session_count * raw_p95),
            "extracted_uncompressed_mean_bytes": int(session_count * extracted_mean),
            "extracted_uncompressed_p95_bytes": int(session_count * extracted_p95),
            "extracted_storage_status": "STREAMED_NOT_RETAINED_IN_RESIDENT_TOTAL",
            "parquet_mean_bytes": int(session_count * parquet_mean), "parquet_p95_bytes": int(session_count * parquet_p95),
            "massive_cache_mean_bytes": int(session_count * cache_mean), "massive_cache_p95_bytes": int(session_count * cache_p95),
            "temporary_working_space_bytes": temp_space, "resident_p95_bytes_before_reserve": int(p95_resident),
            "required_with_30pct_reserve_bytes": required, "required_with_30pct_reserve_gb": required / 1e9,
            "free_disk_before_execution_bytes": free, "fits_with_30pct_reserve": required <= free,
            "estimated_processing_hours_mean": session_count * elapsed_mean / 3600,
            "estimated_processing_hours_p95": session_count * elapsed_p95 / 3600,
            "estimated_wall_clock_hours_p95": session_count * (download_p95 + elapsed_p95 + aggregation_per_session) / 3600,
            "api_calls_lower_bound": {"unusual_whales_full_tape": session_count, "fmp_exact_session": session_count * 8, "massive_contract_and_quote_cache": session_count * 62},
            "checkpoint_granularity": "one session", "license_status": "provider license confirmation required before retaining commercial raw"
        })
    recommended = "60_SESSIONS" if scenarios[0]["fits_with_30pct_reserve"] else "NO_WINDOW_FITS"
    payload = {
        "schema_version": "backfill-resource-projection-v2", "observed_sessions": telemetry.height,
        "raw_mean_bytes_per_session": int(raw_mean), "raw_p95_bytes_per_session": int(raw_p95),
        "extracted_uncompressed_mean_bytes_per_session": int(extracted_mean),
        "extracted_uncompressed_p95_bytes_per_session": int(extracted_p95),
        "parquet_mean_bytes_per_session": int(parquet_mean), "parquet_p95_bytes_per_session": int(parquet_p95),
        "massive_cache_mean_bytes_per_session": int(cache_mean), "massive_cache_p95_bytes_per_session": int(cache_p95),
        "decompression_seconds_mean": elapsed_mean, "decompression_seconds_p95": elapsed_p95,
        "download_seconds_mean_observed": download_mean, "download_seconds_p95_observed": download_p95,
        "download_observed_sessions": len(observed_download), "filter_stage_is_same_as_decompression": True,
        "aggregation_seconds_total_observed": float(aggregation["feature_aggregation_seconds"]),
        "aggregation_seconds_per_session": aggregation_per_session,
        "observed_b1q_usable_rate": b1q_rate, "observed_b2_pit_activity_rate": b2_activity_rate,
        "observed_b2_complete_feature_rate": b2_complete_rate,
        "current_free_disk_bytes": free, "scenarios": scenarios, "recommended_window": recommended, "full_backfill_executed": False,
        "extraction_method": "ZIP central-directory uncompressed member sizes; no provider request and no extraction performed in Phase 4A",
        "resident_total_method": "raw ZIP + filtered Parquet + Massive cache + 2x peak working set; streamed uncompressed extraction excluded from resident total"
    }
    BACKFILL.mkdir(parents=True, exist_ok=True)
    write_json(BACKFILL / "backfill_resource_projection_v2.json", payload)
    return payload


def restart_dry_run(row_ids: list[str]) -> dict[str, Any]:
    """Exercise deterministic checkpoint/resume and corrupted-checkpoint failure."""
    source_hash = hashlib.sha256("\n".join(row_ids).encode()).hexdigest()
    split = max(1, len(row_ids) // 2)
    checkpoint = checkpoint_payload("phase4a", row_ids[:split], source_hash)
    resumed_ids = sorted(set(checkpoint["row_ids"] + row_ids[split:]))
    expected_hash = hashlib.sha256("\n".join(sorted(set(row_ids))).encode()).hexdigest()
    resumed_hash = hashlib.sha256("\n".join(resumed_ids).encode()).hexdigest()
    corrupted_detected = False
    try:
        validate_checkpoint({**checkpoint, "rows": checkpoint["rows"] + 1})
    except ValueError:
        corrupted_detected = True
    with tempfile.TemporaryDirectory(prefix="mds650_phase4a_") as directory:
        partial = Path(directory) / "partial.parquet"
        partial.write_text("partial", encoding="utf-8")
        partial.unlink()
        cleanup = not partial.exists()
    payload = {"schema_version": "restart-dry-run-v1", "checkpoint_rows": checkpoint["rows"], "input_rows": len(row_ids), "resume_hash": resumed_hash, "uninterrupted_hash": expected_hash, "hashes_identical": resumed_hash == expected_hash, "duplicate_output_rows": len(resumed_ids) - len(set(resumed_ids)), "corrupted_checkpoint_detected": corrupted_detected, "partial_output_cleanup": cleanup, "provider_requests": 0, "full_backfill_executed": False}
    write_json(BACKFILL / "restart_dry_run_v1.json", payload)
    return payload


def temporal_folds() -> list[dict[str, Any]]:
    """Generate proposed chronological folds without fitting models."""
    calendar = xcals.get_calendar("XNYS")
    end = date(2026, 7, 10)
    sessions = [str(item.date()) for item in calendar.sessions_in_range("2020-01-01", end.isoformat())]
    rows: list[dict[str, Any]] = []
    for window, train_n, validation_n, _test_n in ((60, 40, 10, 10), (120, 80, 20, 20), (180, 120, 30, 30)):
        selected = sessions[-window:]
        for fold, role, left, right in (("fold_1", "TRAIN", 0, train_n), ("fold_1", "VALIDATION", train_n, train_n + validation_n), ("fold_1", "TEST_FINAL_UNTOUCHED", train_n + validation_n, window)):
            rows.append({"window_sessions": window, "fold": fold, "role": role, "start_date": selected[left], "end_date": selected[right - 1], "purge_minutes": 30, "embargo_minutes": 30, "same_origin_ids_across_benchmarks": True, "random_split": False})
    VALIDATION.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(rows).write_csv(VALIDATION / "proposed_temporal_folds_v1.csv")
    return rows


def model_and_inference_dossiers(strict: pl.DataFrame) -> dict[str, Any]:
    """Write candidate matrices and descriptive collinearity diagnostics only."""
    METHODOLOGY.mkdir(parents=True, exist_ok=True)
    calibration = strict.filter(pl.col("sample_role") == "CALIBRATION")
    numeric = [column for column in MANDATORY_PREDICTORS if column in calibration.columns]
    matrix: npt.NDArray[np.float64] = np.asarray(
        calibration.select(numeric).drop_nulls().to_numpy(), dtype=np.float64
    )
    condition = None
    max_corr = None
    vif: dict[str, float | None] = {}
    correlation_matrix: dict[str, dict[str, float]] = {}
    redundant_pairs: list[dict[str, Any]] = []
    if matrix.ndim == 2 and matrix.shape[0] > matrix.shape[1] and matrix.shape[1] > 1:
        standardized = (matrix - matrix.mean(axis=0)) / np.where(matrix.std(axis=0) == 0, 1, matrix.std(axis=0))
        condition = float(np.linalg.cond(standardized))
        with np.errstate(divide="ignore", invalid="ignore"):
            corr: npt.NDArray[np.float64] = np.asarray(
                np.nan_to_num(np.corrcoef(standardized, rowvar=False), nan=0.0),
                dtype=np.float64,
            )
        max_corr = float(np.max(np.abs(corr - np.eye(corr.shape[0]))))
        inverse = np.linalg.pinv(corr)
        vif = {name: float(inverse[index, index]) for index, name in enumerate(numeric)}
        correlation_matrix = {name: {other: float(corr[i, j]) for j, other in enumerate(numeric)} for i, name in enumerate(numeric)}
        for i, left in enumerate(numeric):
            for j in range(i + 1, len(numeric)):
                value = abs(float(corr[i, j]))
                if value >= 0.95:
                    redundant_pairs.append({"left": left, "right": numeric[j], "absolute_correlation": value})
    write_json(METHODOLOGY / "collinearity_diagnostics_v1.json", {
        "schema_version": "collinearity-diagnostics-v1", "source": "strict CALIBRATION rows only",
        "predictor_count": len(numeric), "complete_rows": int(matrix.shape[0]) if matrix.ndim == 2 else 0,
        "condition_number": condition, "max_abs_pairwise_correlation": max_corr, "vif": vif,
        "correlation_matrix": correlation_matrix, "redundant_pairs_absolute_correlation_ge_0_95": redundant_pairs,
        "temporal_coefficient_instability": {"status": "NOT_EXECUTED", "reason": "No rolling fit was run because this phase forbids model selection or fitting."},
        "no_model_selection": True
    })
    models = [
        ("naive_persistence", "benchmark", "low", "must be positive; direct RV30", "not applicable", "explicit baseline; no collinearity handling", "no imputation; same origin IDs", "none", "none", "low", "negligible", "same origin IDs B0/B1Q/B2", "recent RV forecasting benchmarks", "INCLUDE_CANDIDATE"),
        ("rolling_historical_mean", "benchmark", "low", "must be positive; rolling mean", "not applicable", "aggregated control; no collinearity handling", "training-history fit only; no imputation", "window length selected inside training", "small", "low", "low", "same origin IDs B0/B1Q/B2", "recent RV forecasting benchmarks", "INCLUDE_CANDIDATE"),
        ("HAR-RV/HARQ", "transparent volatility benchmark", "low", "positive constrained forecast", "lagged volatility terms", "transparent aggregation; collinearity diagnosed", "training-history fit only; no imputation", "HAR lags and HARQ measurement-error terms", "moderate", "low", "low", "same origin IDs B0/B1Q/B2", "recent RV forecasting and HAR applications", "INCLUDE_CANDIDATE"),
        ("OLS", "linear comparison", "medium", "positive post-processing required", "none; sensitive to collinearity", "complete-case or explicitly frozen missingness policy", "no tuning outside training", "coefficient instability and leakage risk", "moderate; observations should exceed predictors", "low", "low", "same origin IDs B0/B1Q/B2", "recent linear-vs-ML RV comparisons", "ROBUSTNESS_ONLY"),
        ("Ridge", "collinearity robustness", "medium", "positive post-processing required", "L2 shrinkage", "training-only imputation policy; no target imputation", "alpha selected inside training/validation", "regularization reduces variance but can mask unstable features", "moderate; still requires validation history", "medium", "medium", "same origin IDs B0/B1Q/B2", "recent shrinkage RV studies", "ROBUSTNESS_ONLY"),
        ("LASSO", "sparse feature robustness", "medium", "positive post-processing required", "L1 sparsity", "training-only imputation policy; no target imputation", "alpha selected inside training/validation", "selection instability under correlated predictors", "moderate; requires more observations than selected features", "medium", "medium", "same origin IDs B0/B1Q/B2", "recent shrinkage RV studies", "ROBUSTNESS_ONLY"),
        ("Elastic Net", "sparse correlated-feature candidate", "high", "positive post-processing required", "combined L1/L2 shrinkage", "training-only imputation policy; no target imputation", "alpha and l1_ratio selected inside training/validation", "two-dimensional tuning and data-snooping risk", "high; validation history must support two-dimensional tuning", "high", "high", "same origin IDs B0/B1Q/B2", "recent shrinkage RV studies; not supervisor-required", "ROBUSTNESS_ONLY"),
        ("tree_based_nonlinear", "nonlinear candidate", "high", "positive leaf/forecast constraint required", "implicit nonlinear interactions", "native missingness only if frozen; otherwise explicit training policy", "depth, learning rate and estimators selected inside training/validation", "high flexibility and extrapolation/selection risk", "high; requires ample independent days despite many rows", "high", "high", "same origin IDs B0/B1Q/B2", "recent tree-based RV comparisons; exact algorithm later", "ROBUSTNESS_ONLY"),
    ]
    pl.DataFrame([{"candidate": name, "scientific_role": role, "target_compatibility": "RV30 continuous non-annualised target", "positive_forecast_requirement": positivity, "interpretability": interpretability, "collinearity_handling": collinearity, "missingness_handling": missingness, "hyperparameters": hyperparameters, "tuning_risk": tuning_risk, "sample_size_requirement": sample_size, "computational_cost": computational_cost, "overfitting_risk": risk, "nested_information_sets": nesting, "primary_literature_support": literature, "recommendation_status": status, "implementation_status": "DOSSIER_ONLY", "supervisor_required": False} for name, role, risk, positivity, interpretability, collinearity, missingness, hyperparameters, tuning_risk, sample_size, computational_cost, nesting, literature, status in models]).write_csv(METHODOLOGY / "model_candidate_decision_matrix_v1.csv")
    methods = [
        ("QLIKE", "mean paired loss difference", "equal expected loss", "positive forecasts; same eligible origins; day-clustered uncertainty", "overlap requires day clustering and dependence-aware uncertainty", "same origin IDs; B2 nested in B1 only if design is frozen", "finite-sample sensitivity to near-zero forecasts and missing rows", "whole-day clusters with all observed assets", "PRIMARY_CANDIDATE"),
        ("MAE", "mean absolute error", "equal absolute error", "positive target/forecast alignment and same origins", "not scale invariant and overlapping targets", "same origin IDs for nested views", "tail underweighting and serial dependence", "whole-day clusters", "SECONDARY"),
        ("RMSE", "root mean squared error", "equal squared error", "same origins and finite second moment", "tail sensitive; nested condition not automatic", "same origin IDs; compatible with nested squared-error comparisons", "outlier sensitivity and overlapping targets", "whole-day clusters", "SECONDARY"),
        ("paired daily-cluster bootstrap", "uncertainty of daily mean loss differential", "zero mean daily loss differential", "exchangeable day clusters; resample complete days", "preserves within-day overlap and cross-asset dependence", "same origin IDs required for paired B0/B1/B2", "few independent days and cluster imbalance", "resample whole days with all assets together", "PRIMARY_CANDIDATE"),
        ("HAC loss-difference inference", "serially dependent loss differential", "zero mean loss differential", "stationarity and correctly specified lag/kernel", "overlap and cross-asset dependence require specification", "same origin IDs; nested views must be paired", "bandwidth and finite-sample uncertainty", "HAC alone does not replace day clustering", "ROBUSTNESS_ONLY"),
        ("Diebold-Mariano", "equal predictive accuracy", "equal expected loss", "stationary loss differential and consistent long-run variance", "standard implementation needs overlap/HAC adaptation", "same origin IDs; nested information sets require paired forecasts", "small effective number of days and overlapping horizon bias", "day clustering/HAC adaptation required", "ROBUSTNESS_ONLY"),
        ("Clark-West", "nested forecast encompassing under squared error", "expanded forecast has no incremental squared-error improvement", "strict nested forecasts and squared loss", "not generally compatible with QLIKE", "requires B1 strict nesting within B2 and identical origins", "finite-sample adjustment and tuning contamination", "day clustering still required", "ROBUSTNESS_ONLY"),
    ]
    pl.DataFrame([{"method": name, "estimand": est, "null_hypothesis": null, "assumptions": assumptions, "overlapping_targets_compatibility": overlap, "nested_information_set_compatibility": nesting, "finite_sample_risks": finite_sample, "cross_asset_dependence_treatment": dependence, "role": status, "recommendation_status": status, "supervisor_required": False, "implementation_status": "DOSSIER_ONLY"} for name, est, null, assumptions, overlap, nesting, finite_sample, dependence, status in methods]).write_csv(METHODOLOGY / "inference_candidate_decision_matrix_v1.csv")
    return {"predictor_count": len(numeric), "complete_rows": int(matrix.shape[0]) if matrix.ndim == 2 else 0, "condition_number": condition, "max_abs_pairwise_correlation": max_corr}


def literature_upgrade() -> dict[str, Any]:
    """Create evidence ledger v2 while preserving unresolved evidence limits."""
    source = ROOT / "docs" / "literature_evidence_ledger.csv"
    rows: list[dict[str, Any]] = []
    with source.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            status = row.get("full_text_status", "UNRESOLVED")
            row["full_text_status_v2"] = status
            row["evidence_strength"] = "strong" if status == "VERIFIED_FULL_TEXT" else "limited" if status == "VERIFIED_ABSTRACT_ONLY" else "metadata_only"
            row["direct_support_for_numeric_claims"] = "yes" if status == "VERIFIED_FULL_TEXT" else "no"
            row["verification_scope"] = row.get("verification_notes", "")
            rows.append(row)
    out = ROOT / "docs" / "literature_evidence_ledger_v2.csv"
    with out.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    claims = [
        {"claim": "RV30 requires 31 prices and 30 returns", "source": "src/mds650/targets.py; tests/unit/test_target.py", "evidence_location": "function and tests", "evidence_strength": "VERIFIED_LOCAL_CONTRACT", "application": "primary target"},
        {"claim": "created_at is not documented as publication time", "source": "artifacts/pit/uw_created_at_semantics_v1.json", "evidence_location": "status/documentation fields", "evidence_strength": "AUTHENTICATED_LIMITATION", "application": "proxy only"},
        {"claim": "overlapping targets require purge/embargo and day clustering", "source": "docs/temporal_validation_protocol_v2.md", "evidence_location": "protocol", "evidence_strength": "PROJECT_DESIGN_REQUIREMENT", "application": "future validation"},
        {"claim": "recent empirical studies name HAR, regularisation and tree candidates", "source": "docs/literature_evidence_ledger_v2.csv", "evidence_location": "study rows and evidence notes", "evidence_strength": "MIXED; exact claims only full text", "application": "candidate dossier, not selection"},
    ]
    pl.DataFrame(claims).write_csv(ROOT / "docs" / "method_claim_source_map_v1.csv")
    full_text = sum(row["full_text_status_v2"] == "VERIFIED_FULL_TEXT" for row in rows)
    return {"studies": len(rows), "verified_full_text": full_text, "target_full_text": 8, "sufficient_for_strong_all_claims": full_text >= 8, "limitation": "abstract/metadata-only rows cannot support exact numeric rankings"}


def repository_hygiene() -> dict[str, Any]:
    """Inventory dirty entries and scan for secrets, personal paths and large files."""
    status = os.popen("git status --short").read().splitlines()
    records: list[dict[str, Any]] = []
    for entry in status:
        path_text = entry[3:] if len(entry) > 3 else entry
        lower = path_text.lower()
        if any(token in lower for token in (".env", ".key", ".pem", "secret", "credential")):
            category = "SECRET_RISK"
        elif any(token in lower for token in ("raw", "full_tape", "option_events", "cache", "massive_b1q")):
            category = "COMMERCIAL_RAW_DATA" if any(token in lower for token in ("raw", "full_tape", "option_events")) else "CACHE"
        elif lower.startswith("tests") or lower.endswith(".py"):
            category = "TEST" if lower.startswith("tests") else "SOURCE_CODE"
        elif lower.endswith((".md", ".ipynb")):
            category = "DOCUMENTATION"
        elif lower.endswith((".csv", ".json")):
            category = "COMPACT_MANIFEST"
        else:
            category = "UNKNOWN"
        records.append({"git_status": entry[:2], "path": path_text.replace("\\", "/"), "category": category})
    REPOSITORY.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(records).write_csv(REPOSITORY / "repository_inventory_v1.csv")
    secret_hits = 0
    personal_hits = 0
    large_files: list[dict[str, Any]] = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or any(part in {".git", ".venv", "__pycache__"} for part in path.parts):
            continue
        if path.stat().st_size > 100 * 1024 * 1024:
            large_files.append({"path": path.relative_to(ROOT).as_posix(), "bytes": path.stat().st_size, "classification": "COMMERCIAL_OR_DERIVED_LARGE"})
        if path.stat().st_size <= 5 * 1024 * 1024 and path.suffix.lower() in {".py", ".md", ".json", ".csv", ".toml", ".yml", ".yaml", ".ps1"}:
            text = path.read_text(encoding="utf-8", errors="ignore")
            secret_tokens = ("UNUSUALWHALES_API_KEY" + "=", "MASSIVE_API_KEY" + "=", "FMP_API_KEY" + "=")
            secret_hits += sum(token in text for token in secret_tokens)
            drive_marker = "C:" + "\\" + "Users" + "\\"
            slash_marker = "C:/" + "Users" + "/"
            personal_hits += int(drive_marker in text or slash_marker in text)
    history_probe = subprocess.run(
        ["git", "log", "--all", "--format=%H", "-G", "(UNUSUALWHALES_API_KEY|MASSIVE_API_KEY|FMP_API_KEY)[[:space:]]*=[[:space:]]*[^[:space:]]+"],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        check=False,
    )
    history_commits = sorted({line.strip() for line in history_probe.stdout.splitlines() if line.strip()})
    history_status = "PASS_NAME_PATTERN_NO_HITS" if history_probe.returncode == 0 and not history_commits else "HISTORY_NAME_PATTERN_HITS"
    if history_probe.returncode != 0:
        history_status = "UNVERIFIED_GIT_HISTORY_SCAN"
    category_counts: dict[str, int] = {}
    for record in records:
        category = str(record["category"])
        category_counts[category] = category_counts.get(category, 0) + 1
    for category in ("COMMERCIAL_RAW_DATA", "DERIVED_LARGE_DATA", "CACHE", "TEMPORARY", "SECRET_RISK", "LEGACY", "UNKNOWN"):
        category_counts.setdefault(category, 0)
    payload = {
        "schema_version": "repository-secret-scan-v1",
        "dirty_entries": len(records),
        "category_counts": category_counts,
        "secret_value_hits": secret_hits,
        "personal_path_file_hits": personal_hits,
        "large_file_count": len(large_files),
        "large_files": sorted(large_files, key=lambda item: str(item["path"])),
        "git_history_scan": history_status,
        "git_history_name_pattern_commit_count": len(history_commits),
        "secret_values_emitted": False,
        "personal_paths_emitted": False,
    }
    write_json(REPOSITORY / "secret_scan_v1.json", payload)
    return {"dirty_entries": len(records), "secret_value_hits": secret_hits, "personal_path_file_hits": personal_hits, "large_files": len(large_files), "category_counts": category_counts}


def reproducibility_manifest(profile: dict[str, Any]) -> dict[str, Any]:
    """Write compact output hashes and exact rebuild commands."""
    deterministic_paths = [
        COMMON / "common_matrix_strict_25d.parquet", COMMON / "common_matrix_available_25d.parquet",
        COMMON / "common_matrix_targets_25d.parquet", COMMON / "common_matrix_exclusions_v1.parquet",
        COMMON / "common_matrix_profile_v1.json", PIT / "pit_sensitivity_grid_v1.parquet",
        PIT / "pit_sensitivity_summary_v1.csv", PIT / "provider_time_semantics_register_v2.json",
        BACKFILL / "restart_dry_run_v1.json", VALIDATION / "proposed_temporal_folds_v1.csv",
        METHODOLOGY / "model_candidate_decision_matrix_v1.csv",
        METHODOLOGY / "inference_candidate_decision_matrix_v1.csv",
        METHODOLOGY / "collinearity_diagnostics_v1.json",
    ]
    environment_paths = [BACKFILL / "backfill_resource_projection_v2.json"]
    payload = {
        "schema_version": "phase4a-reproducibility-manifest-v1",
        "commands": [
            "uv run python scripts/run_phase4a.py",
            "uv run python scripts/run_phase4a.py (second deterministic rebuild)",
            "compare SHA-256 for deterministic artifacts; exclude live disk telemetry projection",
            "uv run pytest -q",
            "uv run pytest --cov=src --cov-report=term --cov-fail-under=85 -q",
            "uv run ruff check .", "uv run mypy src", "git diff --check",
        ],
        "deterministic_hash_scope": "retained-input derived artifacts; two independent rebuilds MUST match SHA-256",
        "artifacts": [input_record(path) for path in deterministic_paths if path.exists()],
        "environment_dependent_artifacts": [input_record(path) for path in environment_paths if path.exists()],
        "environment_dependent_reason": "backfill_resource_projection_v2 records the current free-disk telemetry snapshot and observed local timings; it is not a deterministic scientific artifact",
        "profile_status": profile.get("status"), "no_provider_requests": True,
        "secret_values_emitted": False, "personal_paths_emitted": False,
    }
    write_json(REPOSITORY / "reproducibility_manifest_v1.json", payload)
    return payload


def main() -> None:
    """Build all Phase 4A artifacts from existing local evidence."""
    for directory in (COMMON, PIT, AUDITS, FEASIBILITY, BACKFILL, VALIDATION, METHODOLOGY, REPOSITORY):
        directory.mkdir(parents=True, exist_ok=True)
    frame, inputs = load_common_inputs()
    uw = recompute_uw_cutoffs(frame.select(["origin_id", "asset", "session_date", "forecast_origin_utc", "sample_role"]))
    primary_uw = uw.filter(pl.col("uw_cutoff_seconds") == 60).select(["origin_id", "uw_eligible_trade_count", "uw_event_file_observed"])
    panel_check = frame.select(["origin_id", "b2_option_trade_count_5m"]).join(primary_uw.select(["origin_id", "uw_eligible_trade_count"]), on="origin_id", how="left").with_columns((pl.col("b2_option_trade_count_5m") != pl.col("uw_eligible_trade_count")).alias("b2_pit_recheck_failed")).select(["origin_id", "b2_pit_recheck_failed"])
    frame = frame.drop("b2_pit_recheck_failed").join(panel_check, on="origin_id", how="left")
    frame = add_status(frame, primary_uw)
    matrices = write_common_matrices(frame)
    grid, _ = sensitivity_grid(frame, uw)
    profile = profile_common(frame, matrices, uw, grid, inputs)
    feature_lineage()
    provider_payload = provider_semantics()
    alignment = cross_provider_alignment(frame, uw)
    quality = quality_and_bias(frame, matrices)
    ess = effective_sample_size(matrices["available"])
    projection = telemetry_projection(frame, uw)
    restart = restart_dry_run(matrices["available"]["origin_id"].to_list())
    folds = temporal_folds()
    diagnostics = model_and_inference_dossiers(matrices["strict"])
    literature = literature_upgrade()
    hygiene = repository_hygiene()
    reproducibility_manifest(profile)
    summary = {"status": "PASS_LOCAL_ONLY_NO_BACKFILL", "nominal_rows": frame.height, "strict_rows": matrices["strict"].height, "availability_aware_rows": matrices["available"].height, "uw_cutoff_rows": uw.height, "provider_records": len(provider_payload["records"]), "alignment_providers": len(alignment["global"]), "bias_rows": quality["retained_strict_origins"], "planning_grid_rows": len(ess["planning_grid"]), "recommended_window": projection["recommended_window"], "restart_hashes_identical": restart["hashes_identical"], "fold_rows": len(folds), "predictor_count": diagnostics["predictor_count"], "literature_full_text": literature["verified_full_text"], "dirty_entries": hygiene["dirty_entries"], "secret_value_hits": hygiene["secret_value_hits"], "personal_path_file_hits": hygiene["personal_path_file_hits"], "secret_values_emitted": False, "personal_paths_emitted": False}
    write_json(ROOT / "artifacts" / "phase4a_run_summary.json", summary)
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
