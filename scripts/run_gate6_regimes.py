"""Gate 6: regime/event composition table and leave-event-week-out sensitivity.

Maps every campaign's session range to its VIX distribution (FMP end-of-day
^VIX closes), its own realized-variance level, and the named macro events it
contains; then re-estimates the Gamma B2 contrast on the frozen C6 and C5
evaluators with the event weeks removed. Tests the alternative reading of the
decay narrative: "the signal exists only around exceptional macro events and
every calm window is a true null." Re-analysis of frozen artifacts plus one
public index series; no sealed reads.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import polars as pl

from mds650 import inference

REPO = Path(__file__).resolve().parents[1]
DATA_ROOT = Path(os.environ.get("MDS650_EXTERNAL_ROOT", "D:/MDS650"))
EVIDENCE_ROOT = Path(os.environ.get("MDS650_EVIDENCE_ROOT", DATA_ROOT / "evidence_root"))
OUTPUT = REPO / "artifacts" / "gate6_regimes"

GAMMA = "gamma_glm_confirmatory"

NAMED_EVENTS = {
    "2024-08-05": "yen-carry unwind volatility shock (VIX intraday ~65)",
    "2024-09-18": "FOMC first cut of the easing cycle",
    "2024-11-05": "US presidential election",
    "2024-12-18": "FOMC hawkish-cut selloff",
    "2025-06-13": "Middle East escalation risk-off",
    "2026-07-29": "FOMC meeting inside prospective holdout",
}
EVENT_WEEKS = {
    "C6_b1v3": [("2024-11-03", "2024-11-09")],
    "C5_block_a": [("2024-08-03", "2024-08-09")],
    "C5_block_b": [("2024-11-03", "2024-11-09")],
}

CAMPAIGNS: dict[str, dict[str, Any]] = {
    "C1_development": {
        "path": REPO / "artifacts" / "phase5" / "development_forecasts.parquet",
        "model_column": "model_role",
        "model": GAMMA,
        "base": "B1a",
        "expanded": "B2",
    },
    "C2_holdout": {
        "path": EVIDENCE_ROOT / "artifacts" / "phase5" / "holdout_forecasts.parquet",
        "model_column": "model_role",
        "model": GAMMA,
        "base": "B1a",
        "expanded": "B2",
    },
    "C4c_replication": {
        "path": DATA_ROOT
        / "independent_replication_30"
        / "derived"
        / "pit_v2_evaluation"
        / "predictions_pit_v2.parquet",
        "model_column": "model_role",
        "model": GAMMA,
        "base": "B1v2a",
        "expanded": "B2v2",
    },
    "C5_block_a": {
        "path": REPO / "artifacts" / "b2_confirmation" / "frozen_evaluation_forecasts.parquet",
        "model_column": "model_name",
        "model": "gamma_glm",
        "base": "B1a",
        "expanded": "B2",
        "block": "block_a_2024_08_02_2024_09_13",
    },
    "C5_block_b": {
        "path": REPO / "artifacts" / "b2_confirmation" / "frozen_evaluation_forecasts.parquet",
        "model_column": "model_name",
        "model": "gamma_glm",
        "base": "B1a",
        "expanded": "B2",
        "block": "block_b_2024_10_01_2024_11_11",
    },
    "C6_b1v3": {
        "path": DATA_ROOT / "b1v3_confirmation" / "evaluation" / "primary_forecasts.parquet",
        "model_column": "model_role",
        "model": GAMMA,
        "base": "B1v3a",
        "expanded": "B2",
    },
}


def _vix_closes(from_date: str, to_date: str, api_key: str) -> dict[str, float]:
    url = "https://financialmodelingprep.com/stable/historical-price-eod/full"
    with httpx.Client(timeout=60) as client:
        response = client.get(
            url,
            params={"symbol": "^VIX", "from": from_date, "to": to_date, "apikey": api_key},
        )
        response.raise_for_status()
        payload = response.json()
    rows = payload if isinstance(payload, list) else payload.get("historical", [])
    return {
        str(row["date"]): float(row["close"])
        for row in rows
        if isinstance(row, dict) and "date" in row and "close" in row
    }


def _stats_block(values: np.ndarray) -> dict[str, Any]:
    return {
        "cluster_t": inference.cluster_t_test(values),
        "newey_west": inference.newey_west_t_test(values),
        "wild_rademacher": inference.wild_cluster_bootstrap(values),
        "days": int(values.size),
    }


def main() -> None:
    api_key = os.environ.get("FMP_API_KEY")
    if not api_key:
        raise SystemExit("GATE6_FMP_KEY_MISSING")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    results: dict[str, Any] = {
        "schema_version": "gate6-regimes-v1.0",
        "named_events": NAMED_EVENTS,
        "campaigns": {},
        "leave_event_week_out": {},
    }
    for name, spec in CAMPAIGNS.items():
        frame = pl.read_parquet(Path(spec["path"]))
        if "timing_variant" in frame.columns:
            frame = frame.filter(pl.col("timing_variant") == "PRIMARY")
        if "block" in spec:
            frame = frame.filter(pl.col("block_id") == spec["block"])
        sessions = sorted(str(value) for value in frame["session_date"].unique().to_list())
        vix = _vix_closes(sessions[0], sessions[-1], api_key)
        vix_values = [vix[session] for session in sessions if session in vix]
        daily_rv = (
            frame.group_by("session_date")
            .agg(pl.col("rv30").mean())
            .sort("session_date")["rv30"]
            .to_numpy()
        )
        results["campaigns"][name] = {
            "first_session": sessions[0],
            "last_session": sessions[-1],
            "sessions": len(sessions),
            "vix_median": float(np.median(vix_values)) if vix_values else None,
            "vix_p90": float(np.quantile(vix_values, 0.9)) if vix_values else None,
            "vix_max": float(np.max(vix_values)) if vix_values else None,
            "mean_daily_rv30": float(daily_rv.mean()),
            "events_inside_window": {
                day: label
                for day, label in NAMED_EVENTS.items()
                if sessions[0] <= day <= sessions[-1]
            },
        }
        daily = inference.paired_daily_differences(
            frame,
            base_set=str(spec["base"]),
            expanded_set=str(spec["expanded"]),
            model=str(spec["model"]),
            model_column=str(spec["model_column"]),
        )
        if name in EVENT_WEEKS:
            full_values = daily["mean_difference"].to_numpy()
            kept = daily
            for start, end in EVENT_WEEKS[name]:
                kept = kept.filter(
                    ~pl.col("session_date")
                    .cast(pl.Utf8)
                    .is_between(pl.lit(start), pl.lit(end))
                )
            results["leave_event_week_out"][name] = {
                "event_weeks_dropped": EVENT_WEEKS[name],
                "sessions_dropped": int(daily.height - kept.height),
                "full_sample": _stats_block(full_values),
                "without_event_weeks": _stats_block(kept["mean_difference"].to_numpy()),
            }
    payload = json.dumps(results, indent=1, sort_keys=True, default=str)
    (OUTPUT / "results.json").write_text(payload, encoding="utf-8")
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    (OUTPUT / "results.sha256").write_text(digest + "\n", encoding="utf-8")
    print(f"[gate6] wrote {OUTPUT / 'results.json'} sha256={digest[:16]}")


if __name__ == "__main__":
    main()
