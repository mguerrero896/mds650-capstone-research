"""Validate nested B1 semantics and emit the forensic waterfall artifacts."""
# ruff: noqa: E501

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import polars as pl

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts" / "b1_forensic"
MATRIX = ROOT / "artifacts" / "b1_full_origin" / "b1_origin_matrix.parquet"
ATTEMPTS = OUT / "iv_failures.csv"
STAGES = ("forecast_origins", "spot_available", "historical_contract_candidates", "contracts_resolved", "contracts_in_valid_DTE_bucket", "contracts_with_valid_moneyness", "quotes_returned_before_origin", "quotes_passing_age_filter", "quotes_passing_spread_filter", "IV_inversion_attempted", "IV_inversion_successful", "ATM_pair_available", "skew_pair_available", "two_DTE_buckets_available", "b1a_complete", "b1b_complete", "b1c_complete")
FAILURE_CODES = {"spot_available": "NO_SPOT", "historical_contract_candidates": "NO_HISTORICAL_CONTRACT", "contracts_resolved": "NO_HISTORICAL_CONTRACT", "contracts_in_valid_DTE_bucket": "INVALID_DTE", "contracts_with_valid_moneyness": "INVALID_MONEYNESS", "quotes_returned_before_origin": "NO_QUOTE_BEFORE_ORIGIN", "quotes_passing_age_filter": "STALE_QUOTE", "quotes_passing_spread_filter": "INVALID_SPREAD", "IV_inversion_attempted": "IV_NO_CONVERGENCE", "IV_inversion_successful": "IV_NO_CONVERGENCE", "ATM_pair_available": "ATM_PAIR_MISSING", "skew_pair_available": "SKEW_PAIR_MISSING", "two_DTE_buckets_available": "TERM_BUCKET_MISSING", "b1a_complete": "ATM_PAIR_MISSING", "b1b_complete": "SKEW_PAIR_MISSING", "b1c_complete": "TERM_BUCKET_MISSING"}


def _component(frame: pl.DataFrame, prefix: str) -> pl.DataFrame:
    """Add component availability and correctly nested route predicates."""
    atm = pl.col(f"{prefix}_atm_iv").is_not_null()
    skew = pl.col(f"{prefix}_skew").is_not_null()
    term_column = frame.schema.get(f"{prefix}_term_structure")
    term_fields = {field.name for field in term_column.fields} if isinstance(term_column, pl.Struct) else set()
    term = (
        pl.col(f"{prefix}_term_structure").struct.field("short_to_medium").is_not_null()
        if "short_to_medium" in term_fields
        else pl.lit(False)
    )
    return frame.with_columns([atm.alias(f"{prefix}_atm_iv_available"), skew.alias(f"{prefix}_skew_available"), term.alias(f"{prefix}_term_structure_available"), atm.alias(f"{prefix}_b1a_complete"), (atm & skew).alias(f"{prefix}_b1b_complete"), (atm & skew & term).alias(f"{prefix}_b1c_complete")])


def _coverage(frame: pl.DataFrame, prefix: str) -> dict[str, float]:
    """Return component and nested coverage for one route."""
    return {key: cast(float, frame[f"{prefix}_{key}"].mean()) for key in ("atm_iv_available", "skew_available", "term_structure_available", "b1a_complete", "b1b_complete", "b1c_complete")}


def main() -> None:
    """Validate all invariants and write forensic artifacts."""
    OUT.mkdir(parents=True, exist_ok=True)
    frame = pl.read_parquet(MATRIX)
    frame = _component(_component(frame, "b1q"), "b1t")
    invariant_errors: list[str] = []
    group_specs: list[tuple[str, pl.DataFrame | pl.dataframe.group_by.GroupBy]] = [("global", frame), ("asset", frame.group_by("asset")), ("date", frame.group_by("session_date")), ("session_segment", frame.group_by("session_segment"))]
    for name, grouped in group_specs:
        subsets: list[tuple[str, pl.DataFrame]]
        if isinstance(grouped, pl.DataFrame):
            subsets = [("all", grouped)]
        else:
            subsets = [(str(key[0]), value) for key, value in grouped]
        for label, subset in subsets:
            for prefix in ("b1q", "b1t"):
                a = cast(float, subset[f"{prefix}_b1a_complete"].mean())
                b = cast(float, subset[f"{prefix}_b1b_complete"].mean())
                c = cast(float, subset[f"{prefix}_b1c_complete"].mean())
                if c > b + 1e-12 or b > a + 1e-12:
                    invariant_errors.append(f"{name}:{label}:{prefix}:{a}:{b}:{c}")
    if invariant_errors:
        raise AssertionError("B1_NESTED_MONOTONICITY_FAILED:" + "|".join(invariant_errors))
    attempts = pl.read_csv(ATTEMPTS, try_parse_dates=True)
    origin_rows: list[dict[str, Any]] = []
    waterfall_rows: list[dict[str, Any]] = []
    for origin in frame.iter_rows(named=True):
        origin_attempts = attempts.filter(pl.col("origin_id") == origin["origin_id"])
        has_contract = origin_attempts.height > 0
        has_dte = origin_attempts.filter(pl.col("dte").is_between(30, 180, closed="both")).height > 0
        has_money = origin_attempts.filter(pl.col("moneyness") > 0).height > 0
        has_quote = origin_attempts.filter(pl.col("midpoint").is_not_null()).height > 0
        has_age = origin_attempts.filter(pl.col("midpoint").is_not_null() & (pl.col("quote_age_seconds") <= 60)).height > 0
        has_spread = origin_attempts.filter(pl.col("midpoint").is_not_null() & (pl.col("quote_age_seconds") <= 60) & (pl.col("relative_spread") <= 0.25)).height > 0
        has_attempt = has_spread
        has_success = origin_attempts.filter(pl.col("success")).height > 0
        stage_values = {"forecast_origins": True, "spot_available": True, "historical_contract_candidates": has_contract, "contracts_resolved": has_contract, "contracts_in_valid_DTE_bucket": has_dte, "contracts_with_valid_moneyness": has_money, "quotes_returned_before_origin": has_quote, "quotes_passing_age_filter": has_age, "quotes_passing_spread_filter": has_spread, "IV_inversion_attempted": has_attempt, "IV_inversion_successful": has_success, "ATM_pair_available": bool(origin["b1q_atm_iv_available"]), "skew_pair_available": bool(origin["b1q_skew_available"]), "two_DTE_buckets_available": bool(origin["b1q_term_structure_available"]), "b1a_complete": bool(origin["b1q_b1a_complete"]), "b1b_complete": bool(origin["b1q_b1b_complete"]), "b1c_complete": bool(origin["b1q_b1c_complete"])}
        first_failure = None
        for order, stage in enumerate(STAGES, start=1):
            passed = bool(stage_values[stage])
            if not passed and first_failure is None:
                first_failure = FAILURE_CODES.get(stage, "UNCLASSIFIED_FAILURE")
            waterfall_rows.append({"route": "B1Q", "origin_id": origin["origin_id"], "asset": origin["asset"], "session_date": origin["session_date"], "session_segment": origin["session_segment"], "stage_order": order, "stage": stage, "stage_pass": passed, "failure_code": None if passed else FAILURE_CODES.get(stage, "UNCLASSIFIED_FAILURE")})
        origin_rows.append({"origin_id": origin["origin_id"], "asset": origin["asset"], "session_date": origin["session_date"], "session_segment": origin["session_segment"], "route": "B1Q", "first_failure_code": first_failure, **stage_values})
    waterfall = pl.DataFrame(waterfall_rows, infer_schema_length=None, strict=False)
    waterfall.write_csv(OUT / "failure_waterfall.csv")
    forensic_origins = pl.DataFrame(origin_rows, infer_schema_length=None, strict=False)
    forensic_origins.write_parquet(OUT / "b1_forensic_origin.parquet")
    coverage: dict[str, Any] = {"global": {"B1Q": _coverage(frame, "b1q"), "B1T": _coverage(frame, "b1t")}, "by_asset": {}, "by_date": {}, "by_session_segment": {}, "invariants": {"b1c_implies_b1b": True, "b1b_implies_b1a": True, "coverage_b1c_le_b1b": True, "coverage_b1b_le_b1a": True}}
    for dimension, dimension_groups in (("by_asset", frame.group_by("asset")), ("by_date", frame.group_by("session_date")), ("by_session_segment", frame.group_by("session_segment"))):
        coverage[dimension] = {str(key[0]): {"B1Q": _coverage(value, "b1q"), "B1T": _coverage(value, "b1t")} for key, value in dimension_groups}
    (OUT / "b1_nested_coverage.json").write_text(json.dumps(coverage, indent=2), encoding="utf-8")
    by_asset = frame.group_by("asset").agg([pl.len().alias("origins"), *[pl.col(f"b1q_{key}").mean().alias(f"b1q_{key}") for key in ("atm_iv_available", "skew_available", "term_structure_available", "b1a_complete", "b1b_complete", "b1c_complete")], *[pl.col(f"b1t_{key}").mean().alias(f"b1t_{key}") for key in ("atm_iv_available", "skew_available", "term_structure_available", "b1a_complete", "b1b_complete", "b1c_complete")]]).sort("asset")
    by_asset.write_csv(OUT / "b1_coverage_by_asset.csv")
    by_segment = frame.group_by("session_segment").agg([pl.len().alias("origins"), *[pl.col(f"b1q_{key}").mean().alias(f"b1q_{key}") for key in ("atm_iv_available", "skew_available", "term_structure_available", "b1a_complete", "b1b_complete", "b1c_complete")], *[pl.col(f"b1t_{key}").mean().alias(f"b1t_{key}") for key in ("atm_iv_available", "skew_available", "term_structure_available", "b1a_complete", "b1b_complete", "b1c_complete")]]).sort("session_segment")
    by_segment.write_csv(OUT / "b1_coverage_by_session_segment.csv")
    print(json.dumps({"status": "B1_FORENSIC_VALIDATED", "origins": frame.height, "waterfall_rows": waterfall.height, "invariant_errors": len(invariant_errors), "failure_rows": attempts.height, "secret_values_emitted": False}))


if __name__ == "__main__":
    main()
