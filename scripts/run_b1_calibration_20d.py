"""Recompute the repaired B1Q route over the authorized twenty-session origins."""
# ruff: noqa: E501

from __future__ import annotations

import json
import os
import time as time_module
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass, replace
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

import httpx
import polars as pl
import run_b1_closure as closure

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts" / "calibration_20d"
CACHE = OUT / "massive_b1q_cache_v4"
ASSETS = closure.ASSETS
DEFAULT_ORIGINS_PATH = OUT / "b2_calibration_origins.parquet"


@dataclass(frozen=True)
class B1BuildConfig:
    """Explicit B1 output/cache roots and authorized sessions."""

    output_root: Path
    cache_root: Path
    sessions: tuple[str, ...]
    origins_path: Path | None = None
    contract_cache_filename: str = "resolved_contracts_phase6_strict_v3.json"

    def __post_init__(self) -> None:
        if self.sessions and tuple(sorted(set(self.sessions))) != self.sessions:
            raise ValueError("B1_SESSION_ALLOWLIST_INVALID")
        if not self.sessions and self.origins_path is None:
            raise ValueError("B1_SESSION_ALLOWLIST_INVALID")
        contract_cache = Path(self.contract_cache_filename)
        if (
            contract_cache.name != self.contract_cache_filename
            or contract_cache.suffix.lower() != ".json"
        ):
            raise ValueError("B1_CONTRACT_CACHE_FILENAME_INVALID")


DEFAULT_CONFIG = B1BuildConfig(
    output_root=OUT,
    cache_root=CACHE,
    sessions=(),
    origins_path=DEFAULT_ORIGINS_PATH,
)


def _authorized_sessions(config: B1BuildConfig) -> tuple[str, ...]:
    """Resolve the explicit session allow-list only when execution needs it.

    The module must remain importable in a clean checkout that intentionally
    omits commercial pilot Parquet.  Reading the authorized origin source is an
    execution concern, never an import-time side effect.
    """
    if config.sessions:
        return config.sessions
    source = config.origins_path
    if source is None or not source.is_file():
        raise RuntimeError("B1_ORIGIN_SOURCE_MISSING")
    sessions = tuple(
        sorted(
            str(value)
            for value in pl.read_parquet(source).get_column("session_date").unique().to_list()
        )
    )
    if not sessions:
        raise RuntimeError("B1_ORIGIN_SESSION_ALLOWLIST_EMPTY")
    return sessions


def _with_authorized_sessions(config: B1BuildConfig) -> B1BuildConfig:
    """Return an execution config whose session allow-list is explicit."""
    if config.sessions:
        return config
    return replace(config, sessions=_authorized_sessions(config))


def _secret(name: str) -> str:
    """Return a required provider secret without logging its value."""
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"MISSING_SECRET:{name}")
    return value


def _fmp_list_request(
    client: httpx.Client,
    url: str,
    params: dict[str, str],
    key: str,
    *,
    max_attempts: int = 4,
    backoff_seconds: float = 1.0,
) -> list[dict[str, Any]]:
    """Request one FMP list payload with bounded transient retries."""
    safe = {**params, "apikey": key}
    for attempt in range(1, max_attempts + 1):
        try:
            response = client.get(url, params=safe)
        except httpx.TransportError:
            if attempt == max_attempts:
                raise RuntimeError("FMP_REQUEST_RETRY_EXHAUSTED") from None
            time_module.sleep(backoff_seconds * 2 ** (attempt - 1))
            continue
        retryable = response.status_code == 429 or response.status_code >= 500
        if retryable and attempt < max_attempts:
            time_module.sleep(backoff_seconds * 2 ** (attempt - 1))
            continue
        if response.status_code != 200:
            raise RuntimeError(f"FMP_HTTP_{response.status_code}")
        try:
            payload = response.json()
        except ValueError:
            raise RuntimeError("FMP_RESPONSE_NOT_JSON") from None
        if not isinstance(payload, list) or not all(isinstance(row, dict) for row in payload):
            raise RuntimeError("FMP_RESPONSE_NOT_LIST")
        return payload
    raise RuntimeError("FMP_REQUEST_RETRY_EXHAUSTED")


def _market_input_window(config: B1BuildConfig) -> tuple[date, date]:
    """Return the trailing-year PIT input window for rates and dividends."""
    sessions = _authorized_sessions(config)
    first = min(date.fromisoformat(day) for day in sessions)
    last = max(date.fromisoformat(day) for day in sessions)
    return first - timedelta(days=365), last


def _date_windows(first: date, last: date) -> tuple[tuple[date, date], ...]:
    """Split an inclusive date range into contiguous 31-day requests."""
    windows: list[tuple[date, date]] = []
    start = first
    while start <= last:
        end = min(start + timedelta(days=30), last)
        windows.append((start, end))
        start = end + timedelta(days=1)
    return tuple(windows)


def _rates_and_dividends(
    fmp_key: str,
    origins: pl.DataFrame,
    config: B1BuildConfig = DEFAULT_CONFIG,
) -> tuple[dict[str, float], dict[tuple[str, str], float]]:
    """Load pre-origin rate and dividend inputs for the twenty-session window."""
    first, last = _market_input_window(config)
    rates: dict[str, float] = {}
    with httpx.Client(timeout=90.0) as client:
        for window_start, window_end in _date_windows(first, last):
            payload = _fmp_list_request(
                client,
                "https://financialmodelingprep.com/stable/treasury-rates",
                {"from": window_start.isoformat(), "to": window_end.isoformat()},
                fmp_key,
            )
            for row in payload:
                if row.get("date") and row.get("month3") is not None:
                    observed = str(row["date"])
                    if not window_start.isoformat() <= observed <= window_end.isoformat():
                        raise RuntimeError("FMP_TREASURY_RATE_OUTSIDE_REQUEST_WINDOW")
                    rates[observed] = float(row["month3"]) / 100.0
    if not rates:
        raise RuntimeError("FMP_TREASURY_RATES_EMPTY")
    dividends: dict[str, list[dict[str, Any]]] = {}
    with httpx.Client(timeout=90.0) as client:
        for asset in ASSETS:
            dividends[asset] = _fmp_list_request(
                client,
                "https://financialmodelingprep.com/stable/dividends",
                {
                    "symbol": asset,
                    "from": first.isoformat(),
                    "to": last.isoformat(),
                },
                fmp_key,
            )
    result: dict[tuple[str, str], float] = {}
    for row in (
        origins.group_by(["asset", "session_date"])
        .agg(pl.col("spot").first())
        .iter_rows(named=True)
    ):
        asset, day, spot = str(row["asset"]), str(row["session_date"]), float(row["spot"])
        cutoff = date.fromisoformat(day)
        total = 0.0
        for item in dividends.get(asset, []):
            try:
                declared = date.fromisoformat(str(item.get("declarationDate")))
                if cutoff - timedelta(days=365) <= declared < cutoff:
                    total += float(item.get("adjDividend") or item.get("dividend") or 0.0)
            except (TypeError, ValueError):
                continue
        result[(asset, day)] = total / spot if spot > 0 else 0.0
    return rates, result


def _rate_for(day: str, rates: dict[str, float]) -> float:
    """Select the latest Treasury rate strictly before the origin date."""
    return _rate_observation_for(day, rates)[1]


def _rate_observation_for(
    day: str,
    rates: dict[str, float],
) -> tuple[str, float]:
    """Return the latest strictly pre-origin Treasury observation and value."""
    candidates = [key for key in rates if key < day]
    if not candidates:
        raise RuntimeError(f"B1Q_RATE_NOT_AVAILABLE:{day}")
    source_date = max(candidates)
    return source_date, rates[source_date]


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    """Persist a resumable provider cache without exposing partial JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_text(
        json.dumps(payload, separators=(",", ":"), default=str),
        encoding="utf-8",
    )
    for attempt in range(5):
        try:
            temporary.replace(path)
            return
        except PermissionError:
            if attempt == 4:
                raise
            time_module.sleep(0.05 * 2**attempt)


def _write_parquet_atomic(frame: pl.DataFrame, path: Path) -> None:
    """Write one Parquet completely before atomically exposing its final name."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.unlink(missing_ok=True)
    try:
        frame.write_parquet(temporary, compression="zstd")
        _ = pl.read_parquet_schema(temporary)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _run_metadata(session_count: int) -> dict[str, str]:
    """Return session-count-accurate metadata for a target-blind B1Q run."""
    if session_count < 1:
        raise ValueError("B1Q_SESSION_COUNT_INVALID")
    return {
        "status": "PASS_B1Q_RECOMPUTATION",
        "scope": f"TARGET_BLIND_{session_count}_SESSIONS",
    }


def _resolve_contracts(
    origins: pl.DataFrame,
    massive_key: str,
    config: B1BuildConfig = DEFAULT_CONFIG,
) -> dict[tuple[str, str], list[dict[str, Any]]]:
    """Resolve and checkpoint historical contracts once per asset/session."""
    spots = (
        origins.group_by(["asset", "session_date"])
        .agg(pl.col("spot").first())
        .sort(["asset", "session_date"])
    )
    cache_path = config.cache_root / config.contract_cache_filename
    if cache_path.exists():
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
        if (
            not isinstance(payload, dict)
            or payload.get("schema_version") != "b1q-contract-grid-3.0"
            or not isinstance(payload.get("records"), list)
        ):
            raise RuntimeError("B1Q_CONTRACT_CACHE_INVALID")
    else:
        payload = {"schema_version": "b1q-contract-grid-3.0", "records": []}
    records = payload["records"]
    cached = {
        (str(row.get("asset")), str(row.get("session_date"))): row
        for row in records
        if isinstance(row, dict)
    }
    if len(cached) != len(records):
        raise RuntimeError("B1Q_CONTRACT_CACHE_DUPLICATE")
    result: dict[tuple[str, str], list[dict[str, Any]]] = {}
    with httpx.Client(timeout=90.0, follow_redirects=True) as client:
        for row in spots.iter_rows(named=True):
            asset, day, spot = str(row["asset"]), str(row["session_date"]), float(row["spot"])
            key = (asset, day)
            old = cached.get(key)
            if old is not None:
                if float(old.get("spot", -1.0)) != spot or not isinstance(
                    old.get("contracts"), list
                ):
                    raise RuntimeError(f"B1Q_CONTRACT_CACHE_MISMATCH:{asset}:{day}")
                result[key] = old["contracts"]
                continue
            contracts = closure.resolve_contracts(client, massive_key, asset, day, spot)
            record = {
                "asset": asset,
                "session_date": day,
                "spot": spot,
                "contracts": contracts,
            }
            records.append(record)
            cached[key] = record
            result[key] = contracts
            _atomic_json(cache_path, payload)
    return result


def _fetch_quotes(
    contracts: dict[tuple[str, str], list[dict[str, Any]]],
    massive_key: str,
    config: B1BuildConfig = DEFAULT_CONFIG,
) -> tuple[
    dict[tuple[str, str, str], tuple[Path, str]],
    dict[str, int],
]:
    """Fetch each resolved contract-day once into the V4 ordered-event cache."""
    config.cache_root.mkdir(parents=True, exist_ok=True)
    closure.CACHE = config.cache_root
    unique_jobs: dict[tuple[str, str, str], tuple[str, str, dict[str, Any]]] = {}
    for (asset, day), values in contracts.items():
        for contract in values:
            key = (asset, day, str(contract["contract"]))
            unique_jobs.setdefault(key, (asset, day, contract))
    jobs = list(unique_jobs.values())
    output: dict[tuple[str, str, str], tuple[Path, str]] = {}
    transient_retries: dict[tuple[str, str, str], int] = {}
    audit = {
        "contract_day_jobs": len(jobs),
        "pagination_explicit": 0,
        "pagination_inferred_terminal_partial": 0,
        "cache_hits": 0,
        "network_fetches": 0,
        "pages": 0,
        "provider_duplicate_rows_removed": 0,
    }
    # Massive occasionally emits transient 502s under high parallelism.  A
    # bounded four-worker pool plus spaced retries keeps the request contract
    # unchanged while avoiding a false coverage failure caused by pressure.
    with ThreadPoolExecutor(max_workers=4) as executor:
        job_iterator = iter(jobs)
        pending = {}
        for _ in range(min(8, len(jobs))):
            job = next(job_iterator)
            pending[executor.submit(closure.fetch_contract_day, job, massive_key)] = job
        while pending:
            completed, _ = wait(pending, return_when=FIRST_COMPLETED)
            for future in completed:
                asset, day, contract = pending.pop(future)
                job_key = (asset, day, str(contract["contract"]))
                try:
                    cache = future.result()
                except RuntimeError as error:
                    message = str(error)
                    attempts = transient_retries.get(job_key, 0)
                    if (
                        "MASSIVE_QUOTE_HTTP_502" in message or "MASSIVE_QUOTE_HTTP_503" in message
                    ) and attempts < 4:
                        transient_retries[job_key] = attempts + 1
                        time_module.sleep(min(30, 5 * 2**attempts))
                        pending[
                            executor.submit(
                                closure.fetch_contract_day, (asset, day, contract), massive_key
                            )
                        ] = (
                            asset,
                            day,
                            contract,
                        )
                        continue
                    raise
                if cache.get("http_status") != 200:
                    raise RuntimeError(f"B1Q_QUOTE_CACHE_HTTP_FAILURE:{asset}:{day}")
                pagination = cache.get("pagination_complete")
                if pagination is True:
                    audit["pagination_explicit"] += 1
                elif pagination == "INFERRED_TERMINAL_PARTIAL_PAGE":
                    audit["pagination_inferred_terminal_partial"] += 1
                else:
                    raise RuntimeError(f"B1Q_QUOTE_PAGINATION_UNVERIFIED:{asset}:{day}")
                audit["cache_hits" if cache.get("cache_hit") else "network_fetches"] += 1
                audit["pages"] += int(cache.get("pages", 0))
                audit["provider_duplicate_rows_removed"] += int(
                    cache.get("provider_duplicate_rows_removed", 0)
                )
                cache_path = Path(str(cache.get("cache_path", "")))
                source_hash = cache.get("source_request_hash")
                if not cache_path.is_file() or not isinstance(source_hash, str):
                    raise RuntimeError(f"B1Q_QUOTE_CACHE_EVIDENCE_MISSING:{asset}:{day}")
                output[(asset, day, contract["contract"])] = (
                    cache_path,
                    source_hash,
                )
                try:
                    job = next(job_iterator)
                except StopIteration:
                    continue
                pending[
                    executor.submit(
                        closure.fetch_contract_day,
                        job,
                        massive_key,
                    )
                ] = job
    if len(output) != len(jobs) or audit["pagination_explicit"] + audit[
        "pagination_inferred_terminal_partial"
    ] != len(jobs):
        raise RuntimeError("B1Q_QUOTE_CACHE_AUDIT_INCOMPLETE")
    return output, audit


@lru_cache(maxsize=32)
def _load_quote_cache(path: Path) -> dict[str, Any]:
    """Load one contract-day cache with bounded process memory."""
    payload = closure._read_cache_payload(path)
    if not isinstance(payload, dict) or payload.get("http_status") != 200:
        raise RuntimeError(f"B1Q_QUOTE_CACHE_INVALID:{path.name}")
    payload["results"] = closure._compact_quotes(payload.get("results", []))
    return payload


def _first_failure(iv_rows: list[dict[str, Any]], summary: dict[str, Any]) -> str:
    """Map missing B1Q inputs to a stable first diagnostic code."""
    if not iv_rows:
        return "NO_HISTORICAL_CONTRACT"
    if not any(row.get("midpoint") is not None for row in iv_rows):
        return "NO_QUOTE_BEFORE_ORIGIN"
    if not any(
        row.get("quote_age_seconds") is not None and row.get("quote_age_seconds", 9999) <= 60
        for row in iv_rows
    ):
        return "STALE_QUOTE"
    if not any(row.get("iv_success") for row in iv_rows):
        return "IV_NO_CONVERGENCE"
    if summary.get("b1q_atm_iv") is None:
        return "ATM_PAIR_MISSING"
    if summary.get("b1q_skew") is None:
        return "SKEW_PAIR_MISSING"
    term = summary.get("b1q_term_structure") or {}
    if (
        term.get("short_to_medium") is None
        and term.get("medium_to_long") is None
        and term.get("short_to_long") is None
    ):
        return "TERM_BUCKET_MISSING"
    return "NO_FAILURE"


def _quote_pit_evidence(
    iv_rows: list[dict[str, Any]],
    origin_ns: int,
) -> dict[str, int | bool | None]:
    """Summarize observed SIP timestamps for one forecast origin."""
    timestamps = [
        int(row["sip_timestamp"]) for row in iv_rows if isinstance(row.get("sip_timestamp"), int)
    ]
    latest = max(timestamps) if timestamps else None
    not_after_origin = latest is not None and latest <= origin_ns
    return {
        "b1q_max_sip_timestamp_ns": latest,
        "b1q_quote_not_after_origin": not_after_origin,
        "b1q_pit_evidence_valid": bool(timestamps) and not_after_origin,
    }


def _coverage(frame: pl.DataFrame) -> dict[str, Any]:
    """Compute component and nested coverage for one frame."""
    n = frame.height or 1
    return {
        "atm_iv_component": frame["atm_iv_available"].mean(),
        "skew_component": frame["skew_available"].mean(),
        "term_structure_component": frame["term_structure_available"].mean(),
        "b1a": frame["b1a_complete"].mean(),
        "b1b": frame["b1b_complete"].mean(),
        "b1c": frame["b1c_complete"].mean(),
        "iv_success_rate": frame["iv_inversion_success_rate"].mean() if n else 0.0,
    }


def _load_origins(config: B1BuildConfig) -> pl.DataFrame:
    """Load the explicit origin source and enforce its session allow-list."""
    source = config.origins_path or config.output_root / "b2_calibration_origins.parquet"
    origins = pl.read_parquet(source).select(
        ["origin_id", "asset", "session_date", "forecast_origin_utc", "spot", "session_segment"]
    )
    observed_sessions = tuple(
        sorted(str(value) for value in origins.get_column("session_date").unique().to_list())
    )
    if observed_sessions != _authorized_sessions(config):
        raise RuntimeError("B1_ORIGIN_SESSION_ALLOWLIST_MISMATCH")
    return origins.with_columns(pl.col("forecast_origin_utc").dt.timestamp("ns").alias("origin_ns"))


def main(config: B1BuildConfig = DEFAULT_CONFIG) -> None:
    """Run B1Q over all twenty origins and write coverage/failure artifacts."""
    config = _with_authorized_sessions(config)
    config.output_root.mkdir(parents=True, exist_ok=True)
    origins = _load_origins(config)
    fmp_key, massive_key = _secret("FMP_API_KEY"), _secret("MASSIVE_API_KEY")
    rates, dividend_yields = _rates_and_dividends(fmp_key, origins, config)
    contracts = _resolve_contracts(origins, massive_key, config)
    quote_cache_refs, quote_cache_audit = _fetch_quotes(contracts, massive_key, config)
    _load_quote_cache.cache_clear()
    origins = origins.sort(["asset", "session_date", "forecast_origin_utc"])
    rows: list[dict[str, Any]] = []
    attempt_rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for origin in origins.iter_rows(named=True):
        asset, day = str(origin["asset"]), str(origin["session_date"])
        rate_source_date, rate = _rate_observation_for(day, rates)
        dividend_yield = dividend_yields.get((asset, day), 0.0)
        iv_rows: list[dict[str, Any]] = []
        for contract in contracts.get((asset, day), []):
            cache_path, source_hash = quote_cache_refs[(asset, day, contract["contract"])]
            cache = _load_quote_cache(cache_path)
            quote = closure.latest_quote(cache, int(origin["origin_ns"]))
            attempt: dict[str, Any] = {
                **contract,
                "asset": asset,
                "session_date": day,
                "origin_id": origin["origin_id"],
                "forecast_origin_utc": origin["forecast_origin_utc"].isoformat(),
                "forecast_origin_ns": int(origin["origin_ns"]),
                "spot": float(origin["spot"]),
                "moneyness": float(contract["strike"]) / float(origin["spot"]),
                "rate": rate,
                "rate_source_date": rate_source_date,
                "dividend_yield": dividend_yield,
                "dividend_assumption": "PRE_ORIGIN_TRAILING_DECLARATIONS"
                if dividend_yield > 0
                else "NO_PRE_ORIGIN_DIVIDEND_Q_ZERO",
                "source_request_hash": source_hash,
                "iv_success": False,
                "iv": None,
                "failure_reason": "NO_QUOTE_BEFORE_ORIGIN",
            }
            if quote:
                attempt["sip_timestamp"] = quote.get("sip_timestamp")
                attempt["failure_reason"] = quote.get(
                    "missing_reason",
                    "NO_QUOTE_BEFORE_ORIGIN",
                )
            if quote and quote.get("midpoint") is not None:
                attempt.update(
                    {
                        "bid": quote.get("bid"),
                        "ask": quote.get("ask"),
                        "quote_age_seconds": quote.get("quote_age_seconds"),
                        "relative_spread": quote.get("relative_spread"),
                        "midpoint": quote.get("midpoint"),
                    }
                )
                if quote["quote_age_seconds"] > 60:
                    attempt["failure_reason"] = "STALE_QUOTE"
                elif quote["relative_spread"] > 0.25:
                    attempt["failure_reason"] = "INVALID_SPREAD"
                else:
                    result = closure.invert_iv(
                        float(origin["spot"]),
                        float(contract["strike"]),
                        float(contract["dte"]) / 365.0,
                        attempt["rate"],
                        attempt["dividend_yield"],
                        float(quote["midpoint"]),
                        str(contract["option_type"]),
                    )
                    attempt.update(
                        {
                            "iv_success": bool(result["success"]),
                            "iv": result.get("iv"),
                            "failure_reason": result.get("failure_reason"),
                            "iterations": result.get("iterations"),
                            "lower_bound": result.get("lower_bound"),
                            "upper_bound": result.get("upper_bound"),
                        }
                    )
            iv_rows.append(attempt)
        attempt_rows.extend(iv_rows)
        summary = closure.route_summary(iv_rows, route="B1Q")
        atm, skew, term = (
            summary.get("b1q_atm_iv"),
            summary.get("b1q_skew"),
            summary.get("b1q_term_structure") or {},
        )
        pit_evidence = _quote_pit_evidence(iv_rows, int(origin["origin_ns"]))
        row = {
            "origin_id": origin["origin_id"],
            "asset": asset,
            "session_date": day,
            "forecast_origin_utc": origin["forecast_origin_utc"],
            "session_segment": origin["session_segment"],
            "instrument_type": "ETF" if asset in {"SPY", "QQQ"} else "equity",
            "rate": rate,
            "rate_source_date": rate_source_date,
            "dividend_yield": dividend_yield,
            "dividend_assumption": "PRE_ORIGIN_TRAILING_DECLARATIONS"
            if dividend_yield > 0
            else "NO_PRE_ORIGIN_DIVIDEND_Q_ZERO",
            "atm_iv_available": atm is not None,
            "skew_available": skew is not None,
            "term_structure_available": any(value is not None for value in term.values()),
            "b1a_complete": atm is not None,
            "b1b_complete": atm is not None and skew is not None,
            "b1c_complete": atm is not None
            and skew is not None
            and all(
                value is not None
                for value in (
                    term.get("short_to_medium"),
                    term.get("medium_to_long"),
                    term.get("short_to_long"),
                )
            ),
            "b1q_atm_iv": atm,
            "b1q_skew": skew,
            "b1q_term_structure": term,
            "valid_contract_count": summary.get("valid_contract_count", 0),
            "valid_quote_count": summary.get("valid_quote_count", 0),
            "valid_expiry_bucket_count": summary.get("valid_expiry_bucket_count", 0),
            "median_quote_age": summary.get("median_quote_age"),
            "median_relative_spread": summary.get("median_relative_spread"),
            "iv_attempts": len(iv_rows),
            "iv_successes": sum(bool(item.get("iv_success")) for item in iv_rows),
            "iv_inversion_success_rate": sum(bool(item.get("iv_success")) for item in iv_rows)
            / len(iv_rows)
            if iv_rows
            else 0.0,
            "first_failure_code": _first_failure(iv_rows, summary),
            **pit_evidence,
            "route": "B1Q_MASSIVE_PRIMARY",
            "b1t_status": "DIAGNOSTIC_ONLY",
        }
        rows.append(row)
        failures.extend(
            {
                key: item.get(key)
                for key in (
                    "asset",
                    "origin_id",
                    "contract",
                    "option_type",
                    "dte",
                    "moneyness",
                    "rate",
                    "dividend_yield",
                    "sip_timestamp",
                    "midpoint",
                    "quote_age_seconds",
                    "relative_spread",
                    "iv_success",
                    "failure_reason",
                    "iv",
                )
            }
            for item in iv_rows
            if not item.get("iv_success")
        )
    frame = pl.DataFrame(rows, infer_schema_length=None, strict=False)
    _write_parquet_atomic(
        frame,
        config.output_root / "b1_origin_matrix_20d.parquet",
    )
    _write_parquet_atomic(
        pl.DataFrame(
            attempt_rows,
            infer_schema_length=None,
            strict=False,
        ),
        config.output_root / "b1_iv_attempts_20d.parquet",
    )
    frame.group_by("asset").agg(
        [
            pl.len().alias("origins"),
            pl.col("atm_iv_available").mean().alias("atm_iv_component"),
            pl.col("skew_available").mean().alias("skew_component"),
            pl.col("term_structure_available").mean().alias("term_structure_component"),
            pl.col("b1a_complete").mean().alias("b1a"),
            pl.col("b1b_complete").mean().alias("b1b"),
            pl.col("b1c_complete").mean().alias("b1c"),
            pl.col("iv_inversion_success_rate").mean().alias("iv_success_rate"),
        ]
    ).sort("asset").write_csv(config.output_root / "b1_coverage_by_asset.csv")
    frame.group_by("session_segment").agg(
        [
            pl.len().alias("origins"),
            pl.col("atm_iv_available").mean().alias("atm_iv_component"),
            pl.col("skew_available").mean().alias("skew_component"),
            pl.col("term_structure_available").mean().alias("term_structure_component"),
            pl.col("b1a_complete").mean().alias("b1a"),
            pl.col("b1b_complete").mean().alias("b1b"),
            pl.col("b1c_complete").mean().alias("b1c"),
            pl.col("iv_inversion_success_rate").mean().alias("iv_success_rate"),
        ]
    ).sort("session_segment").write_csv(config.output_root / "b1_coverage_by_session_segment.csv")
    global_cov = _coverage(frame)
    by_date = {
        str(row["session_date"]): _coverage(
            frame.filter(pl.col("session_date") == row["session_date"])
        )
        for row in frame.select("session_date").unique().iter_rows(named=True)
    }
    by_route = {"B1Q": global_cov, "B1T": {"status": "DIAGNOSTIC_ONLY", "coverage": None}}
    session_count = frame["session_date"].n_unique()
    summary = {
        **_run_metadata(session_count),
        "session_count": session_count,
        "origins": frame.height,
        "iv_attempt_rows": len(attempt_rows),
        "global": global_cov,
        "by_date": by_date,
        "by_route": by_route,
        "nested_invariants": {
            "b1c_implies_b1b": bool(
                frame.filter(pl.col("b1c_complete") & ~pl.col("b1b_complete")).height == 0
            ),
            "b1b_implies_b1a": bool(
                frame.filter(pl.col("b1b_complete") & ~pl.col("b1a_complete")).height == 0
            ),
            "coverage_b1c_le_b1b": global_cov["b1c"] <= global_cov["b1b"],
            "coverage_b1b_le_b1a": global_cov["b1b"] <= global_cov["b1a"],
        },
        "pit_invariants": {
            "future_quote_rows": frame.filter(
                ~pl.col("b1q_quote_not_after_origin")
                & pl.col("b1q_max_sip_timestamp_ns").is_not_null()
            ).height,
            "b1a_without_pit_evidence": frame.filter(
                pl.col("b1a_complete") & ~pl.col("b1q_pit_evidence_valid")
            ).height,
            "future_rate_source_rows": frame.filter(
                pl.col("rate_source_date") >= pl.col("session_date")
            ).height,
        },
        "quote_cache_audit": quote_cache_audit,
        "contract_resolution_schema": "b1q-contract-grid-3.0",
        "primary_quote_age_seconds": 60,
        "primary_relative_spread": 0.25,
        "b1t_independent": False,
        "modeling": "BLOCKED",
        "qlike": "BLOCKED",
        "secret_values_emitted": False,
    }
    _assert_invariants(frame, summary)
    (config.output_root / "b1_coverage_20d.json").write_text(
        json.dumps(summary, indent=2, default=str), encoding="utf-8"
    )
    pl.DataFrame(failures, infer_schema_length=None, strict=False).write_csv(
        config.output_root / "b1_iv_failures_20d.csv"
    )
    print(
        json.dumps(
            {
                "status": summary["status"],
                "origins": frame.height,
                "global": global_cov,
                "cache_files": len(list(config.cache_root.glob("*.json"))),
                "secret_values_emitted": False,
            }
        )
    )


def _assert_invariants(frame: pl.DataFrame, summary: dict[str, Any]) -> None:
    """Fail closed on nested B1 violations globally and in declared subgroups."""
    if not all(summary["nested_invariants"].values()):
        raise RuntimeError("B1Q_NESTED_INVARIANT_FAILURE")
    if any(summary["pit_invariants"].values()):
        raise RuntimeError("B1Q_PIT_INVARIANT_FAILURE")
    for column in ("asset", "session_date", "session_segment", "instrument_type"):
        for _, group in frame.group_by(column):
            values = _coverage(group)
            if values["b1c"] > values["b1b"] or values["b1b"] > values["b1a"]:
                raise RuntimeError(f"B1Q_NESTED_SUBGROUP_FAILURE:{column}")


if __name__ == "__main__":
    main()
