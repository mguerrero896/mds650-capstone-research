"""Materialize the completed frozen-window provider raw run without networking."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from run_window_pipeline import ASSETS, _write_backfill

from mds650.providers.fmp import parse_earnings_payload
from mds650.providers.unusual_whales import parse_flow_alert_payload


def _payloads(raw_root: Path, provider: str, run_id: str, marker: str) -> list[tuple[Path, Any]]:
    paths = sorted((raw_root / provider).glob(f"{run_id}-{marker}*/payload.bin"))
    return [(path, json.loads(path.read_bytes())) for path in paths]


def materialize(run_id: str, raw_root: Path) -> dict[str, Any]:
    """Read one complete raw run and write normalized backfill tables."""
    fmp = [
        (path, json.loads(path.read_bytes()))
        for path in sorted((raw_root / "fmp").glob(f"{run_id}-*/payload.bin"))
    ]
    uw = _payloads(raw_root, "unusual_whales", run_id, "uw-")
    raw_hashes = [hashlib.sha256(path.read_bytes()).hexdigest() for path, _ in [*fmp, *uw]]
    raw_underlying: dict[str, list[dict[str, object]]] = {asset: [] for asset in ASSETS}
    earnings: list[Any] = []
    for path, payload in fmp:
        label = path.parent.name
        if "-earnings-" in label:
            asset = label.split("-earnings-", 1)[1].split("-", 1)[0]
            earnings.extend(
                parse_earnings_payload(
                    payload,
                    run_id=run_id,
                    source_response_id=f"fmp-earnings-{asset}",
                )
            )
        elif "-fmp-" in label:
            asset = label.split("-fmp-", 1)[1].split("-", 1)[0]
            if asset in raw_underlying and isinstance(payload, list):
                raw_underlying[asset].extend(row for row in payload if isinstance(row, dict))
    unusual: list[Any] = []
    for path, payload in uw:
        label = path.parent.name
        asset = label.split("-uw-", 1)[1].split("-", 1)[0]
        data = payload.get("data", []) if isinstance(payload, dict) else []
        unusual.extend(
            parse_flow_alert_payload(
                {"data": data},
                run_id=run_id,
                source_response_id=f"uw-{asset}-backfill",
            )
        )
    dedup: dict[str, Any] = {}
    for event in unusual:
        dedup.setdefault(event.event_id, event)
    duplicate_event_count = len(unusual) - len(dedup)
    return _write_backfill(
        raw_underlying=raw_underlying,
        earnings=earnings,
        unusual=list(dedup.values()),
        run_id=run_id,
        raw_hashes=raw_hashes,
        capped_windows=[],
        duplicate_event_count=duplicate_event_count,
    )


def main() -> int:
    """Materialize the requested raw run and print a sanitized summary."""
    parser = argparse.ArgumentParser()
    parser.add_argument("run_id")
    parser.add_argument("--raw-root", type=Path, default=Path(r"C:\Users\Public\MDS650\raw"))
    args = parser.parse_args()
    manifest = materialize(args.run_id, args.raw_root)
    print(
        json.dumps(
            {
                k: manifest[k]
                for k in ("run_id", "row_counts", "frozen_assets", "b1_status", "benchmark_status")
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
