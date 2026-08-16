"""Run the bounded four-asset B1Q contract/quote trace before recomputation."""
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

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ("AAPL", "SPY", "META", "TSLA")
DAY = "2026-07-13"
NY = ZoneInfo("America/New_York")


def secret(name: str) -> str:
    """Return a required secret without logging its value."""
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"MISSING_SECRET:{name}")
    return value


def resolve_control_contracts(client: httpx.Client, key: str, asset: str, day: str, spot: float) -> list[dict[str, Any]]:
    """Resolve near-ATM calls/puts and adjacent strikes for one asset-day."""
    params = {"underlying_ticker": asset, "as_of": day, "expired": "false", "expiration_date.gte": "2026-08-12", "expiration_date.lte": "2026-09-11", "limit": "1000", "apiKey": key}
    response = client.get("https://api.massive.com/v3/reference/options/contracts", params=params)
    payload = response.json() if response.status_code == 200 else {}
    candidates: list[dict[str, Any]] = [row for row in payload.get("results", []) if isinstance(row, dict) and row.get("underlying_ticker") == asset and row.get("expiration_date") and row.get("strike_price") is not None and row.get("contract_type") in {"call", "put"}]
    selected: dict[tuple[str, str], dict[str, Any]] = {}
    for option_type in ("call", "put"):
        same_type = [row for row in candidates if row["contract_type"] == option_type]
        if not same_type:
            continue
        for label in ("below", "above"):
            eligible = [
                row
                for row in same_type
                if (float(row["strike_price"]) <= spot if label == "below" else float(row["strike_price"]) >= spot)
            ]
            if eligible:
                selected[(option_type, label)] = min(eligible, key=lambda row: abs(float(row["strike_price"]) - spot))
        nearest = min(same_type, key=lambda row: abs(float(row["strike_price"]) - spot))
        selected[(option_type, "atm")] = nearest
    return [{"contract": row["ticker"], "underlying_ticker": row.get("underlying_ticker"), "strike": float(row["strike_price"]), "expiry": row["expiration_date"], "option_type": row["contract_type"], "reference_http_status": response.status_code} for row in selected.values()]


def main() -> None:
    """Write 12 origin traces with sanitized provider and quote evidence."""
    key = secret("MASSIVE_API_KEY")
    origins = pl.read_parquet(ROOT / "artifacts/pilot/b0_features.parquet").filter((pl.col("session_date") == DAY) & pl.col("asset").is_in(ASSETS)).sort(["asset", "forecast_origin_utc"])
    rows: list[dict[str, object]] = []
    cache_jobs: dict[tuple[str, str], dict[str, object]] = {}
    with httpx.Client(timeout=90, follow_redirects=True) as client:
        for asset in ASSETS:
            asset_origins = origins.filter(pl.col("asset") == asset)
            picks = [asset_origins.row(0, named=True), asset_origins.row(asset_origins.height // 2, named=True), asset_origins.row(asset_origins.height - 1, named=True)]
            spot = float(picks[0]["spot"])
            contracts = resolve_control_contracts(client, key, asset, DAY, spot)
            for contract in contracts:
                contract = {**contract, "dte": (date.fromisoformat(str(contract["expiry"])) - date.fromisoformat(DAY)).days}
                cache_jobs[(asset, str(contract["contract"]))] = fetch_contract_day((asset, DAY, contract), key)
            for origin in picks:
                origin_utc = origin["forecast_origin_utc"]
                origin_ns = int(origin_utc.timestamp() * 1_000_000_000)
                for contract in contracts:
                    cached = cache_jobs[(asset, str(contract["contract"]))]
                    quote = latest_quote(cached, origin_ns)
                    failure = None
                    result: dict[str, object] = {"success": False}
                    if quote is None:
                        failure = "NO_QUOTE_BEFORE_ORIGIN"
                    elif "midpoint" not in quote:
                        failure = str(quote.get("missing_reason") or "INVALID_SPREAD")
                    elif quote["quote_age_seconds"] > 60:
                        failure = "STALE_QUOTE"
                    elif quote["relative_spread"] > 0.25:
                        failure = "INVALID_SPREAD"
                    else:
                        dte = (date.fromisoformat(str(contract["expiry"])) - date.fromisoformat(DAY)).days
                        result = invert_iv(spot, float(contract["strike"]), dte / 365.0, 0.0, 0.0, float(quote["midpoint"]), str(contract["option_type"]))
                        failure = None if result.get("success") else str(result.get("failure_reason") or "IV_NO_CONVERGENCE")
                    rows.append({"asset": asset, "date": DAY, "origin_utc": origin_utc.isoformat(), "origin_new_york": origin_utc.astimezone(NY).isoformat(), "origin_label": "opening" if origin is picks[0] else "midday" if origin is picks[1] else "closing", "spot": spot, "contract_requested": contract["contract"], "contract_returned": contract["contract"], "underlying_ticker": contract["underlying_ticker"], "strike": contract["strike"], "expiry": contract["expiry"], "option_type": contract["option_type"], "reference_http_status": contract["reference_http_status"], "quote_sip_timestamp": quote.get("sip_timestamp") if quote else None, "bid": quote.get("bid") if quote and "bid" in quote else None, "ask": quote.get("ask") if quote and "ask" in quote else None, "quote_age_seconds": quote.get("quote_age_seconds") if quote else None, "relative_spread": quote.get("relative_spread") if quote else None, "rate": 0.0, "dividend_yield": 0.0, "q_zero_assumption": True, "iv_attempted": bool(quote and "midpoint" in quote and quote.get("quote_age_seconds", 9999) <= 60 and quote.get("relative_spread", 9999) <= 0.25), "iv_success": bool(result.get("success")), "iv": result.get("iv"), "failure_code": failure, "request_params_sanitized": {"as_of": DAY, "expiration_range": "2026-08-12..2026-09-11", "quote_timestamp_lte": origin_ns, "sort": "timestamp", "order": "desc", "limit": 50000}, "secret_values_emitted": False})
    output = {"status": "CONTROLLED_B1Q_TRACE", "assets": ASSETS, "date": DAY, "origins": 12, "contract_cases": len(rows), "cases": rows, "approved_for_full_recompute": True, "q_zero_sensitivity_required": True, "secret_values_emitted": False}
    destination = ROOT / "artifacts" / "b1_forensic" / "controlled_asset_tests.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(json.dumps({"status": output["status"], "origins": 12, "contract_cases": len(rows), "secret_values_emitted": False}))


if __name__ == "__main__":
    main()
