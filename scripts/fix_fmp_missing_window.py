"""Fill only the FMP sessions omitted by the inclusive-window bug."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import httpx
from exchange_calendars import get_calendar
from run_window_pipeline import ASSETS, END, START, _request

RUN_ID = "29db8e70-0686-4585-86d5-dfabc00295cf"
RAW_ROOT = Path(r"C:\Users\Public\MDS650\raw")


def observed(asset: str) -> set[str]:
    dates: set[str] = set()
    for path in (RAW_ROOT / "fmp").glob(f"{RUN_ID}-fmp-{asset}-*/payload.bin"):
        payload = json.loads(path.read_bytes())
        dates.update(
            str(row["date"])[:10] for row in payload if isinstance(row, dict) and "date" in row
        )
    return dates


def main() -> int:
    """Fetch missing sessions with FMP's inclusive ``to`` boundary."""
    calendar = get_calendar("XNYS")
    sessions = [
        stamp.date()
        for stamp in calendar.sessions_in_range(
            START.isoformat(), (END - date.resolution).isoformat()
        )
    ]
    total = 0
    with httpx.Client(timeout=60.0) as client:
        for asset in ASSETS:
            for session in sessions:
                if session.isoformat() in observed(asset):
                    continue
                _request(
                    client,
                    provider="fmp",
                    url="https://financialmodelingprep.com/stable/historical-chart/1min",
                    params={
                        "symbol": asset,
                        "from": session.isoformat(),
                        "to": session.isoformat(),
                    },
                    key_name="FMP_API_KEY",
                    run_id=RUN_ID,
                    label=f"fmp-{asset}-fix-{session}",
                )
                total += 1
    print(json.dumps({"run_id": RUN_ID, "requests": total, "secret_values_emitted": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
