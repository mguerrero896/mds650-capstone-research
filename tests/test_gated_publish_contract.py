"""Standing tripwire: no licensed-derived dataset may reach the public mirror.

Every tracked parquet larger than the fixture threshold must be listed in
scripts/_gated_exclude_list.txt (which publish_mirror.sh strips from the whole
published history). A new granular artifact committed without registering it
here fails the suite BEFORE it can leak into the public repository.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EXCLUDE_LIST = REPO / "scripts" / "_gated_exclude_list.txt"
FIXTURE_ALLOWED_PREFIXES = ("artifacts/pilot_preview/fixture_",)
AGGREGATE_MAX_BYTES = 512 * 1024  # tiny stability/audit summaries are aggregates


def test_every_large_parquet_is_gated() -> None:
    excluded = set(EXCLUDE_LIST.read_text(encoding="utf-8").split())
    tracked = subprocess.run(
        ["git", "ls-files", "*.parquet"], capture_output=True, text=True, cwd=REPO
    ).stdout.split()
    leaks = []
    for path in tracked:
        if path in excluded or path.startswith(FIXTURE_ALLOWED_PREFIXES):
            continue
        if (REPO / path).stat().st_size > AGGREGATE_MAX_BYTES:
            leaks.append(path)
    assert not leaks, (
        "Granular parquet(s) not registered in scripts/_gated_exclude_list.txt "
        f"(would leak to the public mirror): {leaks}"
    )


QUOTE_LEVEL_COLUMNS = {
    "bid",
    "ask",
    "midpoint",
    "sip_timestamp",
    "quote_time_utc",
    "provider_timestamp_ns",
    "premium",
    "trade_price",
}


def test_no_quote_level_csv_reaches_the_mirror() -> None:
    """Row-level market data (real contracts, timestamps, prices) must be gated
    regardless of file size — found live in b1_iv_failures_20d.csv (2026-08-18)."""
    excluded = set(EXCLUDE_LIST.read_text(encoding="utf-8").split())
    tracked = subprocess.run(
        ["git", "ls-files", "*.csv"], capture_output=True, text=True, cwd=REPO
    ).stdout.split()
    leaks = []
    for path in tracked:
        if path in excluded or path.startswith(FIXTURE_ALLOWED_PREFIXES):
            continue
        with (REPO / path).open(encoding="utf-8", errors="replace") as handle:
            header = {column.strip().lower() for column in handle.readline().split(",")}
        if header & QUOTE_LEVEL_COLUMNS:
            leaks.append(path)
    assert not leaks, (
        "CSV(s) with quote-level market data not registered in "
        f"scripts/_gated_exclude_list.txt: {leaks}"
    )


def test_pointers_cover_the_exclude_list() -> None:
    import json

    pointers = json.loads(
        (REPO / "data" / "GATED_DATA_POINTERS.json").read_text(encoding="utf-8")
    )
    pointer_paths = {entry["path"] for entry in pointers["files"]}
    excluded = set(EXCLUDE_LIST.read_text(encoding="utf-8").split())
    assert excluded == pointer_paths, (
        "exclude list and GATED_DATA_POINTERS.json disagree: "
        f"only-excluded={sorted(excluded - pointer_paths)} "
        f"only-pointers={sorted(pointer_paths - excluded)}"
    )
