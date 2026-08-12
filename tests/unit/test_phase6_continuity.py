"""Fail-closed continuity and storage gates for Phase 6."""

from __future__ import annotations

from collections import namedtuple
from datetime import date
from pathlib import Path

import pytest

from mds650.phase5_storage import GIB, Phase5StorageConfig
from mds650.phase6 import (
    MARKET_CONTROLS,
    OUTCOME_ASSETS,
    continuity_verdict,
    phase6_storage_preflight,
)


def _passing_rows(day: str) -> list[dict[str, object]]:
    return [
        {
            "asset": asset,
            "date": day,
            "fmp_provider_available": True,
            "fmp_session_pass": True,
            "uw_file_metadata_pass": True,
            "massive_quote_pass": True,
        }
        for asset in (*OUTCOME_ASSETS, *MARKET_CONTROLS)
    ]


def test_continuity_requires_every_allowlisted_date_and_provider() -> None:
    expected = {"2025-07-07", "2025-07-08"}

    assert (
        continuity_verdict(_passing_rows("2025-07-07"), expected)
        == "REPLICATION_SESSION_ALLOWLIST_INCOMPLETE"
    )

    rows = [*_passing_rows("2025-07-07"), *_passing_rows("2025-07-08")]
    rows[0]["fmp_provider_available"] = False
    assert continuity_verdict(rows, expected) == "PROVIDER_CONTINUITY_FAILURE"


def test_incomplete_minutes_do_not_masquerade_as_provider_outage() -> None:
    rows = _passing_rows("2025-07-07")
    rows[0]["fmp_session_pass"] = False

    assert continuity_verdict(rows, {"2025-07-07"}) == "PASS_PHASE6_CONTINUITY"


def test_continuity_rejects_duplicate_asset_date() -> None:
    rows = _passing_rows("2025-07-07")

    assert (
        continuity_verdict([*rows, rows[0]], {"2025-07-07"}) == "REPLICATION_CONTINUITY_DUPLICATE"
    )


def test_continuity_passes_only_complete_matrix() -> None:
    rows = _passing_rows("2025-07-07")

    assert continuity_verdict(rows, {"2025-07-07"}) == "PASS_PHASE6_CONTINUITY"


def test_storage_rejects_peak_below_80_gib(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    usage = namedtuple("usage", "total used free")
    monkeypatch.setattr(
        "mds650.phase5_storage.shutil.disk_usage",
        lambda _path: usage(500 * GIB, 421 * GIB, 79 * GIB),
    )
    config = Phase5StorageConfig(
        sessions=(date(2025, 7, 7),),
        excluded_dates=frozenset(),
        data_root=tmp_path,
        minimum_free_bytes=80 * GIB,
        projected_peak_additional_bytes=1,
    )

    result = phase6_storage_preflight(config, session_count=1)

    assert result["status"] == "STORAGE_FLOOR_BREACH"


def test_storage_passes_with_exact_allowlist_and_peak_margin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    usage = namedtuple("usage", "total used free")
    monkeypatch.setattr(
        "mds650.phase5_storage.shutil.disk_usage",
        lambda _path: usage(500 * GIB, 200 * GIB, 300 * GIB),
    )
    config = Phase5StorageConfig(
        sessions=(date(2025, 7, 7),),
        excluded_dates=frozenset(),
        data_root=tmp_path,
        minimum_free_bytes=80 * GIB,
        projected_peak_additional_bytes=100 * GIB,
    )

    result = phase6_storage_preflight(config, session_count=1)

    assert result["status"] == "PASS_PHASE6_STORAGE"
    assert result["projected_minimum_free_bytes"] == 200 * GIB


def test_storage_rejects_allowlist_count_mismatch(tmp_path: Path) -> None:
    config = Phase5StorageConfig(
        sessions=(date(2025, 7, 7),),
        excluded_dates=frozenset(),
        data_root=tmp_path,
        minimum_free_bytes=80 * GIB,
        projected_peak_additional_bytes=1,
    )

    result = phase6_storage_preflight(config, session_count=180)

    assert result["status"] == "REPLICATION_SESSION_ALLOWLIST_INCOMPLETE"
