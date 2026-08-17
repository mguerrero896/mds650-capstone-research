"""Gate 5.2: +7-day reconciliation of live UW observations vs historical tape.

For every collected session at least ``RECONCILE_AFTER_DAYS`` old and not yet
reconciled, downloads the historical full tape for that session, joins it to
the live intraday observations, and publishes: (a) the receipt-minus-created_at
latency distribution per asset and NY hour, (b) the backfill upper bound (tape
rows never observed live — the flow channel is a filtered subset, so this is an
upper bound, stated as such), and (c) the revision rate (matched rows whose
shared fields differ). Alerts loudly on download failure.
"""

from __future__ import annotations

import datetime as dt
import io
import json
import os
import zipfile
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import numpy as np
import polars as pl

DATA_ROOT = Path(os.environ.get("MDS650_EXTERNAL_ROOT", "D:/MDS650"))
STORE = DATA_ROOT / "uw_latency" / "sessions"
LOGS = DATA_ROOT / "logs"
ASSETS = ("AAPL", "AMZN", "META", "MSFT", "NVDA", "TSLA")
NY = ZoneInfo("America/New_York")
RECONCILE_AFTER_DAYS = 7
TAPE_URL = "https://api.unusualwhales.com/api/option-trades/full-tape/{date}"


def _alert(message: str) -> None:
    LOGS.mkdir(parents=True, exist_ok=True)
    with (LOGS / "UW_LATENCY_ALERT.txt").open("a", encoding="utf-8") as handle:
        handle.write(f"{dt.datetime.now(dt.UTC).isoformat()} {message}\n")
    print(f"[uw-reconcile] ALERT: {message}")


def _fingerprint(row: dict[str, Any]) -> str:
    parts = [
        str(row.get("underlying_symbol") or row.get("ticker_symbol") or row.get("ticker") or ""),
        str(row.get("executed_at") or row.get("tape_time") or row.get("start_time") or ""),
        str(row.get("strike") or ""),
        str(row.get("expiry") or ""),
        str(row.get("premium") or row.get("total_premium") or ""),
    ]
    return "|".join(parts)


def _download_tape(session: dt.date, api_key: str, destination: Path) -> Path:
    url = TAPE_URL.format(date=session.isoformat())
    with httpx.Client(timeout=600) as client:
        response = client.get(url, headers={"Authorization": f"Bearer {api_key}"})
        response.raise_for_status()
        destination.write_bytes(response.content)
    return destination


def _tape_rows(zip_path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with zipfile.ZipFile(zip_path) as archive:
        for name in archive.namelist():
            with archive.open(name) as handle:
                text = io.TextIOWrapper(handle, encoding="utf-8")
                first = text.read(1)
                text.seek(0)
                if first == "[":
                    rows.extend(json.load(text))
                else:
                    for line in text:
                        line = line.strip()
                        if line:
                            rows.append(json.loads(line))
    return [
        row
        for row in rows
        if isinstance(row, dict)
        and str(row.get("underlying_symbol") or row.get("ticker_symbol") or "") in ASSETS
    ]


def _reconcile(session: dt.date, api_key: str) -> None:
    session_dir = STORE / session.isoformat()
    observations_path = session_dir / "observations.jsonl"
    if not observations_path.exists():
        _alert(f"session {session}: no observations to reconcile")
        return
    live: dict[str, dict[str, Any]] = {}
    with observations_path.open(encoding="utf-8") as handle:
        for line in handle:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("kind") != "observation":
                continue
            record = row.get("record") or {}
            live[_fingerprint(record)] = {
                "receipt_utc": row.get("receipt_utc"),
                "record": record,
            }
    zip_path = session_dir / f"historical_tape_{session.isoformat()}.zip"
    if not zip_path.exists():
        try:
            _download_tape(session, api_key, zip_path)
        except httpx.HTTPError as error:
            _alert(f"session {session}: tape download failed: {error!r}")
            return
    tape = _tape_rows(zip_path)
    matched = 0
    revised = 0
    latencies: list[dict[str, Any]] = []
    for row in tape:
        key = _fingerprint(row)
        observed = live.get(key)
        if observed is None:
            continue
        matched += 1
        created = row.get("created_at")
        receipt = observed.get("receipt_utc")
        if isinstance(created, str) and isinstance(receipt, str):
            try:
                created_utc = dt.datetime.fromisoformat(created.replace("Z", "+00:00"))
                receipt_utc = dt.datetime.fromisoformat(receipt)
                latencies.append(
                    {
                        "asset": str(row.get("underlying_symbol") or row.get("ticker_symbol")),
                        "ny_hour": created_utc.astimezone(NY).hour,
                        "latency_seconds": (receipt_utc - created_utc).total_seconds(),
                    }
                )
            except ValueError:
                pass
        shared = {"strike", "expiry", "premium"} & set(row) & set(observed["record"])
        if any(str(row[field]) != str(observed["record"][field]) for field in shared):
            revised += 1
    summary: dict[str, Any] = {
        "session": session.isoformat(),
        "reconciled_utc": dt.datetime.now(dt.UTC).isoformat(),
        "tape_rows_outcome_assets": len(tape),
        "live_observations": len(live),
        "matched": matched,
        "backfill_upper_bound_rate": (len(tape) - matched) / len(tape) if tape else None,
        "revision_rate_among_matched": revised / matched if matched else None,
        "note": (
            "flow-alerts is a filtered channel; unmatched tape rows are an UPPER bound "
            "on backfill, not a point estimate"
        ),
    }
    if latencies:
        frame = pl.DataFrame(latencies)
        latency_values = frame["latency_seconds"].to_numpy()
        summary["latency_seconds_quantiles"] = {
            str(quantile): float(np.quantile(latency_values, quantile))
            for quantile in (0.1, 0.5, 0.9, 0.99)
        }
        summary["latency_by_asset_median"] = {
            str(asset[0]): float(np.median(group["latency_seconds"].to_numpy()))
            for asset, group in frame.group_by("asset")
        }
    (session_dir / "reconciliation.json").write_text(
        json.dumps(summary, indent=1), encoding="utf-8"
    )
    print(f"[uw-reconcile] {session}: matched {matched}/{len(tape)} tape rows; report written")


def main() -> None:
    api_key = os.environ.get("UNUSUAL_WHALES_API_KEY") or os.environ.get("UNUSUALWHALES_API_KEY")
    if not api_key:
        _alert("RECONCILE_CREDENTIALS_MISSING")
        raise SystemExit(1)
    if not STORE.exists():
        print("[uw-reconcile] no sessions collected yet")
        return
    today = dt.datetime.now(NY).date()
    for session_dir in sorted(STORE.iterdir()):
        if not session_dir.is_dir():
            continue
        session = dt.date.fromisoformat(session_dir.name)
        age = (today - session).days
        if age >= RECONCILE_AFTER_DAYS and not (session_dir / "reconciliation.json").exists():
            _reconcile(session, api_key)


if __name__ == "__main__":
    main()
