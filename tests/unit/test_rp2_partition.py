"""Block 1 — the frozen D/V/C partition must stay temporal, disjoint and sealed."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from mds650.rp2.partition import (
    CONFIRMATION_FIRST_SESSION,
    MULTI_ASSET,
    SEALED_CONFIRMATION,
    VALIDATION_FIRST_SESSION,
    TapeSource,
    assign_role,
    discover_sessions,
    inventory_digest,
    role_summary,
    temporal_ordering_holds,
)


def _make_store(root: Path, sessions: dict[str, list[str]]) -> None:
    for session, assets in sessions.items():
        for asset in assets:
            if asset == MULTI_ASSET:
                target = root / f"date={session}" / "events.parquet"
            else:
                target = root / f"date={session}" / f"asset={asset}" / "events.parquet"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"x" * 7)


@pytest.mark.parametrize(
    ("session", "expected"),
    [
        (date(2024, 8, 2), "D"),
        (date(2026, 3, 23), "D"),
        (date(2026, 3, 24), "V"),
        (date(2026, 7, 17), "V"),
        (date(2026, 7, 20), "BURNED"),
        (date(2026, 8, 28), "BURNED"),
    ],
)
def test_assign_role_follows_the_frozen_boundaries(session: date, expected: str) -> None:
    assert assign_role(session) == expected


def test_boundaries_are_ordered_and_match_the_sealed_cohort() -> None:
    assert VALIDATION_FIRST_SESSION < CONFIRMATION_FIRST_SESSION
    assert SEALED_CONFIRMATION.first_session == CONFIRMATION_FIRST_SESSION
    assert SEALED_CONFIRMATION.reads_permitted == 1


def test_discovery_assigns_roles_and_supports_both_layouts(tmp_path: Path) -> None:
    source = TapeSource("fixture", "store")
    _make_store(
        tmp_path / "store",
        {
            "2025-01-06": ["AAPL", "MSFT"],
            "2026-04-01": ["AAPL"],
            "2026-07-15": [MULTI_ASSET],
        },
    )
    files = discover_sessions([source], tmp_path)
    assert [item.role for item in files] == ["D", "D", "V", "V"]
    assert files[-1].asset == MULTI_ASSET
    assert temporal_ordering_holds(files)

    summary = role_summary(files)
    assert summary["D"]["sessions"] == 1
    assert summary["V"]["sessions"] == 2
    assert summary["BURNED"]["sessions"] == 0


def test_sealed_confirmation_sessions_are_never_enumerated(tmp_path: Path) -> None:
    source = TapeSource("fixture", "store")
    _make_store(
        tmp_path / "store",
        {"2025-01-06": ["AAPL"], "2026-04-01": ["AAPL"], "2026-08-10": ["AAPL"]},
    )
    files = discover_sessions([source], tmp_path)
    burned = [item for item in files if item.role == "BURNED"]
    assert [item.session_date for item in burned] == [date(2026, 8, 10)]
    # The sealed window is enumerable as metadata but is excluded from D and V.
    assert not any(item.role in {"D", "V"} for item in burned)


def test_inventory_digest_is_deterministic_and_content_sensitive(tmp_path: Path) -> None:
    source = TapeSource("fixture", "store")
    _make_store(tmp_path / "store", {"2025-01-06": ["AAPL"]})
    first = discover_sessions([source], tmp_path)
    assert inventory_digest(first) == inventory_digest(discover_sessions([source], tmp_path))

    _make_store(tmp_path / "store", {"2026-04-01": ["AAPL"]})
    assert inventory_digest(discover_sessions([source], tmp_path)) != inventory_digest(first)


def test_temporal_ordering_fails_without_both_universes(tmp_path: Path) -> None:
    source = TapeSource("fixture", "store")
    _make_store(tmp_path / "store", {"2025-01-06": ["AAPL"]})
    assert not temporal_ordering_holds(discover_sessions([source], tmp_path))


def test_missing_store_is_skipped_not_fatal(tmp_path: Path) -> None:
    assert discover_sessions([TapeSource("absent", "nope")], tmp_path) == []
