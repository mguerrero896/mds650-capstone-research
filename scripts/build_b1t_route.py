"""Build the dependent B1T route from the five cached Full Tape partitions.

B1T is diagnostic only: it shares the Full Tape provenance with B2 and therefore
cannot be presented as an independent option-state benchmark.
"""
# ruff: noqa: E501,UP017,I001

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import polars as pl

from run_b1_closure import BUCKETS, invert_iv, route_summary

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts" / "b1_full_origin"
EVENT_ROOT = ROOT / "artifacts" / "pilot" / "option_events"


def _required_mean(series: pl.Series) -> float:
    """Return a numeric mean, failing explicitly for an empty/non-numeric series."""
    value = series.mean()
    if not isinstance(value, (int, float)):
        raise ValueError("B1_COVERAGE_MEAN_UNAVAILABLE")
    return float(value)


def _segment(value: datetime) -> str:
    """Return a deterministic first/middle/last session segment."""
    if value.hour == 13 and value.minute < 50:
        return "first"
    if value.hour >= 19:
        return "last"
    return "middle"


def _build_origin_route(origin: dict[str, Any], events: pl.DataFrame) -> dict[str, Any]:
    """Build one B1T origin using only the five-minute operational window."""
    origin_time = origin["forecast_origin_utc"]
    if origin_time.tzinfo is None:
        origin_time = origin_time.replace(tzinfo=timezone.utc)
    cutoff = origin_time - timedelta(seconds=60)
    window_start = cutoff - timedelta(minutes=5)
    candidates = events.filter(
        (pl.col("created_at") <= cutoff)
        & (pl.col("created_at") > window_start)
        & (pl.col("expiry") > origin_time.date())
        & (pl.col("option_chain_id").is_not_null())
    )
    if candidates.is_empty():
        summary = route_summary([], route="B1T")
        return _row(origin, summary, 0, 0)
    latest = (
        candidates.sort(["option_chain_id", "created_at"])
        .unique(subset=["option_chain_id"], keep="last", maintain_order=True)
    )
    iv_rows: list[dict[str, Any]] = []
    for event in latest.iter_rows(named=True):
        bid, ask = event.get("nbbo_bid"), event.get("nbbo_ask")
        strike, option_type = event.get("strike"), str(event.get("option_type") or "").lower()
        created_at = event.get("created_at")
        if not isinstance(bid, (int, float)) or not isinstance(ask, (int, float)) or bid <= 0 or ask <= bid:
            continue
        if not isinstance(strike, (int, float)) or option_type not in {"call", "put"} or not isinstance(created_at, datetime):
            continue
        midpoint = (float(bid) + float(ask)) / 2.0
        age = (origin_time - created_at).total_seconds()
        spread = (float(ask) - float(bid)) / midpoint
        if age < 0 or age > 300 or spread > 0.50:
            continue
        dte = (event["expiry"] - origin_time.date()).days
        bucket = next((name for name, (lo, hi) in BUCKETS.items() if lo <= dte <= hi), None)
        if bucket is None:
            continue
        spot = float(origin["spot"])
        moneyness = float(strike) / spot if spot > 0 else None
        if moneyness is None:
            continue
        result = invert_iv(spot, float(strike), dte / 365.0, 0.0, 0.0, midpoint, option_type)
        iv_rows.append(
            {
                "contract": str(event["option_chain_id"]),
                "bucket": bucket,
                "option_type": option_type,
                "moneyness": moneyness,
                "iv_success": bool(result["success"]),
                "iv": result.get("iv"),
                "quote_age_seconds": age,
                "relative_spread": spread,
            }
        )
    summary = route_summary(iv_rows, route="B1T")
    return _row(origin, summary, len(latest), len(iv_rows))


def _row(origin: dict[str, Any], summary: dict[str, Any], valid_contracts: int, valid_quotes: int) -> dict[str, Any]:
    """Flatten a route summary into the shared origin contract."""
    return {
        "origin_id": origin["origin_id"],
        "asset": origin["asset"],
        "session_date": origin["session_date"],
        "forecast_origin_utc": origin["forecast_origin_utc"].isoformat(),
        "session_segment": _segment(origin["forecast_origin_utc"]),
        "b1t_atm_iv": summary.get("b1t_atm_iv"),
        "b1t_skew": summary.get("b1t_skew"),
        "b1t_term_structure": summary.get("b1t_term_structure"),
        "b1t_complete": summary.get("b1t_atm_iv") is not None,
        "b1t_b1b_complete": summary.get("b1t_atm_iv") is not None and summary.get("b1t_skew") is not None,
        "b1t_b1c_complete": summary.get("b1t_atm_iv") is not None and summary.get("b1t_term_structure", {}).get("short_to_medium") is not None,
        "b1t_valid_contract_count": summary.get("valid_contract_count", valid_contracts),
        "b1t_valid_quote_count": summary.get("valid_quote_count", valid_quotes),
        "b1t_valid_expiry_bucket_count": summary.get("valid_expiry_bucket_count", 0),
        "b1t_median_quote_age": summary.get("median_quote_age"),
        "b1t_median_relative_spread": summary.get("median_relative_spread"),
        "b1t_iv_inversion_success_rate": summary.get("iv_inversion_success_rate", 0.0),
        "b1t_missing_reason": summary.get("missing_reason"),
    }


def main() -> None:
    """Create B1T artifacts and merge them into the B1 origin matrix."""
    matrix_path = OUT / "b1_origin_matrix.parquet"
    matrix = pl.read_parquet(matrix_path)
    existing_b1t = [column for column in matrix.columns if column.startswith("b1t_")]
    if existing_b1t:
        matrix = matrix.drop(existing_b1t)
    spots = pl.read_parquet(ROOT / "artifacts/pilot/b0_features.parquet").select(["origin_id", "spot"])
    spot_map = {row["origin_id"]: float(row["spot"]) for row in spots.iter_rows(named=True)}
    origin_rows = [
        {
            **row,
            "forecast_origin_utc": datetime.fromisoformat(row["forecast_origin_utc"]),
            "spot": spot_map[row["origin_id"]],
        }
        for row in matrix.select(["origin_id", "asset", "session_date", "forecast_origin_utc"]).iter_rows(named=True)
    ]
    event_cache: dict[str, pl.DataFrame] = {}
    output: list[dict[str, Any]] = []
    for day_path in sorted(EVENT_ROOT.glob("date=*/events.parquet")):
        day = day_path.parent.name.split("=", 1)[1]
        events = pl.read_parquet(day_path, columns=["underlying_symbol", "option_chain_id", "created_at", "nbbo_bid", "nbbo_ask", "expiry", "strike", "option_type"])
        for asset in sorted(events["underlying_symbol"].drop_nulls().unique().to_list()):
            event_cache[asset] = events.filter(pl.col("underlying_symbol") == asset)
        for origin in [row for row in origin_rows if row["session_date"] == day]:
            output.append(_build_origin_route(origin, event_cache.get(origin["asset"], pl.DataFrame())))
    b1t = pl.DataFrame(output, infer_schema_length=None, strict=False)
    merged = matrix.join(b1t, on=["origin_id", "asset", "session_date", "forecast_origin_utc", "session_segment"], how="left")
    merged.write_parquet(matrix_path)
    b1t.select([column for column in b1t.columns if column != "b1t_term_structure"]).write_csv(OUT / "b1t_origin_route.csv")
    q_b1a = _required_mean(merged["b1q_complete"])
    q_b1b = _required_mean(merged["b1q_skew"].is_not_null())
    q_b1c = merged.filter(pl.col("b1q_term_structure").struct.field("short_to_medium").is_not_null()).height / merged.height
    t_b1a = _required_mean(merged["b1t_complete"])
    t_b1b = _required_mean(merged["b1t_skew"].is_not_null())
    t_b1c = merged.filter(pl.col("b1t_term_structure").struct.field("short_to_medium").is_not_null()).height / merged.height
    comparison = "route,origins,b1a_coverage,b1b_coverage,b1c_coverage,usable_for_primary\n"
    comparison += f"B1Q,{merged.height},{q_b1a},{q_b1b},{q_b1c},{str(q_b1a >= 0.70).lower()}\n"
    comparison += f"B1T,{merged.height},{t_b1a},{t_b1b},{t_b1c},false\n"
    (OUT / "b1q_vs_b1t_comparison.csv").write_text(comparison, encoding="utf-8")
    summary_path = OUT / "b1_coverage_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["coverage"]["b1t_b1a"] = merged["b1t_complete"].mean()
    summary["coverage"]["b1t_b1b"] = merged["b1t_skew"].is_not_null().mean()
    summary["coverage"]["b1t_b1c"] = merged.filter(pl.col("b1t_term_structure").struct.field("short_to_medium").is_not_null()).height / merged.height
    summary["coverage_thresholds"] = {
        str(threshold): {"b1q_b1a_meets": summary["coverage"]["b1a"] >= threshold, "b1t_b1a_meets": summary["coverage"]["b1t_b1a"] >= threshold}
        for threshold in (0.50, 0.60, 0.70, 0.80)
    }
    summary["b1t_route"] = {"status": "DEPENDENT_FULL_TAPE_DIAGNOSTIC", "primary_cutoff_seconds": 60, "primary_window_minutes": 5, "sensitivity_window_minutes": 15, "independent_of_b2": False}
    summary["status"] = "B1Q_B1T_FULL_ORIGIN_EXPLORATORY"
    summary["usable_for_primary"] = False
    summary["note"] = "B1Q below the 70% gate; B1T is dependent on Full Tape provenance and remains diagnostic only."
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    merged.group_by("asset").agg([
        pl.len().alias("origins"),
        pl.col("b1q_complete").mean().alias("b1q_b1a_coverage"),
        pl.col("b1q_skew").is_not_null().mean().alias("b1q_b1b_coverage"),
        pl.col("b1q_term_structure").struct.field("short_to_medium").is_not_null().mean().alias("b1q_b1c_coverage"),
        pl.col("b1t_complete").mean().alias("b1t_b1a_coverage"),
        pl.col("b1t_skew").is_not_null().mean().alias("b1t_b1b_coverage"),
        pl.col("b1t_term_structure").struct.field("short_to_medium").is_not_null().mean().alias("b1t_b1c_coverage"),
    ]).sort("asset").write_csv(OUT / "b1_coverage_by_asset.csv")
    merged.group_by("session_segment").agg([
        pl.len().alias("origins"),
        pl.col("b1q_complete").mean().alias("b1q_b1a_coverage"),
        pl.col("b1q_term_structure").struct.field("short_to_medium").is_not_null().mean().alias("b1q_b1c_coverage"),
        pl.col("b1t_complete").mean().alias("b1t_b1a_coverage"),
        pl.col("b1t_term_structure").struct.field("short_to_medium").is_not_null().mean().alias("b1t_b1c_coverage"),
    ]).sort("session_segment").write_csv(OUT / "b1_coverage_by_session_segment.csv")


if __name__ == "__main__":
    main()
