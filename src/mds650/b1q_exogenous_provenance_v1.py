"""Target-free provenance closure for B1Q rate and dividend inputs."""

from __future__ import annotations

import math
import re
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from xml.etree import ElementTree
from zoneinfo import ZoneInfo

import polars as pl

_NY = ZoneInfo("America/New_York")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ATOM_ENTRY = "{http://www.w3.org/2005/Atom}entry"
_M_PROPERTIES = "{http://schemas.microsoft.com/ado/2007/08/dataservices/metadata}properties"
_REQUIRED_MATRIX = {
    "origin_id",
    "asset",
    "session_date",
    "forecast_origin_utc",
    "rate",
    "rate_source_date",
    "dividend_yield",
    "dividend_assumption",
}
_REQUIRED_SPOTS = {"asset", "session_date", "spot"}


def parse_treasury_yield_curve_xml(payload: bytes) -> dict[str, float]:
    """Parse official daily three-month Treasury par yields.

    Parameters
    ----------
    payload:
        Raw XML bytes from the U.S. Treasury daily yield-curve feed.

    Returns
    -------
    dict[str, float]
        Observation date mapped to decimal three-month rate.

    Raises
    ------
    ValueError
        If XML is malformed, contains a duplicate date, or has no usable rate.
    """
    try:
        root = ElementTree.fromstring(payload)
    except ElementTree.ParseError as exc:
        raise ValueError("B1Q_TREASURY_XML_INVALID") from exc
    rates: dict[str, float] = {}
    for entry in root.findall(_ATOM_ENTRY):
        properties = entry.find(f".//{_M_PROPERTIES}")
        if properties is None:
            continue
        row = {element.tag.rsplit("}", 1)[-1]: element.text for element in properties}
        raw_date, raw_rate = row.get("NEW_DATE"), row.get("BC_3MONTH")
        if not raw_date or not raw_rate:
            continue
        observation_date = raw_date[:10]
        if observation_date in rates:
            raise ValueError("B1Q_TREASURY_DATE_DUPLICATED")
        try:
            rates[observation_date] = float(raw_rate) / 100.0
        except ValueError as exc:
            raise ValueError("B1Q_TREASURY_RATE_INVALID") from exc
    if not rates:
        raise ValueError("B1Q_TREASURY_RATES_EMPTY")
    return rates


def augment_b1q_exogenous_provenance(
    matrix: pl.DataFrame,
    asset_day_spots: pl.DataFrame,
    *,
    treasury_rates: dict[str, float],
    dividends_by_asset: dict[str, list[dict[str, Any]]],
    treasury_payload_sha256_by_year: dict[str, str],
    dividend_payload_sha256_by_asset: dict[str, str],
) -> pl.DataFrame:
    """Bind exact source values and conservative availability to B1Q rows.

    The function never computes IV or reads a target. It verifies that the
    retained numeric rate and dividend yield are exactly reproducible from
    official Treasury observations and FMP declaration-date records.

    Parameters
    ----------
    matrix:
        Existing target-free B1Q origin matrix.
    asset_day_spots:
        One frozen spot per asset-session, matching the original B1Q build.
    treasury_rates:
        Official three-month Treasury rates in decimal form.
    dividends_by_asset:
        Raw FMP dividend records keyed by asset.
    treasury_payload_sha256_by_year, dividend_payload_sha256_by_asset:
        Immutable raw-payload identities.

    Returns
    -------
    polars.DataFrame
        Original rows plus provenance hashes, conservative availability times,
        bases, and a verified flag.

    Raises
    ------
    ValueError
        If identity, timing, source parity, or payload hashes fail closed.
    """
    _require_columns(matrix, _REQUIRED_MATRIX, "B1Q_MATRIX_SCHEMA_INVALID")
    _require_columns(asset_day_spots, _REQUIRED_SPOTS, "B1Q_SPOT_SCHEMA_INVALID")
    _assert_unique(matrix, ["origin_id", "asset", "session_date"], "B1Q_MATRIX_DUPLICATE")
    _assert_unique(asset_day_spots, ["asset", "session_date"], "B1Q_SPOT_DUPLICATE")
    if getattr(matrix["forecast_origin_utc"].dtype, "time_zone", None) != "UTC":
        raise ValueError("B1Q_FORECAST_ORIGIN_NOT_UTC")

    daily = matrix.select(
        "asset",
        "session_date",
        "rate",
        "rate_source_date",
        "dividend_yield",
        "dividend_assumption",
    ).unique()
    _assert_unique(daily, ["asset", "session_date"], "B1Q_EXOGENOUS_NOT_CONSTANT")
    daily = daily.join(asset_day_spots, on=["asset", "session_date"], how="inner", validate="1:1")
    if (
        daily.height != asset_day_spots.height
        or daily.height != matrix.select("asset", "session_date").unique().height
    ):
        raise ValueError("B1Q_SPOT_COVERAGE_MISMATCH")

    records = [
        _asset_day_evidence(
            row,
            treasury_rates=treasury_rates,
            dividends_by_asset=dividends_by_asset,
            treasury_payload_sha256_by_year=treasury_payload_sha256_by_year,
            dividend_payload_sha256_by_asset=dividend_payload_sha256_by_asset,
        )
        for row in daily.iter_rows(named=True)
    ]
    evidence = pl.DataFrame(records, infer_schema_length=None)
    result = (
        matrix.with_row_index("_b1q_row_order")
        .join(evidence, on=["asset", "session_date"], how="left", validate="m:1")
        .sort("_b1q_row_order")
        .drop("_b1q_row_order")
    )
    if (
        result["b1q_exogenous_provenance_verified"].null_count()
        or not result["b1q_exogenous_provenance_verified"].all()
    ):
        raise ValueError("B1Q_EXOGENOUS_PROVENANCE_INCOMPLETE")
    if result.filter(
        (pl.col("rate_source_available_at_utc") > pl.col("forecast_origin_utc"))
        | (pl.col("dividend_source_available_at_utc") > pl.col("forecast_origin_utc"))
    ).height:
        raise ValueError("B1Q_EXOGENOUS_EVIDENCE_AFTER_ORIGIN")
    return result


def _asset_day_evidence(
    row: dict[str, Any],
    *,
    treasury_rates: dict[str, float],
    dividends_by_asset: dict[str, list[dict[str, Any]]],
    treasury_payload_sha256_by_year: dict[str, str],
    dividend_payload_sha256_by_asset: dict[str, str],
) -> dict[str, Any]:
    """Build one verified asset-session evidence record."""
    asset = str(row["asset"])
    session_date = date.fromisoformat(str(row["session_date"]))
    rate_source_date = date.fromisoformat(str(row["rate_source_date"]))
    if rate_source_date >= session_date:
        raise ValueError("B1Q_RATE_NOT_STRICTLY_PRIOR")
    official_rate = treasury_rates.get(rate_source_date.isoformat())
    if official_rate is None or not math.isclose(
        float(row["rate"]), official_rate, rel_tol=0.0, abs_tol=1e-12
    ):
        raise ValueError("B1Q_TREASURY_VALUE_MISMATCH")

    rate_hash = treasury_payload_sha256_by_year.get(str(rate_source_date.year))
    dividend_hash = dividend_payload_sha256_by_asset.get(asset)
    if not _valid_hash(rate_hash) or not _valid_hash(dividend_hash):
        raise ValueError("B1Q_EXOGENOUS_PAYLOAD_HASH_INVALID")
    dividend_rows = dividends_by_asset.get(asset)
    if dividend_rows is None:
        raise ValueError("B1Q_DIVIDEND_PAYLOAD_MISSING")

    eligible: list[tuple[date, float]] = []
    for dividend in dividend_rows:
        try:
            declaration_date = date.fromisoformat(str(dividend.get("declarationDate")))
            value = float(dividend.get("adjDividend") or dividend.get("dividend") or 0.0)
        except (TypeError, ValueError):
            continue
        if session_date - timedelta(days=365) <= declaration_date < session_date and value > 0:
            eligible.append((declaration_date, value))

    spot = float(row["spot"])
    if not math.isfinite(spot) or spot <= 0:
        raise ValueError("B1Q_SPOT_INVALID")
    derived_yield = sum(value for _, value in eligible) / spot
    if not math.isclose(float(row["dividend_yield"]), derived_yield, rel_tol=0.0, abs_tol=1e-12):
        raise ValueError("B1Q_DIVIDEND_VALUE_MISMATCH")
    expected_assumption = (
        "PRE_ORIGIN_TRAILING_DECLARATIONS" if eligible else "NO_PRE_ORIGIN_DIVIDEND_Q_ZERO"
    )
    if row["dividend_assumption"] != expected_assumption:
        raise ValueError("B1Q_DIVIDEND_ASSUMPTION_MISMATCH")

    rate_available_at = datetime.combine(rate_source_date, time(20), _NY).astimezone(UTC)
    if eligible:
        latest_declaration = max(item[0] for item in eligible)
        dividend_available_at = datetime.combine(
            latest_declaration + timedelta(days=1), time(2), _NY
        ).astimezone(UTC)
        dividend_basis = "DECLARATION_DATE_END_PLUS_FMP_MAX_CYCLE"
    else:
        dividend_available_at = datetime.combine(session_date, time(2), _NY).astimezone(UTC)
        dividend_basis = "NO_PRIOR_DECLARATION_THROUGH_PRIOR_DAY_PLUS_FMP_MAX_CYCLE"

    return {
        "asset": asset,
        "session_date": session_date.isoformat(),
        "rate_source_available_at_utc": rate_available_at,
        "rate_source_payload_sha256": rate_hash,
        "rate_availability_basis": "US_TREASURY_18_ET_PLUS_FMP_MAX_CYCLE",
        "dividend_source_available_at_utc": dividend_available_at,
        "dividend_source_payload_sha256": dividend_hash,
        "dividend_availability_basis": dividend_basis,
        "b1q_exogenous_provenance_verified": True,
        "b1q_source_missing_reason": None,
    }


def _require_columns(frame: pl.DataFrame, required: set[str], error_code: str) -> None:
    """Require a compact dataframe schema."""
    if required - set(frame.columns):
        raise ValueError(error_code)


def _assert_unique(frame: pl.DataFrame, keys: list[str], error_code: str) -> None:
    """Reject duplicated identity keys."""
    if frame.select(keys).n_unique() != frame.height:
        raise ValueError(error_code)


def _valid_hash(value: object) -> bool:
    """Return whether a value is one lower-case SHA-256 digest."""
    return isinstance(value, str) and _SHA256.fullmatch(value) is not None
