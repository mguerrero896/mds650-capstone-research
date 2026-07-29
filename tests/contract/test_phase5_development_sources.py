"""Contracts for the Phase 5 development-only provider sources."""

from __future__ import annotations

import sys
from datetime import UTC, date, datetime
from pathlib import Path

import polars as pl

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import build_b2_calibration_20d as b2_builder  # noqa: E402
import run_b1_calibration_20d as b1_builder  # noqa: E402


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


def test_b1q_reads_origins_from_explicit_fmp_source(tmp_path: Path) -> None:
    origins_path = tmp_path / "fmp" / "origins.parquet"
    origins_path.parent.mkdir()
    pl.DataFrame(
        {
            "origin_id": ["AAPL:2026-03-24T13:35:00+00:00"],
            "asset": ["AAPL"],
            "session_date": ["2026-03-24"],
            "forecast_origin_utc": [datetime(2026, 3, 24, 13, 35, tzinfo=UTC)],
            "spot": [100.0],
            "session_segment": ["first"],
        }
    ).write_parquet(origins_path)
    config = b1_builder.B1BuildConfig(
        output_root=tmp_path / "b1q",
        cache_root=tmp_path / "cache",
        sessions=("2026-03-24",),
        origins_path=origins_path,
    )

    result = b1_builder._load_origins(config)

    assert result.height == 1
    assert result["origin_id"].to_list() == ["AAPL:2026-03-24T13:35:00+00:00"]
    assert result["origin_ns"].to_list() == [1774359300000000000]


def test_b1q_market_inputs_cover_full_trailing_year(tmp_path: Path) -> None:
    config = b1_builder.B1BuildConfig(
        output_root=tmp_path / "b1q",
        cache_root=tmp_path / "cache",
        sessions=("2026-03-24", "2026-06-10"),
    )

    assert b1_builder._market_input_window(config) == (
        date(2025, 3, 24),
        date(2026, 6, 10),
    )


def test_b1q_origin_records_observed_quote_pit_evidence() -> None:
    origin_ns = 1774359300000000000

    valid = b1_builder._quote_pit_evidence(
        [
            {"sip_timestamp": origin_ns - 2_000_000_000},
            {"sip_timestamp": origin_ns - 1_000_000_000},
            {"sip_timestamp": None},
        ],
        origin_ns,
    )
    assert valid == {
        "b1q_max_sip_timestamp_ns": origin_ns - 1_000_000_000,
        "b1q_quote_not_after_origin": True,
        "b1q_pit_evidence_valid": True,
    }

    assert b1_builder._quote_pit_evidence([], origin_ns)[
        "b1q_pit_evidence_valid"
    ] is False
    assert b1_builder._quote_pit_evidence(
        [{"sip_timestamp": origin_ns + 1}],
        origin_ns,
    )["b1q_quote_not_after_origin"] is False
