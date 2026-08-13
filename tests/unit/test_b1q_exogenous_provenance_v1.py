"""Target-free tests for B1Q rate and dividend provenance."""

from __future__ import annotations

from datetime import UTC, datetime

import polars as pl
import pytest

from mds650.b1q_exogenous_provenance_v1 import (
    augment_b1q_exogenous_provenance,
    parse_treasury_yield_curve_xml,
)

TREASURY_XML = b"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:m="http://schemas.microsoft.com/ado/2007/08/dataservices/metadata"
      xmlns:d="http://schemas.microsoft.com/ado/2007/08/dataservices">
  <entry><content type="application/xml"><m:properties>
    <d:NEW_DATE>2025-07-03T00:00:00</d:NEW_DATE>
    <d:BC_3MONTH>4.40</d:BC_3MONTH>
  </m:properties></content></entry>
</feed>
"""


def _matrix(*, aapl_q: float = 0.00125) -> pl.DataFrame:
    origin = datetime(2025, 7, 7, 13, 35, tzinfo=UTC)
    return pl.DataFrame(
        {
            "origin_id": ["AAPL:2025-07-07:0935", "AMZN:2025-07-07:0935"],
            "asset": ["AAPL", "AMZN"],
            "session_date": ["2025-07-07", "2025-07-07"],
            "forecast_origin_utc": [origin, origin],
            "rate": [0.044, 0.044],
            "rate_source_date": ["2025-07-03", "2025-07-03"],
            "dividend_yield": [aapl_q, 0.0],
            "dividend_assumption": [
                "PRE_ORIGIN_TRAILING_DECLARATIONS",
                "NO_PRE_ORIGIN_DIVIDEND_Q_ZERO",
            ],
        }
    )


def _spots() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "asset": ["AAPL", "AMZN"],
            "session_date": ["2025-07-07", "2025-07-07"],
            "spot": [200.0, 220.0],
        }
    )


def test_parses_official_treasury_xml() -> None:
    """The official XML date and three-month rate are parsed exactly."""
    assert parse_treasury_yield_curve_xml(TREASURY_XML) == {"2025-07-03": pytest.approx(0.044)}


def test_augments_exact_rate_and_dividend_provenance() -> None:
    """Exact source matches gain hashes and conservative availability times."""
    result = augment_b1q_exogenous_provenance(
        _matrix(),
        _spots(),
        treasury_rates={"2025-07-03": 0.044},
        dividends_by_asset={
            "AAPL": [{"declarationDate": "2025-05-01", "adjDividend": 0.25}],
            "AMZN": [],
        },
        treasury_payload_sha256_by_year={"2025": "a" * 64},
        dividend_payload_sha256_by_asset={"AAPL": "b" * 64, "AMZN": "c" * 64},
    )

    assert result.height == 2
    assert result["b1q_exogenous_provenance_verified"].to_list() == [True, True]
    assert result["rate_source_payload_sha256"].to_list() == ["a" * 64, "a" * 64]
    assert result["dividend_source_payload_sha256"].to_list() == ["b" * 64, "c" * 64]
    assert result.filter(
        pl.col("rate_source_available_at_utc") > pl.col("forecast_origin_utc")
    ).is_empty()
    assert result.filter(
        pl.col("dividend_source_available_at_utc") > pl.col("forecast_origin_utc")
    ).is_empty()
    assert set(result["dividend_availability_basis"].to_list()) == {
        "DECLARATION_DATE_END_PLUS_FMP_MAX_CYCLE",
        "NO_PRIOR_DECLARATION_THROUGH_PRIOR_DAY_PLUS_FMP_MAX_CYCLE",
    }


def test_rejects_dividend_value_drift() -> None:
    """A revised or differently constructed dividend yield fails closed."""
    with pytest.raises(ValueError, match="B1Q_DIVIDEND_VALUE_MISMATCH"):
        augment_b1q_exogenous_provenance(
            _matrix(aapl_q=0.002),
            _spots(),
            treasury_rates={"2025-07-03": 0.044},
            dividends_by_asset={
                "AAPL": [{"declarationDate": "2025-05-01", "adjDividend": 0.25}],
                "AMZN": [],
            },
            treasury_payload_sha256_by_year={"2025": "a" * 64},
            dividend_payload_sha256_by_asset={"AAPL": "b" * 64, "AMZN": "c" * 64},
        )


def test_rejects_same_session_rate() -> None:
    """A same-session rate remains unavailable at the opening origin."""
    matrix = _matrix().with_columns(pl.lit("2025-07-07").alias("rate_source_date"))
    with pytest.raises(ValueError, match="B1Q_RATE_NOT_STRICTLY_PRIOR"):
        augment_b1q_exogenous_provenance(
            matrix,
            _spots(),
            treasury_rates={"2025-07-07": 0.044},
            dividends_by_asset={"AAPL": [], "AMZN": []},
            treasury_payload_sha256_by_year={"2025": "a" * 64},
            dividend_payload_sha256_by_asset={"AAPL": "b" * 64, "AMZN": "c" * 64},
        )
