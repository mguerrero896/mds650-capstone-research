"""Target-blind construction of the owner-approved B1v3 option-state benchmark.

The module consumes quote/IV attempts that are already associated with a forecast
origin.  It never reads realized variance, predictions, losses, or result files.
Legacy B1v2 behavior remains untouched in :mod:`mds650.phase6`.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any, Final, Literal
from zoneinfo import ZoneInfo

import polars as pl

B1V3A_FEATURES: Final[tuple[str, ...]] = (
    "b1v3_log_atm_variance_30d",
    "b1v3_log_atm_variance_change_5m",
    "b1v3_log_atm_variance_change_30m",
)
B1V3B_FEATURES: Final[tuple[str, ...]] = (
    "b1v3_log_symmetric_skew_30d",
    "b1v3_log_symmetric_skew_change_30m",
)
B1V3C_FEATURES: Final[tuple[str, ...]] = (
    "b1v3_log_forward_variance_short_medium",
    "b1v3_log_forward_variance_medium_long",
    "b1v3_log_forward_variance_short_medium_change_30m",
    "b1v3_log_forward_variance_medium_long_change_30m",
)
B1V3_FEATURES: Final[tuple[str, ...]] = (
    *B1V3A_FEATURES,
    *B1V3B_FEATURES,
    *B1V3C_FEATURES,
)

_HASH_RE: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}$")
_NEW_YORK: Final[ZoneInfo] = ZoneInfo("America/New_York")
_VALID_DIVIDEND_ASSUMPTIONS: Final[frozenset[str]] = frozenset(
    {"NO_PRE_ORIGIN_DIVIDEND_Q_ZERO", "PRE_ORIGIN_TRAILING_DECLARATIONS"}
)
_REQUIRED_INPUT_COLUMNS: Final[frozenset[str]] = frozenset(
    {
        "origin_id",
        "asset",
        "session_date",
        "forecast_origin_utc",
        "forecast_origin_ns",
        "contract",
        "expiry",
        "strike",
        "option_type",
        "dte",
        "spot",
        "moneyness",
        "target_moneyness",
        "rate",
        "rate_source_date",
        "dividend_yield",
        "dividend_assumption",
        "source_request_hash",
        "iv_success",
        "iv",
        "failure_reason",
        "sip_timestamp",
        "bid",
        "ask",
        "quote_age_seconds",
        "relative_spread",
        "midpoint",
    }
)
_OPTIONAL_INPUT_COLUMNS: Final[frozenset[str]] = frozenset(
    {
        "bucket",
        "reference_request_id",
        "instrument_type",
        "iterations",
        "lower_bound",
        "upper_bound",
        "fmp_delay_minutes",
        "quote_cutoff_seconds",
        "sequence_number",
        "session_tercile",
    }
)
_FORBIDDEN_COLUMN_FRAGMENTS: Final[tuple[str, ...]] = (
    "rv30",
    "qlike",
    "prediction",
    "predicted",
    "outcome",
    "residual",
    "loss",
    "model_result",
)


@dataclass(frozen=True, slots=True)
class IvObservation:
    """One target-free point-in-time contract IV observation.

    Parameters
    ----------
    contract:
        Exact OCC-style contract identifier.
    expiry:
        Contract expiration date.
    strike:
        Positive strike price.
    option_type:
        ``"call"`` or ``"put"``.
    dte:
        Calendar days to expiration at the forecast origin.
    spot:
        Positive underlying spot at the forecast origin.
    iv:
        Positive finite implied volatility.
    sip_timestamp_ns:
        Nanosecond SIP timestamp of the selected quote.
    source_request_hash:
        Lower-case SHA-256 of the source request/evidence identity.

    Raises
    ------
    ValueError
        The consuming function raises when any field is invalid or ambiguous.
    """

    contract: str
    expiry: date
    strike: float
    option_type: Literal["call", "put"] | str
    dte: int
    spot: float
    iv: float
    sip_timestamp_ns: int
    source_request_hash: str


@dataclass(frozen=True, slots=True)
class ConsensusPoint:
    """Same-expiry/same-strike arithmetic call-put IV consensus."""

    expiry: date
    dte: int
    strike: float
    moneyness: float
    iv: float
    call_contract: str
    put_contract: str
    max_sip_timestamp_ns: int
    source_request_hashes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class InterpolatedIv:
    """An ATM IV estimate with deterministic interpolation provenance."""

    iv: float
    expiry: date
    dte: int
    interpolated: bool
    lower_strike: float
    upper_strike: float
    max_sip_timestamp_ns: int
    source_request_hashes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SkewEstimate:
    """Same-expiry symmetric OTM put/call log-skew estimate."""

    put_iv: float
    call_iv: float
    log_skew: float
    put_interpolated: bool
    call_interpolated: bool
    source_request_hashes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CoverageMetric:
    """Coverage rates and their registered threshold decision."""

    global_coverage: float
    minimum_asset_coverage: float
    minimum_tercile_coverage: float
    passed: bool


@dataclass(frozen=True, slots=True)
class B1v3CoverageDecision:
    """Nested B1v3 technical coverage decision, independent of outcomes."""

    status: str
    b1v3a: CoverageMetric
    b1v3b: CoverageMetric
    b1v3c: CoverageMetric


@dataclass(frozen=True, slots=True)
class _SideIv:
    iv: float
    interpolated: bool
    source_request_hashes: tuple[str, ...]


def _validate_observation(row: IvObservation) -> None:
    if not row.contract.strip():
        raise ValueError("B1V3_CONTRACT_EMPTY")
    if row.option_type not in {"call", "put"}:
        raise ValueError("B1V3_OPTION_TYPE_INVALID")
    if row.dte <= 0:
        raise ValueError("B1V3_DTE_INVALID")
    if not math.isfinite(row.strike) or row.strike <= 0:
        raise ValueError("B1V3_STRIKE_INVALID")
    if not math.isfinite(row.spot) or row.spot <= 0:
        raise ValueError("B1V3_SPOT_INVALID")
    if not math.isfinite(row.iv) or row.iv <= 0:
        raise ValueError("B1V3_IV_INVALID")
    if row.sip_timestamp_ns <= 0:
        raise ValueError("B1V3_SIP_TIMESTAMP_INVALID")
    if not _HASH_RE.fullmatch(row.source_request_hash):
        raise ValueError("B1V3_SOURCE_REQUEST_HASH_INVALID")


def pair_call_put_consensus(rows: Sequence[IvObservation]) -> tuple[ConsensusPoint, ...]:
    """Pair call and put IVs only when expiry and strike are identical.

    Parameters
    ----------
    rows:
        Valid target-free contract observations for one forecast origin.

    Returns
    -------
    tuple[ConsensusPoint, ...]
        Deterministically sorted consensus points. Unpaired strikes are omitted.

    Raises
    ------
    ValueError
        If an observation is invalid, a side is duplicated, or paired metadata
        disagree.

    Examples
    --------
    Two observations with identical expiry/strike and opposite option types
    produce one point whose IV is their arithmetic mean.
    """
    grouped: dict[tuple[date, float], dict[str, IvObservation]] = {}
    for row in rows:
        _validate_observation(row)
        key = (row.expiry, row.strike)
        sides = grouped.setdefault(key, {})
        if row.option_type in sides:
            raise ValueError("B1V3_DUPLICATE_OPTION_SIDE")
        sides[row.option_type] = row

    points: list[ConsensusPoint] = []
    for (expiry, strike), sides in grouped.items():
        call = sides.get("call")
        put = sides.get("put")
        if call is None or put is None:
            continue
        if call.dte != put.dte or not math.isclose(call.spot, put.spot, rel_tol=0.0, abs_tol=1e-9):
            raise ValueError("B1V3_PAIRED_METADATA_MISMATCH")
        hashes = tuple(sorted({call.source_request_hash, put.source_request_hash}))
        points.append(
            ConsensusPoint(
                expiry=expiry,
                dte=call.dte,
                strike=strike,
                moneyness=strike / call.spot,
                iv=(call.iv + put.iv) / 2.0,
                call_contract=call.contract,
                put_contract=put.contract,
                max_sip_timestamp_ns=max(call.sip_timestamp_ns, put.sip_timestamp_ns),
                source_request_hashes=hashes,
            )
        )
    return tuple(
        sorted(
            points,
            key=lambda point: (
                point.dte,
                point.expiry,
                point.strike,
                point.call_contract,
                point.put_contract,
            ),
        )
    )


def _combine_point_provenance(points: Sequence[ConsensusPoint]) -> tuple[int, tuple[str, ...]]:
    return (
        max(point.max_sip_timestamp_ns for point in points),
        tuple(sorted({value for point in points for value in point.source_request_hashes})),
    )


def _interpolate_consensus_at_atm(
    points: Sequence[ConsensusPoint],
    *,
    max_nearest_log_moneyness: float,
) -> InterpolatedIv | None:
    exact = [point for point in points if math.isclose(point.moneyness, 1.0, abs_tol=1e-12)]
    if exact:
        point = min(exact, key=lambda item: (item.call_contract, item.put_contract))
        return InterpolatedIv(
            iv=point.iv,
            expiry=point.expiry,
            dte=point.dte,
            interpolated=False,
            lower_strike=point.strike,
            upper_strike=point.strike,
            max_sip_timestamp_ns=point.max_sip_timestamp_ns,
            source_request_hashes=point.source_request_hashes,
        )

    lower = [point for point in points if point.moneyness < 1.0]
    upper = [point for point in points if point.moneyness > 1.0]
    if lower and upper:
        low = max(lower, key=lambda point: (point.moneyness, point.strike))
        high = min(upper, key=lambda point: (point.moneyness, point.strike))
        x_low = math.log(low.moneyness)
        x_high = math.log(high.moneyness)
        weight = -x_low / (x_high - x_low)
        max_sip, hashes = _combine_point_provenance((low, high))
        return InterpolatedIv(
            iv=low.iv + weight * (high.iv - low.iv),
            expiry=low.expiry,
            dte=low.dte,
            interpolated=True,
            lower_strike=low.strike,
            upper_strike=high.strike,
            max_sip_timestamp_ns=max_sip,
            source_request_hashes=hashes,
        )

    nearest = min(
        points,
        key=lambda point: (
            abs(math.log(point.moneyness)),
            point.strike,
            point.call_contract,
            point.put_contract,
        ),
        default=None,
    )
    if nearest is None or abs(math.log(nearest.moneyness)) > max_nearest_log_moneyness:
        return None
    return InterpolatedIv(
        iv=nearest.iv,
        expiry=nearest.expiry,
        dte=nearest.dte,
        interpolated=False,
        lower_strike=nearest.strike,
        upper_strike=nearest.strike,
        max_sip_timestamp_ns=nearest.max_sip_timestamp_ns,
        source_request_hashes=nearest.source_request_hashes,
    )


def select_atm_iv(
    points: Sequence[ConsensusPoint],
    *,
    spot: float,
    target_dte: int = 30,
    tolerance: int = 10,
    minimum_dte: int = 1,
) -> InterpolatedIv | None:
    """Select one tenor and estimate ATM consensus IV in log moneyness.

    Parameters
    ----------
    points:
        Same-expiry/same-strike call-put consensus points.
    spot:
        Positive spot used to validate point moneyness.
    target_dte:
        Registered target tenor in calendar days.
    tolerance:
        Maximum absolute distance from ``target_dte``.
    minimum_dte:
        Hard lower DTE bound; the short bucket uses seven.

    Returns
    -------
    InterpolatedIv | None
        Deterministic ATM estimate or ``None`` when no valid expiry/strike
        geometry is available.

    Raises
    ------
    ValueError
        If arguments or consensus metadata are invalid.
    """
    if not math.isfinite(spot) or spot <= 0:
        raise ValueError("B1V3_SPOT_INVALID")
    if target_dte <= 0 or tolerance < 0 or minimum_dte <= 0:
        raise ValueError("B1V3_TENOR_ARGUMENT_INVALID")
    eligible = [
        point
        for point in points
        if point.dte >= minimum_dte and abs(point.dte - target_dte) <= tolerance
    ]
    if not eligible:
        return None
    for point in eligible:
        if not math.isclose(point.moneyness, point.strike / spot, rel_tol=0.0, abs_tol=1e-9):
            raise ValueError("B1V3_CONSENSUS_SPOT_MISMATCH")
    selected_expiry = min(
        eligible,
        key=lambda point: (
            abs(point.dte - target_dte),
            point.expiry,
            point.call_contract,
            point.put_contract,
        ),
    ).expiry
    expiry_points = [point for point in eligible if point.expiry == selected_expiry]
    dtes = {point.dte for point in expiry_points}
    if len(dtes) != 1:
        raise ValueError("B1V3_EXPIRY_DTE_AMBIGUOUS")
    return _interpolate_consensus_at_atm(
        expiry_points,
        max_nearest_log_moneyness=abs(math.log(1.025)),
    )


def _interpolate_side_iv(
    rows: Sequence[IvObservation],
    *,
    expiry: date,
    option_type: Literal["call", "put"],
    target_moneyness: float,
    spot: float,
) -> _SideIv | None:
    candidates: dict[float, IvObservation] = {}
    for row in rows:
        if row.expiry != expiry or row.option_type != option_type:
            continue
        _validate_observation(row)
        if not math.isclose(row.spot, spot, rel_tol=0.0, abs_tol=1e-9):
            raise ValueError("B1V3_SKEW_SPOT_MISMATCH")
        if row.strike in candidates:
            raise ValueError("B1V3_DUPLICATE_SKEW_STRIKE")
        candidates[row.strike] = row
    if not candidates:
        return None
    ordered = sorted(candidates.values(), key=lambda row: (row.strike, row.contract))
    target_x = math.log(target_moneyness)
    exact = [
        row for row in ordered if math.isclose(row.strike / spot, target_moneyness, abs_tol=1e-12)
    ]
    if exact:
        row = exact[0]
        return _SideIv(row.iv, False, (row.source_request_hash,))

    lower = [row for row in ordered if row.strike / spot < target_moneyness]
    upper = [row for row in ordered if row.strike / spot > target_moneyness]
    if lower and upper:
        low = max(lower, key=lambda row: row.strike)
        high = min(upper, key=lambda row: row.strike)
        x_low = math.log(low.strike / spot)
        x_high = math.log(high.strike / spot)
        weight = (target_x - x_low) / (x_high - x_low)
        return _SideIv(
            low.iv + weight * (high.iv - low.iv),
            True,
            tuple(sorted({low.source_request_hash, high.source_request_hash})),
        )

    nearest = min(
        ordered,
        key=lambda row: (abs(row.strike / spot - target_moneyness), row.strike, row.contract),
    )
    if abs(nearest.strike / spot - target_moneyness) > 0.0125:
        return None
    return _SideIv(nearest.iv, False, (nearest.source_request_hash,))


def select_symmetric_skew(
    rows: Sequence[IvObservation],
    *,
    expiry: date,
    spot: float,
) -> SkewEstimate | None:
    """Estimate registered same-expiry symmetric put/call log skew.

    Parameters
    ----------
    rows:
        Target-free contract observations for one origin.
    expiry:
        The already-selected near-30-day expiry.
    spot:
        Positive spot at that origin.

    Returns
    -------
    SkewEstimate | None
        Log put/call IV ratio or ``None`` if either side is unavailable.

    Raises
    ------
    ValueError
        If duplicate or inconsistent side observations are present.
    """
    put = _interpolate_side_iv(
        rows,
        expiry=expiry,
        option_type="put",
        target_moneyness=0.975,
        spot=spot,
    )
    call = _interpolate_side_iv(
        rows,
        expiry=expiry,
        option_type="call",
        target_moneyness=1.025,
        spot=spot,
    )
    if put is None or call is None or put.iv <= 0 or call.iv <= 0:
        return None
    return SkewEstimate(
        put_iv=put.iv,
        call_iv=call.iv,
        log_skew=math.log(put.iv / call.iv),
        put_interpolated=put.interpolated,
        call_interpolated=call.interpolated,
        source_request_hashes=tuple(
            sorted({*put.source_request_hashes, *call.source_request_hashes})
        ),
    )


def compute_forward_variance(left: InterpolatedIv, right: InterpolatedIv) -> float | None:
    """Compute positive forward variance from ordered total variances.

    Parameters
    ----------
    left, right:
        ATM IV tenor states with ``left.dte < right.dte``.

    Returns
    -------
    float | None
        Positive finite forward variance, otherwise ``None``. Invalid values
        are never clipped.
    """
    if left.dte >= right.dte:
        return None
    left_time = left.dte / 365.0
    right_time = right.dte / 365.0
    left_total = left.iv**2 * left_time
    right_total = right.iv**2 * right_time
    if not all(math.isfinite(value) for value in (left_total, right_total)):
        return None
    if right_total < left_total:
        return None
    value = (right_total - left_total) / (right_time - left_time)
    return value if math.isfinite(value) and value > 0 else None


def _parse_date(value: object, *, code: str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(code) from exc
    raise ValueError(code)


def _parse_utc(value: object) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("B1V3_ORIGIN_TIMESTAMP_INVALID") from exc
    else:
        raise ValueError("B1V3_ORIGIN_TIMESTAMP_INVALID")
    if parsed.tzinfo is None:
        raise ValueError("B1V3_ORIGIN_TIMESTAMP_INVALID")
    return parsed.astimezone(UTC)


def _session_tercile(origin: datetime) -> str:
    local = origin.astimezone(_NEW_YORK)
    minute = (local.hour * 60 + local.minute) - (9 * 60 + 30)
    if minute < 0:
        raise ValueError("B1V3_ORIGIN_OUTSIDE_REGULAR_SESSION")
    if minute < 130:
        return "first"
    if minute < 260:
        return "middle"
    return "last"


def _validate_input_columns(columns: Sequence[str]) -> None:
    missing = sorted(_REQUIRED_INPUT_COLUMNS - set(columns))
    if missing:
        raise ValueError(f"B1V3_INPUT_SCHEMA_INVALID:{','.join(missing)}")
    allowed = _REQUIRED_INPUT_COLUMNS | _OPTIONAL_INPUT_COLUMNS
    for column in columns:
        lower = column.lower()
        if column == "target_moneyness":
            continue
        if lower.startswith("target") or any(
            token in lower for token in _FORBIDDEN_COLUMN_FRAGMENTS
        ):
            raise ValueError(f"B1V3_FORBIDDEN_INPUT_COLUMN:{column}")
        if column not in allowed:
            raise ValueError(f"B1V3_INPUT_COLUMN_NOT_ALLOWLISTED:{column}")


def _as_finite_float(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    converted = float(value)
    return converted if math.isfinite(converted) else None


def _row_to_observation(
    row: Mapping[str, Any],
    *,
    cutoff_ns: int,
    session_date: date,
) -> tuple[IvObservation | None, str | None]:
    sip = row.get("sip_timestamp")
    if not isinstance(sip, int):
        return None, "SIP_TIMESTAMP_INVALID"
    if sip > cutoff_ns:
        raise ValueError("B1V3_FUTURE_QUOTE")
    age = (cutoff_ns - sip) / 1_000_000_000
    if age < 0 or age > 60:
        return None, "STALE_QUOTE"
    bid = _as_finite_float(row.get("bid"))
    ask = _as_finite_float(row.get("ask"))
    if bid is None or ask is None or bid <= 0 or ask <= bid:
        return None, "INVALID_SELECTED_SPREAD"
    midpoint = (bid + ask) / 2.0
    relative_spread = (ask - bid) / midpoint
    if relative_spread > 0.25:
        return None, "INVALID_SELECTED_SPREAD"
    if row.get("iv_success") is not True:
        return None, str(row.get("failure_reason") or "IV_NOT_SUCCESSFUL")
    iv = _as_finite_float(row.get("iv"))
    strike = _as_finite_float(row.get("strike"))
    spot = _as_finite_float(row.get("spot"))
    dte = row.get("dte")
    if iv is None or iv <= 0:
        return None, "IV_INVALID"
    if strike is None or strike <= 0 or spot is None or spot <= 0:
        return None, "CONTRACT_GEOMETRY_INVALID"
    if not isinstance(dte, int) or dte <= 0:
        return None, "DTE_INVALID"
    rate_date = _parse_date(row.get("rate_source_date"), code="B1V3_RATE_SOURCE_DATE_INVALID")
    if rate_date >= session_date:
        raise ValueError("B1V3_RATE_NOT_PRE_ORIGIN")
    assumption = row.get("dividend_assumption")
    if assumption not in _VALID_DIVIDEND_ASSUMPTIONS:
        raise ValueError("B1V3_DIVIDEND_ASSUMPTION_INVALID")
    expiry = _parse_date(row.get("expiry"), code="B1V3_EXPIRY_INVALID")
    if expiry <= session_date:
        return None, "EXPIRY_NOT_AFTER_ORIGIN"
    option_type = row.get("option_type")
    if option_type not in {"call", "put"}:
        raise ValueError("B1V3_OPTION_TYPE_INVALID")
    source_hash = row.get("source_request_hash")
    if not isinstance(source_hash, str):
        raise ValueError("B1V3_SOURCE_REQUEST_HASH_INVALID")
    observation = IvObservation(
        contract=str(row.get("contract", "")),
        expiry=expiry,
        strike=strike,
        option_type=option_type,
        dte=dte,
        spot=spot,
        iv=iv,
        sip_timestamp_ns=sip,
        source_request_hash=source_hash,
    )
    _validate_observation(observation)
    return observation, None


def _log_positive(value: float | None) -> float | None:
    return math.log(value) if value is not None and math.isfinite(value) and value > 0 else None


def _origin_level(
    rows: Sequence[Mapping[str, Any]], *, quote_cutoff_seconds: int
) -> dict[str, Any]:
    first = rows[0]
    origin_id = str(first["origin_id"])
    asset = str(first["asset"])
    session = _parse_date(first["session_date"], code="B1V3_SESSION_DATE_INVALID")
    origin = _parse_utc(first["forecast_origin_utc"])
    origin_ns = first["forecast_origin_ns"]
    if not isinstance(origin_ns, int) or origin_ns != int(origin.timestamp() * 1_000_000_000):
        raise ValueError("B1V3_ORIGIN_NS_MISMATCH")
    cutoff_ns = origin_ns - quote_cutoff_seconds * 1_000_000_000
    expected_metadata = (origin_id, asset, session.isoformat(), origin_ns)
    observations: list[IvObservation] = []
    failure_reasons: list[str] = []
    seen_contracts: set[str] = set()
    for row in rows:
        metadata = (
            str(row["origin_id"]),
            str(row["asset"]),
            _parse_date(row["session_date"], code="B1V3_SESSION_DATE_INVALID").isoformat(),
            row["forecast_origin_ns"],
        )
        if metadata != expected_metadata:
            raise ValueError("B1V3_ORIGIN_METADATA_INCONSISTENT")
        contract = str(row["contract"])
        if contract in seen_contracts:
            raise ValueError("B1V3_AMBIGUOUS_CONTRACT_ORIGIN")
        seen_contracts.add(contract)
        observation, reason = _row_to_observation(row, cutoff_ns=cutoff_ns, session_date=session)
        if observation is not None:
            observations.append(observation)
        elif reason is not None:
            failure_reasons.append(reason)

    consensus = pair_call_put_consensus(observations)
    spot_values = {row.spot for row in observations}
    if len(spot_values) > 1:
        raise ValueError("B1V3_ORIGIN_SPOT_AMBIGUOUS")
    spot = next(iter(spot_values), _as_finite_float(first.get("spot")))
    if spot is None or spot <= 0:
        raise ValueError("B1V3_SPOT_INVALID")
    medium = select_atm_iv(consensus, spot=spot)
    short = select_atm_iv(consensus, spot=spot, target_dte=7, tolerance=7, minimum_dte=7)
    long = select_atm_iv(consensus, spot=spot, target_dte=90, tolerance=30, minimum_dte=60)
    skew = (
        select_symmetric_skew(observations, expiry=medium.expiry, spot=spot)
        if medium is not None
        else None
    )
    short_medium = (
        compute_forward_variance(short, medium)
        if short is not None and medium is not None
        else None
    )
    medium_long = (
        compute_forward_variance(medium, long) if medium is not None and long is not None else None
    )
    level_reason = None
    if medium is None:
        level_reason = "ATM_STATE_MISSING"
    elif skew is None:
        level_reason = "SKEW_STATE_MISSING"
    elif short is None or long is None:
        level_reason = "TERM_TENOR_MISSING"
    elif short_medium is None or medium_long is None:
        level_reason = "FORWARD_VARIANCE_INVALID"
    elif failure_reasons:
        level_reason = sorted(failure_reasons)[0]

    configured_tercile = first.get("session_tercile")
    derived_tercile = _session_tercile(origin)
    if configured_tercile is not None and configured_tercile != derived_tercile:
        raise ValueError("B1V3_SESSION_TERCILE_MISMATCH")
    source_hashes = tuple(sorted({row.source_request_hash for row in observations}))
    return {
        "origin_id": origin_id,
        "asset": asset,
        "session_date": session.isoformat(),
        "forecast_origin_utc": origin.isoformat(),
        "forecast_origin_ns": origin_ns,
        "session_tercile": derived_tercile,
        "quote_cutoff_seconds": quote_cutoff_seconds,
        "valid_contract_count": len(observations),
        "valid_consensus_point_count": len(consensus),
        "max_sip_timestamp_ns": max((row.sip_timestamp_ns for row in observations), default=None),
        "source_request_hashes": list(source_hashes),
        "atm_expiry": medium.expiry.isoformat() if medium else None,
        "atm_dte": medium.dte if medium else None,
        "atm_interpolated": medium.interpolated if medium else None,
        "skew_put_interpolated": skew.put_interpolated if skew else None,
        "skew_call_interpolated": skew.call_interpolated if skew else None,
        "short_dte": short.dte if short else None,
        "medium_dte": medium.dte if medium else None,
        "long_dte": long.dte if long else None,
        "b1v3_log_atm_variance_30d": _log_positive(medium.iv**2) if medium else None,
        "b1v3_log_symmetric_skew_30d": skew.log_skew if skew else None,
        "b1v3_log_forward_variance_short_medium": _log_positive(short_medium),
        "b1v3_log_forward_variance_medium_long": _log_positive(medium_long),
        "b1v3_level_missing_reason": level_reason,
    }


def _level_change(
    current: Mapping[str, Any],
    previous: Mapping[str, Any] | None,
    feature: str,
) -> float | None:
    current_value = _as_finite_float(current.get(feature))
    previous_value = _as_finite_float(previous.get(feature)) if previous is not None else None
    return (
        current_value - previous_value
        if current_value is not None and previous_value is not None
        else None
    )


def build_b1v3_features(
    attempts: pl.DataFrame,
    *,
    quote_cutoff_seconds: int = 0,
) -> pl.DataFrame:
    """Build one target-blind B1v3 row per forecast origin.

    Parameters
    ----------
    attempts:
        Target-free per-origin IV attempts with the approved source schema.
    quote_cutoff_seconds:
        Registered Massive cutoff shift. The existing attempt corpus is valid
        only for zero; non-zero inputs must explicitly carry the matching
        ``quote_cutoff_seconds`` selection identity.

    Returns
    -------
    polars.DataFrame
        Deterministically ordered origin rows, nine B1v3 features, diagnostics
        and nested completeness flags.

    Raises
    ------
    ValueError
        If schemas, target-blind boundaries, timing, provenance, duplicate
        identities or nested invariants fail.

    Examples
    --------
    ``build_b1v3_features(attempts)`` builds the primary origin-cutoff variant.
    """
    if attempts.is_empty():
        raise ValueError("B1V3_EMPTY_INPUT")
    if quote_cutoff_seconds not in {0, 60, 300}:
        raise ValueError("B1V3_QUOTE_CUTOFF_INVALID")
    _validate_input_columns(attempts.columns)
    if quote_cutoff_seconds != 0:
        if "quote_cutoff_seconds" not in attempts.columns:
            raise ValueError("B1V3_SHIFTED_RESELECTION_IDENTITY_REQUIRED")
        values = set(attempts["quote_cutoff_seconds"].drop_nulls().to_list())
        if values != {quote_cutoff_seconds}:
            raise ValueError("B1V3_SHIFTED_RESELECTION_IDENTITY_MISMATCH")
    if "fmp_delay_minutes" in attempts.columns:
        fmp_delay = attempts["fmp_delay_minutes"]
        values = set(fmp_delay.drop_nulls().to_list())
        if values and (fmp_delay.null_count() or values not in ({1}, {2})):
            raise ValueError("B1V3_FMP_DELAY_IDENTITY_INVALID")

    order = [
        "asset",
        "session_date",
        "forecast_origin_ns",
        "origin_id",
        "expiry",
        "strike",
        "option_type",
        "contract",
    ]
    sorted_attempts = attempts.sort(order)
    levels: list[dict[str, Any]] = []
    current_origin: str | None = None
    current_rows: list[Mapping[str, Any]] = []
    for row in sorted_attempts.iter_rows(named=True):
        origin_id = str(row["origin_id"])
        if current_origin is not None and origin_id != current_origin:
            levels.append(_origin_level(current_rows, quote_cutoff_seconds=quote_cutoff_seconds))
            current_rows = []
        current_origin = origin_id
        current_rows.append(row)
    if current_rows:
        levels.append(_origin_level(current_rows, quote_cutoff_seconds=quote_cutoff_seconds))

    if len({str(row["origin_id"]) for row in levels}) != len(levels):
        raise ValueError("B1V3_DUPLICATE_ORIGIN")
    by_time = {
        (str(row["asset"]), str(row["session_date"]), int(row["forecast_origin_ns"])): row
        for row in levels
    }
    output: list[dict[str, Any]] = []
    for row in levels:
        key = (str(row["asset"]), str(row["session_date"]))
        origin_ns = int(row["forecast_origin_ns"])
        prior_5 = by_time.get((*key, origin_ns - 5 * 60 * 1_000_000_000))
        prior_30 = by_time.get((*key, origin_ns - 30 * 60 * 1_000_000_000))
        enriched = {
            **row,
            "b1v3_log_atm_variance_change_5m": _level_change(
                row, prior_5, "b1v3_log_atm_variance_30d"
            ),
            "b1v3_log_atm_variance_change_30m": _level_change(
                row, prior_30, "b1v3_log_atm_variance_30d"
            ),
            "b1v3_log_symmetric_skew_change_30m": _level_change(
                row, prior_30, "b1v3_log_symmetric_skew_30d"
            ),
            "b1v3_log_forward_variance_short_medium_change_30m": _level_change(
                row, prior_30, "b1v3_log_forward_variance_short_medium"
            ),
            "b1v3_log_forward_variance_medium_long_change_30m": _level_change(
                row, prior_30, "b1v3_log_forward_variance_medium_long"
            ),
        }
        enriched["b1v3a_complete"] = all(
            _as_finite_float(enriched.get(feature)) is not None for feature in B1V3A_FEATURES
        )
        enriched["b1v3b_complete"] = bool(enriched["b1v3a_complete"]) and all(
            _as_finite_float(enriched.get(feature)) is not None for feature in B1V3B_FEATURES
        )
        enriched["b1v3c_complete"] = bool(enriched["b1v3b_complete"]) and all(
            _as_finite_float(enriched.get(feature)) is not None for feature in B1V3C_FEATURES
        )
        enriched["b1v3_missing_reason"] = (
            None
            if enriched["b1v3a_complete"]
            else (
                "B1V3A_EXACT_LAG_MISSING"
                if enriched.get("b1v3_log_atm_variance_30d") is not None
                else str(enriched.get("b1v3_level_missing_reason") or "B1V3A_STATE_MISSING")
            )
        )
        output.append(enriched)

    frame = pl.DataFrame(output, infer_schema_length=None, strict=False).sort(
        ["asset", "session_date", "forecast_origin_ns", "origin_id"]
    )
    if frame.filter(
        pl.col("max_sip_timestamp_ns").is_not_null()
        & (
            pl.col("max_sip_timestamp_ns")
            > pl.col("forecast_origin_ns") - pl.col("quote_cutoff_seconds") * 1_000_000_000
        )
    ).height:
        raise ValueError("B1V3_FUTURE_QUOTE")
    if frame.filter(pl.col("b1v3c_complete") & ~pl.col("b1v3b_complete")).height:
        raise ValueError("B1V3_NESTED_ROW_INVARIANT_FAILURE")
    if frame.filter(pl.col("b1v3b_complete") & ~pl.col("b1v3a_complete")).height:
        raise ValueError("B1V3_NESTED_ROW_INVARIANT_FAILURE")
    return frame


def _coverage_metric(
    frame: pl.DataFrame,
    *,
    column: str,
    global_minimum: float,
    asset_minimum: float,
    tercile_minimum: float,
) -> CoverageMetric:
    global_value = frame[column].mean()
    asset_value = (
        frame.group_by("asset").agg(pl.col(column).mean().alias("coverage"))["coverage"].min()
    )
    tercile_value = (
        frame.group_by("session_tercile")
        .agg(pl.col(column).mean().alias("coverage"))["coverage"]
        .min()
    )
    if not isinstance(global_value, int | float):
        raise ValueError("B1V3_COVERAGE_UNDEFINED")
    if not isinstance(asset_value, int | float):
        raise ValueError("B1V3_COVERAGE_UNDEFINED")
    if not isinstance(tercile_value, int | float):
        raise ValueError("B1V3_COVERAGE_UNDEFINED")
    global_coverage = float(global_value)
    minimum_asset = float(asset_value)
    minimum_tercile = float(tercile_value)
    return CoverageMetric(
        global_coverage=global_coverage,
        minimum_asset_coverage=minimum_asset,
        minimum_tercile_coverage=minimum_tercile,
        passed=(
            global_coverage >= global_minimum
            and minimum_asset >= asset_minimum
            and minimum_tercile >= tercile_minimum
        ),
    )


def summarize_b1v3_coverage(frame: pl.DataFrame) -> B1v3CoverageDecision:
    """Apply registered nested B1v3 technical coverage gates.

    Parameters
    ----------
    frame:
        One row per target-blind origin with nested completion flags.

    Returns
    -------
    B1v3CoverageDecision
        Global, minimum-asset and minimum-tercile coverage plus a technical
        feasibility status. It contains no forecasting-performance statement.

    Raises
    ------
    ValueError
        If required dimensions are absent or nested coverage is inconsistent
        globally or within an asset/date/tercile/cutoff subgroup.
    """
    required = {
        "asset",
        "session_date",
        "session_tercile",
        "quote_cutoff_seconds",
        "b1v3a_complete",
        "b1v3b_complete",
        "b1v3c_complete",
    }
    if frame.is_empty() or not required.issubset(frame.columns):
        raise ValueError("B1V3_COVERAGE_SCHEMA_INVALID")
    if frame.filter(pl.col("b1v3c_complete") & ~pl.col("b1v3b_complete")).height:
        raise ValueError("B1V3_NESTED_COVERAGE_VIOLATION")
    if frame.filter(pl.col("b1v3b_complete") & ~pl.col("b1v3a_complete")).height:
        raise ValueError("B1V3_NESTED_COVERAGE_VIOLATION")
    group_dimensions = (
        ["asset"],
        ["session_date"],
        ["session_tercile"],
        ["quote_cutoff_seconds"],
    )
    for dimensions in group_dimensions:
        grouped = frame.group_by(dimensions).agg(
            pl.col("b1v3a_complete").mean().alias("a"),
            pl.col("b1v3b_complete").mean().alias("b"),
            pl.col("b1v3c_complete").mean().alias("c"),
        )
        if grouped.filter((pl.col("c") > pl.col("b")) | (pl.col("b") > pl.col("a"))).height:
            raise ValueError("B1V3_NESTED_COVERAGE_VIOLATION")

    b1v3a = _coverage_metric(
        frame,
        column="b1v3a_complete",
        global_minimum=0.80,
        asset_minimum=0.65,
        tercile_minimum=0.60,
    )
    b1v3b = _coverage_metric(
        frame,
        column="b1v3b_complete",
        global_minimum=0.70,
        asset_minimum=0.50,
        tercile_minimum=0.40,
    )
    b1v3c = _coverage_metric(
        frame,
        column="b1v3c_complete",
        global_minimum=0.70,
        asset_minimum=0.50,
        tercile_minimum=0.40,
    )
    if not b1v3a.passed:
        status = "REVISE_B1V3"
    elif b1v3b.passed and b1v3c.passed:
        status = "PASS_B1V3A_WITH_ENRICHED_ROBUSTNESS"
    else:
        status = "PASS_B1V3A_ONLY"
    return B1v3CoverageDecision(status=status, b1v3a=b1v3a, b1v3b=b1v3b, b1v3c=b1v3c)
