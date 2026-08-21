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


def granular_leaks(repo: Path, paths: list[str], *, excluded: set[str]) -> list[str]:
    """Return the parquet paths carrying quote-level columns that nobody registered.

    Size is a proxy for granularity and a poor one: a single session of option
    quotes compresses well below the aggregate threshold. Columns are the actual
    signal, and they are the same ones the CSV rule already uses.
    """
    import pyarrow as pa
    import pyarrow.parquet as pq

    leaks = []
    for path in paths:
        if path in excluded or path.startswith(FIXTURE_ALLOWED_PREFIXES):
            continue
        target = repo / path
        if not target.exists():
            continue
        try:
            names = {name.lower() for name in pq.read_schema(target).names}
        except (OSError, pa.ArrowInvalid):
            # Unreadable cannot be certified as safe, so it counts as a leak.
            leaks.append(path)
            continue
        if names & QUOTE_LEVEL_COLUMNS:
            leaks.append(path)
    return leaks


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


# ---------------------------------------------------------------------------
# Schema tripwire for parquet.
#
# The size rule above catches a large granular parquet. It cannot catch a small
# one: the six unregistered aggregates in this tree are 5 to 16 KB, so a single
# session of option trades would sit far under the 512 KB threshold and pass.
# CSVs already get a column check; parquet got none. These tests close that gap
# with synthetic fixtures, so the assertion does not depend on a granular file
# ever existing in the public line.
# ---------------------------------------------------------------------------


def _synthetic_parquet(path: Path, columns: dict[str, list[object]]) -> Path:
    import pyarrow as pa
    import pyarrow.parquet as pq

    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.table(columns), path)
    return path


def test_unregistered_granular_parquet_is_a_leak(tmp_path: Path) -> None:
    """A new per-contract parquet nobody registered must fail the gate."""
    _synthetic_parquet(
        tmp_path / "artifacts" / "new_capture" / "option_quotes.parquet",
        {"bid": [1.0], "ask": [1.2], "sip_timestamp": [1], "symbol": ["SPY"]},
    )
    leaks = granular_leaks(
        tmp_path, ["artifacts/new_capture/option_quotes.parquet"], excluded=set()
    )
    assert leaks == ["artifacts/new_capture/option_quotes.parquet"]


def test_small_granular_parquet_is_still_a_leak(tmp_path: Path) -> None:
    """Below the size threshold is not below the licence."""
    target = _synthetic_parquet(
        tmp_path / "artifacts" / "new_capture" / "trades.parquet",
        {"premium": [900.0], "trade_price": [1.5]},
    )
    assert target.stat().st_size < AGGREGATE_MAX_BYTES, "fixture must be under the size rule"
    assert granular_leaks(tmp_path, ["artifacts/new_capture/trades.parquet"], excluded=set())


def test_registered_granular_parquet_is_not_a_leak(tmp_path: Path) -> None:
    """Correctly registered is the contractual path, and must stay quiet."""
    _synthetic_parquet(
        tmp_path / "artifacts" / "new_capture" / "option_quotes.parquet",
        {"bid": [1.0], "ask": [1.2]},
    )
    path = "artifacts/new_capture/option_quotes.parquet"
    assert granular_leaks(tmp_path, [path], excluded={path}) == []


def test_aggregate_parquet_is_not_a_leak(tmp_path: Path) -> None:
    """The six unregistered aggregates in this tree must keep passing."""
    _synthetic_parquet(
        tmp_path / "artifacts" / "methodology" / "stability.parquet",
        {"model": ["har"], "rank": [1], "score": [0.5]},
    )
    aggregate = ["artifacts/methodology/stability.parquet"]
    assert granular_leaks(tmp_path, aggregate, excluded=set()) == []


def test_fixture_prefix_stays_exempt(tmp_path: Path) -> None:
    """The synthetic pilot_preview fixtures are shaped like real data on purpose."""
    path = "artifacts/pilot_preview/fixture_20260721/option_quotes.parquet"
    _synthetic_parquet(tmp_path / path, {"bid": [1.0], "ask": [1.2]})
    assert granular_leaks(tmp_path, [path], excluded=set()) == []


def test_public_line_has_no_unregistered_granular_parquet() -> None:
    """The live assertion: run the schema rule over what is actually tracked."""
    excluded = set(EXCLUDE_LIST.read_text(encoding="utf-8").split())
    tracked = subprocess.run(
        ["git", "ls-files", "*.parquet"], capture_output=True, text=True, cwd=REPO
    ).stdout.split()
    leaks = granular_leaks(REPO, tracked, excluded=excluded)
    assert not leaks, (
        "Parquet(s) carrying quote-level columns and not registered in "
        f"scripts/_gated_exclude_list.txt: {leaks}"
    )
