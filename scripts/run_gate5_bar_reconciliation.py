"""Gate 5.1: cross-provider 1-minute bar reconciliation (FMP vs Massive).

For ten stratified sessions spanning the C5 (2024), C4 (mid-2025) and C6
evaluation windows plus the 2026 development era, downloads the same
one-minute bars from FMP and from the Polygon-compatible Massive aggregates
endpoint, aligns closes under both label conventions (identical labels vs FMP
shifted +1 minute), and reports which convention minimizes disagreement.
This turns registered assumption A001 (FMP bar-label semantics) into a
measured quantity with an independent second source. Artifact under
``artifacts/gate5_pit/``; raw responses are not persisted (closes only).
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from mds650.providers.fmp import FMPProvider, parse_minute_payload
from mds650.providers.massive import MassiveProvider

REPO = Path(__file__).resolve().parents[1]
OUTPUT = REPO / "artifacts" / "gate5_pit"
ASSETS = ("AAPL", "AMZN", "META", "MSFT", "NVDA", "TSLA")
SESSIONS = (
    "2024-08-06",
    "2024-09-10",
    "2024-10-15",
    "2024-11-06",
    "2024-12-03",
    "2025-05-28",
    "2025-06-17",
    "2025-07-01",
    "2026-04-15",
    "2026-07-10",
)


def _fmp_closes(provider: FMPProvider, asset: str, session: str) -> pl.DataFrame:
    response = provider.minute_bars(asset, from_date=session, to_date=session)
    bars = parse_minute_payload(
        response.payload,
        asset=asset,
        run_id="gate5_bar_reconciliation",
        source_response_id=f"gate5:fmp:{asset}:{session}",
        source_timezone="America/New_York",
    )
    return pl.DataFrame(
        {
            "bar_start_utc": [bar.bar_start_utc for bar in bars],
            "fmp_close": [bar.close for bar in bars],
        }
    )


def _massive_closes(provider: MassiveProvider, asset: str, session: str) -> pl.DataFrame:
    try:
        response = provider.stock_minute_aggregates(asset, from_date=session, to_date=session)
    except Exception:  # noqa: BLE001 - single bounded retry after the per-minute window resets
        time.sleep(65)
        response = provider.stock_minute_aggregates(asset, from_date=session, to_date=session)
    payload = response.payload if isinstance(response.payload, dict) else {}
    results = payload.get("results")
    if not isinstance(results, list):
        raise ValueError(f"GATE5_MASSIVE_SHAPE:{asset}:{session}")
    frame = pl.DataFrame(
        {
            "epoch_ms": [int(row["t"]) for row in results if isinstance(row, dict)],
            "massive_close": [float(row["c"]) for row in results if isinstance(row, dict)],
        }
    )
    return frame.with_columns(
        pl.from_epoch(pl.col("epoch_ms"), time_unit="ms")
        .dt.replace_time_zone("UTC")
        .alias("bar_start_utc")
    ).drop("epoch_ms")


def _compare(fmp: pl.DataFrame, massive: pl.DataFrame) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name, shift in (("same_label", 0), ("fmp_plus_1m", 1)):
        shifted = fmp.with_columns(pl.col("bar_start_utc").dt.offset_by(f"{shift}m"))
        joined = shifted.join(massive, on="bar_start_utc", how="inner")
        if joined.is_empty():
            out[name] = {"matched": 0}
            continue
        relative = (
            (joined["fmp_close"] - joined["massive_close"]).abs()
            / joined["massive_close"]
        ).to_numpy()
        out[name] = {
            "matched": joined.height,
            "median_rel_close_diff": float(np.median(relative)),
            "max_rel_close_diff": float(relative.max()),
            "exact_equal_share": float((relative == 0.0).mean()),
        }
    return out


def main() -> None:
    fmp_key = os.environ.get("FMP_API_KEY")
    massive_key = os.environ.get("MASSIVE_API_KEY")
    if not fmp_key or not massive_key:
        raise SystemExit("GATE5_PROVIDER_KEYS_MISSING")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    fmp = FMPProvider(fmp_key)
    massive = MassiveProvider(massive_key)
    per_cell: dict[str, Any] = {}
    try:
        for session in SESSIONS:
            for asset in ASSETS:
                try:
                    comparison = _compare(
                        _fmp_closes(fmp, asset, session),
                        _massive_closes(massive, asset, session),
                    )
                except Exception as error:  # noqa: BLE001 - keep the sweep going, report per cell
                    comparison = {"error": repr(error)}
                per_cell[f"{session}|{asset}"] = comparison
                # ponytail: Massive's tier allows ~5 requests/minute; 13s keeps us under.
                time.sleep(13)
            print(f"[gate5.1] {session} done")
    finally:
        fmp.close()
        massive.close()
    same = [
        cell["same_label"]["median_rel_close_diff"]
        for cell in per_cell.values()
        if isinstance(cell.get("same_label"), dict) and cell["same_label"].get("matched")
    ]
    shifted = [
        cell["fmp_plus_1m"]["median_rel_close_diff"]
        for cell in per_cell.values()
        if isinstance(cell.get("fmp_plus_1m"), dict) and cell["fmp_plus_1m"].get("matched")
    ]
    winner = (
        "same_label"
        if same and (not shifted or float(np.median(same)) <= float(np.median(shifted)))
        else "fmp_plus_1m"
    )
    results = {
        "schema_version": "gate5-bar-reconciliation-v1.0",
        "sessions": list(SESSIONS),
        "assets": list(ASSETS),
        "cells": per_cell,
        "median_of_median_rel_diff": {
            "same_label": float(np.median(same)) if same else None,
            "fmp_plus_1m": float(np.median(shifted)) if shifted else None,
        },
        "winning_convention": winner,
    }
    payload = json.dumps(results, indent=1, sort_keys=True)
    (OUTPUT / "bar_reconciliation.json").write_text(payload, encoding="utf-8")
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    (OUTPUT / "bar_reconciliation.sha256").write_text(digest + "\n", encoding="utf-8")
    print(f"[gate5.1] winner={winner} medians={results['median_of_median_rel_diff']}")
    print(f"[gate5.1] wrote {OUTPUT / 'bar_reconciliation.json'} sha256={digest[:16]}")


if __name__ == "__main__":
    main()
