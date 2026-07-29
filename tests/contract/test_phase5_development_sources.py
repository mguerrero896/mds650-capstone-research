"""Contracts for the Phase 5 development-only provider sources."""

from __future__ import annotations

import sys
from datetime import UTC, date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import build_b2_calibration_20d as b2_builder  # noqa: E402


def test_fmp_source_filters_exact_session_and_records_both_delays() -> None:
    rows, returned_dates = b2_builder._normalize_fmp_session_rows(
        "AAPL",
        date(2026, 3, 24),
        [
            {
                "date": "2026-03-24 09:30:00",
                "open": 100,
                "high": 101,
                "low": 99,
                "close": 100.5,
                "volume": 123,
            },
            {
                "date": "2026-03-25 09:30:00",
                "open": 200,
                "high": 201,
                "low": 199,
                "close": 200.5,
                "volume": 456,
            },
        ],
    )

    assert returned_dates == ["2026-03-24", "2026-03-25"]
    assert len(rows) == 1
    assert rows[0]["bar_timestamp_raw_utc"] == datetime(
        2026,
        3,
        24,
        13,
        30,
        tzinfo=UTC,
    )
    assert rows[0]["available_at_utc"] == datetime(
        2026,
        3,
        24,
        13,
        31,
        tzinfo=UTC,
    )
    assert rows[0]["available_at_plus_2m_utc"] == datetime(
        2026,
        3,
        24,
        13,
        32,
        tzinfo=UTC,
    )
