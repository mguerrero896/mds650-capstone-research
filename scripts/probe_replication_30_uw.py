"""Probe historical Unusual Whales Full Tape metadata without downloading ZIPs."""

from __future__ import annotations

import argparse
import json
import os
from datetime import date
from pathlib import Path

import httpx
from exchange_calendars import get_calendar  # type: ignore[import-untyped]

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "artifacts" / "api_audit" / "b2_replication_30_uw_metadata_probe.json"


def _secret(name: str) -> str:
    """Return a required secret without exposing its value.

    Raises
    ------
    RuntimeError
        If the environment variable is absent or blank.
    """
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"MISSING_SECRET:{name}")
    return value


def _dates(warmup_count: int = 0) -> list[date]:
    """Return target sessions and an optional causal warm-up prefix."""
    if warmup_count < 0:
        raise ValueError("WARMUP_COUNT_INVALID")
    calendar = get_calendar("XNYS")
    sessions = calendar.sessions_in_range("2025-01-01", "2025-07-06")
    return [stamp.date() for stamp in sessions.to_pydatetime()][-(30 + warmup_count) :]


def _probe(client: httpx.Client, key: str, session_date: date) -> dict[str, object]:
    """Request one byte and record only sanitized response metadata."""
    response = client.get(
        f"https://api.unusualwhales.com/api/option-trades/full-tape/{session_date.isoformat()}",
        headers={
            "Authorization": f"Bearer {key}",
            "Accept": "application/json",
            "Range": "bytes=0-0",
        },
    )
    content_range = response.headers.get("content-range", "")
    total = None
    if "/" in content_range and content_range.rsplit("/", 1)[1].isdigit():
        total = int(content_range.rsplit("/", 1)[1])
    return {
        "date": session_date.isoformat(),
        "http_status": response.status_code,
        "content_range_present": bool(content_range),
        "bytes_total": total,
        "bytes_sampled": len(response.content),
        "file_metadata_pass": response.status_code in {200, 206} and total is not None,
        "full_tape_downloaded": False,
        "secret_values_emitted": False,
    }


def main() -> None:
    """Write a reproducible, metadata-only availability probe."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--warmup-count", type=int, default=0)
    arguments = parser.parse_args()
    key = _secret("UNUSUALWHALES_API_KEY")
    dates = _dates(arguments.warmup_count)
    with httpx.Client(timeout=60, follow_redirects=True) as client:
        rows = [_probe(client, key, session_date) for session_date in dates]
    payload = {
        "schema_version": "b2-replication-30-uw-metadata-probe-1.0",
        "status": (
            "PASS_METADATA_ONLY"
            if all(row["file_metadata_pass"] for row in rows)
            else "FAIL_METADATA_ONLY"
        ),
        "window_start": dates[0].isoformat(),
        "window_end": dates[-1].isoformat(),
        "session_count": len(rows),
        "metadata_pass_count": sum(bool(row["file_metadata_pass"]) for row in rows),
        "full_tape_downloaded": False,
        "pit_claim": False,
        "note": (
            "Range/Content-Range proves file metadata availability only; it is not "
            "row-level PIT evidence."
        ),
        "records": rows,
        "secret_values_emitted": False,
    }
    output = OUTPUT.with_name(
        f"b2_replication_{len(dates)}_uw_metadata_probe.json"
        if arguments.warmup_count
        else OUTPUT.name
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    summary_keys = (
        "status",
        "window_start",
        "window_end",
        "session_count",
        "metadata_pass_count",
        "full_tape_downloaded",
        "secret_values_emitted",
    )
    print(json.dumps({key: payload[key] for key in summary_keys}))


if __name__ == "__main__":
    main()
