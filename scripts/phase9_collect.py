"""Phase 9 nightly collector (decision 58 protocol; activation under decision 59).

Collects, for the just-closed XNYS session, the raw inputs the frozen Phase 9
protocol needs — FMP 1-minute bars (6 assets), the UW full-tape day archive,
and a Massive ATM quote sweep at the five-minute origins — into crash-safe
per-session storage with a manifest of SHA-256 hashes. Zero scientific reads:
the access counter stays at 0 until the one-read evaluation after session 60.

Usage:
    uv run python scripts/phase9_collect.py              # just-closed session
    uv run python scripts/phase9_collect.py --dry-run    # bounded rehearsal
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import hashlib
import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import exchange_calendars  # type: ignore[import-untyped]
import httpx
import polars as pl

from mds650.providers.fmp import FMPProvider, parse_minute_payload
from mds650.providers.massive import MassiveProvider

DATA_ROOT = Path(os.environ.get("MDS650_EXTERNAL_ROOT", "D:/MDS650"))
STORE = DATA_ROOT / "phase9"
LOGS = DATA_ROOT / "logs"
ALERT = LOGS / "PHASE9_ALERT.txt"
ASSETS = ("AAPL", "AMZN", "META", "MSFT", "NVDA", "TSLA")
NY = ZoneInfo("America/New_York")
TAPE_URL = "https://api.unusualwhales.com/api/option-trades/full-tape/{date}"
MIN_FREE_GB = 120
# Frozen protocol window (decision 58): the first 60 XNYS sessions STRICTLY after
# 2026-08-18; earlier sessions are outside the campaign and are never collected.
WINDOW_START = dt.date(2026, 8, 19)
MASSIVE_PACING_SECONDS = 13
TARGET_SESSIONS = 60


def _alert(message: str) -> None:
    LOGS.mkdir(parents=True, exist_ok=True)
    with ALERT.open("a", encoding="utf-8") as handle:
        handle.write(f"{dt.datetime.now(dt.UTC).isoformat()} {message}\n")
    with contextlib.suppress(OSError):
        subprocess.run(
            ["msg", "*", f"MDS650 Phase 9: {message}"],
            check=False,
            capture_output=True,
            timeout=10,
        )
    print(f"[phase9] ALERT: {message}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _last_closed_session() -> dt.date | None:
    calendar = exchange_calendars.get_calendar("XNYS")
    probe = dt.datetime.now(NY)
    for _ in range(7):
        day = probe.date()
        if calendar.is_session(day.isoformat()):
            close_ny = dt.datetime.combine(day, dt.time(16, 0), tzinfo=NY)
            if probe > close_ny + dt.timedelta(minutes=30):
                return day
        probe -= dt.timedelta(days=1)
    return None


def _origins_utc(session: dt.date) -> list[dt.datetime]:
    origins = []
    cursor = dt.datetime.combine(session, dt.time(10, 0), tzinfo=NY)
    end = dt.datetime.combine(session, dt.time(15, 30), tzinfo=NY)
    while cursor <= end:
        origins.append(cursor.astimezone(dt.UTC))
        cursor += dt.timedelta(minutes=5)
    return origins


def _collect_bars(session: dt.date, session_dir: Path, api_key: str) -> pl.DataFrame:
    provider = FMPProvider(api_key)
    frames: list[pl.DataFrame] = []
    try:
        for asset in ASSETS:
            response = provider.minute_bars(
                asset, from_date=session.isoformat(), to_date=session.isoformat()
            )
            bars = parse_minute_payload(
                response.payload,
                asset=asset,
                run_id="phase9_collect",
                source_response_id=f"phase9:{asset}:{session}",
                source_timezone="America/New_York",
            )
            if bars:
                frames.append(
                    pl.DataFrame(
                        {
                            "asset": [bar.asset for bar in bars],
                            "bar_start_utc": [bar.bar_start_utc for bar in bars],
                            "open": [bar.open for bar in bars],
                            "high": [bar.high for bar in bars],
                            "low": [bar.low for bar in bars],
                            "close": [bar.close for bar in bars],
                            "volume": [bar.volume for bar in bars],
                        }
                    )
                )
            time.sleep(0.15)
    finally:
        provider.close()
    combined = pl.concat(frames).sort("asset", "bar_start_utc")
    combined.write_parquet(session_dir / "bars.parquet")
    return combined


def _collect_tape(session: dt.date, session_dir: Path, api_key: str) -> Path:
    destination = session_dir / f"full_tape_{session.isoformat()}.zip"
    if destination.exists() and destination.stat().st_size > 1_000_000:
        return destination
    with httpx.Client(timeout=1200, follow_redirects=True) as client, client.stream(
        "GET",
        TAPE_URL.format(date=session.isoformat()),
        headers={"Authorization": f"Bearer {api_key}"},
    ) as response:
        response.raise_for_status()
        tmp = destination.with_suffix(".zip.tmp")
        with tmp.open("wb") as handle:
            for chunk in response.iter_bytes(1 << 20):
                handle.write(chunk)
        tmp.replace(destination)
    return destination


def _spot_at(bars: pl.DataFrame, asset: str, origin_utc: dt.datetime) -> float | None:
    subset = bars.filter(
        (pl.col("asset") == asset) & (pl.col("bar_start_utc") < origin_utc)
    ).sort("bar_start_utc")
    if subset.is_empty():
        return None
    return float(subset["close"][-1])


def _collect_quotes(
    session: dt.date,
    session_dir: Path,
    bars: pl.DataFrame,
    api_key: str,
    *,
    max_origins: int | None = None,
) -> pl.DataFrame:
    provider = MassiveProvider(api_key)
    origins = _origins_utc(session)
    if max_origins is not None:
        origins = origins[:max_origins]
    rows: list[dict[str, Any]] = []
    heartbeat = session_dir / "heartbeat.json"
    try:
        listings: dict[str, list[dict[str, Any]]] = {}
        expiration_gte = (session + dt.timedelta(days=21)).isoformat()
        expiration_lte = (session + dt.timedelta(days=45)).isoformat()
        for asset in ASSETS:
            listing_spot = _spot_at(bars, asset, origins[0]) or 0.0
            response = provider.option_contract_listing(
                asset,
                expiration_gte=expiration_gte,
                expiration_lte=expiration_lte,
                strike_gte=listing_spot * 0.9,
                strike_lte=listing_spot * 1.1,
            )
            payload = response.payload if isinstance(response.payload, dict) else {}
            raw_results = payload.get("results")
            listings[asset] = raw_results if isinstance(raw_results, list) else []
            time.sleep(MASSIVE_PACING_SECONDS)
        for index, origin in enumerate(origins):
            for asset in ASSETS:
                spot = _spot_at(bars, asset, origin)
                candidates = listings.get(asset) or []
                if spot is None or not candidates:
                    rows.append(
                        {"asset": asset, "origin_utc": origin.isoformat(), "status": "NO_INPUT"}
                    )
                    continue
                contract = min(
                    candidates,
                    key=lambda row: abs(float(row.get("strike_price", 0.0)) - spot),
                )
                ticker = str(contract.get("ticker", ""))
                origin_ns = int(origin.timestamp() * 1_000_000_000)
                try:
                    quote = provider.directed_quotes(ticker, forecast_origin_ns=origin_ns)
                    quote_payload = (
                        quote.payload if isinstance(quote.payload, dict) else {}
                    )
                    results = quote_payload.get("results")
                    record = results[0] if isinstance(results, list) and results else {}
                    rows.append(
                        {
                            "asset": asset,
                            "origin_utc": origin.isoformat(),
                            "status": "OK" if record else "EMPTY",
                            "contract": ticker,
                            "strike": float(contract.get("strike_price", 0.0)),
                            "expiry": str(contract.get("expiration_date", "")),
                            "quote": json.dumps(record, default=str),
                        }
                    )
                except Exception as error:  # noqa: BLE001 - one failed quote must not kill the night
                    rows.append(
                        {
                            "asset": asset,
                            "origin_utc": origin.isoformat(),
                            "status": f"ERROR:{error!r}"[:200],
                            "contract": ticker,
                        }
                    )
                time.sleep(MASSIVE_PACING_SECONDS)
            heartbeat.write_text(
                json.dumps(
                    {
                        "utc": dt.datetime.now(dt.UTC).isoformat(),
                        "origin_index": index,
                        "of": len(origins),
                    }
                ),
                encoding="utf-8",
            )
    finally:
        provider.close()
    frame = pl.DataFrame(rows, infer_schema_length=None)
    frame.write_parquet(session_dir / "quotes.parquet")
    return frame


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--session", default=None)
    arguments = parser.parse_args()
    fmp_key = os.environ.get("FMP_API_KEY")
    uw_key = os.environ.get("UNUSUAL_WHALES_API_KEY") or os.environ.get("UNUSUALWHALES_API_KEY")
    massive_key = os.environ.get("MASSIVE_API_KEY")
    if not (fmp_key and uw_key and massive_key):
        _alert("COLLECTOR_CREDENTIALS_MISSING")
        raise SystemExit(1)
    free_gb = shutil.disk_usage(DATA_ROOT).free / (1 << 30)
    if free_gb < MIN_FREE_GB:
        _alert(f"DISK_FREE_BELOW_MINIMUM: {free_gb:.0f}GB < {MIN_FREE_GB}GB")
        raise SystemExit(1)
    session = (
        dt.date.fromisoformat(arguments.session) if arguments.session else _last_closed_session()
    )
    if session is None:
        print("[phase9] no closed XNYS session found; exiting")
        return
    if not arguments.dry_run and session < WINDOW_START:
        print(f"[phase9] session {session} predates the frozen window start {WINDOW_START}")
        return
    root = STORE / ("dryrun" if arguments.dry_run else "raw")
    session_dir = root / session.isoformat()
    manifest_path = session_dir / "session_manifest.json"
    if manifest_path.exists() and not arguments.dry_run:
        print(f"[phase9] session {session} already collected")
        return
    session_dir.mkdir(parents=True, exist_ok=True)
    started = dt.datetime.now(dt.UTC).isoformat()
    bars = _collect_bars(session, session_dir, fmp_key)
    tape = _collect_tape(session, session_dir, uw_key)
    quotes = _collect_quotes(
        session,
        session_dir,
        bars,
        massive_key,
        max_origins=3 if arguments.dry_run else None,
    )
    ok_quotes = quotes.filter(pl.col("status") == "OK").height if "status" in quotes.columns else 0
    manifest = {
        "session": session.isoformat(),
        "dry_run": bool(arguments.dry_run),
        "started_utc": started,
        "finished_utc": dt.datetime.now(dt.UTC).isoformat(),
        "bars_rows": bars.height,
        "tape_bytes": tape.stat().st_size,
        "quote_rows": quotes.height,
        "quote_ok": ok_quotes,
        "sha256": {
            "bars.parquet": _sha256(session_dir / "bars.parquet"),
            tape.name: _sha256(tape),
            "quotes.parquet": _sha256(session_dir / "quotes.parquet"),
        },
    }
    manifest_path.write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    if not arguments.dry_run:
        counter_path = STORE / "counter.json"
        counter: dict[str, Any] = (
            json.loads(counter_path.read_text(encoding="utf-8"))
            if counter_path.exists()
            else {"reads": 0, "sessions": []}
        )
        sessions_list: list[str] = list(counter.get("sessions", []))
        if session.isoformat() not in sessions_list:
            sessions_list.append(session.isoformat())
        counter["sessions"] = sessions_list
        counter_path.write_text(json.dumps(counter, indent=1), encoding="utf-8")
        captured = len(sessions_list)
        print(f"[phase9] session {session} captured ({captured}/{TARGET_SESSIONS})")
        if captured >= TARGET_SESSIONS:
            _alert(f"PHASE9_COLLECTION_COMPLETE: {captured}/{TARGET_SESSIONS} sessions")
        if bars.height < 6 * 380 or ok_quotes == 0:
            _alert(
                f"session {session}: capture shortfall (bars={bars.height}, quotes_ok={ok_quotes})"
            )
    else:
        print(f"[phase9] dry run complete for {session}: manifest at {manifest_path}")


if __name__ == "__main__":
    main()
