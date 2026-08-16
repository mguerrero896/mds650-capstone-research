"""Trace SPY, QQQ, META and TSLA at three Pilot V2 origins each."""
# ruff: noqa: E501

from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import polars as pl
from run_b1_closure import fetch_contract_day, invert_iv, latest_quote
from run_b1_controlled import resolve_control_contracts

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ("SPY", "QQQ", "META", "TSLA")
DAY = "2026-07-13"
NY = ZoneInfo("America/New_York")


def main() -> None:
    """Write the four zero-coverage traces without models or backfill."""
    key = os.environ.get("MASSIVE_API_KEY")
    if not key:
        raise RuntimeError("MISSING_SECRET:MASSIVE_API_KEY")
    origins = pl.read_parquet(ROOT / "artifacts/pilot/b0_features.parquet").filter((pl.col("session_date") == DAY) & pl.col("asset").is_in(ASSETS)).sort(["asset", "forecast_origin_utc"])
    rows: list[dict[str, object]] = []
    with httpx.Client(timeout=90, follow_redirects=True) as client:
        for asset in ASSETS:
            subset = origins.filter(pl.col("asset") == asset)
            picks = [subset.row(0, named=True), subset.row(subset.height // 2, named=True), subset.row(subset.height - 1, named=True)]
            spot = float(picks[0]["spot"])
            contracts = resolve_control_contracts(client, key, asset, DAY, spot)
            caches = {str(contract["contract"]): fetch_contract_day((asset, DAY, {**contract, "dte": (date.fromisoformat(str(contract["expiry"])) - date.fromisoformat(DAY)).days}), key) for contract in contracts}
            for label, origin in zip(("opening", "midday", "closing"), picks, strict=True):
                origin_ns = int(origin["forecast_origin_utc"].timestamp() * 1_000_000_000)
                for contract in contracts:
                    quote = latest_quote(caches[str(contract["contract"])], origin_ns)
                    failure = "NO_QUOTE_BEFORE_ORIGIN" if quote is None else str(quote.get("missing_reason")) if "midpoint" not in quote else None
                    result: dict[str, Any] = {"success": False}
                    if quote and "midpoint" in quote and quote["quote_age_seconds"] <= 60 and quote["relative_spread"] <= 0.25:
                        dte = (date.fromisoformat(str(contract["expiry"])) - date.fromisoformat(DAY)).days
                        result = invert_iv(spot, float(contract["strike"]), dte / 365.0, 0.0, 0.0, float(quote["midpoint"]), str(contract["option_type"]))
                        failure = None if result.get("success") else str(result.get("failure_reason") or "IV_NO_CONVERGENCE")
                    rows.append({"asset": asset, "date": DAY, "origin_label": label, "origin_utc": origin["forecast_origin_utc"].isoformat(), "origin_new_york": origin["forecast_origin_utc"].astimezone(NY).isoformat(), "spot": spot, "contract_requested": contract["contract"], "contract_returned": contract["contract"], "underlying_ticker": contract["underlying_ticker"], "strike": contract["strike"], "expiry": contract["expiry"], "option_type": contract["option_type"], "quote_sip_timestamp": quote.get("sip_timestamp") if quote else None, "bid": quote.get("bid") if quote and "bid" in quote else None, "ask": quote.get("ask") if quote and "ask" in quote else None, "quote_age_seconds": quote.get("quote_age_seconds") if quote else None, "relative_spread": quote.get("relative_spread") if quote else None, "rate": 0.0, "dividend_yield": 0.0, "q_zero_assumption": True, "iv_success": bool(result.get("success")), "iv": result.get("iv"), "failure_code": failure, "secret_values_emitted": False})
    destination = ROOT / "artifacts" / "b1_forensic" / "zero_coverage_controlled.json"
    destination.write_text(json.dumps({"status": "ZERO_COVERAGE_CONTROLLED_TRACE", "assets": ASSETS, "origins": 12, "cases": rows, "q_zero_assumption": "diagnostic sensitivity only", "secret_values_emitted": False}, indent=2), encoding="utf-8")
    print(json.dumps({"status": "ZERO_COVERAGE_CONTROLLED_TRACE", "origins": 12, "cases": len(rows), "secret_values_emitted": False}))


if __name__ == "__main__":
    main()
