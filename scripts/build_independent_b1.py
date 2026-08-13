"""Build the target-free B1v2a ATM-IV state for the 90-session replication.

Only the preregistered medium DTE bucket is fetched for the primary route.  A
single contract-day quote cache is reused across every five-minute origin;
the local join always selects the last SIP quote at or before that origin.
"""

from __future__ import annotations

import argparse
import gc
import json
import math
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import httpx
import polars as pl
import run_b1_closure as b1

from mds650.b1q_exogenous_provenance_v1 import parse_treasury_yield_curve_xml
from mds650.phase5_storage import sha256_file
from mds650.phase6 import OUTCOME_ASSETS, build_b1v2_features
from mds650.study_design import canonical_sha256

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_ROOT = ROOT / "artifacts" / "independent_replication"
WINDOW_PATH = ARTIFACT_ROOT / "window_manifest.json"
DATA_ROOT = Path("D:/MDS650/independent_replication_30")
DERIVED_ROOT = DATA_ROOT / "derived" / "b1"
CACHE_ROOT = DATA_ROOT / "cache" / "massive_b1_medium"
BARS_PATH = DATA_ROOT / "derived" / "underlying_1min_90d.parquet"
ORIGINS_PATH = DATA_ROOT / "derived" / "origins_90d.parquet"
ATTEMPTS_PATH = DERIVED_ROOT / "iv_attempts_90d.parquet"
FEATURES_PATH = DERIVED_ROOT / "b1v2a_90d.parquet"
CONTRACTS_PATH = DERIVED_ROOT / "contracts_90d.json"
PIT_V2_ROOT = DATA_ROOT / "derived" / "b1_pit_v2"
PIT_V2_ATTEMPTS_PATH = PIT_V2_ROOT / "iv_attempts_90d_pit_v2.parquet"
PIT_V2_FEATURES_PATH = PIT_V2_ROOT / "b1v2a_90d_pit_v2.parquet"
EXOGENOUS_ROOT = (
    Path(os.environ.get("MDS650_BULK_ROOT", "D:/MDS650")) / "phase6" / "raw" / "fmp_exogenous_v1"
)
ASSETS = tuple(OUTCOME_ASSETS)
MONEY = (0.95, 0.975, 1.0, 1.025, 1.05)
LOW_DTE, HIGH_DTE = 30, 60


def _secret(name: str) -> str:
    """Return a required secret without printing its value."""
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"MISSING_SECRET:{name}")
    return value


def _json(path: Path) -> dict[str, Any]:
    """Read a JSON object."""
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"JSON_OBJECT_REQUIRED:{path.name}")
    return value


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    """Write a hashed JSON manifest atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    unsigned = {key: value for key, value in payload.items() if key != "manifest_sha256"}
    output = {**unsigned, "manifest_sha256": canonical_sha256(unsigned)}
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_text(
        json.dumps(output, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def _resolve_medium(
    client: httpx.Client, key: str, asset: str, day: str, spot: float
) -> list[dict[str, Any]]:
    """Resolve one medium-DTE contract grid as of one historical session."""
    requested = date.fromisoformat(day)
    base_params = {
        "underlying_ticker": asset,
        "as_of": day,
        "expiration_date.gte": (requested + timedelta(days=LOW_DTE)).isoformat(),
        "expiration_date.lte": (requested + timedelta(days=HIGH_DTE)).isoformat(),
        "strike_price.gte": f"{spot * 0.90:.6f}",
        "strike_price.lte": f"{spot * 1.10:.6f}",
        "limit": "1000",
    }
    endpoint = "https://api.massive.com/v3/reference/options/contracts"

    def fetch(expired: str) -> tuple[list[dict[str, Any]], str | None, int, dict[str, Any]]:
        """Fetch and fully paginate one explicit expired-parameter route."""
        params = {**base_params, "expired": expired}
        status, payload, request_id = b1._request_json(client, endpoint, params, key)
        if status != 200:
            raise RuntimeError(f"MASSIVE_CONTRACT_REFERENCE_HTTP_{status}:{asset}:{day}")
        first_rows = payload.get("results", [])
        if not isinstance(first_rows, list):
            raise RuntimeError("MASSIVE_CONTRACT_RESULTS_NOT_LIST")
        candidates = list(first_rows)
        next_url = payload.get("next_url")
        seen_urls: set[str] = set()
        pages = 1
        while next_url:
            if not isinstance(next_url, str) or next_url in seen_urls:
                raise RuntimeError("MASSIVE_CONTRACT_PAGINATION_REPEATED")
            seen_urls.add(next_url)
            page_status, page, _ = b1._request_json(client, next_url, {}, key)
            if page_status != 200:
                raise RuntimeError(f"MASSIVE_CONTRACT_PAGE_HTTP_{page_status}:{asset}:{day}")
            page_rows = page.get("results", [])
            if not isinstance(page_rows, list):
                raise RuntimeError("MASSIVE_CONTRACT_RESULTS_NOT_LIST")
            candidates.extend(page_rows)
            next_url = page.get("next_url")
            pages += 1
        return (
            candidates,
            request_id,
            pages,
            {
                "expired": expired,
                "http_status": status,
                "request_id": request_id,
                "pages": pages,
                "candidate_rows": len(candidates),
                "params_sanitized": params,
            },
        )

    candidates, request_id, pages, first_attempt = fetch("true")
    attempts = [first_attempt]
    if not candidates:
        candidates, request_id, pages, fallback_attempt = fetch("false")
        attempts.append(fallback_attempt)
    expired_behavior = (
        "EXPIRED_TRUE_NON_EMPTY"
        if first_attempt["candidate_rows"]
        else "EXPIRED_TRUE_EMPTY_FALLBACK_FALSE"
    )
    selected: dict[tuple[str, float], dict[str, Any]] = {}
    for row in candidates:
        try:
            if str(row.get("underlying_ticker")) != asset:
                continue
            kind = str(row["contract_type"]).lower()
            expiry = date.fromisoformat(str(row["expiration_date"]))
            strike = float(row["strike_price"])
            ticker = str(row["ticker"])
        except (KeyError, TypeError, ValueError):
            continue
        dte = (expiry - requested).days
        if kind not in {"call", "put"} or not LOW_DTE <= dte <= HIGH_DTE:
            continue
        moneyness = strike / spot
        for target in MONEY:
            if abs(moneyness - target) > 0.04:
                continue
            key_name = (kind, target)
            previous = selected.get(key_name)
            if previous is None or abs(moneyness - target) < abs(previous["moneyness"] - target):
                selected[key_name] = {
                    "contract": ticker,
                    "expiry": expiry.isoformat(),
                    "strike": strike,
                    "option_type": kind,
                    "dte": dte,
                    "moneyness": moneyness,
                    "reference_request_id": request_id,
                    "reference_pages": pages,
                    "reference_attempts": attempts,
                    "expired_parameter_behavior": expired_behavior,
                }
    return list({row["contract"]: row for row in selected.values()}.values())


def _spot_by_day(bars: pl.DataFrame, origins: pl.DataFrame) -> pl.DataFrame:
    """Return the first conservative spot available for each asset-day."""
    return (
        origins.join(
            bars.select(
                "asset",
                "session_date",
                pl.col("available_at_utc").alias("forecast_origin_utc"),
                pl.col("close").alias("spot"),
            ),
            on=["asset", "session_date", "forecast_origin_utc"],
            how="left",
            validate="1:1",
        )
        .group_by(["asset", "session_date"])
        .agg(pl.col("spot").first())
    )


def _fmp_date_range_rows(
    client: httpx.Client,
    endpoint: str,
    key: str,
    start: date,
    end: date,
    base_params: dict[str, str],
    label: str,
) -> list[dict[str, Any]]:
    """Fetch a bounded FMP date range in chunks and preserve only row objects.

    FMP may silently cap a broad historical range.  Chunking keeps the rate and
    dividend inputs available strictly before each forecast session instead of
    accepting a truncated response that would masquerade as missing data.
    """
    rows_by_value: dict[str, dict[str, Any]] = {}
    cursor = start
    while cursor <= end:
        chunk_end = min(cursor + timedelta(days=60), end)
        response = client.get(
            endpoint,
            params={
                **base_params,
                "from": cursor.isoformat(),
                "to": chunk_end.isoformat(),
                "apikey": key,
            },
        )
        if response.status_code != 200:
            raise RuntimeError(f"{label}_HTTP:{response.status_code}:{cursor}:{chunk_end}")
        payload = response.json()
        if not isinstance(payload, list):
            raise RuntimeError(f"{label}_SCHEMA:{cursor}:{chunk_end}")
        for row in payload:
            if isinstance(row, dict):
                rows_by_value.setdefault(
                    json.dumps(row, sort_keys=True, separators=(",", ":")), row
                )
        cursor = chunk_end + timedelta(days=1)
    return list(rows_by_value.values())


def _load_contract_day_caches(
    asset: str,
    day: str,
    day_contracts: list[dict[str, Any]],
    cache_paths: dict[tuple[str, str, str], str],
) -> dict[str, dict[str, Any]]:
    """Load each contract-day quote cache once for all origins in that day."""
    return {
        str(contract["contract"]): _json(Path(cache_paths[(asset, day, str(contract["contract"]))]))
        for contract in day_contracts
    }


def _rates_and_dividends(
    client: httpx.Client,
    fmp_key: str,
    spots: pl.DataFrame,
    first_day: str,
    last_day: str,
) -> tuple[dict[str, float], dict[tuple[str, str], float], dict[tuple[str, str], str]]:
    """Load only information available by each origin and label q=0 assumptions."""
    first_date = date.fromisoformat(first_day)
    last_date = date.fromisoformat(last_day)
    rate_rows = _fmp_date_range_rows(
        client,
        "https://financialmodelingprep.com/stable/treasury-rates",
        fmp_key,
        first_date - timedelta(days=365),
        last_date,
        {},
        "FMP_TREASURY",
    )
    rates = {
        str(row["date"]): float(row["month3"]) / 100.0
        for row in rate_rows
        if row.get("date") and row.get("month3") is not None
    }
    dividend_rows: dict[str, list[dict[str, Any]]] = {}
    for asset in ASSETS:
        dividend_rows[asset] = _fmp_date_range_rows(
            client,
            "https://financialmodelingprep.com/stable/dividends",
            fmp_key,
            first_date - timedelta(days=365),
            last_date,
            {"symbol": asset},
            f"FMP_DIVIDENDS:{asset}",
        )
    dividend_yields: dict[tuple[str, str], float] = {}
    q_labels: dict[tuple[str, str], str] = {}
    for row in spots.iter_rows(named=True):
        asset, day, spot = str(row["asset"]), str(row["session_date"]), float(row["spot"] or 0.0)
        dividend_yields[(asset, day)], q_labels[(asset, day)] = _declared_dividend_yield(
            dividend_rows[asset], day, spot
        )
    return rates, dividend_yields, q_labels


def _prior_rate(rates: dict[str, float], day: str) -> float | None:
    """Return the latest date-level Treasury rate strictly before ``day``."""
    eligible = [key for key in rates if key < day]
    return rates[max(eligible)] if eligible else None


def _declared_dividend_yield(
    events: list[dict[str, Any]], session_day: str, spot: float
) -> tuple[float, str]:
    """Return trailing declared dividends divided by the frozen daily spot."""
    cutoff = date.fromisoformat(session_day)
    values: list[float] = []
    for event in events:
        try:
            declaration_day = date.fromisoformat(str(event.get("declarationDate")))
            value = float(event.get("adjDividend") or event.get("dividend") or 0.0)
        except (TypeError, ValueError):
            continue
        if cutoff - timedelta(days=365) <= declaration_day < cutoff and value > 0:
            values.append(value)
    if values and spot > 0:
        return sum(values) / spot, "PRE_ORIGIN_TRAILING_DECLARATIONS"
    return 0.0, "NO_PRE_ORIGIN_DIVIDEND_Q_ZERO"


def build_b1() -> None:
    """Resolve contracts, cache quotes and build B1v2a for all 90 sessions."""
    massive_key = _secret("MASSIVE_API_KEY")
    fmp_key = _secret("FMP_API_KEY")
    if not BARS_PATH.exists() or not ORIGINS_PATH.exists():
        raise RuntimeError("REPLICATION_B1_INPUTS_MISSING")
    origins = pl.read_parquet(ORIGINS_PATH)
    bars = pl.read_parquet(BARS_PATH)
    spots = _spot_by_day(bars, origins)
    if spots["spot"].null_count() or spots.filter(pl.col("spot") <= 0).height:
        raise RuntimeError("REPLICATION_B1_SPOT_MISSING")
    first_day, last_day = str(origins["session_date"].min()), str(origins["session_date"].max())
    with httpx.Client(timeout=90.0, follow_redirects=True) as client:
        rates, dividend_yields, q_labels = _rates_and_dividends(
            client, fmp_key, spots, first_day, last_day
        )
        contracts: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for spot_row in spots.sort(["asset", "session_date"]).iter_rows(named=True):
            contracts[(str(spot_row["asset"]), str(spot_row["session_date"]))] = _resolve_medium(
                client,
                massive_key,
                str(spot_row["asset"]),
                str(spot_row["session_date"]),
                float(spot_row["spot"]),
            )
    _write_json(
        CONTRACTS_PATH,
        {
            "schema_version": "b2-independent-replication-contract-resolution-1.0",
            "status": "PASS_HISTORICAL_CONTRACTS_RESOLVED",
            "route": "MASSIVE_REFERENCE_AS_OF",
            "dte_bucket": "30-60",
            "rate_availability_rule": "latest FMP treasury date strictly before session date",
            "dividend_availability_rule": "FMP dividend event date strictly before session date",
            "records": [
                {
                    "asset": asset,
                    "session_date": day,
                    "contracts": values,
                }
                for (asset, day), values in sorted(contracts.items())
            ],
            "target_outcome_read": False,
            "secret_values_emitted": False,
            "personal_paths_emitted": False,
        },
    )
    CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    b1.CACHE = CACHE_ROOT
    jobs = [
        (asset, day, contract) for (asset, day), values in contracts.items() for contract in values
    ]
    cache_paths: dict[tuple[str, str, str], str] = {}
    print(
        json.dumps(
            {
                "contract_day_jobs": len(jobs),
                "cached_files": len(list(CACHE_ROOT.glob("*.json"))),
                "workers": 8,
            }
        ),
        flush=True,
    )
    with ThreadPoolExecutor(max_workers=8) as executor:
        for batch_start in range(0, len(jobs), 32):
            batch = jobs[batch_start : batch_start + 32]
            futures = {
                executor.submit(b1.fetch_contract_day, job, massive_key): job for job in batch
            }
            for offset, future in enumerate(as_completed(futures), start=1):
                job = futures[future]
                cache_result = future.result()
                cache_paths[(job[0], job[1], job[2]["contract"])] = str(cache_result["cache_path"])
                index = batch_start + offset
                if index % 25 == 0 or index == len(jobs):
                    print(
                        json.dumps(
                            {
                                "quote_jobs_completed": index,
                                "quote_jobs_total": len(jobs),
                            }
                        ),
                        flush=True,
                    )
            del futures, batch
            gc.collect()
    attempts: list[dict[str, Any]] = []
    spot_by_day = {
        (str(row["asset"]), str(row["session_date"])): float(row["spot"] or 0.0)
        for row in spots.iter_rows(named=True)
    }
    origins_by_day: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for origin in origins.sort(["asset", "session_date", "forecast_origin_utc"]).to_dicts():
        key = (str(origin["asset"]), str(origin["session_date"]))
        origins_by_day.setdefault(key, []).append(origin)
    for (asset, day), day_origins in origins_by_day.items():
        spot = spot_by_day[(asset, day)]
        rate = _prior_rate(rates, day)
        if rate is None:
            raise RuntimeError(f"MISSING_RATE_BEFORE_ORIGIN:{asset}:{day}")
        day_contracts = contracts.get((asset, day), [])
        day_caches = _load_contract_day_caches(asset, day, day_contracts, cache_paths)
        for origin in day_origins:
            origin_ns = int(origin["forecast_origin_utc"].timestamp() * 1_000_000_000)
            for contract in day_contracts:
                cache = day_caches[str(contract["contract"])]
                quote = b1.latest_quote(cache, origin_ns)
                failure: str | None = "NO_QUOTE_BEFORE_ORIGIN"
                iv_result: dict[str, Any] = {"success": False}
                if quote is not None and quote.get("sip_timestamp", origin_ns + 1) > origin_ns:
                    raise RuntimeError("MASSIVE_QUOTE_AFTER_ORIGIN")
                if quote is not None and "midpoint" not in quote:
                    failure = str(quote.get("missing_reason") or "INVALID_SPREAD")
                elif quote is not None and quote["quote_age_seconds"] > 60:
                    failure = "STALE_QUOTE"
                elif quote is not None and quote["relative_spread"] > 0.25:
                    failure = "INVALID_SPREAD"
                elif quote is not None:
                    iv_result = b1.invert_iv(
                        spot,
                        float(contract["strike"]),
                        float(contract["dte"]) / 365.0,
                        rate,
                        float(dividend_yields[(asset, day)]),
                        float(quote["midpoint"]),
                        str(contract["option_type"]),
                    )
                    failure = (
                        None
                        if iv_result.get("success")
                        else str(iv_result.get("failure_reason") or "IV_NO_CONVERGENCE")
                    )
                attempts.append(
                    {
                        "origin_id": origin["origin_id"],
                        "asset": asset,
                        "session_date": day,
                        "forecast_origin_utc": origin["forecast_origin_utc"],
                        "contract": contract["contract"],
                        "expiry": contract["expiry"],
                        "option_type": contract["option_type"],
                        "dte": int(contract["dte"]),
                        "moneyness": float(contract["moneyness"]),
                        "sip_timestamp_ns": int(quote["sip_timestamp"]) if quote else None,
                        "bid": float(quote["bid"]) if quote and "bid" in quote else None,
                        "ask": float(quote["ask"]) if quote and "ask" in quote else None,
                        "implied_volatility": (
                            iv_result.get("iv") if iv_result.get("success") else None
                        ),
                        "quote_age_seconds": quote.get("quote_age_seconds") if quote else None,
                        "relative_spread": quote.get("relative_spread") if quote else None,
                        "rate": rate,
                        "dividend_yield": dividend_yields[(asset, day)],
                        "q_label": q_labels[(asset, day)],
                        "success": bool(iv_result.get("success")),
                        "failure_code": failure,
                        "iterations": iv_result.get("iterations"),
                        "lower_bound": iv_result.get("lower_bound"),
                        "upper_bound": iv_result.get("upper_bound"),
                    }
                )
    attempts_frame = pl.DataFrame(attempts, infer_schema_length=None, strict=False)
    DERIVED_ROOT.mkdir(parents=True, exist_ok=True)
    attempts_frame.write_parquet(ATTEMPTS_PATH, compression="zstd")
    feature_input = attempts_frame.select(
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
    )
    features = build_b1v2_features(
        origins.select(
            "origin_id", "asset", "session_date", "forecast_origin_utc", "session_tercile", "role"
        ),
        feature_input,
    )
    features.write_parquet(FEATURES_PATH, compression="zstd")
    _write_json(
        ARTIFACT_ROOT / "b1_manifest.json",
        {
            "schema_version": "b2-independent-replication-b1-1.0",
            "status": "PASS_B1V2A_TARGET_FREE",
            "route": "B1Q_MASSIVE",
            "origin_count": features.height,
            "attempt_count": attempts_frame.height,
            "success_count": attempts_frame.filter(pl.col("success")).height,
            "b1v2a_coverage": features["b1v2a_complete"].mean(),
            "quote_age_seconds": 60,
            "relative_spread_max": 0.25,
            "dte_bucket": "30-60",
            "feature_sha256": sha256_file(FEATURES_PATH),
            "attempts_sha256": sha256_file(ATTEMPTS_PATH),
            "target_outcome_read": False,
            "secret_values_emitted": False,
            "personal_paths_emitted": False,
        },
    )
    print(
        json.dumps(
            {
                "status": "PASS_B1V2A_TARGET_FREE",
                "origins": features.height,
                "coverage": features["b1v2a_complete"].mean(),
            }
        )
    )


def rebuild_b1_pit_v2() -> None:
    """Recompute cached independent B1 IVs after exogenous-input correction.

    This target-free repair reuses immutable quotes, contracts, origins and
    bars. It never opens RV30, predictions, QLIKE or model outputs.
    """
    required = (
        ATTEMPTS_PATH,
        FEATURES_PATH,
        CONTRACTS_PATH,
        ORIGINS_PATH,
        BARS_PATH,
        EXOGENOUS_ROOT / "treasury_2025.xml",
        EXOGENOUS_ROOT / "capture_manifest.json",
    )
    if any(not path.is_file() for path in required):
        raise RuntimeError("REPLICATION_B1_PIT_V2_INPUT_MISSING")

    origins = pl.read_parquet(ORIGINS_PATH)
    bars = pl.read_parquet(BARS_PATH)
    spots_frame = _spot_by_day(bars, origins)
    spots = {
        (str(row["asset"]), str(row["session_date"])): float(row["spot"])
        for row in spots_frame.iter_rows(named=True)
    }
    rates = parse_treasury_yield_curve_xml((EXOGENOUS_ROOT / "treasury_2025.xml").read_bytes())
    dividends: dict[str, list[dict[str, Any]]] = {}
    for asset in ASSETS:
        payload = json.loads(
            (EXOGENOUS_ROOT / f"dividends_{asset}.json").read_text(encoding="utf-8")
        )
        if not isinstance(payload, list) or not all(isinstance(row, dict) for row in payload):
            raise RuntimeError(f"REPLICATION_B1_PIT_V2_DIVIDEND_SCHEMA:{asset}")
        dividends[asset] = payload

    contract_manifest = _json(CONTRACTS_PATH)
    contract_records = contract_manifest.get("records")
    if not isinstance(contract_records, list):
        raise RuntimeError("REPLICATION_B1_PIT_V2_CONTRACT_SCHEMA")
    strikes: dict[tuple[str, str, str], float] = {}
    for record in contract_records:
        if not isinstance(record, dict) or not isinstance(record.get("contracts"), list):
            raise RuntimeError("REPLICATION_B1_PIT_V2_CONTRACT_SCHEMA")
        asset, day = str(record.get("asset")), str(record.get("session_date"))
        for contract in record["contracts"]:
            if isinstance(contract, dict):
                strikes[(asset, day, str(contract.get("contract")))] = float(contract["strike"])

    daily: dict[tuple[str, str], tuple[float, str, str, float]] = {}
    for (asset, day), spot in spots.items():
        rate_source_date = max(source_day for source_day in rates if source_day < day)
        dividend_yield, assumption = _declared_dividend_yield(dividends[asset], day, spot)
        daily[(asset, day)] = (
            dividend_yield,
            assumption,
            rate_source_date,
            rates[rate_source_date],
        )

    original = pl.read_parquet(ATTEMPTS_PATH)
    observed_daily = {
        (str(row["asset"]), str(row["session_date"])): float(row["dividend_yield"])
        for row in original.group_by("asset", "session_date")
        .agg(pl.col("dividend_yield").first())
        .iter_rows(named=True)
    }
    duplication_factors: set[float] = set()
    declaration_window_changed_asset_days = 0
    for (asset, day), (corrected_yield, _, _, _) in daily.items():
        cutoff = date.fromisoformat(day)
        event_values: list[float] = []
        for event in dividends[asset]:
            try:
                event_day = date.fromisoformat(str(event.get("date")))
                value = float(event.get("adjDividend") or event.get("dividend") or 0.0)
            except (TypeError, ValueError):
                continue
            if cutoff - timedelta(days=365) <= event_day < cutoff and value > 0:
                event_values.append(value)
        event_yield = sum(event_values) / spots[(asset, day)] if event_values else 0.0
        if event_yield > 0:
            duplication_factors.add(round(observed_daily[(asset, day)] / event_yield, 12))
        if not math.isclose(event_yield, corrected_yield, rel_tol=0.0, abs_tol=1e-12):
            declaration_window_changed_asset_days += 1
    if duplication_factors != {9.0}:
        raise RuntimeError("REPLICATION_B1_PIT_V2_DUPLICATION_FACTOR_UNEXPECTED")

    corrected_rows: list[dict[str, Any]] = []
    rate_mismatches = 0
    dividend_changed_rows = 0
    iv_changed_rows = 0
    for row in original.iter_rows(named=True):
        asset, day = str(row["asset"]), str(row["session_date"])
        key = (asset, day)
        dividend_yield, assumption, rate_source_date, rate = daily[key]
        if not math.isclose(float(row["rate"]), rate, rel_tol=0.0, abs_tol=1e-12):
            rate_mismatches += 1
        if not math.isclose(
            float(row["dividend_yield"]), dividend_yield, rel_tol=0.0, abs_tol=1e-12
        ):
            dividend_changed_rows += 1

        bid, ask = row.get("bid"), row.get("ask")
        age, spread = row.get("quote_age_seconds"), row.get("relative_spread")
        valid_quote = (
            bid is not None
            and ask is not None
            and age is not None
            and spread is not None
            and float(bid) > 0
            and float(ask) > float(bid)
            and float(age) <= 60.0
            and float(spread) <= 0.25
        )
        updated = {
            **row,
            "spot": spots[key],
            "strike": strikes[(asset, day, str(row["contract"]))],
            "rate": rate,
            "rate_source_date": rate_source_date,
            "dividend_yield": dividend_yield,
            "dividend_assumption": assumption,
            "q_label": assumption,
            "exogenous_pit_verified": True,
        }
        if valid_quote:
            assert bid is not None and ask is not None
            iv_result = b1.invert_iv(
                spots[key],
                updated["strike"],
                float(row["dte"]) / 365.0,
                rate,
                dividend_yield,
                (float(bid) + float(ask)) / 2.0,
                str(row["option_type"]),
            )
            new_iv = iv_result.get("iv") if iv_result.get("success") else None
            old_iv = row.get("implied_volatility")
            if (old_iv is None) != (new_iv is None) or (
                old_iv is not None
                and new_iv is not None
                and not math.isclose(float(old_iv), float(new_iv), rel_tol=0.0, abs_tol=1e-12)
            ):
                iv_changed_rows += 1
            updated.update(
                {
                    "implied_volatility": new_iv,
                    "success": bool(iv_result.get("success")),
                    "failure_code": (
                        None
                        if iv_result.get("success")
                        else str(iv_result.get("failure_reason") or "IV_NO_CONVERGENCE")
                    ),
                    "iterations": iv_result.get("iterations"),
                    "lower_bound": iv_result.get("lower_bound"),
                    "upper_bound": iv_result.get("upper_bound"),
                }
            )
        corrected_rows.append(updated)

    if rate_mismatches:
        raise RuntimeError("REPLICATION_B1_PIT_V2_RATE_MISMATCH")
    corrected = pl.DataFrame(corrected_rows, infer_schema_length=None, strict=False)
    if corrected.height != original.height or not corrected["exogenous_pit_verified"].all():
        raise RuntimeError("REPLICATION_B1_PIT_V2_ATTEMPT_INVARIANT")
    if any(name.lower().startswith(("rv30", "qlike", "target")) for name in corrected.columns):
        raise RuntimeError("REPLICATION_B1_PIT_V2_TARGET_COLUMN")

    features = build_b1v2_features(origins, corrected)
    if features.height != origins.height:
        raise RuntimeError("REPLICATION_B1_PIT_V2_ORIGIN_MISMATCH")
    PIT_V2_ROOT.mkdir(parents=True, exist_ok=True)
    corrected.write_parquet(PIT_V2_ATTEMPTS_PATH, compression="zstd")
    features.write_parquet(PIT_V2_FEATURES_PATH, compression="zstd")

    old_features = pl.read_parquet(FEATURES_PATH)
    feature_comparison = old_features.select(
        "origin_id", pl.col("b1v2_atm_iv_30_60_dte").alias("old_atm")
    ).join(
        features.select("origin_id", pl.col("b1v2_atm_iv_30_60_dte").alias("new_atm")),
        on="origin_id",
        how="inner",
        validate="1:1",
    )
    changed_feature_origins = feature_comparison.filter(
        (pl.col("old_atm").is_null() != pl.col("new_atm").is_null())
        | (
            pl.col("old_atm").is_not_null()
            & pl.col("new_atm").is_not_null()
            & ((pl.col("old_atm") - pl.col("new_atm")).abs() > 1e-12)
        )
    ).height
    capture_manifest = EXOGENOUS_ROOT / "capture_manifest.json"
    _write_json(
        ARTIFACT_ROOT / "b1_pit_v2_manifest.json",
        {
            "schema_version": "b2-independent-replication-b1-pit-v2-1.0",
            "status": "PASS_TARGET_FREE_REPAIR_REQUIRES_NEW_EVALUATION",
            "route": "B1Q_MASSIVE_CACHED_QUOTES",
            "origin_count": features.height,
            "attempt_count": corrected.height,
            "rate_value_mismatch_count": rate_mismatches,
            "dividend_rows_corrected": dividend_changed_rows,
            "provider_over_return_duplication_factor": 9,
            "declaration_window_changed_asset_days": declaration_window_changed_asset_days,
            "iv_rows_changed": iv_changed_rows,
            "atm_feature_origins_changed": changed_feature_origins,
            "old_b1a_coverage": old_features["b1v2a_complete"].mean(),
            "corrected_b1a_coverage": features["b1v2a_complete"].mean(),
            "old_attempts_sha256": sha256_file(ATTEMPTS_PATH),
            "corrected_attempts_sha256": sha256_file(PIT_V2_ATTEMPTS_PATH),
            "corrected_features_sha256": sha256_file(PIT_V2_FEATURES_PATH),
            "exogenous_capture_manifest_sha256": sha256_file(capture_manifest),
            "rate_availability_rule": "LATEST_TREASURY_DATE_STRICTLY_BEFORE_SESSION",
            "dividend_availability_rule": "DECLARATION_DATE_STRICTLY_BEFORE_SESSION",
            "existing_sealed_results_reconciled": False,
            "new_evaluation_authorized": False,
            "target_outcome_read": False,
            "secret_values_emitted": False,
            "personal_paths_emitted": False,
        },
    )
    print(
        json.dumps(
            {
                "status": "PASS_TARGET_FREE_REPAIR_REQUIRES_NEW_EVALUATION",
                "origins": features.height,
                "corrected_b1a_coverage": features["b1v2a_complete"].mean(),
                "atm_feature_origins_changed": changed_feature_origins,
            },
            sort_keys=True,
        )
    )


def main() -> None:
    """Run the independent B1 stage."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=("b1", "repair-pit-v2"), default="b1")
    args = parser.parse_args()
    if args.stage == "repair-pit-v2":
        rebuild_b1_pit_v2()
    else:
        build_b1()


if __name__ == "__main__":
    main()
