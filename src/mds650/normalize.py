"""Provider-row normalization with explicit schema and duplicate gates."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, cast

from mds650.contracts import UnderlyingBar
from mds650.errors import QualityGateError, SchemaDriftError
from mds650.time import parse_market_timestamp

_FMP_UNDERLYING_FIELDS = frozenset({"date", "open", "low", "high", "close", "volume"})


def normalize_underlying_bars(
    rows: Sequence[Mapping[str, object]],
    *,
    asset: str,
    run_id: str,
    source_response_id: str,
    source_timezone: str | None,
) -> list[UnderlyingBar]:
    """Normalize FMP one-minute OHLCV rows without silent repair.

    Parameters
    ----------
    rows:
        Raw FMP row mappings. The exact six-field schema is required.
    asset, run_id, source_response_id:
        Provenance identifiers retained on each normalized record.
    source_timezone:
        Explicit IANA timezone for FMP's naive timestamp strings.

    Returns
    -------
    list[UnderlyingBar]
        UTC-canonical bars with computed New York renderings.

    Raises
    ------
    SchemaDriftError
        If any row has missing or unexpected FMP fields.
    QualityGateError
        If two rows share the ``(asset, bar_start_utc)`` key.
    ValueError
        If timestamp, price, volume, or timezone validation fails.

    Examples
    --------
    ``normalize_underlying_bars(rows, asset="SPY", run_id="r", ... )``
    produces one auditable record per unique market minute.
    """
    normalized: list[UnderlyingBar] = []
    seen: set[tuple[str, object]] = set()
    for row in rows:
        if set(row) != _FMP_UNDERLYING_FIELDS:
            raise SchemaDriftError("FMP_UNDERLYING_SCHEMA_DRIFT")
        timestamp = parse_market_timestamp(str(row["date"]), source_timezone=source_timezone)
        bar = UnderlyingBar(
            run_id=run_id,
            source_provider="fmp",
            source_response_id=source_response_id,
            observed_at_utc=timestamp,
            asset=asset,
            bar_start_utc=timestamp,
            open=_as_float(row["open"]),
            high=_as_float(row["high"]),
            low=_as_float(row["low"]),
            close=_as_float(row["close"]),
            volume=None if row["volume"] is None else _as_float(row["volume"]),
        )
        key = (bar.asset, bar.bar_start_utc)
        if key in seen:
            raise QualityGateError("DUPLICATE_UNDERLYING_BAR")
        seen.add(key)
        normalized.append(bar)
    return normalized


def _as_float(value: object) -> float:
    try:
        return float(cast(Any, value))
    except (TypeError, ValueError) as exc:
        raise ValueError("NUMERIC_VALUE_INVALID") from exc
