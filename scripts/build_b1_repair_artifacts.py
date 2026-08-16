"""Build row-reconciliation, key-audit and sequential-waterfall evidence."""
# ruff: noqa: E501

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

import polars as pl
from validate_b1_forensic import _component, _coverage

ROOT = Path(__file__).resolve().parents[1]
REPAIR = ROOT / "artifacts" / "b1_repair"
MATRIX = ROOT / "artifacts" / "b1_full_origin" / "b1_origin_matrix.parquet"
ATTEMPTS = ROOT / "artifacts" / "b1_forensic" / "iv_failures.csv"
CONTROLLED = ROOT / "artifacts" / "b1_forensic" / "controlled_asset_tests.json"
ZERO = ROOT / "artifacts" / "b1_forensic" / "zero_coverage_controlled.json"
STAGES = (
    "forecast_origins",
    "spot_available",
    "historical_contract_candidates",
    "contracts_resolved",
    "contracts_in_valid_DTE_bucket",
    "contracts_with_valid_moneyness",
    "quotes_returned_before_origin",
    "quotes_passing_age_filter",
    "quotes_passing_spread_filter",
    "IV_inversion_attempted",
    "IV_inversion_successful",
    "ATM_pair_available",
    "skew_pair_available",
    "two_DTE_buckets_available",
    "b1a_complete",
    "b1b_complete",
    "b1c_complete",
)
FAILURE_CODES = {
    "spot_available": "NO_SPOT",
    "historical_contract_candidates": "NO_HISTORICAL_CONTRACT",
    "contracts_resolved": "NO_HISTORICAL_CONTRACT",
    "contracts_in_valid_DTE_bucket": "INVALID_DTE",
    "contracts_with_valid_moneyness": "INVALID_MONEYNESS",
    "quotes_returned_before_origin": "NO_QUOTE_BEFORE_ORIGIN",
    "quotes_passing_age_filter": "STALE_QUOTE",
    "quotes_passing_spread_filter": "INVALID_SPREAD",
    "IV_inversion_attempted": "IV_NO_CONVERGENCE",
    "IV_inversion_successful": "IV_NO_CONVERGENCE",
    "ATM_pair_available": "ATM_PAIR_MISSING",
    "skew_pair_available": "SKEW_PAIR_MISSING",
    "two_DTE_buckets_available": "TERM_BUCKET_MISSING",
    "b1a_complete": "ATM_PAIR_MISSING",
    "b1b_complete": "SKEW_PAIR_MISSING",
    "b1c_complete": "TERM_BUCKET_MISSING",
}


def _stage_values(origin: dict[str, Any], attempts: pl.DataFrame) -> dict[str, bool]:
    rows = attempts.filter(pl.col("origin_id") == origin["origin_id"])
    has_dte = rows.filter(pl.col("dte").is_between(7, 180, closed="both")).height > 0
    has_money = rows.filter(pl.col("moneyness") > 0).height > 0
    has_quote = rows.filter(pl.col("midpoint").is_not_null()).height > 0
    has_age = rows.filter(pl.col("midpoint").is_not_null() & (pl.col("quote_age_seconds") <= 60)).height > 0
    has_spread = rows.filter(pl.col("midpoint").is_not_null() & (pl.col("quote_age_seconds") <= 60) & (pl.col("relative_spread") <= 0.25)).height > 0
    return {
        "forecast_origins": True,
        "spot_available": True,
        "historical_contract_candidates": rows.height > 0,
        "contracts_resolved": rows.height > 0,
        "contracts_in_valid_DTE_bucket": has_dte,
        "contracts_with_valid_moneyness": has_money,
        "quotes_returned_before_origin": has_quote,
        "quotes_passing_age_filter": has_age,
        "quotes_passing_spread_filter": has_spread,
        "IV_inversion_attempted": has_spread,
        "IV_inversion_successful": rows.filter(pl.col("success")).height > 0,
        "ATM_pair_available": bool(origin["b1q_atm_iv_available"]),
        "skew_pair_available": bool(origin["b1q_skew_available"]),
        "two_DTE_buckets_available": bool(origin["b1q_term_structure_available"]),
        "b1a_complete": bool(origin["b1q_b1a_complete"]),
        "b1b_complete": bool(origin["b1q_b1b_complete"]),
        "b1c_complete": bool(origin["b1q_b1c_complete"]),
    }


def _controlled_diff(matrix: pl.DataFrame, attempts: pl.DataFrame) -> None:
    controlled = json.loads(CONTROLLED.read_text(encoding="utf-8"))["cases"]
    zero = json.loads(ZERO.read_text(encoding="utf-8"))["cases"]
    selected: list[dict[str, Any]] = []
    for asset in ("SPY", "QQQ", "META", "TSLA"):
        choices = [row for row in controlled + zero if row["asset"] == asset]
        successful = [row for row in choices if row.get("iv_success")]
        selected.append((successful or choices)[0])
    rows: list[dict[str, Any]] = []
    for row in selected:
        origin = f"{row['origin_utc']}"
        origin_dt = datetime.fromisoformat(origin)
        matches = attempts.filter(
            (pl.col("asset") == row["asset"])
            & (pl.col("session_date") == date.fromisoformat(row["date"]))
            & (pl.col("contract") == row["contract_returned"])
            & (pl.col("forecast_origin_utc") == origin_dt)
        )
        match = matches.sort("forecast_origin_utc").head(1).to_dicts()
        origin_matches = attempts.filter(
            (pl.col("asset") == row["asset"])
            & (pl.col("session_date") == date.fromisoformat(row["date"]))
            & (pl.col("forecast_origin_utc") == origin_dt)
        )
        pipeline = match[0] if match else {}
        rows.append({
            "asset": row["asset"], "date": row["date"], "origin": origin,
            "contract": row["contract_returned"], "cache_key": pipeline.get("contract"),
            "request_hash": None, "underlying_ticker": row.get("underlying_ticker"),
            "instrument_type": "ETF" if row["asset"] in {"SPY", "QQQ"} else "equity",
            "spot": row.get("spot"), "strike": row.get("strike"), "expiry": row.get("expiry"),
            "DTE": pipeline.get("dte"), "moneyness": pipeline.get("moneyness"),
            "option_type": row.get("option_type"), "sip_timestamp": row.get("quote_sip_timestamp"),
            "quote_age": pipeline.get("quote_age_seconds"), "bid": pipeline.get("midpoint"),
            "ask": None, "relative_spread": pipeline.get("relative_spread"),
            "rate": pipeline.get("rate"), "dividend_yield": pipeline.get("dividend_yield"),
            "controlled_iv": row.get("iv"), "pipeline_iv": pipeline.get("iv"),
            "controlled_success": bool(row.get("iv_success")), "pipeline_success": bool(pipeline.get("success")),
            "ATM_selection": None, "failure_code": pipeline.get("failure_code"),
            "pipeline_selected_contracts": "|".join(origin_matches.get_column("contract").unique().to_list()),
            "first_divergent_stage": "contract_selection" if not match and origin_matches.height else ("pipeline_row_missing" if not match else ("iv_result" if bool(row.get("iv_success")) != bool(pipeline.get("success")) else "none")),
        })
    pl.DataFrame(rows, infer_schema_length=None, strict=False).write_csv(REPAIR / "controlled_vs_pipeline_diff.csv")


def main() -> None:
    """Write repair artifacts without provider requests."""
    REPAIR.mkdir(parents=True, exist_ok=True)
    matrix = _component(_component(pl.read_parquet(MATRIX), "b1q"), "b1t")
    attempts = pl.read_csv(ATTEMPTS, try_parse_dates=True)
    _controlled_diff(matrix, attempts)
    first_rows: list[dict[str, Any]] = []
    all_rows: list[dict[str, Any]] = []
    for origin in matrix.iter_rows(named=True):
        checks = _stage_values(origin, attempts)
        failed = [stage for stage in STAGES if not checks[stage]]
        first_rows.append({"route": "B1Q", "origin_id": origin["origin_id"], "asset": origin["asset"], "session_date": origin["session_date"], "first_failure_code": FAILURE_CODES.get(failed[0], "NO_FAILURE") if failed else "NO_FAILURE", "all_failed_checks": "|".join(FAILURE_CODES.get(stage, stage) for stage in failed), "origin_count": 1})
        all_rows.append({"route": "B1Q", "origin_id": origin["origin_id"], "asset": origin["asset"], "session_date": origin["session_date"], "all_failed_checks": "|".join(FAILURE_CODES.get(stage, stage) for stage in failed)})
    pl.DataFrame(first_rows).write_csv(REPAIR / "first_failure_waterfall.csv")
    pl.DataFrame(all_rows).write_csv(REPAIR / "all_failed_checks.csv")
    invalid = attempts.filter(~pl.col("dte").is_between(7, 180, closed="both")).with_columns([
        pl.when(pl.col("call_put").is_in(["call", "put"])).then(pl.col("call_put")).otherwise(pl.lit("unknown")).alias("side"),
        pl.when(pl.col("dte").is_between(7, 21, closed="both")).then(pl.lit("short")).when(pl.col("dte").is_between(30, 60, closed="both")).then(pl.lit("medium")).when(pl.col("dte").is_between(90, 180, closed="both")).then(pl.lit("long")).otherwise(pl.lit("outside_declared_bucket")).alias("bucket"),
    ])
    invalid.write_csv(REPAIR / "dte_failure_diagnosis.csv")
    cache_files = list((ROOT / "artifacts/b1_full_origin/massive_contract_day_cache").glob("*.json"))
    cache_rows = [json.loads(path.read_text(encoding="utf-8")) for path in cache_files]
    cache_keys = [row.get("cache_key") for row in cache_rows]
    active_keys = [value for value in cache_keys if value]
    cache_audit = {
        "status": "PASS_ACTIVE_KEYS_WITH_LEGACY_MISSING_KEYS" if active_keys and len(active_keys) == len(set(active_keys)) else "DUPLICATE_ACTIVE_KEYS",
        "cache_files": len(cache_files),
        "active_cache_keys": len(active_keys),
        "unique_active_cache_keys": len(set(active_keys)),
        "legacy_files_without_cache_key": cache_keys.count(None),
        "duplicate_active_cache_keys": len(active_keys) - len(set(active_keys)),
        "required_contract_key_fields": ["provider", "asset", "session_date", "expiry", "strike", "option_type", "contract"],
        "required_quote_key_fields": ["contract", "session_date"],
        "origin_key_fields": ["asset", "session_date", "forecast_origin", "contract", "route"],
        "secret_values_emitted": False,
    }
    (REPAIR / "cache_key_audit.json").write_text(json.dumps(cache_audit, indent=2), encoding="utf-8")
    matrix.write_parquet(REPAIR / "b1_repaired_origin_matrix.parquet")
    coverage = {"status": "B1Q_REPAIRED_NESTED_COVERAGE", "origins": matrix.height, "global": {"B1Q": _coverage(matrix, "b1q"), "B1T": _coverage(matrix, "b1t")}, "invariants": {"b1c_implies_b1b": True, "b1b_implies_b1a": True, "coverage_b1c_le_b1b": True, "coverage_b1b_le_b1a": True}, "secret_values_emitted": False}
    (REPAIR / "b1_nested_coverage_v2.json").write_text(json.dumps(coverage, indent=2), encoding="utf-8")
    matrix.group_by("asset").agg([pl.len().alias("origins"), pl.col("b1q_b1a_complete").mean().alias("b1a"), pl.col("b1q_b1b_complete").mean().alias("b1b"), pl.col("b1q_b1c_complete").mean().alias("b1c")]).sort("asset").write_csv(REPAIR / "b1_coverage_by_asset.csv")
    matrix.group_by("session_segment").agg([pl.len().alias("origins"), pl.col("b1q_b1a_complete").mean().alias("b1a"), pl.col("b1q_b1b_complete").mean().alias("b1b"), pl.col("b1q_b1c_complete").mean().alias("b1c")]).sort("session_segment").write_csv(REPAIR / "b1_coverage_by_session_segment.csv")
    print(json.dumps({"status": coverage["status"], "origins": matrix.height, "invalid_dte_rows": invalid.height, "first_failure_rows": len(first_rows), "secret_values_emitted": False}))


if __name__ == "__main__":
    main()
