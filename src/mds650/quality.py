"""Explicit, non-destructive data-quality accounting."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from math import isfinite
from typing import Any, cast


@dataclass(frozen=True, slots=True)
class QualityReport:
    """Counts and ratios needed by the quality gate."""

    row_count: int
    duplicate_key_count: int
    critical_null_count: int
    completeness_ratio: float
    schema_mismatch_count: int = 0
    invalid_ohlc_count: int = 0


def assess_rows(
    rows: Sequence[Mapping[str, object]],
    *,
    key_fields: tuple[str, ...],
    required_fields: tuple[str, ...],
    expected_rows: int,
    expected_fields: tuple[str, ...] = (),
    ohlc_fields: tuple[str, str, str, str] | None = None,
) -> QualityReport:
    """Count duplicate keys, required nulls, and expected-row completeness.

    Parameters
    ----------
    rows:
        Normalized row mappings. They are never modified.
    key_fields, required_fields:
        Fields used for duplicate and critical-null accounting.
    expected_rows:
        Positive expected count for the validated session window.
    expected_fields:
        Optional exact normalized schema. A row with missing or unexpected fields
        increments ``schema_mismatch_count`` and is never repaired.
    ohlc_fields:
        Optional ``(open, high, low, close)`` field names for relationship checks.

    Returns
    -------
    QualityReport
        Deterministic quality counts.

    Raises
    ------
    ValueError
        If no key or required fields are supplied, or ``expected_rows`` is not
        positive.
    """
    if not key_fields or not required_fields or expected_rows <= 0:
        raise ValueError("QUALITY_CONFIGURATION_INVALID")
    keys = [tuple(row.get(field) for field in key_fields) for row in rows]
    duplicate_key_count = sum(count - 1 for count in Counter(keys).values() if count > 1)
    critical_null_count = sum(
        1 for row in rows if any(row.get(field) is None for field in required_fields)
    )
    expected_schema = set(expected_fields)
    schema_mismatch_count = (
        sum(1 for row in rows if set(row) != expected_schema) if expected_fields else 0
    )
    invalid_ohlc_count = 0
    if ohlc_fields is not None:
        open_field, high_field, low_field, close_field = ohlc_fields
        for row in rows:
            try:
                opening, high, low, close = (
                    float(cast(Any, row[open_field])),
                    float(cast(Any, row[high_field])),
                    float(cast(Any, row[low_field])),
                    float(cast(Any, row[close_field])),
                )
                valid = all(isfinite(value) and value > 0 for value in (opening, high, low, close))
                valid = valid and low <= min(opening, close) and high >= max(opening, close)
            except (KeyError, TypeError, ValueError):
                valid = False
            if not valid:
                invalid_ohlc_count += 1
    ratio = min(len(rows) / expected_rows, 1.0)
    if not isfinite(ratio):
        raise ValueError("QUALITY_RATIO_INVALID")
    return QualityReport(
        row_count=len(rows),
        duplicate_key_count=duplicate_key_count,
        critical_null_count=critical_null_count,
        completeness_ratio=ratio,
        schema_mismatch_count=schema_mismatch_count,
        invalid_ohlc_count=invalid_ohlc_count,
    )
