"""Run the bounded B1Q/B1T feasibility closure over Pilot V2 origins.

The script fetches one cached Massive quote response per selected contract-day,
then performs all origin joins locally. It never downloads a full options market
or the proposed twenty-session extension.
"""
# ruff: noqa: E501

from __future__ import annotations

import hashlib
import json
import math
import os
import time as time_module
from bisect import bisect_right
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import httpx
import polars as pl

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts" / "b1_full_origin"
CACHE = OUT / "massive_contract_day_cache"
ASSETS = ("SPY", "QQQ", "AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "META")
BUCKETS = {"short": (7, 21), "medium": (30, 60), "long": (90, 180)}
# The full target grid is retained as a contract-selection reference. The
# bounded feasibility probe selects ATM per bucket plus medium OTM wings to
# keep contract-day requests finite; wider grid points are a later sensitivity.
MONEY = (0.95, 0.975, 1.0, 1.025, 1.05)


def need_secret(name: str) -> str:
    """Return a required secret without logging its value."""
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"MISSING_SECRET:{name}")
    return value


def norm_cdf(value: float) -> float:
    """Evaluate the standard normal CDF using the Python standard library."""
    return 0.5 * (1.0 + math.erf(value / math.sqrt(2.0)))


def bsm_price(spot: float, strike: float, time_years: float, rate: float, dividend: float, sigma: float, kind: str) -> float:
    """Return a Black–Scholes–Merton European price approximation."""
    if min(spot, strike, time_years, sigma) <= 0:
        return 0.0
    root_t = math.sqrt(time_years)
    d1 = (math.log(spot / strike) + (rate - dividend + sigma * sigma / 2.0) * time_years) / (sigma * root_t)
    d2 = d1 - sigma * root_t
    if kind == "call":
        return spot * math.exp(-dividend * time_years) * norm_cdf(d1) - strike * math.exp(-rate * time_years) * norm_cdf(d2)
    return strike * math.exp(-rate * time_years) * norm_cdf(-d2) - spot * math.exp(-dividend * time_years) * norm_cdf(-d1)


def invert_iv(spot: float, strike: float, time_years: float, rate: float, dividend: float, midpoint: float, kind: str) -> dict[str, Any]:
    """Invert BSM volatility with a bounded bisection and explicit diagnostics."""
    lower = max(0.0, (spot * math.exp(-dividend * time_years) - strike * math.exp(-rate * time_years)) if kind == "call" else (strike * math.exp(-rate * time_years) - spot * math.exp(-dividend * time_years)))
    upper = spot * math.exp(-dividend * time_years) if kind == "call" else strike * math.exp(-rate * time_years)
    if not lower <= midpoint <= upper or midpoint <= 0:
        return {"success": False, "failure_reason": "ARBITRAGE_BOUND", "lower_bound": lower, "upper_bound": upper, "iterations": 0}
    lo, hi = 1e-6, 5.0
    if bsm_price(spot, strike, time_years, rate, dividend, hi, kind) < midpoint:
        return {"success": False, "failure_reason": "IV_UPPER_BOUND", "lower_bound": lower, "upper_bound": upper, "iterations": 0}
    for iteration in range(1, 101):
        mid = (lo + hi) / 2.0
        value = bsm_price(spot, strike, time_years, rate, dividend, mid, kind)
        if abs(value - midpoint) <= 1e-6:
            return {"success": True, "iv": mid, "failure_reason": None, "lower_bound": lower, "upper_bound": upper, "iterations": iteration}
        if value > midpoint:
            hi = mid
        else:
            lo = mid
    return {"success": True, "iv": (lo + hi) / 2.0, "failure_reason": "MAX_ITERATIONS", "lower_bound": lower, "upper_bound": upper, "iterations": 100}


def _request_json(
    client: httpx.Client,
    url: str,
    params: dict[str, str],
    key: str,
    *,
    max_attempts: int = 4,
    backoff_seconds: float = 1.0,
) -> tuple[int, dict[str, Any], str | None]:
    safe = dict(params)
    safe["apiKey"] = key
    for attempt in range(1, max_attempts + 1):
        try:
            response = client.get(url, params=safe)
        except httpx.TransportError:
            if attempt == max_attempts:
                raise RuntimeError("MASSIVE_REQUEST_RETRY_EXHAUSTED") from None
            time_module.sleep(backoff_seconds * 2 ** (attempt - 1))
            continue
        if (
            response.status_code == 429 or response.status_code >= 500
        ) and attempt < max_attempts:
            retry_after = response.headers.get("retry-after")
            delay = (
                float(retry_after)
                if retry_after and retry_after.replace(".", "", 1).isdigit()
                else backoff_seconds * 2 ** (attempt - 1)
            )
            time_module.sleep(delay)
            continue
        payload = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
        return response.status_code, payload if isinstance(payload, dict) else {}, response.headers.get("x-request-id") or response.headers.get("request_id")
    raise RuntimeError("MASSIVE_REQUEST_RETRY_EXHAUSTED")


def resolve_contracts(client: httpx.Client, key: str, asset: str, day: str, spot: float) -> list[dict[str, Any]]:
    """Resolve the target contract grid once for one asset-date."""
    selected: dict[str, dict[str, Any]] = {}
    requested_day = date.fromisoformat(day)
    for bucket, (lower_dte, upper_dte) in BUCKETS.items():
        start = requested_day + timedelta(days=lower_dte)
        end = requested_day + timedelta(days=upper_dte)
        params = {
            "underlying_ticker": asset,
            "as_of": day,
            "expired": "true" if end < date.today() else "false",
            "expiration_date.gte": start.isoformat(),
            "expiration_date.lte": end.isoformat(),
            "strike_price.gte": f"{spot * 0.90:.6f}",
            "strike_price.lte": f"{spot * 1.10:.6f}",
            "limit": "1000",
        }
        status, payload, request_id = _request_json(client, "https://api.massive.com/v3/reference/options/contracts", params, key)
        if status != 200:
            raise RuntimeError(f"MASSIVE_CONTRACT_REFERENCE_HTTP_{status}:{asset}:{day}:{bucket}")
        candidates = list(payload.get("results", []))
        next_url = payload.get("next_url")
        seen_urls: set[str] = set()
        pages = 1
        while next_url and next_url not in seen_urls and pages < 100:
            seen_urls.add(next_url)
            page_status, page, _ = _request_json(client, next_url, {}, key)
            if page_status != 200:
                break
            candidates.extend(page.get("results", []))
            next_url = page.get("next_url")
            pages += 1
        for row in candidates:
            try:
                if str(row.get("underlying_ticker", "")) != asset:
                    continue
                expiry = date.fromisoformat(str(row["expiration_date"]))
                strike = float(row["strike_price"])
                dte = (expiry - requested_day).days
                kind = str(row.get("contract_type", "")).lower()
                ticker = str(row["ticker"])
                if kind not in {"call", "put"} or dte <= 0:
                    continue
            except (KeyError, TypeError, ValueError):
                continue
            if not lower_dte <= dte <= upper_dte:
                continue
            moneyness = strike / spot
            target_candidates = (0.975, 1.0) if bucket == "medium" and kind == "put" else (1.0, 1.025) if bucket == "medium" and kind == "call" else (1.0,)
            for target in target_candidates:
                key_name = f"{bucket}:{target:.3f}:{kind}"
                if abs(moneyness - target) > 0.04:
                    continue
                previous = selected.get(key_name)
                if previous is None or abs(moneyness - target) < abs(float(previous["strike"]) / spot - target):
                    selected[key_name] = {"contract": ticker, "expiry": expiry.isoformat(), "strike": strike, "option_type": kind, "dte": dte, "bucket": bucket, "target_moneyness": target, "reference_request_id": request_id, "instrument_type": "ETF" if asset in {"SPY", "QQQ"} else "equity"}
    return list(selected.values())


def fetch_contract_day(item: tuple[str, str, dict[str, Any]], key: str) -> dict[str, Any]:
    """Fetch or reuse one contract-day response and return sanitized quote rows."""
    asset, day, contract = item
    ticker = contract["contract"]
    cache_key = f"provider=massive|asset={asset}|session_date={day}|expiry={contract['expiry']}|strike={contract['strike']}|option_type={contract['option_type']}|contract={ticker}|route=B1Q|schema_version=2"
    digest = hashlib.sha256(cache_key.encode()).hexdigest()[:16]
    path = CACHE / f"{asset}_{day}_{ticker.replace(':', '_')}_{digest}.json"
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise RuntimeError(f"MASSIVE_QUOTE_CACHE_INVALID:{path.name}")
        data["results"] = _compact_quotes(data.get("results", []))
        data["cache_hit"] = True
        data.setdefault("cache_key", cache_key)
        data.setdefault("source_request_hash", hashlib.sha256(f"https://api.massive.com/v3/quotes/{ticker}|timestamp={day}|sort=timestamp|order=desc|limit=50000|route=B1Q|schema_version=2".encode()).hexdigest())
        data["cache_path"] = str(path)
        return data
    params = {"timestamp": day, "sort": "timestamp", "order": "desc", "limit": "50000"}
    with httpx.Client(timeout=90, follow_redirects=True) as client:
        status, payload, request_id = _request_json(client, f"https://api.massive.com/v3/quotes/{ticker}", params, key)
    source_request_hash = hashlib.sha256(f"https://api.massive.com/v3/quotes/{ticker}|{json.dumps(params, sort_keys=True)}|route=B1Q|schema_version=2".encode()).hexdigest()
    safe: dict[str, Any] = {"asset": asset, "day": day, "contract": contract, "cache_key": cache_key, "quote_cache_key": f"provider=massive|contract={ticker}|session_date={day}|route=B1Q|schema_version=2", "route": "B1Q", "schema_version": 2, "http_status": status, "request_params_sanitized": params, "source_request_hash": source_request_hash, "request_id": request_id, "pages": 1, "results": _compact_quotes(payload.get("results", [])), "cache_hit": False}
    # A next_url is followed only for this contract-day; it is never expanded into a market-wide download.
    next_url = payload.get("next_url")
    seen_urls: set[str] = set()
    while next_url and next_url not in seen_urls and safe["pages"] < 20:
        seen_urls.add(next_url)
        with httpx.Client(timeout=90, follow_redirects=True) as client:
            page_status, page, _ = _request_json(client, next_url, {}, key)
        if page_status != 200:
            break
        safe["pages"] += 1
        safe["results"].extend(_compact_quotes(page.get("results", [])))
        next_url = page.get("next_url")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(safe, separators=(",", ":")), encoding="utf-8")
    safe["cache_path"] = str(path)
    return safe


def _compact_quotes(rows: Any) -> list[dict[str, Any]]:
    """Retain only fields required for the local as-of quote contract."""
    if not isinstance(rows, list):
        return []
    return [
        {key: row.get(key) for key in ("sip_timestamp", "bid_price", "ask_price")}
        for row in rows
        if isinstance(row, dict) and isinstance(row.get("sip_timestamp"), int)
    ]


def latest_quote(cache: dict[str, Any], origin_ns: int) -> dict[str, Any] | None:
    """Select the last valid SIP quote at or before an origin."""
    rows = cache.get("results", [])
    timestamps = cache.get("_sip_timestamps")
    if not isinstance(timestamps, list):
        rows = sorted(
            (
                row
                for row in rows
                if isinstance(row, dict)
                and isinstance(row.get("sip_timestamp"), int)
            ),
            key=lambda row: row["sip_timestamp"],
        )
        timestamps = [row["sip_timestamp"] for row in rows]
        cache["results"] = rows
        cache["_sip_timestamps"] = timestamps
    index = bisect_right(timestamps, origin_ns) - 1
    if index < 0:
        return None
    row = rows[index]
    bid, ask = row.get("bid_price"), row.get("ask_price")
    if not isinstance(bid, int | float) or not isinstance(ask, int | float) or bid <= 0 or ask <= bid:
        return {"missing_reason": "INVALID_SPREAD", "sip_timestamp": row["sip_timestamp"]}
    midpoint = (float(bid) + float(ask)) / 2.0
    return {"sip_timestamp": row["sip_timestamp"], "bid": float(bid), "ask": float(ask), "midpoint": midpoint, "quote_age_seconds": (origin_ns - row["sip_timestamp"]) / 1e9, "relative_spread": (float(ask) - float(bid)) / midpoint}


def route_summary(rows: list[dict[str, Any]], *, route: str) -> dict[str, Any]:
    """Summarize route-specific IV rows into B1a/B1b/B1c fields."""
    valid = [row for row in rows if row.get("iv_success") and row.get("quote_age_seconds") is not None and row.get("relative_spread") is not None]
    by_bucket: dict[str, list[dict[str, Any]]] = {name: [row for row in valid if row["bucket"] == name] for name in BUCKETS}
    medium = by_bucket["medium"]
    below = sorted([row for row in medium if row["moneyness"] <= 1.0], key=lambda row: abs(row["moneyness"] - 1.0))
    above = sorted([row for row in medium if row["moneyness"] >= 1.0], key=lambda row: abs(row["moneyness"] - 1.0))
    atm_interpolated = bool(below and above and below[0]["contract"] != above[0]["contract"])
    atm = ((below[0]["iv"] + above[0]["iv"]) / 2.0 if atm_interpolated else (below[0]["iv"] if below else above[0]["iv"] if above else None))
    puts = sorted([row for row in medium if row["option_type"] == "put" and row["moneyness"] <= 0.99], key=lambda row: abs(row["moneyness"] - 0.975))
    calls = sorted([row for row in medium if row["option_type"] == "call" and row["moneyness"] >= 1.01], key=lambda row: abs(row["moneyness"] - 1.025))
    skew = puts[0]["iv"] - calls[0]["iv"] if puts and calls else None
    bucket_atm = {bucket: (min(values, key=lambda row: abs(row["moneyness"] - 1.0))["iv"] if values else None) for bucket, values in by_bucket.items()}
    slopes = {"short_to_medium": None, "medium_to_long": None, "short_to_long": None}
    if bucket_atm["short"] is not None and bucket_atm["medium"] is not None:
        slopes["short_to_medium"] = bucket_atm["medium"] - bucket_atm["short"]
    if bucket_atm["medium"] is not None and bucket_atm["long"] is not None:
        slopes["medium_to_long"] = bucket_atm["long"] - bucket_atm["medium"]
    if bucket_atm["short"] is not None and bucket_atm["long"] is not None:
        slopes["short_to_long"] = bucket_atm["long"] - bucket_atm["short"]
    return {"route": route, "b1q_atm_iv" if route == "B1Q" else "b1t_atm_iv": atm, "b1q_skew" if route == "B1Q" else "b1t_skew": skew, "b1q_term_structure" if route == "B1Q" else "b1t_term_structure": slopes, "atm_interpolated": atm_interpolated, "valid_contract_count": len({row["contract"] for row in valid}), "valid_quote_count": len(valid), "valid_expiry_bucket_count": sum(value is not None for value in bucket_atm.values()), "median_quote_age": _median([row["quote_age_seconds"] for row in valid]), "median_relative_spread": _median([row["relative_spread"] for row in valid]), "iv_inversion_success_rate": (sum(row.get("iv_success", False) for row in rows) / len(rows) if rows else 0.0), "missing_reason": None if atm is not None else "NO_VALID_MEDIUM_ATM"}


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    values = sorted(values)
    middle = len(values) // 2
    return values[middle] if len(values) % 2 else (values[middle - 1] + values[middle]) / 2.0


def main() -> None:
    """Build route-specific B1 matrices and coverage artifacts."""
    massive_key = need_secret("MASSIVE_API_KEY")
    fmp_key = need_secret("FMP_API_KEY")
    OUT.mkdir(parents=True, exist_ok=True)
    CACHE.mkdir(parents=True, exist_ok=True)
    origins = pl.read_parquet(ROOT / "artifacts/pilot/b0_features.parquet").select(["origin_id", "asset", "session_date", "forecast_origin_utc", "spot"])
    origins = origins.with_columns(pl.col("forecast_origin_utc").dt.timestamp("ns").alias("origin_ns"))
    date_spots = origins.group_by(["asset", "session_date"]).agg(pl.col("spot").first()).sort(["asset", "session_date"])
    rates: dict[str, float] = {}
    with httpx.Client(timeout=60) as client:
        response = client.get("https://financialmodelingprep.com/stable/treasury-rates", params={"from": "2026-07-01", "to": "2026-07-17", "apikey": fmp_key})
        payload = response.json() if response.status_code == 200 else []
        for row in payload if isinstance(payload, list) else []:
            if isinstance(row, dict) and row.get("date") and row.get("month3") is not None:
                rates[str(row["date"])] = float(row["month3"]) / 100.0
    dividend_yields: dict[tuple[str, str], float] = {}
    for asset in ASSETS:
        response = httpx.get("https://financialmodelingprep.com/stable/dividends", params={"symbol": asset, "from": "2025-07-01", "to": "2026-07-17", "apikey": fmp_key}, timeout=60)
        payload = response.json() if response.status_code == 200 and response.headers.get("content-type", "").startswith("application/json") else []
        rows_for_asset = payload if isinstance(payload, list) else []
        for origin_row in date_spots.filter(pl.col("asset") == asset).iter_rows(named=True):
            day = str(origin_row["session_date"])
            cutoff = date.fromisoformat(day)
            trailing_start = cutoff - timedelta(days=365)
            total = 0.0
            for dividend in rows_for_asset:
                try:
                    declaration = date.fromisoformat(str(dividend.get("declarationDate")))
                    if trailing_start <= declaration <= cutoff:
                        total += float(dividend.get("adjDividend") or dividend.get("dividend") or 0.0)
                except (TypeError, ValueError):
                    continue
            spot_value = float(origin_row["spot"])
            dividend_yields[(asset, day)] = total / spot_value if spot_value > 0 else 0.0
    contracts: dict[tuple[str, str], list[dict[str, Any]]] = {}
    with httpx.Client(timeout=60) as client:
        for row in date_spots.iter_rows(named=True):
            contracts[(row["asset"], row["session_date"])] = resolve_contracts(client, massive_key, row["asset"], row["session_date"], float(row["spot"]))
    jobs = [(asset, day, contract) for (asset, day), values in contracts.items() for contract in values]
    print(json.dumps({"contract_day_jobs": len(jobs), "cached_files": len(list(CACHE.glob("*.json")))}), flush=True)
    cache_paths: dict[tuple[str, str, str], str] = {}
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(fetch_contract_day, job, massive_key): job for job in jobs}
        for index, future in enumerate(as_completed(futures), start=1):
            item = futures[future]
            cache_paths[(item[0], item[1], item[2]["contract"])] = future.result()["cache_path"]
            if index % 25 == 0 or index == len(futures):
                print(json.dumps({"quote_jobs_completed": index, "quote_jobs_total": len(futures)}), flush=True)
    rows: list[dict[str, Any]] = []
    failure_counts: dict[str, int] = {}
    iv_attempt_rows: list[dict[str, Any]] = []
    # Process one asset-day at a time so the local as-of join is bounded in
    # memory even when a cache contains many historical quotes.
    grouped_origins: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for origin in origins.iter_rows(named=True):
        grouped_origins.setdefault((origin["asset"], origin["session_date"]), []).append(origin)
    for (asset, day), group in sorted(grouped_origins.items()):
        group_caches: dict[str, dict[str, Any]] = {}
        for contract in contracts.get((asset, day), []):
            cache_path = cache_paths[(asset, day, contract["contract"])]
            cached = json.loads(Path(cache_path).read_text(encoding="utf-8"))
            cached["results"] = _compact_quotes(cached.get("results", []))
            group_caches[contract["contract"]] = cached
        for origin in group:
            spot, origin_ns = float(origin["spot"]), int(origin["origin_ns"])
            iv_rows: list[dict[str, Any]] = []
            for contract in contracts.get((asset, day), []):
                quote = latest_quote(group_caches[contract["contract"]], origin_ns)
                row = {**contract, "contract": contract["contract"], "moneyness": contract["strike"] / spot, "quote_age_seconds": quote.get("quote_age_seconds") if quote else None, "relative_spread": quote.get("relative_spread") if quote else None, "iv_success": False, "iv": None, "failure_reason": "NO_QUOTE" if quote is None else quote.get("missing_reason")}
                if quote and "midpoint" in quote and quote["quote_age_seconds"] > 60:
                    row["failure_reason"] = "STALE_QUOTE"
                elif quote and "midpoint" in quote and quote["relative_spread"] > 0.25:
                    row["failure_reason"] = "INVALID_SPREAD"
                elif quote and "midpoint" in quote and quote["quote_age_seconds"] <= 60 and quote["relative_spread"] <= 0.25:
                    result = invert_iv(spot, contract["strike"], contract["dte"] / 365.0, rates.get(day, 0.0), dividend_yields.get((asset, day), 0.0), quote["midpoint"], contract["option_type"])
                    row.update({"iv_success": bool(result["success"]), "iv": result.get("iv"), "failure_reason": result.get("failure_reason"), "iterations": result.get("iterations"), "lower_bound": result.get("lower_bound"), "upper_bound": result.get("upper_bound")})
                iv_rows.append(row)
                failure_reason = row.get("failure_reason")
                if failure_reason is None and not row["iv_success"]:
                    failure_reason = "IV_NO_CONVERGENCE"
                if failure_reason == "NO_QUOTE":
                    failure_reason = "NO_QUOTE_BEFORE_ORIGIN"
                elif failure_reason in {"ARBITRAGE_BOUND", "IV_UPPER_BOUND"}:
                    failure_reason = "ARBITRAGE_BOUND_FAILURE" if failure_reason == "ARBITRAGE_BOUND" else "IV_NO_CONVERGENCE"
                iv_attempt_rows.append({"asset": asset, "origin_id": origin["origin_id"], "session_date": day, "forecast_origin_utc": origin["forecast_origin_utc"].isoformat(), "contract": contract["contract"], "call_put": contract["option_type"], "spot": spot, "strike": contract["strike"], "dte": contract["dte"], "moneyness": contract["strike"] / spot, "rate": rates.get(day, 0.0), "dividend_yield": dividend_yields.get((asset, day), 0.0), "midpoint": quote.get("midpoint") if quote and "midpoint" in quote else None, "quote_age_seconds": row.get("quote_age_seconds"), "relative_spread": row.get("relative_spread"), "success": bool(row["iv_success"]), "failure_code": None if row["iv_success"] else failure_reason, "iv": row.get("iv")})
                if not row["iv_success"]:
                    reason = str(row.get("failure_reason") or "UNKNOWN")
                    failure_counts[reason] = failure_counts.get(reason, 0) + 1
            summary = route_summary(iv_rows, route="B1Q")
            atm_available = summary.get("b1q_atm_iv") is not None
            skew_available = summary.get("b1q_skew") is not None
            term_available = summary.get("b1q_term_structure", {}).get("short_to_medium") is not None
            rows.append({"origin_id": origin["origin_id"], "asset": asset, "session_date": day, "forecast_origin_utc": origin["forecast_origin_utc"].isoformat(), "session_segment": "first" if origin["forecast_origin_utc"].hour == 13 and origin["forecast_origin_utc"].minute < 50 else "last" if origin["forecast_origin_utc"].hour >= 19 else "middle", **summary, "b1q_atm_iv": summary.get("b1q_atm_iv"), "b1q_skew": summary.get("b1q_skew"), "b1q_term_structure": summary.get("b1q_term_structure"), "b1q_complete": atm_available, "b1a_complete": atm_available, "b1b_complete": atm_available and skew_available, "b1c_complete": atm_available and skew_available and term_available, "b1t_atm_iv": None, "b1t_skew": None, "b1t_term_structure": None, "b1t_complete": False, "iv_attempts": len(iv_rows), "iv_successes": sum(row["iv_success"] for row in iv_rows), "dividend_yield": dividend_yields.get((asset, day), 0.0), "route_status": "B1Q_MASSIVE_PRIMARY"})
    frame = pl.DataFrame(rows, infer_schema_length=None, strict=False)
    frame.write_parquet(OUT / "b1_origin_matrix.parquet")
    frame.group_by("asset").agg([
        pl.len().alias("origins"),
        pl.col("b1q_complete").mean().alias("b1q_b1a_coverage"),
        pl.col("b1q_skew").is_not_null().mean().alias("b1q_b1b_coverage"),
        pl.col("b1q_atm_iv").is_not_null().mean().alias("b1q_b1a_non_null"),
        pl.col("iv_attempts").sum().alias("iv_attempts"),
        pl.col("iv_successes").sum().alias("iv_successes"),
    ]).sort("asset").write_csv(OUT / "b1_coverage_by_asset.csv")
    segments = frame.group_by(["session_segment"]).agg([pl.len().alias("origins"), pl.col("b1q_complete").mean().alias("b1q_atm_coverage")]).sort("session_segment")
    segments.write_csv(OUT / "b1_coverage_by_session_segment.csv")
    summary = {"status": "B1Q_MASSIVE_FULL_ORIGIN_EXPLORATORY", "origins": frame.height, "assets": ASSETS, "coverage": {"b1a": frame["b1q_complete"].mean(), "b1b": frame.filter(pl.col("b1q_skew").is_not_null()).height / frame.height, "b1c": frame.filter(pl.col("b1q_atm_iv").is_not_null() & pl.col("b1q_skew").is_not_null() & pl.col("b1q_term_structure").struct.field("short_to_medium").is_not_null()).height / frame.height if frame.height else 0.0}, "thresholds": {"primary_quote_age_seconds": 60, "primary_relative_spread": 0.25, "sensitivity_quote_age_seconds": 300, "sensitivity_relative_spread": 0.50}, "cache_contract_days": len(jobs), "full_backfill": False, "usable_for_primary": False, "note": "B1T and dividend-aware rerun remain required before acceptance."}
    (OUT / "b1_coverage_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (OUT / "b1q_vs_b1t_comparison.csv").write_text("route,origins,b1a_coverage,b1b_coverage,b1c_coverage,usable_for_primary\nB1Q," + str(frame.height) + "," + str(summary["coverage"]["b1a"]) + "," + str(summary["coverage"]["b1b"]) + "," + str(summary["coverage"]["b1c"]) + ",false\nB1T,0,0,0,0,false\n", encoding="utf-8")
    (OUT / "iv_inversion_diagnostics.json").write_text(json.dumps({"status": "B1Q_IV_DIAGNOSTICS", "attempts": int(frame["iv_attempts"].sum()), "successes": int(frame["iv_successes"].sum()), "failure_counts": failure_counts, "rates_source": "FMP stable treasury-rates month3 before origin", "dividend_source": "FMP stable dividends declarationDate <= origin, trailing 365-day sum divided by spot", "future_rates_or_dividends_used": False, "bsm_american_approximation": True}, indent=2), encoding="utf-8")
    forensic_dir = ROOT / "artifacts" / "b1_forensic"
    forensic_dir.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(iv_attempt_rows, infer_schema_length=None, strict=False).write_csv(forensic_dir / "iv_failures.csv")
    print(json.dumps({"origins": frame.height, "contract_days": len(jobs), "b1a": summary["coverage"]["b1a"], "b1b": summary["coverage"]["b1b"], "b1c": summary["coverage"]["b1c"]}))


if __name__ == "__main__":
    main()
