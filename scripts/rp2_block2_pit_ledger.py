"""Block 2 - build the receipt-latency / backfill / revisions ledger.

Streams every frozen ``D`` and ``V`` tape partition, measures provider ingestion latency
``created_at - executed_at``, and pools the distribution in log bins.  Also reads the live
receipt campaign (``uw_latency``) to measure ``local_received_at - provider_created_at``
for records that arrived *after* the collector started, excluding the initial window
backlog which would otherwise masquerade as latency.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import numpy.typing as npt
import polars as pl

from mds650.b1v3_confirmation import canonical_sha256
from mds650.rp2.partition import (
    DEFAULT_DATA_ROOT,
    TAPE_SOURCES,
    SessionFile,
    discover_sessions,
)
from mds650.rp2.pit_ledger import (
    BACKFILL_THRESHOLD_SECONDS,
    LatencySample,
    empty_sample,
    pooled_quantile,
    recommended_cutoff_seconds,
    stability_verdict,
    summarise_latencies,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "artifacts" / "rp2_block2_pit"
LIVE_CAMPAIGN = Path("D:/MDS650/uw_latency/sessions")
QUANTILES = (0.5, 0.9, 0.95, 0.99, 0.999)


def _read_partition(item: SessionFile) -> tuple[str, LatencySample]:
    frame = pl.read_parquet(item.path, columns=["id", "executed_at", "created_at"])
    delta = (frame["created_at"] - frame["executed_at"]).dt.total_microseconds().to_numpy()
    latency = np.asarray(delta, dtype=np.float64) / 1e6
    executed_dates = frame["executed_at"].dt.date().to_numpy()
    cross_session = int(np.count_nonzero(executed_dates != item.session_date))
    duplicates = int(frame.height - frame["id"].n_unique())
    sample = summarise_latencies(
        latency, duplicate_id_rows=duplicates, cross_session_rows=cross_session
    )
    return item.session_date.isoformat(), sample


def _quantile_block(histogram: npt.NDArray[np.int64]) -> dict[str, float]:
    return {f"p{q * 100:g}": pooled_quantile(histogram, q) for q in QUANTILES}


def _describe(sample: LatencySample) -> dict[str, object]:
    rows = sample.rows
    return {
        "rows": rows,
        "quantiles_seconds": _quantile_block(sample.histogram),
        "mean_seconds": sample.total_seconds / rows if rows else float("nan"),
        "min_seconds": sample.minimum_seconds,
        "max_seconds": sample.maximum_seconds,
        "non_positive_rows": sample.non_positive,
        "non_positive_share": sample.non_positive / rows if rows else float("nan"),
        "backfill_rows": sample.over_backfill_threshold,
        "backfill_share": sample.over_backfill_threshold / rows if rows else float("nan"),
        "backfill_threshold_seconds": BACKFILL_THRESHOLD_SECONDS,
        "duplicate_id_rows": sample.duplicate_id_rows,
        "revision_share": sample.duplicate_id_rows / rows if rows else float("nan"),
        "cross_session_rows": sample.cross_session_rows,
        "cross_session_share": sample.cross_session_rows / rows if rows else float("nan"),
    }


def _p95_of(stats: dict[str, object]) -> float:
    quantiles = stats["quantiles_seconds"]
    assert isinstance(quantiles, dict)
    return float(quantiles["p95"])


def measure_tape(
    data_root: Path, *, roles: tuple[str, ...], workers: int
) -> tuple[dict[str, object], dict[str, dict[str, object]]]:
    """Pool latency statistics over every partition in the requested roles."""

    files = [item for item in discover_sessions(TAPE_SOURCES, data_root) if item.role in roles]
    if not files:
        raise SystemExit("RP2_BLOCK2_NO_PARTITIONS")
    per_session: dict[str, LatencySample] = defaultdict(empty_sample)
    pooled = empty_sample()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for session, sample in pool.map(_read_partition, files):
            per_session[session] = per_session[session].merged_with(sample)
            pooled = pooled.merged_with(sample)
    sessions = {name: _describe(sample) for name, sample in sorted(per_session.items())}
    session_p95 = [_p95_of(stats) for stats in sessions.values()]
    summary = _describe(pooled)
    summary["sessions"] = len(sessions)
    summary["partitions"] = len(files)
    summary["p95_stable_across_sessions"] = stability_verdict(session_p95)
    summary["session_p95_max_seconds"] = max(session_p95)
    summary["session_p95_median_seconds"] = float(np.median(session_p95))
    return summary, sessions


def measure_live_receipt(campaign_root: Path) -> dict[str, object]:
    """Latency from provider ``created_at`` to local receipt, steady-state arrivals only."""

    if not campaign_root.is_dir():
        return {"status": "NO_LIVE_CAMPAIGN", "root": campaign_root.as_posix()}
    sessions: dict[str, object] = {}
    pooled = empty_sample()
    for session_dir in sorted(campaign_root.iterdir()):
        observations = session_dir / "observations.jsonl"
        if not observations.is_file():
            sessions[session_dir.name] = {"status": "NO_OBSERVATIONS"}
            continue
        first_receipt: dict[str, tuple[datetime, datetime]] = {}
        with observations.open(encoding="utf-8") as handle:
            for line in handle:
                payload = json.loads(line)
                if payload.get("kind") != "observation":
                    continue
                record_id = str(payload["record_id"])
                receipt = datetime.fromisoformat(str(payload["receipt_utc"]))
                created = datetime.fromisoformat(
                    str(payload["record"]["created_at"]).replace("Z", "+00:00")
                )
                previous = first_receipt.get(record_id)
                if previous is None or receipt < previous[0]:
                    first_receipt[record_id] = (receipt, created)
        if not first_receipt:
            sessions[session_dir.name] = {"status": "EMPTY"}
            continue
        collector_start = min(receipt for receipt, _ in first_receipt.values())
        steady = np.array(
            [
                (receipt - created).total_seconds()
                for receipt, created in first_receipt.values()
                if created >= collector_start
            ],
            dtype=np.float64,
        )
        backlog = len(first_receipt) - int(steady.size)
        entry: dict[str, object] = {
            "records": len(first_receipt),
            "initial_window_backlog_records": backlog,
            "steady_state_records": int(steady.size),
            "collector_first_receipt_utc": collector_start.isoformat(),
        }
        if steady.size:
            sample = summarise_latencies(steady)
            pooled = pooled.merged_with(sample)
            entry["steady_state"] = _describe(sample)
        sessions[session_dir.name] = entry
    result: dict[str, object] = {"status": "MEASURED", "sessions": sessions}
    if pooled.rows:
        result["pooled_steady_state"] = _describe(pooled)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--live-campaign", type=Path, default=LIVE_CAMPAIGN)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--roles", default="D,V")
    args = parser.parse_args(argv)

    roles = tuple(part.strip() for part in str(args.roles).split(",") if part.strip())
    summary, sessions = measure_tape(args.data_root, roles=roles, workers=args.workers)
    live = measure_live_receipt(args.live_campaign)

    provider_p95 = _p95_of(summary)
    local_p95 = 0.0
    pooled_live = live.get("pooled_steady_state")
    if isinstance(pooled_live, dict):
        local_p95 = _p95_of(pooled_live)
    end_to_end_p95 = provider_p95 + local_p95

    document: dict[str, object] = {
        "block": 2,
        "program": "docs/research_program_v2.md",
        "label": "EXPLORATORY_MECHANISM_DISCOVERY",
        "roles_measured": list(roles),
        "provider_ingestion_latency": summary,
        "local_receipt_latency": live,
        "end_to_end_p95_seconds": end_to_end_p95,
        "recommended_b2_cutoff_seconds": recommended_cutoff_seconds(end_to_end_p95),
        "incumbent_b2_cutoff_seconds": 60.0,
    }
    document["ledger_sha256"] = canonical_sha256(document)
    document["generated_at_utc"] = datetime.now(UTC).isoformat()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "ledger.json").write_text(
        json.dumps(document, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
    )
    (args.output_dir / "per_session.json").write_text(
        json.dumps(sessions, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
    )
    trimmed = {k: v for k, v in document.items() if k != "local_receipt_latency"}
    print(json.dumps(trimmed, indent=2, default=str))
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
