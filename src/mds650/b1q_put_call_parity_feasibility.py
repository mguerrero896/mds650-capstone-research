"""Target-free feasibility checks for an ex-ante B1Q put-call-parity route.

The module deliberately answers only a data-geometry question: whether the
already cached B1Q quote grid contains two valid paired strikes for a forecast
origin and expiry.  It neither estimates an IV surface nor replaces the
registered rate/dividend provenance requirement.
"""

from __future__ import annotations

import json
import math
import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import polars as pl

from mds650.study_design import canonical_sha256

ALLOWED_ATTEMPT_COLUMNS: tuple[str, ...] = (
    "asset",
    "session_date",
    "origin_id",
    "forecast_origin_utc",
    "forecast_origin_ns",
    "expiry",
    "strike",
    "option_type",
    "contract",
    "sip_timestamp",
    "bid",
    "ask",
    "quote_age_seconds",
    "relative_spread",
)
"""Columns read from the B1Q attempts file; targets, metrics, and IV fields are excluded."""

B1Q_PARITY_OUTPUT_CONFLICT = "B1Q_PARITY_OUTPUT_CONFLICT"
"""Raised when an immutable parity report path already contains different bytes."""

_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_ORIGIN_COLUMNS = (
    "asset",
    "session_date",
    "origin_id",
    "forecast_origin_utc",
    "forecast_origin_ns",
)
_STRIKE_SIDE_COLUMNS = (*_ORIGIN_COLUMNS, "expiry", "strike", "option_type")
_CONTRACT_QUOTE_IDENTITY_COLUMNS = (
    *_STRIKE_SIDE_COLUMNS,
    "contract",
    "sip_timestamp",
    "bid",
    "ask",
)
_EXPIRY_COLUMNS = (*_ORIGIN_COLUMNS, "expiry")


def assess_put_call_parity_feasibility(
    attempts: pl.DataFrame,
    *,
    source_file_sha256: str,
    quote_age_limit_seconds: float = 60.0,
    relative_spread_limit: float = 0.25,
) -> dict[str, object]:
    """Assess whether a target-free quote grid can form paired-strike parity estimates.

    The estimator uses only midpoint quotes that pass the registered B1Q
    as-of, age, and spread checks.  A same-expiry put-call pair at one strike
    is insufficient to recover the discount factor: at least two strikes are
    required.  This diagnostic does not use realised variance, model outputs,
    QLIKE, IV inversion outcomes, rates, dividends, or any holdout input.

    Parameters
    ----------
    attempts:
        In-memory B1Q quote-attempt table.  Only ``ALLOWED_ATTEMPT_COLUMNS``
        are read, so extra target or metric columns are ignored.
    source_file_sha256:
        Lowercase SHA-256 of the source Parquet bytes.
    quote_age_limit_seconds:
        Non-negative maximum age relative to the forecast origin.
    relative_spread_limit:
        Non-negative maximum relative bid/ask spread.

    Returns
    -------
    dict[str, object]
        Deterministic, JSON-serializable feasibility report with a semantic
        self-hash, global counts, and per-asset counts.

    Raises
    ------
    ValueError
        If the source hash, thresholds, required input columns, or valid
        strike-side identity is invalid or ambiguous.

    Examples
    --------
    >>> report = assess_put_call_parity_feasibility(
    ...     pl.DataFrame({"asset": [], "session_date": [], "origin_id": []}),
    ...     source_file_sha256="0" * 64,
    ... )
    Traceback (most recent call last):
    ...
    ValueError: B1Q_PARITY_REQUIRED_COLUMN_MISSING
    """
    _validate_inputs(attempts, source_file_sha256, quote_age_limit_seconds, relative_spread_limit)
    source = attempts.select(list(ALLOWED_ATTEMPT_COLUMNS))
    origins = source.select(list(_ORIGIN_COLUMNS)).unique().sort(list(_ORIGIN_COLUMNS))
    valid_quotes_before_deduplication = _valid_quote_rows(
        source,
        quote_age_limit_seconds=quote_age_limit_seconds,
        relative_spread_limit=relative_spread_limit,
    )
    valid_quotes = valid_quotes_before_deduplication.unique(
        subset=list(_CONTRACT_QUOTE_IDENTITY_COLUMNS),
        maintain_order=True,
    )
    ambiguous_strike_side_groups = _count_ambiguous_strike_sides(valid_quotes)
    if ambiguous_strike_side_groups:
        raise ValueError("B1Q_PARITY_AMBIGUOUS_STRIKE_SIDE")

    pairs = _build_same_strike_pairs(valid_quotes)
    expiry_diagnostics = _build_expiry_diagnostics(pairs)
    two_strike_expiries = expiry_diagnostics.filter(pl.col("paired_strike_count") >= 2)
    valid_discount_expiries = two_strike_expiries.filter(
        pl.col("discount_factor").is_finite()
        & (pl.col("discount_factor") > 0.0)
        & (pl.col("discount_factor") <= 1.1)
    )

    origins_with_any_pair = _unique_origin_count(pairs)
    origins_with_two_strike_expiry = _unique_origin_count(two_strike_expiries)
    origins_with_valid_discount_estimate = _unique_origin_count(valid_discount_expiries)
    origin_count = origins.height
    status = (
        "FEASIBLE_CANDIDATE_REQUIRES_METHOD_AMENDMENT"
        if origins_with_valid_discount_estimate > 0
        else "INFEASIBLE_WITH_CURRENT_CONTRACT_GRID"
    )

    payload: dict[str, object] = {
        "schema_version": "1.0.0",
        "status": status,
        "scope": "TARGET_FREE_B1Q_PUT_CALL_PARITY_FEASIBILITY_ONLY",
        "source_file_sha256": source_file_sha256,
        "source_row_count": source.height,
        "origin_count": origin_count,
        "input_columns_read": list(ALLOWED_ATTEMPT_COLUMNS),
        "forbidden_target_or_outcome_columns_read": [],
        "quote_filters": {
            "sip_timestamp_at_or_before_origin": True,
            "bid_positive": True,
            "ask_strictly_above_bid": True,
            "quote_age_seconds_min": 0.0,
            "quote_age_seconds_max": quote_age_limit_seconds,
            "relative_spread_min": 0.0,
            "relative_spread_max": relative_spread_limit,
            "expiry_strictly_after_session_date": True,
        },
        "valid_quote_rows_before_contract_quote_deduplication": (
            valid_quotes_before_deduplication.height
        ),
        "duplicate_contract_quote_records_dropped": (
            valid_quotes_before_deduplication.height - valid_quotes.height
        ),
        "valid_quote_rows": valid_quotes.height,
        "same_strike_call_put_pairs": pairs.height,
        "expiry_groups_with_two_paired_strikes": two_strike_expiries.height,
        "origins_with_any_pair": origins_with_any_pair,
        "origins_with_two_strike_expiry": origins_with_two_strike_expiry,
        "origins_with_valid_discount_estimate": origins_with_valid_discount_estimate,
        "origin_coverage_any_pair": _fraction(origins_with_any_pair, origin_count),
        "origin_coverage_two_strike_expiry": _fraction(
            origins_with_two_strike_expiry, origin_count
        ),
        "origin_coverage_valid_discount_estimate": _fraction(
            origins_with_valid_discount_estimate, origin_count
        ),
        "valid_discount_estimate_median": _quantile_or_none(
            valid_discount_expiries, "discount_factor", 0.5
        ),
        "valid_discount_estimate_p05": _quantile_or_none(
            valid_discount_expiries, "discount_factor", 0.05
        ),
        "valid_discount_estimate_p95": _quantile_or_none(
            valid_discount_expiries, "discount_factor", 0.95
        ),
        "by_asset": _by_asset(
            origins,
            pairs,
            two_strike_expiries,
            valid_discount_expiries,
        ),
        "method_change_authorized": False,
        "b1q_exogenous_input_provenance_resolved": False,
        "safe_to_reconcile_existing_results": "NO",
        "safe_to_open_or_evaluate_oos": "NO",
        "target_or_metric_data_read": False,
        "interpretation": (
            "This is a target-free contract-grid feasibility diagnostic only; it does not "
            "replace registered rate/dividend provenance or authorize a B1Q method change."
        ),
    }
    payload["semantic_self_hash"] = f"sha256:{canonical_sha256(payload)}"
    return payload


def write_json_if_new_or_identical(path: Path, payload: Mapping[str, Any]) -> str:
    """Write deterministic JSON once and reject a conflicting replay.

    Parameters
    ----------
    path:
        Destination for a sanitized local JSON report.
    payload:
        JSON-serializable report to render deterministically.

    Returns
    -------
    str
        ``"CREATED"`` if this invocation created the report, otherwise
        ``"IDENTICAL"`` if an existing report has exactly the same bytes.

    Raises
    ------
    ValueError
        If the destination exists with different bytes.

    Examples
    --------
    >>> from pathlib import Path
    >>> # write_json_if_new_or_identical(Path("report.json"), {"status": "PASS"})
    """
    rendered = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    except FileExistsError:
        if path.read_bytes() == rendered:
            return "IDENTICAL"
        raise ValueError(B1Q_PARITY_OUTPUT_CONFLICT) from None
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(rendered)
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return "CREATED"


def _validate_inputs(
    attempts: pl.DataFrame,
    source_file_sha256: str,
    quote_age_limit_seconds: float,
    relative_spread_limit: float,
) -> None:
    """Validate the narrow target-free input contract before reading rows."""
    if not _SHA256_PATTERN.fullmatch(source_file_sha256):
        raise ValueError("B1Q_PARITY_SOURCE_SHA256_INVALID")
    if not math.isfinite(quote_age_limit_seconds) or quote_age_limit_seconds < 0.0:
        raise ValueError("B1Q_PARITY_QUOTE_AGE_LIMIT_INVALID")
    if not math.isfinite(relative_spread_limit) or relative_spread_limit < 0.0:
        raise ValueError("B1Q_PARITY_RELATIVE_SPREAD_LIMIT_INVALID")
    missing = sorted(set(ALLOWED_ATTEMPT_COLUMNS).difference(attempts.columns))
    if missing:
        raise ValueError("B1Q_PARITY_REQUIRED_COLUMN_MISSING")


def _valid_quote_rows(
    source: pl.DataFrame,
    *,
    quote_age_limit_seconds: float,
    relative_spread_limit: float,
) -> pl.DataFrame:
    """Filter rows with a valid, selected as-of midpoint quote."""
    return (
        source.with_columns(pl.col("option_type").str.to_lowercase().alias("option_type"))
        .filter(
            _numeric_is_finite("strike")
            & (pl.col("strike") > 0.0)
            & _numeric_is_finite("bid")
            & (pl.col("bid") > 0.0)
            & _numeric_is_finite("ask")
            & (pl.col("ask") > pl.col("bid"))
            & pl.col("sip_timestamp").is_not_null()
            & pl.col("forecast_origin_ns").is_not_null()
            & (pl.col("sip_timestamp") <= pl.col("forecast_origin_ns"))
            & _numeric_is_finite("quote_age_seconds")
            & (pl.col("quote_age_seconds") >= 0.0)
            & (pl.col("quote_age_seconds") <= quote_age_limit_seconds)
            & _numeric_is_finite("relative_spread")
            & (pl.col("relative_spread") >= 0.0)
            & (pl.col("relative_spread") <= relative_spread_limit)
            & pl.col("expiry").is_not_null()
            & pl.col("session_date").is_not_null()
            & (pl.col("expiry") > pl.col("session_date"))
            & pl.col("option_type").is_in(("call", "put"))
        )
        .with_columns(((pl.col("bid") + pl.col("ask")) / 2.0).alias("midpoint"))
    )


def _numeric_is_finite(name: str) -> pl.Expr:
    """Return a typed finite-number predicate for a Polars column."""
    return pl.col(name).is_not_null() & pl.col(name).is_finite()


def _count_ambiguous_strike_sides(valid_quotes: pl.DataFrame) -> int:
    """Count valid strike-side groups that still map to more than one quote identity."""
    return int(
        valid_quotes.group_by(list(_STRIKE_SIDE_COLUMNS))
        .agg(pl.len().alias("quote_count"))
        .filter(pl.col("quote_count") > 1)
        .height
    )


def _build_same_strike_pairs(valid_quotes: pl.DataFrame) -> pl.DataFrame:
    """Join one valid call and put midpoint at each exact strike and expiry."""
    pair_columns = [*_EXPIRY_COLUMNS, "strike"]
    calls = valid_quotes.filter(pl.col("option_type") == "call").select(
        [*pair_columns, pl.col("midpoint").alias("call_midpoint")]
    )
    puts = valid_quotes.filter(pl.col("option_type") == "put").select(
        [*pair_columns, pl.col("midpoint").alias("put_midpoint")]
    )
    return calls.join(puts, on=pair_columns, how="inner").with_columns(
        (pl.col("call_midpoint") - pl.col("put_midpoint")).alias("put_call_parity_value")
    )


def _build_expiry_diagnostics(pairs: pl.DataFrame) -> pl.DataFrame:
    """Calculate one endpoint-slope discount diagnostic for each origin and expiry."""
    if pairs.is_empty():
        return pl.DataFrame(
            schema={
                **{column: pl.String for column in _EXPIRY_COLUMNS[:-1]},
                "forecast_origin_ns": pl.Int64,
                "expiry": pl.String,
                "paired_strike_count": pl.Int64,
                "discount_factor": pl.Float64,
            }
        )
    return (
        pairs.group_by(list(_EXPIRY_COLUMNS))
        .agg(
            pl.len().alias("paired_strike_count"),
            pl.col("strike").min().alias("lowest_strike"),
            pl.col("strike").max().alias("highest_strike"),
            pl.col("put_call_parity_value").sort_by("strike").first().alias("lowest_strike_parity"),
            pl.col("put_call_parity_value").sort_by("strike").last().alias("highest_strike_parity"),
        )
        .with_columns(
            pl.when(pl.col("paired_strike_count") >= 2)
            .then(
                (pl.col("lowest_strike_parity") - pl.col("highest_strike_parity"))
                / (pl.col("highest_strike") - pl.col("lowest_strike"))
            )
            .otherwise(None)
            .alias("discount_factor")
        )
    )


def _unique_origin_count(frame: pl.DataFrame) -> int:
    """Return the number of distinct forecast origins represented by a frame."""
    if frame.is_empty():
        return 0
    return frame.select(list(_ORIGIN_COLUMNS)).unique().height


def _fraction(numerator: int, denominator: int) -> float:
    """Return a finite coverage ratio, with zero for an empty origin set."""
    return 0.0 if denominator == 0 else numerator / denominator


def _quantile_or_none(frame: pl.DataFrame, column: str, quantile: float) -> float | None:
    """Return a finite numeric quantile or ``None`` when no valid estimate exists."""
    if frame.is_empty():
        return None
    result = frame.select(pl.col(column).quantile(quantile)).item()
    if result is None or not isinstance(result, (int, float)) or not math.isfinite(float(result)):
        return None
    return float(result)


def _by_asset(
    origins: pl.DataFrame,
    pairs: pl.DataFrame,
    two_strike_expiries: pl.DataFrame,
    valid_discount_expiries: pl.DataFrame,
) -> list[dict[str, object]]:
    """Summarize target-free parity geometry by asset without exposing row-level quotes."""
    records: list[dict[str, object]] = []
    for asset in origins.get_column("asset").unique().sort().to_list():
        if not isinstance(asset, str):
            raise ValueError("B1Q_PARITY_ASSET_INVALID")
        asset_origins = origins.filter(pl.col("asset") == asset)
        origin_count = asset_origins.height
        any_pair = _unique_origin_count(pairs.filter(pl.col("asset") == asset))
        two_strikes = _unique_origin_count(two_strike_expiries.filter(pl.col("asset") == asset))
        valid_discount = _unique_origin_count(
            valid_discount_expiries.filter(pl.col("asset") == asset)
        )
        records.append(
            {
                "asset": asset,
                "origin_count": origin_count,
                "origins_with_any_pair": any_pair,
                "origins_with_two_strike_expiry": two_strikes,
                "origins_with_valid_discount_estimate": valid_discount,
                "origin_coverage_any_pair": _fraction(any_pair, origin_count),
                "origin_coverage_two_strike_expiry": _fraction(two_strikes, origin_count),
                "origin_coverage_valid_discount_estimate": _fraction(valid_discount, origin_count),
            }
        )
    return records
