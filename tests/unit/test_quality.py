"""TDD tests for explicit duplicate, null and completeness accounting."""

from __future__ import annotations

from mds650.quality import assess_rows


def test_quality_report_counts_duplicates_nulls_and_completeness() -> None:
    """Quality failures are counted, not silently removed."""
    rows = [
        {"asset": "AAPL", "minute": "2026-07-17T13:30:00Z", "close": 1.0},
        {"asset": "AAPL", "minute": "2026-07-17T13:30:00Z", "close": 1.1},
        {"asset": "AAPL", "minute": "2026-07-17T13:31:00Z", "close": None},
    ]

    report = assess_rows(
        rows,
        key_fields=("asset", "minute"),
        required_fields=("close",),
        expected_rows=4,
    )

    assert report.row_count == 3
    assert report.duplicate_key_count == 1
    assert report.critical_null_count == 1
    assert report.completeness_ratio == 0.75


def test_quality_report_handles_empty_input() -> None:
    """An empty response is an explicit zero-completeness result."""
    report = assess_rows(
        [],
        key_fields=("asset", "minute"),
        required_fields=("close",),
        expected_rows=4,
    )

    assert report.row_count == 0
    assert report.completeness_ratio == 0.0


def test_quality_report_rejects_schema_drift_and_invalid_ohlc() -> None:
    report = assess_rows(
        [
            {
                "asset": "AAPL",
                "minute": "2026-07-17T13:30:00Z",
                "open": 10.0,
                "high": 9.0,
                "low": 8.0,
                "close": 9.5,
                "unexpected": 1,
            }
        ],
        key_fields=("asset", "minute"),
        required_fields=("open", "high", "low", "close"),
        expected_rows=1,
        expected_fields=("asset", "minute", "open", "high", "low", "close"),
        ohlc_fields=("open", "high", "low", "close"),
    )

    assert report.schema_mismatch_count == 1
    assert report.invalid_ohlc_count == 1
