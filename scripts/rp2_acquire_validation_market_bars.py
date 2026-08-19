"""Acquire SPY and QQQ one-minute bars for the validation sessions.

Decision 75 recorded an asymmetry nobody had read off the artifacts: the market controls —
SPY and QQQ realized variance and return at each origin — existed for 180 discovery sessions
and for **no** validation session. `market_control_rows` was 71,192 in D and 0 in V.

That means "B0" was underlying state *plus* market-wide state in discovery and underlying
state *alone* in validation, so every D-versus-V comparison in the programme contrasted two
different baselines. It also cuts the wrong way for a null: a weaker validation baseline
should make a B1 or B2 increment *easier* to find there, so its absence was being read
against a handicap.

This closes it. One request per (symbol, session): FMP truncates wide one-minute ranges to
the trailing rows, so a session is the only complete acquisition unit. Resumable — sessions
already on disk are skipped, so an interrupted run continues rather than restarting.

The sessions come from the validation bar store itself rather than from a hand-written list,
so the acquisition cannot drift away from the universe it is meant to complete.
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
DEFAULT_OUTPUT = Path("D:/MDS650/data/fmp/rp2_validation_market")
MARKET_ASSETS = ("SPY", "QQQ")
RUN_ID = "rp2_validation_market_bars"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sessions_without_market_controls(panel: Path) -> list[str]:
    """Every research session whose market controls are still missing, in date order.

    Derived from the panel rather than from a hand-written list, so the acquisition cannot
    drift away from the universe it is meant to complete and re-running it after a rebuild
    asks only for what is still absent.
    """

    frame = pl.read_parquet(panel, columns=["session_date", "SPY_rv_30"])
    covered = (
        frame.filter(pl.col("SPY_rv_30").is_not_null() & pl.col("SPY_rv_30").is_finite())[
            "session_date"
        ]
        .unique()
        .to_list()
    )
    every = frame["session_date"].unique().to_list()
    return sorted({str(value) for value in every} - {str(value) for value in covered})


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--panel", type=Path, default=ROOT / "artifacts" / "rp2_block4_b0" / "b0_panel.parquet"
    )
    parser.add_argument("--limit", type=int, default=0, help="0 means every session")
    args = parser.parse_args(argv)

    api_key = os.environ.get("FMP_API_KEY") or os.environ.get("MDS650_FMP_API_KEY")
    if not api_key:
        raise SystemExit("RP2_VALIDATION_MARKET_FMP_KEY_MISSING")

    sessions = sessions_without_market_controls(args.panel)
    if args.limit:
        sessions = sessions[: args.limit]
    args.output_dir.mkdir(parents=True, exist_ok=True)

    provider = FMPProvider(api_key)
    requested = 0
    written = 0
    empty: list[str] = []
    for session in sessions:
        target = args.output_dir / f"market_{session}.parquet"
        if target.exists() and target.stat().st_size > 1000:
            continue
        frames: list[pl.DataFrame] = []
        for asset in MARKET_ASSETS:
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
            print(f"[market] {written} sessions written, {requested} requests", flush=True)

    parts = sorted(args.output_dir.glob("market_*.parquet"))
    combined = args.output_dir / "market_1min_validation.parquet"
    if parts:
        pl.concat([pl.read_parquet(path) for path in parts], how="vertical").write_parquet(combined)
    document = {
        "acquisition": "rp2_validation_market_bars",
        "run_id": RUN_ID,
        "reason": "decision 75: B0 carried no market-wide state in the validation universe",
        "assets": list(MARKET_ASSETS),
        "sessions_missing_controls": len(sessions),
        "sessions_written_this_run": written,
        "sessions_on_disk": len(parts),
        "sessions_with_no_payload": empty,
        "requests_sent": requested,
        "combined": combined.as_posix() if parts else None,
        "combined_sha256": _sha256(combined) if parts else None,
        "generated_at_utc": datetime.now(UTC).isoformat(),
    }
    output = ROOT / "artifacts" / "rp2_validation_market"
    output.mkdir(parents=True, exist_ok=True)
    (output / "acquisition.json").write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(document, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
