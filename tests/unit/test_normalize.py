from __future__ import annotations

from datetime import UTC

import pytest

from mds650.errors import QualityGateError, SchemaDriftError
from mds650.normalize import normalize_underlying_bars


def _row(timestamp: str = "2026-07-16 09:30:00") -> dict[str, object]:
    return {
        "date": timestamp,
        "open": 600.0,
        "high": 601.0,
        "low": 599.5,
        "close": 600.5,
        "volume": 1000,
    }


def test_normalize_underlying_bars_keeps_utc_and_new_york_renderings() -> None:
    rows = normalize_underlying_bars(
        [_row()],
        asset="SPY",
        run_id="run-1",
        source_response_id="resp-1",
        source_timezone="America/New_York",
    )

    assert len(rows) == 1
    assert rows[0].bar_start_utc.tzinfo == UTC
    assert rows[0].bar_start_ny.hour == 9
    assert rows[0].source_provider == "fmp"


def test_normalize_underlying_bars_fails_on_duplicate_key() -> None:
    with pytest.raises(QualityGateError, match="DUPLICATE_UNDERLYING_BAR"):
        normalize_underlying_bars(
            [_row(), _row()],
            asset="SPY",
            run_id="run-1",
            source_response_id="resp-1",
            source_timezone="America/New_York",
        )


def test_normalize_underlying_bars_fails_closed_on_schema_drift() -> None:
    bad = _row()
    bad.pop("close")

    with pytest.raises(SchemaDriftError, match="FMP_UNDERLYING_SCHEMA_DRIFT"):
        normalize_underlying_bars(
            [bad],
            asset="SPY",
            run_id="run-1",
            source_response_id="resp-1",
            source_timezone="America/New_York",
        )
