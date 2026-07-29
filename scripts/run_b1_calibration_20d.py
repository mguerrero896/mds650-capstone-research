"""Recompute the repaired B1Q route over the authorized twenty-session origins."""
# ruff: noqa: E501

from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import httpx
import polars as pl
import run_b1_closure as closure

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts" / "calibration_20d"
CACHE = OUT / "massive_b1q_cache_v2"
ASSETS = closure.ASSETS
SESSIONS = tuple(sorted({str(row) for row in pl.read_parquet(OUT / "b2_calibration_origins.parquet").get_column("session_date").unique().to_list()}))


@dataclass(frozen=True)
class B1BuildConfig:
    """Explicit B1 output/cache roots and authorized sessions."""

    output_root: Path
    cache_root: Path
    sessions: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.sessions or tuple(sorted(set(self.sessions))) != self.sessions:
            raise ValueError("B1_SESSION_ALLOWLIST_INVALID")


DEFAULT_CONFIG = B1BuildConfig(
    output_root=OUT,
    cache_root=CACHE,
    sessions=SESSIONS,
)


def _secret(name: str) -> str:
    """Return a required provider secret without logging its value."""
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"MISSING_SECRET:{name}")
    return value


def _rates_and_dividends(
    fmp_key: str,
    origins: pl.DataFrame,
    config: B1BuildConfig = DEFAULT_CONFIG,
) -> tuple[dict[str, float], dict[tuple[str, str], float]]:
    """Load pre-origin rate and dividend inputs for the twenty-session window."""
    first = min(date.fromisoformat(day) for day in config.sessions) - timedelta(days=30)
    last = max(date.fromisoformat(day) for day in config.sessions)
    rates: dict[str, float] = {}
    with httpx.Client(timeout=90.0) as client:
        response = client.get("https://financialmodelingprep.com/stable/treasury-rates", params={"from": first.isoformat(), "to": last.isoformat(), "apikey": fmp_key})
        payload = response.json() if response.status_code == 200 else []
        for row in payload if isinstance(payload, list) else []:
            if isinstance(row, dict) and row.get("date") and row.get("month3") is not None:
                rates[str(row["date"])] = float(row["month3"]) / 100.0
    dividends: dict[str, list[dict[str, Any]]] = {}
    with httpx.Client(timeout=90.0) as client:
        for asset in ASSETS:
            response = client.get("https://financialmodelingprep.com/stable/dividends", params={"symbol": asset, "from": first.isoformat(), "to": last.isoformat(), "apikey": fmp_key})
            payload = response.json() if response.status_code == 200 else []
            dividends[asset] = payload if isinstance(payload, list) else []
    result: dict[tuple[str, str], float] = {}
    for row in origins.group_by(["asset", "session_date"]).agg(pl.col("spot").first()).iter_rows(named=True):
        asset, day, spot = str(row["asset"]), str(row["session_date"]), float(row["spot"])
        cutoff = date.fromisoformat(day)
        total = 0.0
        for item in dividends.get(asset, []):
            try:
                declared = date.fromisoformat(str(item.get("declarationDate")))
                if cutoff - timedelta(days=365) <= declared <= cutoff:
                    total += float(item.get("adjDividend") or item.get("dividend") or 0.0)
            except (TypeError, ValueError):
                continue
        result[(asset, day)] = total / spot if spot > 0 else 0.0
    return rates, result


def _rate_for(day: str, rates: dict[str, float]) -> float:
    """Select the latest Treasury rate not after the origin date."""
    candidates = [key for key in rates if key <= day]
    return rates[max(candidates)] if candidates else 0.0


def _resolve_contracts(origins: pl.DataFrame, massive_key: str) -> dict[tuple[str, str], list[dict[str, Any]]]:
    """Resolve historical contracts once per asset/session across DTE buckets."""
    spots = origins.group_by(["asset", "session_date"]).agg(pl.col("spot").first()).sort(["asset", "session_date"])
    result: dict[tuple[str, str], list[dict[str, Any]]] = {}
    with httpx.Client(timeout=90.0, follow_redirects=True) as client:
        for row in spots.iter_rows(named=True):
            result[(str(row["asset"]), str(row["session_date"]))] = closure.resolve_contracts(client, massive_key, str(row["asset"]), str(row["session_date"]), float(row["spot"]))
    return result


def _fetch_quotes(
    contracts: dict[tuple[str, str], list[dict[str, Any]]],
    massive_key: str,
    config: B1BuildConfig = DEFAULT_CONFIG,
) -> dict[tuple[str, str, str], dict[str, Any]]:
    """Fetch each resolved contract-day once into the V2-only cache."""
    config.cache_root.mkdir(parents=True, exist_ok=True)
    closure.CACHE = config.cache_root
    jobs = [(asset, day, contract) for (asset, day), values in contracts.items() for contract in values]
    output: dict[tuple[str, str, str], dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(closure.fetch_contract_day, job, massive_key): job for job in jobs}
        for future in as_completed(futures):
            asset, day, contract = futures[future]
            output[(asset, day, contract["contract"])] = future.result()
    return output


def _first_failure(iv_rows: list[dict[str, Any]], summary: dict[str, Any]) -> str:
    """Map missing B1Q inputs to a stable first diagnostic code."""
    if not iv_rows:
        return "NO_HISTORICAL_CONTRACT"
    if not any(row.get("midpoint") is not None for row in iv_rows):
        return "NO_QUOTE_BEFORE_ORIGIN"
    if not any(row.get("quote_age_seconds") is not None and row.get("quote_age_seconds", 9999) <= 60 for row in iv_rows):
        return "STALE_QUOTE"
    if not any(row.get("iv_success") for row in iv_rows):
        return "IV_NO_CONVERGENCE"
    if summary.get("b1q_atm_iv") is None:
        return "ATM_PAIR_MISSING"
    if summary.get("b1q_skew") is None:
        return "SKEW_PAIR_MISSING"
    term = summary.get("b1q_term_structure") or {}
    if term.get("short_to_medium") is None and term.get("medium_to_long") is None and term.get("short_to_long") is None:
        return "TERM_BUCKET_MISSING"
    return "NO_FAILURE"


def _coverage(frame: pl.DataFrame) -> dict[str, Any]:
    """Compute component and nested coverage for one frame."""
    n = frame.height or 1
    return {"atm_iv_component": frame["atm_iv_available"].mean(), "skew_component": frame["skew_available"].mean(), "term_structure_component": frame["term_structure_available"].mean(), "b1a": frame["b1a_complete"].mean(), "b1b": frame["b1b_complete"].mean(), "b1c": frame["b1c_complete"].mean(), "iv_success_rate": frame["iv_inversion_success_rate"].mean() if n else 0.0}


def main(config: B1BuildConfig = DEFAULT_CONFIG) -> None:
    """Run B1Q over all twenty origins and write coverage/failure artifacts."""
    config.output_root.mkdir(parents=True, exist_ok=True)
    origins = pl.read_parquet(config.output_root / "b2_calibration_origins.parquet").select(["origin_id", "asset", "session_date", "forecast_origin_utc", "spot", "session_segment"])
    observed_sessions = tuple(
        sorted(str(value) for value in origins.get_column("session_date").unique().to_list())
    )
    if observed_sessions != config.sessions:
        raise RuntimeError("B1_ORIGIN_SESSION_ALLOWLIST_MISMATCH")
    origins = origins.with_columns(pl.col("forecast_origin_utc").dt.timestamp("ns").alias("origin_ns"))
    fmp_key, massive_key = _secret("FMP_API_KEY"), _secret("MASSIVE_API_KEY")
    rates, dividend_yields = _rates_and_dividends(fmp_key, origins, config)
    contracts = _resolve_contracts(origins, massive_key)
    quote_caches = _fetch_quotes(contracts, massive_key, config)
    rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for origin in origins.iter_rows(named=True):
        asset, day = str(origin["asset"]), str(origin["session_date"])
        iv_rows: list[dict[str, Any]] = []
        for contract in contracts.get((asset, day), []):
            cache = quote_caches[(asset, day, contract["contract"])]
            quote = closure.latest_quote(cache, int(origin["origin_ns"]))
            attempt: dict[str, Any] = {**contract, "asset": asset, "origin_id": origin["origin_id"], "forecast_origin_utc": origin["forecast_origin_utc"].isoformat(), "spot": float(origin["spot"]), "moneyness": float(contract["strike"]) / float(origin["spot"]), "rate": _rate_for(day, rates), "dividend_yield": dividend_yields.get((asset, day), 0.0), "iv_success": False, "iv": None, "failure_reason": "NO_QUOTE_BEFORE_ORIGIN"}
            if quote and quote.get("midpoint") is not None:
                attempt.update({"sip_timestamp": quote.get("sip_timestamp"), "quote_age_seconds": quote.get("quote_age_seconds"), "relative_spread": quote.get("relative_spread"), "midpoint": quote.get("midpoint")})
                if quote["quote_age_seconds"] > 60:
                    attempt["failure_reason"] = "STALE_QUOTE"
                elif quote["relative_spread"] > 0.25:
                    attempt["failure_reason"] = "INVALID_SPREAD"
                else:
                    result = closure.invert_iv(float(origin["spot"]), float(contract["strike"]), float(contract["dte"]) / 365.0, attempt["rate"], attempt["dividend_yield"], float(quote["midpoint"]), str(contract["option_type"]))
                    attempt.update({"iv_success": bool(result["success"]), "iv": result.get("iv"), "failure_reason": result.get("failure_reason"), "iterations": result.get("iterations"), "lower_bound": result.get("lower_bound"), "upper_bound": result.get("upper_bound")})
            iv_rows.append(attempt)
        summary = closure.route_summary(iv_rows, route="B1Q")
        atm, skew, term = summary.get("b1q_atm_iv"), summary.get("b1q_skew"), summary.get("b1q_term_structure") or {}
        row = {"origin_id": origin["origin_id"], "asset": asset, "session_date": day, "forecast_origin_utc": origin["forecast_origin_utc"], "session_segment": origin["session_segment"], "instrument_type": "ETF" if asset in {"SPY", "QQQ"} else "equity", "atm_iv_available": atm is not None, "skew_available": skew is not None, "term_structure_available": any(value is not None for value in term.values()), "b1a_complete": atm is not None, "b1b_complete": atm is not None and skew is not None, "b1c_complete": atm is not None and skew is not None and all(value is not None for value in (term.get("short_to_medium"), term.get("medium_to_long"), term.get("short_to_long"))), "b1q_atm_iv": atm, "b1q_skew": skew, "b1q_term_structure": term, "valid_contract_count": summary.get("valid_contract_count", 0), "valid_quote_count": summary.get("valid_quote_count", 0), "valid_expiry_bucket_count": summary.get("valid_expiry_bucket_count", 0), "median_quote_age": summary.get("median_quote_age"), "median_relative_spread": summary.get("median_relative_spread"), "iv_attempts": len(iv_rows), "iv_successes": sum(bool(item.get("iv_success")) for item in iv_rows), "iv_inversion_success_rate": sum(bool(item.get("iv_success")) for item in iv_rows) / len(iv_rows) if iv_rows else 0.0, "first_failure_code": _first_failure(iv_rows, summary), "route": "B1Q_MASSIVE_PRIMARY", "b1t_status": "DIAGNOSTIC_ONLY"}
        rows.append(row)
        failures.extend({key: item.get(key) for key in ("asset", "origin_id", "contract", "option_type", "dte", "moneyness", "rate", "dividend_yield", "midpoint", "quote_age_seconds", "relative_spread", "iv_success", "failure_reason", "iv")} for item in iv_rows if not item.get("iv_success"))
    frame = pl.DataFrame(rows, infer_schema_length=None, strict=False)
    frame.write_parquet(config.output_root / "b1_origin_matrix_20d.parquet", compression="zstd")
    frame.group_by("asset").agg([pl.len().alias("origins"), pl.col("atm_iv_available").mean().alias("atm_iv_component"), pl.col("skew_available").mean().alias("skew_component"), pl.col("term_structure_available").mean().alias("term_structure_component"), pl.col("b1a_complete").mean().alias("b1a"), pl.col("b1b_complete").mean().alias("b1b"), pl.col("b1c_complete").mean().alias("b1c"), pl.col("iv_inversion_success_rate").mean().alias("iv_success_rate")]).sort("asset").write_csv(config.output_root / "b1_coverage_by_asset.csv")
    frame.group_by("session_segment").agg([pl.len().alias("origins"), pl.col("atm_iv_available").mean().alias("atm_iv_component"), pl.col("skew_available").mean().alias("skew_component"), pl.col("term_structure_available").mean().alias("term_structure_component"), pl.col("b1a_complete").mean().alias("b1a"), pl.col("b1b_complete").mean().alias("b1b"), pl.col("b1c_complete").mean().alias("b1c"), pl.col("iv_inversion_success_rate").mean().alias("iv_success_rate")]).sort("session_segment").write_csv(config.output_root / "b1_coverage_by_session_segment.csv")
    global_cov = _coverage(frame)
    by_date = {str(row["session_date"]): _coverage(frame.filter(pl.col("session_date") == row["session_date"])) for row in frame.select("session_date").unique().iter_rows(named=True)}
    by_route = {"B1Q": global_cov, "B1T": {"status": "DIAGNOSTIC_ONLY", "coverage": None}}
    summary = {"status": "PASS_B1Q_20_SESSION_RECOMPUTATION", "origins": frame.height, "global": global_cov, "by_date": by_date, "by_route": by_route, "nested_invariants": {"b1c_implies_b1b": bool(frame.filter(pl.col("b1c_complete") & ~pl.col("b1b_complete")).height == 0), "b1b_implies_b1a": bool(frame.filter(pl.col("b1b_complete") & ~pl.col("b1a_complete")).height == 0), "coverage_b1c_le_b1b": global_cov["b1c"] <= global_cov["b1b"], "coverage_b1b_le_b1a": global_cov["b1b"] <= global_cov["b1a"]}, "primary_quote_age_seconds": 60, "primary_relative_spread": 0.25, "b1t_independent": False, "modeling": "BLOCKED", "qlike": "BLOCKED", "secret_values_emitted": False}
    _assert_invariants(frame, summary)
    (config.output_root / "b1_coverage_20d.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    pl.DataFrame(failures, infer_schema_length=None, strict=False).write_csv(config.output_root / "b1_iv_failures_20d.csv")
    print(json.dumps({"status": summary["status"], "origins": frame.height, "global": global_cov, "cache_files": len(list(config.cache_root.glob("*.json"))), "secret_values_emitted": False}))


def _assert_invariants(frame: pl.DataFrame, summary: dict[str, Any]) -> None:
    """Fail closed on nested B1 violations globally and in declared subgroups."""
    if not all(summary["nested_invariants"].values()):
        raise RuntimeError("B1Q_NESTED_INVARIANT_FAILURE")
    for column in ("asset", "session_date", "session_segment", "instrument_type"):
        for _, group in frame.group_by(column):
            values = _coverage(group)
            if values["b1c"] > values["b1b"] or values["b1b"] > values["b1a"]:
                raise RuntimeError(f"B1Q_NESTED_SUBGROUP_FAILURE:{column}")


if __name__ == "__main__":
    main()
