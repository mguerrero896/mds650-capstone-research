"""Build the bounded five-session real pilot; never runs backfill or models."""

# The manifest-building expressions mirror the provider contract and are kept
# together for audit readability; line length is intentionally exempted.
# ruff: noqa: E501

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import os
import zipfile
from collections import Counter, defaultdict
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import polars as pl
import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from mds650.contracts import CANDIDATE_ASSETS
from mds650.targets import compute_realized_variance

ASSETS = tuple(sorted(CANDIDATE_ASSETS))
DATES = tuple(date(2026, 7, d) for d in range(13, 18))
ET = ZoneInfo("America/New_York")
UTC_SESSION_OPEN = time(13, 30)
UTC_SESSION_CLOSE = time(20, 0)
RAW_ROOT = Path("artifacts/raw/full_tape")
OUT = Path("artifacts/pilot")

EVENT_FIELDS = [
    "id", "underlying_symbol", "option_chain_id", "executed_at", "created_at",
    "nbbo_bid", "nbbo_ask", "price", "size", "premium", "volume",
    "open_interest", "implied_volatility", "expiry", "strike", "option_type",
    "report_flags", "tags", "ask_vol", "bid_vol", "no_side_vol", "mid_vol",
    "multi_vol", "exchange", "upstream_condition_detail",
]
EVENT_SCHEMA = pa.schema([
    pa.field("id", pa.string()), pa.field("underlying_symbol", pa.string()),
    pa.field("option_chain_id", pa.string()), pa.field("executed_at", pa.timestamp("us", tz="UTC")),
    pa.field("created_at", pa.timestamp("us", tz="UTC")), pa.field("nbbo_bid", pa.float64()),
    pa.field("nbbo_ask", pa.float64()), pa.field("price", pa.float64()), pa.field("size", pa.float64()),
    pa.field("premium", pa.float64()), pa.field("volume", pa.int64()), pa.field("open_interest", pa.int64()),
    pa.field("implied_volatility", pa.float64()), pa.field("expiry", pa.date32()), pa.field("strike", pa.float64()),
    pa.field("option_type", pa.string()), pa.field("report_flags", pa.string()), pa.field("tags", pa.string()),
    pa.field("ask_vol", pa.int64()), pa.field("bid_vol", pa.int64()), pa.field("no_side_vol", pa.int64()),
    pa.field("mid_vol", pa.int64()), pa.field("multi_vol", pa.int64()), pa.field("exchange", pa.string()),
    pa.field("upstream_condition_detail", pa.string()),
])


def _secret(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"MISSING_SECRET:{name}")
    return value


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _fmp_raw_dt(value: str) -> datetime:
    """Parse FMP's offset-free bar label conservatively as New York local time."""
    normalized = value.replace(" ", "T")
    if normalized.endswith("Z") or "+" in normalized[10:] or "-" in normalized[10:]:
        return _dt(normalized)
    return datetime.fromisoformat(normalized).replace(tzinfo=ET).astimezone(UTC)


def _regular(value: datetime) -> bool:
    local = value.astimezone(ET)
    return local.weekday() < 5 and time(9, 30) <= local.time() < time(16, 0)


def _float(value: str) -> float | None:
    try:
        return float(value) if value != "" else None
    except ValueError:
        return None


def _sha256_file(path: Path) -> str:
    """Hash a file incrementally so the pilot never loads a raw archive in memory."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _int(value: str) -> int | None:
    try:
        return int(float(value)) if value != "" else None
    except ValueError:
        return None


def _event_row(row: dict[str, str]) -> dict[str, Any]:
    executed = _dt(row["executed_at"])
    created = _dt(row["created_at"])
    expiry = date.fromisoformat(row["expiry"]) if row.get("expiry") else None
    return {
        "id": row["id"], "underlying_symbol": row["underlying_symbol"],
        "option_chain_id": row["option_chain_id"], "executed_at": executed,
        "created_at": created, "nbbo_bid": _float(row["nbbo_bid"]),
        "nbbo_ask": _float(row["nbbo_ask"]), "price": _float(row["price"]),
        "size": _float(row["size"]), "premium": _float(row["premium"]),
        "volume": _int(row["volume"]), "open_interest": _int(row["open_interest"]),
        "implied_volatility": _float(row["implied_volatility"]), "expiry": expiry,
        "strike": _float(row["strike"]), "option_type": row["option_type"],
        "report_flags": row["report_flags"], "tags": row["tags"],
        "ask_vol": _int(row["ask_vol"]), "bid_vol": _int(row["bid_vol"]),
        "no_side_vol": _int(row["no_side_vol"]), "mid_vol": _int(row["mid_vol"]),
        "multi_vol": _int(row["multi_vol"]), "exchange": row["exchange"],
        "upstream_condition_detail": row["upstream_condition_detail"],
    }


def filter_full_tape(day: date) -> dict[str, Any]:
    """Stream one ZIP, retain regular-session rows for the eight candidates."""
    source = RAW_ROOT / day.isoformat() / f"full_tape_{day.isoformat()}.zip"
    target = OUT / "option_events" / f"date={day.isoformat()}" / "events.parquet"
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        retained = pl.scan_parquet(target).group_by("underlying_symbol").len().collect()
        existing_counts = {row["underlying_symbol"]: row["len"] for row in retained.to_dicts()}
        return {"date": day.isoformat(), "raw_bytes": source.stat().st_size, "raw_sha256": _sha256_file(source),
                "rows_seen": None, "rows_retained": sum(existing_counts.values()),
                "retained_by_asset": dict(sorted(existing_counts.items())), "parquet": str(target), "reused_existing": True}
    counts: Counter[str] = Counter()
    rows_seen = 0
    writer: pq.ParquetWriter | None = None
    batch: list[dict[str, Any]] = []
    with zipfile.ZipFile(source) as archive, archive.open(archive.namelist()[0]) as raw:
        reader = csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8", newline=""))
        if set(EVENT_FIELDS) - set(reader.fieldnames or []):
            raise RuntimeError("FULL_TAPE_SCHEMA_DRIFT")
        for row in reader:
            rows_seen += 1
            if row.get("underlying_symbol") not in ASSETS:
                continue
            executed = _dt(row["executed_at"])
            if not _regular(executed):
                continue
            batch.append(_event_row(row))
            counts[row["underlying_symbol"]] += 1
            if len(batch) >= 50_000:
                table = pa.Table.from_pylist(batch, schema=EVENT_SCHEMA)
                writer = writer or pq.ParquetWriter(target, EVENT_SCHEMA, compression="zstd")
                writer.write_table(table)
                batch.clear()
    if batch:
        writer = writer or pq.ParquetWriter(target, EVENT_SCHEMA, compression="zstd")
        writer.write_table(pa.Table.from_pylist(batch, schema=EVENT_SCHEMA))
    if writer:
        writer.close()
    digest = _sha256_file(source)
    return {"date": day.isoformat(), "raw_bytes": source.stat().st_size, "raw_sha256": digest,
            "rows_seen": rows_seen, "rows_retained": sum(counts.values()),
            "retained_by_asset": dict(sorted(counts.items())), "parquet": str(target)}


def fetch_fmp_bars(client: httpx.Client) -> list[dict[str, Any]]:
    """Fetch five sessions of FMP one-minute bars and apply the conservative availability rule."""
    existing = OUT / "underlying_1min.parquet"
    if existing.exists():
        return pl.read_parquet(existing).to_dicts()
    rows: list[dict[str, Any]] = []
    for asset in ASSETS:
        for day in DATES:
            response = client.get(
                "https://financialmodelingprep.com/stable/historical-chart/1min",
                params={"symbol": asset, "from": day.isoformat(), "to": (day + timedelta(days=1)).isoformat(), "apikey": _secret("FMP_API_KEY")},
                timeout=60,
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, list):
                raise RuntimeError(f"FMP_SCHEMA_DRIFT:{asset}:{day}")
            for item in payload:
                raw_value = str(item["date"])
                if raw_value[:10] != day.isoformat():
                    continue
                raw = _fmp_raw_dt(raw_value)
                rows.append({"asset": asset, "session_date": day.isoformat(), "bar_timestamp_raw_utc": raw,
                             "bar_timestamp_ny": raw.astimezone(ET), "available_at_utc": raw + timedelta(minutes=1),
                             "open": float(item["open"]), "high": float(item["high"]), "low": float(item["low"]),
                             "close": float(item["close"]), "volume": int(item["volume"])})
    frame = pl.DataFrame(rows).sort(["asset", "bar_timestamp_raw_utc"])
    path = OUT / "underlying_1min.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.write_parquet(path)
    return rows


def build_origins_and_b0(bars: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Create five-minute origins, B0 controls, and exact RV30 targets."""
    by_asset: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in bars:
        by_asset[row["asset"]].append(row)
    origins: list[dict[str, Any]] = []
    targets: list[dict[str, Any]] = []
    for asset, values in by_asset.items():
        values.sort(key=lambda x: x["bar_timestamp_raw_utc"])
        index = {x["bar_timestamp_raw_utc"]: x for x in values}
        for day in DATES:
            start = datetime.combine(day, time(9, 35), tzinfo=ET)
            for step in range(0, 72):
                origin_ny = start + timedelta(minutes=5 * step)
                if origin_ny.time() > time(15, 25):
                    break
                origin = origin_ny.astimezone(UTC)
                anchor_time = origin - timedelta(minutes=1)
                anchor = index.get(anchor_time)
                future = [index.get(anchor_time + timedelta(minutes=i)) for i in range(1, 31)]
                if anchor is None or any(x is None for x in future):
                    continue
                closes = [x["close"] for x in future if x is not None]
                rv = compute_realized_variance(anchor["close"], closes)
                prior = [x for x in values if x["bar_timestamp_raw_utc"] <= anchor_time]
                returns = [math.log(prior[i]["close"] / prior[i - 1]["close"]) for i in range(1, len(prior))]
                b0 = {"origin_id": f"{asset}:{origin.isoformat()}", "asset": asset, "session_date": day.isoformat(),
                      "forecast_origin_utc": origin, "forecast_origin_ny": origin.astimezone(ET),
                      "anchor_timestamp_raw_utc": anchor_time, "spot": anchor["close"],
                      "rv_5m_lag": sum(x * x for x in returns[-5:]), "rv_30m_lag": sum(x * x for x in returns[-30:]),
                      "return_5m_lag": sum(returns[-5:]), "volume_5m_lag": sum(x["volume"] for x in prior[-5:]),
                      "session_minute": (origin.astimezone(ET).hour - 9) * 60 + origin.astimezone(ET).minute - 30,
                      "target_rv30": rv, "target_future_close_count": 30, "target_price_count": 31,
                      "target_validity": "valid"}
                origins.append(b0)
                targets.append({"origin_id": b0["origin_id"], "asset": asset, "forecast_origin_utc": origin,
                                "rv30": rv, "future_close_count": 30, "price_count": 31,
                                "future_close_start_utc": anchor_time + timedelta(minutes=1),
                                "future_close_end_utc": anchor_time + timedelta(minutes=30)})
    pl.DataFrame(origins).write_parquet(OUT / "b0_features.parquet")
    pl.DataFrame(targets).write_parquet(OUT / "rv30_targets.parquet")
    return origins, targets


def build_b2(origins: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Build Level-1 B2 features with a bounded lazy/columnar event pass."""
    specs = {"primary_60s": 60, "sensitivity_15s": 15, "sensitivity_0s": 0}
    origin_key = pl.DataFrame(
        [{"origin_id": x["origin_id"], "underlying_symbol": x["asset"],
          "forecast_origin_utc": x["forecast_origin_utc"], "spot": x["spot"]} for x in origins]
    )
    event_paths = sorted((OUT / "option_events").glob("date=*/events.parquet"))
    if not event_paths:
        raise RuntimeError("PILOT_EVENT_PARQUETS_MISSING")
    events = pl.concat([pl.scan_parquet(path) for path in event_paths], how="diagonal")
    # The five-minute origin is the first grid point at or after execution. Joining
    # before aggregation avoids materialising millions of raw trades in Python.
    events = events.with_columns(pl.col("executed_at").dt.truncate("5m").alias("_grid_floor"))
    events = events.with_columns(
        pl.when(pl.col("executed_at") == pl.col("_grid_floor"))
        .then(pl.col("_grid_floor"))
        .otherwise(pl.col("_grid_floor") + pl.duration(minutes=5))
        .alias("forecast_origin_utc")
    ).drop("_grid_floor")
    events = events.join(origin_key.lazy(), on=["underlying_symbol", "forecast_origin_utc"], how="inner")
    frames: list[pl.DataFrame] = []
    for spec, lag in specs.items():
        eligible = events.filter(pl.col("created_at") <= pl.col("forecast_origin_utc") - pl.duration(seconds=lag))
        summary = eligible.group_by(["origin_id", "underlying_symbol", "forecast_origin_utc", "spot"]).agg([
            pl.len().alias("trade_count_5m"), pl.col("option_chain_id").n_unique().alias("unique_contracts_5m"),
            pl.col("premium").fill_null(0).sum().alias("total_premium_5m"),
            pl.col("premium").max().fill_null(0).alias("max_premium_5m"),
            pl.col("size").fill_null(0).sum().alias("total_size_5m"),
            pl.col("size").max().fill_null(0).alias("max_size_5m"),
            pl.when(pl.col("option_type").str.to_lowercase() == "call").then(pl.col("premium").fill_null(0)).otherwise(0).sum().alias("call_premium_5m"),
            pl.when(pl.col("option_type").str.to_lowercase() == "put").then(pl.col("premium").fill_null(0)).otherwise(0).sum().alias("put_premium_5m"),
            pl.when(pl.col("tags").fill_null("").str.contains("ask_side")).then(pl.col("premium").fill_null(0)).otherwise(0).sum().alias("ask_premium"),
            pl.when(pl.col("tags").fill_null("").str.contains("bid_side")).then(pl.col("premium").fill_null(0)).otherwise(0).sum().alias("bid_premium"),
            pl.when(pl.col("tags").fill_null("").str.contains("multileg")).then(1).otherwise(0).mean().alias("multileg_share"),
            pl.when(pl.col("tags").fill_null("").str.contains("sweep")).then(1).otherwise(0).mean().alias("sweep_or_equivalent_share"),
            pl.col("strike").truediv(pl.col("spot")).median().alias("median_moneyness"),
            (pl.len() - pl.col("option_chain_id").n_unique()).alias("repeated_contract_burst_count"),
        ]).collect(engine="streaming")
        frame = origin_key.join(summary, on=["origin_id", "underlying_symbol", "forecast_origin_utc", "spot"], how="left").with_columns([
            pl.lit(spec).alias("availability_spec"), pl.col("trade_count_5m").fill_null(0),
            pl.col("unique_contracts_5m").fill_null(0), pl.col("total_premium_5m").fill_null(0),
            pl.col("max_premium_5m").fill_null(0), pl.col("total_size_5m").fill_null(0),
            pl.col("max_size_5m").fill_null(0), pl.col("call_premium_5m").fill_null(0),
            pl.col("put_premium_5m").fill_null(0), pl.col("ask_premium").fill_null(0),
            pl.col("bid_premium").fill_null(0), pl.col("multileg_share").fill_null(0),
            pl.col("sweep_or_equivalent_share").fill_null(0), pl.col("repeated_contract_burst_count").fill_null(0),
            pl.col("median_moneyness"),
        ]).with_columns([
            (pl.col("call_premium_5m") - pl.col("put_premium_5m")).alias("call_put_premium_imbalance"),
            pl.when(pl.col("total_premium_5m") > 0).then(pl.col("ask_premium") / pl.col("total_premium_5m")).otherwise(0).alias("ask_side_premium_share"),
            pl.when(pl.col("total_premium_5m") > 0).then(pl.col("bid_premium") / pl.col("total_premium_5m")).otherwise(0).alias("bid_side_premium_share"),
            pl.col("trade_count_5m").gt(0).alias("event_present"), pl.col("total_size_5m").alias("volume_cumulative_internal"),
        ]).drop(["ask_premium", "bid_premium", "spot"])
        frames.append(frame)
    frame = pl.concat(frames, how="vertical").sort(["underlying_symbol", "forecast_origin_utc", "availability_spec"]) if frames else pl.DataFrame()
    frame = frame.rename({"underlying_symbol": "asset"})
    frame.write_parquet(OUT / "b2_features.parquet")
    primary = frame.filter(pl.col("availability_spec") == "primary_60s")
    coverage = {"rows": frame.height, "primary_origins": primary.height,
                "primary_event_origins": primary.filter(pl.col("event_present")).height,
                "primary_no_event_origins": primary.filter(~pl.col("event_present")).height,
                "natural_event_prevalence": primary["event_present"].mean() if primary.height else None,
                "availability_specs": specs, "volume_final_daily_excluded": True,
                "primary_cutoff": "created_at <= origin - 60 seconds"}
    (OUT / "b2_feature_coverage.json").write_text(json.dumps(coverage, indent=2), encoding="utf-8")
    return frame.to_dicts(), coverage


def main() -> None:
    """Run the bounded pilot and emit sanitized manifests/profile tables."""
    OUT.mkdir(parents=True, exist_ok=True)
    filters = [filter_full_tape(day) for day in DATES]
    with httpx.Client(timeout=60) as client:
        bars = fetch_fmp_bars(client)
    origins, targets = build_origins_and_b0(bars)
    _, b2 = build_b2(origins)
    manifest = {"pilot_id": "pilot_20260713_20260717", "sessions": [d.isoformat() for d in DATES],
                "candidate_assets": list(ASSETS), "raw_full_tape": filters,
                "origin_count": len(origins), "rv30_target_count": len(targets),
                "target_contract": "anchor close + 30 future one-minute closes = 31 prices / 30 returns",
                "b2": b2, "b1_status": "PROVISIONAL_PENDING_ORIGIN_COVERAGE",
                "asset_freeze": "BLOCKED", "backfill": "BLOCKED", "modeling": "BLOCKED",
                "final_test": "BLOCKED", "synthetic_data_used": False, "secret_values_emitted": False}
    (OUT / "pilot_manifest.json").write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")
    profile = {"pilot_id": manifest["pilot_id"], "raw_days": len(filters),
               "raw_gb": sum(x["raw_bytes"] for x in filters) / 1e9,
               "filtered_rows": sum(x["rows_retained"] for x in filters),
               "retention_rate": (sum(x["rows_retained"] for x in filters) / sum(x["rows_seen"] for x in filters)
                                  if all(x["rows_seen"] is not None for x in filters) else None),
               "origins": len(origins), "rv30_valid": len(targets), "b2": b2,
               "b0": {"features": ["rv_5m_lag", "rv_30m_lag", "return_5m_lag", "volume_5m_lag", "session_minute"]},
               "pit": {"b2_primary": "created_at <= origin - 60 seconds", "fmp_available_at": "timestamp_raw + 1 minute"},
               "predictive_evaluation": "NOT_RUN"}
    (OUT / "pilot_profile.json").write_text(json.dumps(profile, indent=2, default=str), encoding="utf-8")
    rows = "".join(f"<tr><td>{k}</td><td>{v}</td></tr>" for k, v in profile.items())
    (OUT / "pilot_profile.html").write_text(f"<html><body><h1>{manifest['pilot_id']}</h1><table>{rows}</table></body></html>", encoding="utf-8")
    print(json.dumps({"pilot_id": manifest["pilot_id"], "raw_days": len(filters), "filtered_rows": profile["filtered_rows"], "origins": len(origins), "rv30_valid": len(targets), "backfill": "BLOCKED", "modeling": "BLOCKED"}))


if __name__ == "__main__":
    main()
