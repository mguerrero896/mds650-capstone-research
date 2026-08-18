"""Extension 3 - acquire the one-minute bars for the 153 tape sessions that lack them.

The local option tape covers 469 sessions; only 316 entered the research panel, because
the other 153 have no underlying bars. Those sessions are already-observed eras, so they
cannot serve as confirmation - what they buy is precision on the Block 7 mechanism
estimate, which is where the finding is.

One request per (asset, session): FMP truncates wide one-minute ranges to the trailing
~1,500 rows, so a session is the only complete acquisition unit. Resumable: sessions
already on disk are skipped, so an interrupted run continues rather than restarting.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import polars as pl

from mds650.providers.fmp import FMPProvider, parse_minute_payload

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = Path("D:/MDS650/data/fmp/rp2_ext3")
ASSETS = ("AAPL", "AMZN", "META", "MSFT", "NVDA", "TSLA")
RUN_ID = "rp2_ext3_missing_bars"
INVENTORY = ROOT / "artifacts" / "rp2_block1_partition" / "inventory.jsonl"
B0_PANEL = ROOT / "artifacts" / "rp2_block4_b0" / "b0_panel.parquet"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def missing_sessions() -> list[str]:
    """Sessions with option tape but no bars in the research panel."""

    tape: set[str] = set()
    with INVENTORY.open(encoding="utf-8") as handle:
        for line in handle:
            tape.add(str(json.loads(line)["session_date"]))
    covered = set(
        pl.read_parquet(B0_PANEL, columns=["session_date"])["session_date"].unique().to_list()
    )
    return sorted(tape - covered)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--limit", type=int, default=0, help="0 means every missing session")
    args = parser.parse_args(argv)

    api_key = os.environ.get("FMP_API_KEY") or os.environ.get("MDS650_FMP_API_KEY")
    if not api_key:
        raise SystemExit("RP2_EXT3_FMP_KEY_MISSING")

    sessions = missing_sessions()
    if args.limit:
        sessions = sessions[: args.limit]
    args.output_dir.mkdir(parents=True, exist_ok=True)

    provider = FMPProvider(api_key)
    requested = 0
    written = 0
    empty: list[str] = []
    for session in sessions:
        target = args.output_dir / f"bars_{session}.parquet"
        if target.exists() and target.stat().st_size > 1000:
            continue
        frames: list[pl.DataFrame] = []
        for asset in ASSETS:
            response = provider.minute_bars(asset, from_date=session, to_date=session)
            requested += 1
            bars = parse_minute_payload(
                response.payload,
                asset=asset,
                run_id=RUN_ID,
                source_response_id=f"{RUN_ID}:{asset}:{session}",
                source_timezone="America/New_York",
            )
            if not bars:
                continue
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
        if not frames:
            empty.append(session)
            continue
        pl.concat(frames, how="vertical").write_parquet(target)
        written += 1
        if written % 10 == 0:
            print(f"[ext3] {written} sessions written, {requested} requests", flush=True)

    parts = sorted(args.output_dir.glob("bars_*.parquet"))
    combined = args.output_dir / "underlying_1min_ext3.parquet"
    if parts:
        pl.concat([pl.read_parquet(path) for path in parts], how="vertical").write_parquet(
            combined
        )
    document = {
        "extension": 3,
        "run_id": RUN_ID,
        "sessions_missing": len(sessions),
        "sessions_written_this_run": written,
        "sessions_on_disk": len(parts),
        "sessions_with_no_payload": empty,
        "requests_sent": requested,
        "combined": combined.as_posix() if parts else None,
        "combined_sha256": _sha256(combined) if parts else None,
        "generated_at_utc": datetime.now(UTC).isoformat(),
    }
    (args.output_dir / "acquisition.json").write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(document, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
