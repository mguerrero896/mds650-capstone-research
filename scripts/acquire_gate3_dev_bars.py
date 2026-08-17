"""Gate 3 acquisition: FMP 1-minute bars for the 80 development sessions.

Development-window underlying bars for the six outcome assets, fetched with the
audited FMP client and canonical normalizer. This is development-only model
input (HAR/HARQ realized-variance and quarticity components); it reads no
sealed cohort and starts no evaluation campaign. Output parquet + manifest with
sha256 under ``MDS650_EXTERNAL_ROOT/data/fmp/gate3/``.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path

import polars as pl

from mds650.providers.fmp import FMPProvider, parse_minute_payload

REPO = Path(__file__).resolve().parents[1]
DATA_ROOT = Path(os.environ.get("MDS650_EXTERNAL_ROOT", "D:/MDS650"))
OUTPUT_DIR = DATA_ROOT / "data" / "fmp" / "gate3"
PANEL = REPO / "artifacts" / "phase5" / "common_development_80d.parquet"
ASSETS = ("AAPL", "AMZN", "META", "MSFT", "NVDA", "TSLA")
RUN_ID = "gate3_dev_bars_20260817"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    api_key = os.environ.get("FMP_API_KEY") or os.environ.get("MDS650_FMP_API_KEY")
    if not api_key:
        raise SystemExit("GATE3_FMP_KEY_MISSING")
    sessions = sorted(
        pl.read_parquet(PANEL, columns=["session_date"])["session_date"].unique().to_list()
    )
    if len(sessions) != 80:
        raise SystemExit(f"GATE3_UNEXPECTED_SESSION_COUNT:{len(sessions)}")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output = OUTPUT_DIR / "underlying_1min_dev80.parquet"
    if output.exists() and output.stat().st_size > 1_000_000:
        print(f"[gate3] already acquired: {output}")
        print(f"[gate3] sha256={_sha256(output)}")
        return
    output.unlink(missing_ok=True)
    provider = FMPProvider(api_key)
    frames: list[pl.DataFrame] = []
    request_count = 0
    try:
        # FMP truncates wide 1-minute ranges to the trailing ~1,500 rows, so the
        # only complete acquisition unit is one session per request.
        for asset in ASSETS:
            for session in sessions:
                from_date = to_date = str(session)
                response = provider.minute_bars(asset, from_date=from_date, to_date=to_date)
                bars = parse_minute_payload(
                    response.payload,
                    asset=asset,
                    run_id=RUN_ID,
                    source_response_id=f"{RUN_ID}:{asset}:{from_date}",
                    source_timezone="America/New_York",
                )
                request_count += 1
                if bars:
                    frames.append(
                        pl.DataFrame(
                            [
                                {
                                    "asset": bar.asset,
                                    "bar_start_utc": bar.bar_start_utc,
                                    "open": bar.open,
                                    "high": bar.high,
                                    "low": bar.low,
                                    "close": bar.close,
                                    "volume": bar.volume,
                                }
                                for bar in bars
                            ]
                        )
                    )
                time.sleep(0.15)
            print(f"[gate3] {asset}: cumulative rows {sum(f.height for f in frames)}")
    finally:
        provider.close()
    combined = pl.concat(frames).unique(subset=["asset", "bar_start_utc"], keep="first").sort(
        "asset", "bar_start_utc"
    )
    combined.write_parquet(output)
    manifest = {
        "run_id": RUN_ID,
        "acquired_at_utc": datetime.now(UTC).isoformat(),
        "assets": list(ASSETS),
        "sessions": [str(session) for session in sessions],
        "requests": request_count,
        "rows": combined.height,
        "sha256": _sha256(output),
    }
    (OUTPUT_DIR / "underlying_1min_dev80_manifest.json").write_text(
        json.dumps(manifest, indent=1), encoding="utf-8"
    )
    print(f"[gate3] wrote {output} rows={combined.height} sha256={str(manifest['sha256'])[:16]}")


if __name__ == "__main__":
    main()
