"""Build the twenty-session B2 calibration panel and apply it to Pilot V2.

The calibration fit is deliberately target-free: all location, scale and percentile
parameters are estimated from the twenty sessions before Pilot V2 and are then applied
unchanged to the five Pilot V2 sessions.
"""
# ruff: noqa: E501

from __future__ import annotations

import hashlib
import json
import math
import os
import statistics
import time as time_module
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import polars as pl
from phase4b_common import WINDOW_SPECS

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts" / "calibration_20d"
EVENT_ROOT = OUT / "option_events"
ASSETS = ("SPY", "QQQ", "AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "META")
PILOT_DATES = tuple(date(2026, 7, day) for day in range(13, 18))
SESSIONS = (
    date(2026, 6, 11),
    date(2026, 6, 12),
    date(2026, 6, 15),
    date(2026, 6, 16),
    date(2026, 6, 17),
    date(2026, 6, 18),
    date(2026, 6, 22),
    date(2026, 6, 23),
    date(2026, 6, 24),
    date(2026, 6, 25),
    date(2026, 6, 26),
    date(2026, 6, 29),
    date(2026, 6, 30),
    date(2026, 7, 1),
    date(2026, 7, 2),
    date(2026, 7, 6),
    date(2026, 7, 7),
    date(2026, 7, 8),
    date(2026, 7, 9),
    date(2026, 7, 10),
)
NY = ZoneInfo("America/New_York")
SPECS = WINDOW_SPECS
FEATURES = (
    "option_trade_count_5m",
    "unique_contract_count_5m",
    "total_premium_5m",
    "max_trade_premium_5m",
    "total_contract_size_5m",
    "max_contract_size_5m",
    "call_premium_5m",
    "put_premium_5m",
    "call_put_premium_imbalance",
    "ask_side_premium_share",
    "bid_side_premium_share",
    "midpoint_premium_share",
    "multileg_trade_share",
    "sweep_or_equivalent_share",
    "strike_concentration",
    "expiry_concentration",
    "median_days_to_expiry",
    "median_absolute_moneyness",
    "repeated_contract_trade_count",
    "repeated_contract_premium",
    "implied_volatility_median",
    "within_bin_iv_change",
    "valid_trade_share",
    "missing_iv_share",
)
CORE_FEATURES = (
    "total_premium_5m",
    "option_trade_count_5m",
    "unique_contract_count_5m",
    "max_trade_premium_5m",
    "repeated_contract_premium",
)


@dataclass(frozen=True)
class B2BuildConfig:
    """Explicit roots and session allow-list for one B2 build."""

    output_root: Path
    event_root: Path
    download_manifest: Path
    sessions: tuple[date, ...]

    def __post_init__(self) -> None:
        if not self.sessions or tuple(sorted(set(self.sessions))) != self.sessions:
            raise ValueError("B2_SESSION_ALLOWLIST_INVALID")


DEFAULT_CONFIG = B2BuildConfig(
    output_root=OUT,
    event_root=EVENT_ROOT,
    download_manifest=OUT / "download_manifest.json",
    sessions=SESSIONS,
)


def _secret(name: str) -> str:
    """Return an environment secret without exposing its value."""
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"MISSING_SECRET:{name}")
    return value


def _dt(value: str) -> datetime:
    """Parse an ISO or FMP timestamp to aware UTC."""
    normalized = value.replace(" ", "T")
    if normalized.endswith("Z") or "+" in normalized[10:]:
        parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    else:
        parsed = datetime.fromisoformat(normalized).replace(tzinfo=NY)
    return parsed.astimezone(UTC)


def _atomic_json(path: Path, payload: Any) -> None:
    """Write JSON in a deterministic, atomic fashion."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8"
    )
    temporary.replace(path)


def _request_hash(params: dict[str, str]) -> str:
    """Hash sanitized provider parameters without including a secret."""
    return hashlib.sha256(json.dumps(params, sort_keys=True).encode()).hexdigest()


def _fetch_fmp_bars(config: B2BuildConfig = DEFAULT_CONFIG) -> pl.DataFrame:
    """Fetch exact-session one-minute FMP bars for the twenty sessions.

    Returns
    -------
    polars.DataFrame
        Exact-session OHLCV rows with UTC/New York timestamps and conservative availability.

    Raises
    ------
    RuntimeError
        If a response schema/status is invalid or no exact-session rows are returned.
    """
    destination = config.output_root / "underlying_1min_20d.parquet"
    manifest_path = config.output_root / "fmp_20d_manifest.json"
    if destination.exists() and manifest_path.exists():
        return pl.read_parquet(destination)
    key = _secret("FMP_API_KEY")
    rows: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
    with httpx.Client(timeout=90.0, follow_redirects=True) as client:
        for asset in ASSETS:
            for day in config.sessions:
                params = {
                    "symbol": asset,
                    "from": day.isoformat(),
                    "to": (day + timedelta(days=1)).isoformat(),
                }
                response = client.get(
                    "https://financialmodelingprep.com/stable/historical-chart/1min",
                    params={**params, "apikey": key},
                )
                payload = response.json() if response.status_code == 200 else None
                if response.status_code != 200 or not isinstance(payload, list):
                    raise RuntimeError(
                        f"FMP_20D_HTTP_OR_SCHEMA:{asset}:{day}:{response.status_code}"
                    )
                returned_dates = sorted(
                    {str(item.get("date", ""))[:10] for item in payload if isinstance(item, dict)}
                )
                exact = [
                    item
                    for item in payload
                    if isinstance(item, dict) and str(item.get("date", ""))[:10] == day.isoformat()
                ]
                records.append(
                    {
                        "asset": asset,
                        "session_date": day.isoformat(),
                        "http_status": response.status_code,
                        "requested_date": day.isoformat(),
                        "returned_dates": returned_dates,
                        "provider_over_return": any(
                            value != day.isoformat() for value in returned_dates
                        ),
                        "rows_exact": len(exact),
                        "request_hash": _request_hash(params),
                        "payload_sha256": hashlib.sha256(response.content).hexdigest(),
                    }
                )
                if not exact:
                    raise RuntimeError(f"FMP_20D_EXACT_SESSION_EMPTY:{asset}:{day}")
                for item in exact:
                    raw = _dt(str(item["date"]))
                    rows.append(
                        {
                            "asset": asset,
                            "session_date": day.isoformat(),
                            "bar_timestamp_raw_utc": raw,
                            "bar_timestamp_ny": raw.astimezone(NY),
                            "available_at_utc": raw + timedelta(minutes=1),
                            "open": float(item["open"]),
                            "high": float(item["high"]),
                            "low": float(item["low"]),
                            "close": float(item["close"]),
                            "volume": float(item["volume"]),
                        }
                    )
    frame = pl.DataFrame(rows).sort(["asset", "bar_timestamp_raw_utc"])
    frame.write_parquet(destination, compression="zstd")
    _atomic_json(
        manifest_path,
        {
            "status": "PASS",
            "records": records,
            "fmp_bar_availability": "CONSERVATIVE_RESEARCH_ASSUMPTION",
            "secret_values_emitted": False,
        },
    )
    return frame


def _segment(session_minute: int) -> str:
    """Assign first/middle/last session tercile by elapsed regular-session minutes."""
    return "first" if session_minute < 130 else "middle" if session_minute < 260 else "last"


def _build_origins(
    bars: pl.DataFrame,
    config: B2BuildConfig = DEFAULT_CONFIG,
) -> pl.DataFrame:
    """Build valid five-minute origins and conservative spot values for each session."""
    rows: list[dict[str, Any]] = []
    for asset in ASSETS:
        values = bars.filter(pl.col("asset") == asset).sort("bar_timestamp_raw_utc").to_dicts()
        index = {row["bar_timestamp_raw_utc"]: row for row in values}
        for day in config.sessions:
            for minute in range(5, 356, 5):
                local = datetime.combine(day, time(9, 30), tzinfo=NY) + timedelta(minutes=minute)
                origin = local.astimezone(UTC)
                anchor_time = origin - timedelta(minutes=1)
                anchor = index.get(anchor_time)
                if anchor is None:
                    continue
                rows.append(
                    {
                        "origin_id": f"{asset}:{origin.isoformat()}",
                        "asset": asset,
                        "session_date": day.isoformat(),
                        "forecast_origin_utc": origin,
                        "forecast_origin_ny": local,
                        "anchor_timestamp_raw_utc": anchor_time,
                        "spot": float(anchor["close"]),
                        "session_minute": minute,
                        "session_segment": _segment(minute),
                        "time_band_30m": f"B30_{minute // 30:02d}",
                        "fmp_bar_availability": "CONSERVATIVE_RESEARCH_ASSUMPTION",
                    }
                )
    frame = pl.DataFrame(rows).sort(["asset", "forecast_origin_utc"])
    if frame.is_empty():
        raise RuntimeError("CALIBRATION_ORIGINS_EMPTY")
    frame.write_parquet(
        config.output_root / "b2_calibration_origins.parquet",
        compression="zstd",
    )
    return frame


def _event_paths(config: B2BuildConfig = DEFAULT_CONFIG) -> list[tuple[Path, str, str]]:
    """Return downloaded event partitions and their source hashes."""
    manifest = json.loads(config.download_manifest.read_text(encoding="utf-8"))
    if manifest.get("status") != "PASS" or manifest.get("session_count") != len(
        config.sessions
    ):
        raise RuntimeError("CALIBRATION_DOWNLOAD_NOT_COMPLETE")
    hashes = {row["session_date"]: row["sha256"] for row in manifest["sessions"]}
    paths: list[tuple[Path, str, str]] = []
    for path in sorted(config.event_root.glob("date=*/asset=*/events.parquet")):
        day = path.parts[-3].split("=", 1)[1]
        paths.append((path, day, hashes[day]))
    if not paths:
        raise RuntimeError("CALIBRATION_EVENT_PARQUETS_MISSING")
    return paths


def _build_feature_frame(
    origins: pl.DataFrame,
    config: B2BuildConfig = DEFAULT_CONFIG,
) -> pl.DataFrame:
    """Aggregate continuous B2 features for all origins and three PIT cutoffs."""
    selected = [
        "id",
        "underlying_symbol",
        "option_chain_id",
        "executed_at",
        "created_at",
        "nbbo_bid",
        "nbbo_ask",
        "price",
        "size",
        "premium",
        "expiry",
        "strike",
        "option_type",
        "tags",
        "implied_volatility",
        "session_date",
        "source_hash",
    ]
    frames: list[pl.LazyFrame] = []
    for path, day, source_hash in _event_paths(config):
        frames.append(
            pl.scan_parquet(path)
            .select(selected[:-2])
            .with_columns(
                [pl.lit(day).alias("session_date"), pl.lit(source_hash).alias("source_hash")]
            )
        )
    events = pl.concat(frames, how="vertical")
    origins_key = origins.select(
        ["origin_id", "asset", "forecast_origin_utc", "spot", "session_date"]
    )
    output: list[pl.DataFrame] = []
    for _spec, lag in SPECS.items():
        eligible = (
            events.with_columns(
                (
                    (pl.col("executed_at") + pl.duration(seconds=lag)).dt.truncate("5m")
                    + pl.duration(minutes=5)
                ).alias("_candidate_origin")
            )
            .join(
                origins_key.lazy(),
                left_on=["underlying_symbol", "_candidate_origin", "session_date"],
                right_on=["asset", "forecast_origin_utc", "session_date"],
                how="inner",
            )
            .with_columns(pl.col("_candidate_origin").alias("forecast_origin_utc"))
            .filter(
                (pl.col("executed_at") >= pl.col("forecast_origin_utc") - pl.duration(seconds=lag) - pl.duration(minutes=5))
                & (pl.col("executed_at") < pl.col("forecast_origin_utc") - pl.duration(seconds=lag))
                & (pl.max_horizontal("executed_at", "created_at") <= pl.col("forecast_origin_utc") - pl.duration(seconds=lag))
            )
        )
        counts = (
            eligible.group_by(["origin_id", "underlying_symbol", "forecast_origin_utc", "spot"])
            .agg(
                [
                    pl.len().alias("option_trade_count_5m"),
                    pl.col("option_chain_id").n_unique().alias("unique_contract_count_5m"),
                    pl.col("premium").fill_null(0).sum().alias("total_premium_5m"),
                    pl.col("premium").max().fill_null(0).alias("max_trade_premium_5m"),
                    pl.col("size").fill_null(0).sum().alias("total_contract_size_5m"),
                    pl.col("size").max().fill_null(0).alias("max_contract_size_5m"),
                    pl.when(pl.col("option_type").str.to_lowercase() == "call")
                    .then(pl.col("premium").fill_null(0))
                    .otherwise(0)
                    .sum()
                    .alias("call_premium_5m"),
                    pl.when(pl.col("option_type").str.to_lowercase() == "put")
                    .then(pl.col("premium").fill_null(0))
                    .otherwise(0)
                    .sum()
                    .alias("put_premium_5m"),
                    pl.when(pl.col("tags").fill_null("").str.contains("ask_side"))
                    .then(pl.col("premium").fill_null(0))
                    .otherwise(0)
                    .sum()
                    .alias("_ask_premium"),
                    pl.when(pl.col("tags").fill_null("").str.contains("bid_side"))
                    .then(pl.col("premium").fill_null(0))
                    .otherwise(0)
                    .sum()
                    .alias("_bid_premium"),
                    pl.when(
                        (pl.col("nbbo_bid") > 0)
                        & (pl.col("nbbo_ask") > pl.col("nbbo_bid"))
                        & pl.col("price").is_not_null()
                    )
                    .then(pl.col("premium").fill_null(0))
                    .otherwise(0)
                    .sum()
                    .alias("_midpoint_premium"),
                    pl.when(pl.col("tags").fill_null("").str.contains("multileg"))
                    .then(1)
                    .otherwise(0)
                    .mean()
                    .alias("multileg_trade_share"),
                    pl.when(pl.col("tags").fill_null("").str.contains("sweep"))
                    .then(1)
                    .otherwise(0)
                    .mean()
                    .alias("sweep_or_equivalent_share"),
                    pl.col("implied_volatility").median().alias("implied_volatility_median"),
                    pl.col("implied_volatility").is_not_null().sum().alias("valid_iv_observation_count"),
                    (pl.col("implied_volatility").max() - pl.col("implied_volatility").min()).alias(
                        "within_bin_iv_change"
                    ),
                    pl.when(pl.col("price").is_not_null() & pl.col("premium").is_not_null())
                    .then(1)
                    .otherwise(0)
                    .mean()
                    .alias("valid_trade_share"),
                    pl.col("implied_volatility").is_null().mean().alias("missing_iv_share"),
                    (pl.col("strike") / pl.col("spot") - 1)
                    .abs()
                    .median()
                    .alias("median_absolute_moneyness"),
                    (
                        pl.col("expiry").cast(pl.Int32)
                        - pl.col("forecast_origin_utc").dt.date().cast(pl.Int32)
                    )
                    .median()
                    .alias("median_days_to_expiry"),
                ]
            )
            .collect(engine="streaming")
        )
        repeated = (
            eligible.group_by(["origin_id", "option_chain_id"])
            .agg([pl.len().alias("_n"), pl.col("premium").fill_null(0).sum().alias("_p")])
            .filter(pl.col("_n") > 1)
            .group_by("origin_id")
            .agg(
                [
                    pl.col("_n").sum().alias("repeated_contract_trade_count"),
                    pl.col("_p").sum().alias("repeated_contract_premium"),
                ]
            )
            .collect(engine="streaming")
        )
        strikes = (
            eligible.filter(pl.col("strike").is_not_null())
            .group_by(["origin_id", "strike"])
            .len()
            .group_by("origin_id")
            .agg((pl.col("len").max() / pl.col("len").sum()).alias("strike_concentration"))
            .collect(engine="streaming")
        )
        expiries = (
            eligible.filter(pl.col("expiry").is_not_null())
            .group_by(["origin_id", "expiry"])
            .len()
            .group_by("origin_id")
            .agg((pl.col("len").max() / pl.col("len").sum()).alias("expiry_concentration"))
            .collect(engine="streaming")
        )
        frame = (
            origins.join(
                counts.rename({"underlying_symbol": "asset"}),
                on=["origin_id", "asset", "forecast_origin_utc", "spot"],
                how="left",
            )
            .join(repeated, on="origin_id", how="left")
            .join(strikes, on="origin_id", how="left")
            .join(expiries, on="origin_id", how="left")
        )
        frame = (
            frame.with_columns(
                [
                    pl.lit(_spec).alias("availability_spec"),
                    pl.col("option_trade_count_5m").fill_null(0),
                    pl.col("unique_contract_count_5m").fill_null(0),
                    pl.col("total_premium_5m").fill_null(0),
                    pl.col("max_trade_premium_5m").fill_null(0),
                    pl.col("total_contract_size_5m").fill_null(0),
                    pl.col("max_contract_size_5m").fill_null(0),
                    pl.col("call_premium_5m").fill_null(0),
                    pl.col("put_premium_5m").fill_null(0),
                    pl.col("_ask_premium").fill_null(0),
                    pl.col("_bid_premium").fill_null(0),
                    pl.col("_midpoint_premium").fill_null(0),
                    pl.col("multileg_trade_share").fill_null(0),
                    pl.col("sweep_or_equivalent_share").fill_null(0),
                    pl.col("repeated_contract_trade_count").fill_null(0),
                    pl.col("repeated_contract_premium").fill_null(0),
                    pl.col("strike_concentration").fill_null(0),
                    pl.col("expiry_concentration").fill_null(0),
                    pl.when(pl.col("valid_iv_observation_count").fill_null(0) >= 2)
                    .then(pl.col("within_bin_iv_change"))
                    .otherwise(None)
                    .alias("within_bin_iv_change"),
                    pl.col("median_days_to_expiry").fill_null(0),
                    pl.col("median_absolute_moneyness").fill_null(0),
                    pl.col("valid_trade_share").fill_null(0),
                    pl.col("missing_iv_share").fill_null(1),
                    pl.col("option_trade_count_5m").gt(0).alias("option_activity_present"),
                    pl.lit("NOT_CALIBRATED").alias("unusual_event_status"),
                    pl.lit("operational_availability_proxy").alias("availability_semantics"),
                ]
            )
            .with_columns(
                [
                    (pl.col("call_premium_5m") - pl.col("put_premium_5m")).alias(
                        "call_put_premium_imbalance"
                    ),
                    pl.when(pl.col("total_premium_5m") > 0)
                    .then(pl.col("_ask_premium") / pl.col("total_premium_5m"))
                    .otherwise(0)
                    .alias("ask_side_premium_share"),
                    pl.when(pl.col("total_premium_5m") > 0)
                    .then(pl.col("_bid_premium") / pl.col("total_premium_5m"))
                    .otherwise(0)
                    .alias("bid_side_premium_share"),
                    pl.when(pl.col("total_premium_5m") > 0)
                    .then(pl.col("_midpoint_premium") / pl.col("total_premium_5m"))
                    .otherwise(0)
                    .alias("midpoint_premium_share"),
                ]
            )
            .drop(["_ask_premium", "_bid_premium", "_midpoint_premium", "spot"])
        )
        output.append(frame)
    result = pl.concat(output, how="vertical").sort(
        ["asset", "forecast_origin_utc", "availability_spec"]
    )
    result.write_parquet(
        config.output_root / "b2_calibration_panel.parquet",
        compression="zstd",
    )
    return result


def _median_mad(values: list[float]) -> tuple[float, float, float, str]:
    """Return median, robust scale, raw MAD and fallback label."""
    if not values:
        return 0.0, 1.0, 0.0, "empty_constant"
    median = statistics.median(values)
    mad = statistics.median([abs(value - median) for value in values])
    if mad > 0:
        return median, 1.4826 * mad, mad, "mad"
    quartiles = (
        statistics.quantiles(values, n=4, method="inclusive")
        if len(values) >= 2
        else [median, median, median]
    )
    iqr = quartiles[2] - quartiles[0]
    if iqr > 0:
        return median, iqr / 1.349, mad, "iqr_fallback"
    return median, 1.0, mad, "asset_constant_fallback"


def _empirical_quantile(values: list[float], percentile: float) -> float:
    """Return a deterministic linearly interpolated empirical quantile."""
    if not values:
        return 0.0
    if not 0.0 <= percentile <= 1.0:
        raise ValueError("percentile must be between 0 and 1")
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] + weight * (ordered[upper] - ordered[lower])


def _band_key(asset: str, local: datetime, mode: str = "30m") -> str:
    """Build an asset/time-band calibration key."""
    minute = (local.hour * 60 + local.minute) - (9 * 60 + 30)
    if mode == "asset":
        band = "ALL"
    elif mode == "5m":
        band = f"B05_{minute:03d}"
    elif mode == "60m":
        band = f"B60_{minute // 60:02d}"
    else:
        band = f"B30_{minute // 30:02d}"
    return f"{asset}|{band}"


def _score_row(row: dict[str, Any], params: dict[str, Any], mode: str = "30m") -> dict[str, Any]:
    """Apply frozen robust parameters to one feature row."""
    local = row["forecast_origin_utc"].astimezone(NY)
    key = _band_key(row["asset"], local, mode)
    selected = params.get(key) or params.get(f"{row['asset']}|ALL")
    if selected is None:
        return {
            "calibration_key": key,
            "historical_sample_size": 0,
            "fallback_used": "missing_asset_band",
            "unusual_intensity_score": 0.0,
            "unusual_event": False,
        }
    zscores: list[float] = []
    for feature in CORE_FEATURES:
        value = math.log1p(max(float(row.get(feature) or 0.0), 0.0))
        info = selected["features"][feature]
        zscores.append((value - info["median"]) / info["scale"] if info["scale"] else 0.0)
    positives = sorted((value for value in zscores if value > 0), reverse=True)[:3]
    score = statistics.median(positives) if positives else 0.0
    return {
        "calibration_key": key,
        "historical_sample_size": selected["sample_size"],
        "fallback_used": ";".join(
            sorted({info["fallback"] for info in selected["features"].values()})
        ),
        "unusual_intensity_score": score,
        "unusual_event": score >= selected["p95_threshold"],
    }


def _fit_parameters(
    panel: pl.DataFrame,
    mode: str = "30m",
    percentile: float = 0.95,
    config: B2BuildConfig = DEFAULT_CONFIG,
) -> dict[str, Any]:
    """Fit target-free robust parameters for one banding/threshold configuration."""
    primary = panel.filter(pl.col("availability_spec") == "primary_60s")
    rows = primary.to_dicts()
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        local = row["forecast_origin_utc"].astimezone(NY)
        grouped.setdefault(_band_key(row["asset"], local, mode), []).append(row)
    params: dict[str, Any] = {}
    for key, group in grouped.items():
        feature_params: dict[str, Any] = {}
        for feature in CORE_FEATURES:
            values = [math.log1p(max(float(row.get(feature) or 0.0), 0.0)) for row in group]
            median, scale, mad, fallback = _median_mad(values)
            feature_params[feature] = {
                "median": median,
                "scale": scale,
                "mad": mad,
                "fallback": fallback,
            }
        scored = [
            _score_row(
                row,
                {
                    key: {
                        "features": feature_params,
                        "sample_size": len(group),
                        "p95_threshold": 0.0,
                    }
                },
                mode,
            )["unusual_intensity_score"]
            for row in group
        ]
        params[key] = {
            "asset": key.split("|", 1)[0],
            "band": key.split("|", 1)[1],
            "sample_size": len(group),
            "features": feature_params,
            "p95_threshold": _empirical_quantile(scored, percentile),
            "percentile": percentile,
            "calibration_window_start": min(config.sessions).isoformat(),
            "calibration_window_end": max(config.sessions).isoformat(),
        }
    return params


def _calibration_source_hash(config: B2BuildConfig = DEFAULT_CONFIG) -> str:
    """Return a deterministic bundle hash for the authorized calibration ZIPs."""
    payload = json.loads(config.download_manifest.read_text(encoding="utf-8"))
    hashes = sorted(
        str(row.get("sha256", "")) for row in payload.get("sessions", [])
    )
    if len(hashes) != len(config.sessions) or any(len(value) != 64 for value in hashes):
        raise RuntimeError("CALIBRATION_SOURCE_HASHES_INVALID")
    return hashlib.sha256("|".join(hashes).encode("ascii")).hexdigest()


def _apply_and_emit(
    panel: pl.DataFrame,
    parameters: dict[str, Any],
    origins: pl.DataFrame,
    config: B2BuildConfig = DEFAULT_CONFIG,
) -> None:
    """Emit distributions, sensitivities and the frozen-parameter Pilot V2 application."""
    primary = panel.filter(pl.col("availability_spec") == "primary_60s")
    scored = [dict(row, **_score_row(row, parameters)) for row in primary.to_dicts()]
    score_frame = pl.DataFrame(scored)
    score_frame.group_by("asset").agg(
        [
            pl.len().alias("origins"),
            pl.col("unusual_intensity_score").median().alias("median"),
            pl.col("unusual_intensity_score").quantile(0.90).alias("p90"),
            pl.col("unusual_intensity_score").quantile(0.95).alias("p95"),
            pl.col("unusual_intensity_score").quantile(0.975).alias("p975"),
            pl.col("unusual_intensity_score").max().alias("max"),
        ]
    ).sort("asset").write_csv(config.output_root / "unusual_score_distribution.csv")
    panel.group_by(["asset", "availability_spec"]).agg(
        [
            pl.len().alias("rows"),
            *[pl.col(feature).median().alias(f"{feature}_median") for feature in FEATURES],
            *[pl.col(feature).quantile(0.95).alias(f"{feature}_p95") for feature in FEATURES],
        ]
    ).sort(["asset", "availability_spec"]).write_csv(
        config.output_root / "b2_feature_distributions.csv"
    )
    prevalence = score_frame.group_by("asset").agg(
        [
            pl.len().alias("origins"),
            pl.col("unusual_event").mean().alias("unusual_event_prevalence"),
            pl.col("option_activity_present").mean().alias("option_activity_prevalence"),
        ]
    )
    prevalence.write_csv(config.output_root / "unusual_event_prevalence.csv")
    pilot_path = ROOT / "artifacts" / "pilot_v2" / "b2_features_v2.parquet"
    pilot = pl.read_parquet(pilot_path).filter(pl.col("availability_spec") == "primary_60s")
    pilot_scores = [dict(row, **_score_row(row, parameters)) for row in pilot.to_dicts()]
    calibration_source_hash = _calibration_source_hash(config)
    pl.DataFrame(pilot_scores).with_columns(
        [
            pl.lit("CALIBRATED_SECONDARY_EXPLORATORY").alias(
                "unusual_event_status"
            ),
            pl.lit(calibration_source_hash).alias("calibration_source_hash"),
            pl.lit("artifacts/calibration_20d/download_manifest.json").alias(
                "calibration_source_manifest"
            ),
            pl.lit(min(config.sessions).isoformat()).alias("calibration_window_start"),
            pl.lit(max(config.sessions).isoformat()).alias("calibration_window_end"),
            pl.lit("created_at <= origin - 60 seconds").alias("pit_cutoff"),
            pl.lit(False).alias("rv30_used_for_calibration"),
        ]
    ).write_parquet(
        config.output_root / "pilot_v2_unusual_scores.parquet",
        compression="zstd",
    )
    sensitivity_rows: list[dict[str, Any]] = []
    for mode in ("asset", "5m", "30m", "60m"):
        params = _fit_parameters(panel, mode=mode, percentile=0.95, config=config)
        for cutoff in SPECS:
            subset = panel.filter(pl.col("availability_spec") == cutoff)
            values = [_score_row(row, params, mode)["unusual_event"] for row in subset.to_dicts()]
            sensitivity_rows.append(
                {
                    "definition": mode,
                    "cutoff": cutoff,
                    "percentile": 0.95,
                    "origins": len(values),
                    "unusual_event_prevalence": statistics.mean(values) if values else None,
                }
            )
    for percentile in (0.90, 0.95, 0.975):
        params = _fit_parameters(panel, mode="30m", percentile=percentile, config=config)
        values = [_score_row(row, params)["unusual_event"] for row in primary.to_dicts()]
        sensitivity_rows.append(
            {
                "definition": "30m",
                "cutoff": "primary_60s",
                "percentile": percentile,
                "origins": len(values),
                "unusual_event_prevalence": statistics.mean(values) if values else None,
            }
        )
    pl.DataFrame(sensitivity_rows).write_csv(
        config.output_root / "b2_sensitivity_comparison.csv"
    )


def main(config: B2BuildConfig = DEFAULT_CONFIG) -> None:
    """Build the twenty-session B2 panel, robust calibration and Pilot V2 scores."""
    config.output_root.mkdir(parents=True, exist_ok=True)
    started = time_module.perf_counter()
    stage_started = time_module.perf_counter()
    bars = _fetch_fmp_bars(config)
    fmp_seconds = time_module.perf_counter() - stage_started
    stage_started = time_module.perf_counter()
    origins = _build_origins(bars, config)
    origins_seconds = time_module.perf_counter() - stage_started
    stage_started = time_module.perf_counter()
    panel = _build_feature_frame(origins, config)
    panel_seconds = time_module.perf_counter() - stage_started
    stage_started = time_module.perf_counter()
    parameters = _fit_parameters(panel, config=config)
    fit_seconds = time_module.perf_counter() - stage_started
    _atomic_json(
        config.output_root / "b2_calibration_parameters.json",
        {
            "status": "PASS",
            "primary_cutoff": "created_at <= origin - 60 seconds",
            "sensitivity_cutoffs": SPECS,
            "band": "asset and 30-minute New York band",
            "core_features": [f"log1p({feature})" for feature in CORE_FEATURES],
            "score": "median of the three largest positive robust z-scores",
            "threshold": "historical 95th percentile by asset and band",
            "calibration_sessions": [day.isoformat() for day in config.sessions],
            "pilot_sessions": [day.isoformat() for day in PILOT_DATES],
            "parameter_count": len(parameters),
            "parameters": parameters,
            "rv30_used_for_calibration": False,
            "natural_prevalence": True,
        },
    )
    stage_started = time_module.perf_counter()
    _apply_and_emit(panel, parameters, origins, config)
    apply_seconds = time_module.perf_counter() - stage_started
    _atomic_json(
        config.output_root / "b2_calibration_telemetry.json",
        {
            "status": "PASS",
            "fmp_fetch_seconds": fmp_seconds,
            "origin_build_seconds": origins_seconds,
            "feature_aggregation_seconds": panel_seconds,
            "parameter_fit_seconds": fit_seconds,
            "pilot_application_and_reports_seconds": apply_seconds,
            "total_seconds": time_module.perf_counter() - started,
            "calibration_sessions": [day.isoformat() for day in config.sessions],
            "aggregation_measurement": "feature aggregation is measured around the bounded Polars build; no provider calls occur during calibration",
            "secret_values_emitted": False,
            "personal_paths_emitted": False,
            "larger_backfill": "BLOCKED",
            "modeling": "BLOCKED",
            "qlike": "BLOCKED",
        },
    )
    print(
        json.dumps(
            {
                "status": "PASS",
                "origins": origins.height,
                "panel_rows": panel.height,
                "parameter_groups": len(parameters),
                "elapsed_seconds": time_module.perf_counter() - started,
                "modeling": "BLOCKED",
                "qlike": "BLOCKED",
                "secret_values_emitted": False,
            }
        )
    )


if __name__ == "__main__":
    main()
