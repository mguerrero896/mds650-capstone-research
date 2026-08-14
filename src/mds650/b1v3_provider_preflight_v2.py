"""Target-blind contracts for the B1v3 date-level provider preflight.

This module contains deterministic plan, storage, and response-validation
primitives only.  Network transport is intentionally implemented by a thin
script after these contracts pass their focused tests.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from importlib import import_module
from pathlib import Path
from typing import Final, Protocol, cast
from zoneinfo import ZoneInfo

from mds650.date_level_pit_preflight_v1 import derive_forecast_origin

MIN_FREE_BYTES: Final[int] = 80 * 1024**3
MAX_MASSIVE_SEARCH_PAGES: Final[int] = 3
PRIMARY_QUOTE_AGE_SECONDS: Final[float] = 60.0
PRIMARY_RELATIVE_SPREAD: Final[float] = 0.25
SENSITIVITY_QUOTE_AGE_SECONDS: Final[float] = 300.0
SENSITIVITY_RELATIVE_SPREAD: Final[float] = 0.50
EXPECTED_ASSET_COUNT: Final[int] = 8
EXPECTED_TRAINING_SESSIONS: Final[int] = 60
EXPECTED_CONFIRMATION_SESSIONS: Final[int] = 30
NEW_YORK: Final[ZoneInfo] = ZoneInfo("America/New_York")

_FORBIDDEN_KEYS: Final[frozenset[str]] = frozenset(
    {
        "rv30",
        "qlike",
        "prediction",
        "predictions",
        "loss",
        "losses",
        "residual",
        "residuals",
        "outcome",
        "outcomes",
        "target_value",
        "target_values",
    }
)


class B1V3PreflightError(RuntimeError):
    """Fail-closed error for an invalid B1v3 provider preflight contract."""


class _SessionCalendar(Protocol):
    def is_session(self, session: str) -> bool: ...

    def session_open(self, session: str) -> datetime: ...

    def session_close(self, session: str) -> datetime: ...


class _SchemaValidator(Protocol):
    def is_valid(self, instance: object) -> bool: ...


class _SchemaValidatorClass(Protocol):
    FORMAT_CHECKER: object

    def __call__(
        self,
        schema: Mapping[str, object],
        *,
        format_checker: object,
    ) -> _SchemaValidator: ...

    def check_schema(self, schema: Mapping[str, object]) -> None: ...


@dataclass(frozen=True, slots=True)
class CandidateSession:
    """One target-blind XNYS session and its standardized midday origin."""

    date: str
    role: str
    open_utc: str
    close_utc: str
    forecast_origin_utc: str
    forecast_origin_ns: int
    expected_regular_minutes: int


@dataclass(frozen=True, slots=True)
class CandidatePreflightPlan:
    """Exact 60/30 candidate plan bound before any target or metric read."""

    schema_version: str
    status: str
    target_blind: bool
    outcome_read_count: int
    assets: tuple[str, ...]
    sessions: tuple[CandidateSession, ...]
    training_session_count: int
    confirmation_session_count: int
    source_confirmation_plan_sha256: str
    plan_sha256: str

    def to_mapping(self) -> dict[str, object]:
        """Return the complete deterministic mapping, including its self-hash."""
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "target_blind": self.target_blind,
            "outcome_read_count": self.outcome_read_count,
            "assets": list(self.assets),
            "sessions": [asdict(session) for session in self.sessions],
            "training_session_count": self.training_session_count,
            "confirmation_session_count": self.confirmation_session_count,
            "source_confirmation_plan_sha256": self.source_confirmation_plan_sha256,
            "plan_sha256": self.plan_sha256,
        }

    def to_canonical_json(self) -> bytes:
        """Serialize the plan byte-deterministically for hashing and evidence."""
        return canonical_json(self.to_mapping())


@dataclass(frozen=True, slots=True)
class RequestBudget:
    """Hard HTTP-attempt budget for exact asset/session dimensions."""

    asset_count: int
    session_count: int
    fmp_requests: int
    uw_requests: int
    massive_initial_search_requests: int
    massive_search_request_cap: int
    massive_reference_requests: int
    massive_quote_requests: int
    http_attempt_cap: int


@dataclass(frozen=True, slots=True)
class FmpSessionEvidence:
    """Sanitized exact-session validation for one FMP asset-date response."""

    status: str
    returned_row_count: int
    exact_session_row_count: int
    provider_over_return_count: int
    duplicate_timestamp_count: int
    spot: float
    bar_availability_assumption: str
    pit_claim: bool


@dataclass(frozen=True, slots=True)
class UwZipEvidence:
    """Sanitized Full Tape response metadata without downloading its body."""

    status: str
    content_length_bytes: int
    content_type: str
    request_id: str | None
    full_tape_downloaded: bool
    pit_claim: bool


@dataclass(frozen=True, slots=True)
class MassiveQuoteEvidence:
    """Sanitized source-time quote-as-of validation for one contract."""

    status: str
    contract_id: str
    sip_timestamp_ns: int
    quote_age_seconds: float
    relative_spread: float
    bid: float
    ask: float
    primary_filter_pass: bool
    sensitivity_filter_pass: bool
    pit_receipt_claim: bool


def canonical_json(value: object) -> bytes:
    """Serialize a JSON-compatible value deterministically.

    Parameters
    ----------
    value
        JSON-compatible value without non-finite numbers.

    Returns
    -------
    bytes
        Canonical UTF-8 JSON representation.
    """
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def validate_json_schema(
    instance: object,
    *,
    schema_path: Path,
    error_code: str,
) -> None:
    """Validate an artifact against a Draft 2020-12 JSON Schema.

    The runtime package does not expose typing metadata, so this function keeps
    the dynamic import behind a minimal checked protocol instead of relaxing
    type checking across the project.
    """
    try:
        decoded: object = json.loads(schema_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise B1V3PreflightError(f"{error_code}_SCHEMA_UNAVAILABLE") from exc
    if not isinstance(decoded, dict):
        raise B1V3PreflightError(f"{error_code}_SCHEMA_INVALID")
    schema = cast(Mapping[str, object], decoded)
    try:
        module = import_module("jsonschema")
        raw_validator = getattr(module, "Draft202012Validator", None)
        if raw_validator is None:
            raise AttributeError("Draft202012Validator")
        validator_class = cast(_SchemaValidatorClass, raw_validator)
        validator_class.check_schema(schema)
        validator = validator_class(
            schema,
            format_checker=validator_class.FORMAT_CHECKER,
        )
    except Exception as exc:
        raise B1V3PreflightError(f"{error_code}_SCHEMA_INVALID") from exc
    if not validator.is_valid(instance):
        raise B1V3PreflightError(f"{error_code}_SCHEMA_VALIDATION_FAILED")


def build_candidate_preflight_plan(
    confirmation_plan: Mapping[str, object],
    *,
    assets: Sequence[str],
    calendar_sessions: Sequence[Mapping[str, object]],
) -> CandidatePreflightPlan:
    """Bind an exact target-blind 60/30 plan to calendar-derived sessions.

    Parameters
    ----------
    confirmation_plan
        Metadata-only B1v3 confirmation plan. Result-like keys are prohibited.
    assets
        Eight audited provider assets in deterministic order.
    calendar_sessions
        Ninety ordered XNYS session mappings matching the 60/30 arrays.

    Returns
    -------
    CandidatePreflightPlan
        Self-hashed plan containing no outcome or metric value.

    Raises
    ------
    B1V3PreflightError
        If dimensions, dates, calendar metadata, or target-blind boundaries fail.
    """
    _reject_forbidden_keys(confirmation_plan)
    declared_source_hash = confirmation_plan.get("plan_sha256")
    source_without_hash = {
        key: value for key, value in confirmation_plan.items() if key != "plan_sha256"
    }
    observed_source_hash = hashlib.sha256(canonical_json(source_without_hash)).hexdigest()
    if declared_source_hash != observed_source_hash:
        raise B1V3PreflightError("B1V3_PREFLIGHT_CONFIRMATION_PLAN_HASH_INVALID")
    training = _string_sequence(confirmation_plan.get("training_sessions"))
    confirmation = _string_sequence(confirmation_plan.get("confirmation_sessions"))
    source_hash = declared_source_hash
    if (
        confirmation_plan.get("status") != "PENDING_DATE_LEVEL_PROVIDER_PREFLIGHT"
        or confirmation_plan.get("target_blind") is not True
        or confirmation_plan.get("outcome_read_count") != 0
        or confirmation_plan.get("training_session_count") != EXPECTED_TRAINING_SESSIONS
        or confirmation_plan.get("confirmation_session_count") != EXPECTED_CONFIRMATION_SESSIONS
        or len(training) != EXPECTED_TRAINING_SESSIONS
        or len(confirmation) != EXPECTED_CONFIRMATION_SESSIONS
        or len(set((*training, *confirmation))) != 90
        or not isinstance(source_hash, str)
        or len(source_hash) != 64
    ):
        raise B1V3PreflightError("B1V3_PREFLIGHT_CONFIRMATION_PLAN_INVALID")
    asset_tuple = tuple(assets)
    if (
        len(asset_tuple) != EXPECTED_ASSET_COUNT
        or len(set(asset_tuple)) != EXPECTED_ASSET_COUNT
        or any(not asset or asset != asset.upper() for asset in asset_tuple)
    ):
        raise B1V3PreflightError("B1V3_PREFLIGHT_ASSET_UNIVERSE_INVALID")
    expected_dates = (*training, *confirmation)
    if len(calendar_sessions) != len(expected_dates):
        raise B1V3PreflightError("B1V3_PREFLIGHT_CALENDAR_DIMENSIONS_INVALID")
    sessions: list[CandidateSession] = []
    paired_sessions = zip(expected_dates, calendar_sessions, strict=True)
    for index, (expected_date, raw) in enumerate(paired_sessions):
        if raw.get("date") != expected_date:
            raise B1V3PreflightError("B1V3_PREFLIGHT_CALENDAR_DATE_MISMATCH")
        role = "training_warmup" if index < EXPECTED_TRAINING_SESSIONS else "confirmation"
        session = _candidate_session(raw, role=role)
        sessions.append(session)
    base: dict[str, object] = {
        "schema_version": "b1v3-date-level-pit-preflight-plan-2.0",
        "status": "FROZEN_TARGET_BLIND_PENDING_PROVIDER_EXECUTION",
        "target_blind": True,
        "outcome_read_count": 0,
        "assets": list(asset_tuple),
        "sessions": [asdict(session) for session in sessions],
        "training_session_count": EXPECTED_TRAINING_SESSIONS,
        "confirmation_session_count": EXPECTED_CONFIRMATION_SESSIONS,
        "source_confirmation_plan_sha256": source_hash,
    }
    digest = hashlib.sha256(canonical_json(base)).hexdigest()
    return CandidatePreflightPlan(
        schema_version=cast(str, base["schema_version"]),
        status=cast(str, base["status"]),
        target_blind=True,
        outcome_read_count=0,
        assets=asset_tuple,
        sessions=tuple(sessions),
        training_session_count=EXPECTED_TRAINING_SESSIONS,
        confirmation_session_count=EXPECTED_CONFIRMATION_SESSIONS,
        source_confirmation_plan_sha256=source_hash,
        plan_sha256=digest,
    )


def derive_xnys_calendar_sessions(
    session_dates: Sequence[str],
) -> tuple[dict[str, object], ...]:
    """Derive exact XNYS bounds and one five-minute-aligned midday origin.

    Parameters
    ----------
    session_dates
        Ordered ISO market dates already selected without outcomes.

    Returns
    -------
    tuple[dict[str, object], ...]
        Calendar-only session mappings consumed by
        :func:`build_candidate_preflight_plan`.

    Raises
    ------
    B1V3PreflightError
        If a date is duplicated, not an XNYS session, or has invalid bounds.
    """
    dates = tuple(session_dates)
    if not dates or len(set(dates)) != len(dates):
        raise B1V3PreflightError("B1V3_PREFLIGHT_CALENDAR_DATES_INVALID")
    try:
        module = import_module("exchange_calendars")
        get_calendar = cast(Callable[[str], _SessionCalendar], module.get_calendar)
        calendar = get_calendar("XNYS")
    except Exception as exc:
        raise B1V3PreflightError("B1V3_PREFLIGHT_CALENDAR_UNAVAILABLE") from exc
    sessions: list[dict[str, object]] = []
    for session_date in dates:
        if not isinstance(session_date, str) or not calendar.is_session(session_date):
            raise B1V3PreflightError("B1V3_PREFLIGHT_NOT_XNYS_SESSION")
        opened = calendar.session_open(session_date).astimezone(UTC)
        closed = calendar.session_close(session_date).astimezone(UTC)
        duration_minutes = int((closed - opened).total_seconds() // 60)
        origin = derive_forecast_origin(
            {"open_utc": opened.isoformat(), "close_utc": closed.isoformat()}
        )
        sessions.append(
            {
                "date": session_date,
                "open_utc": opened.isoformat(),
                "close_utc": closed.isoformat(),
                "forecast_origin_utc": origin.forecast_origin_utc,
                "forecast_origin_ns": origin.forecast_origin_ns,
                "expected_regular_minutes": duration_minutes,
            }
        )
    return tuple(sessions)


def build_request_budget(*, asset_count: int, session_count: int) -> RequestBudget:
    """Compute the exact inclusive HTTP-attempt cap for a bounded preflight.

    Massive receives at most three contract-search requests per asset-day,
    followed by at most one reference and one quote. Retries spend the same
    global cap rather than increasing it.
    """
    if (
        isinstance(asset_count, bool)
        or not isinstance(asset_count, int)
        or asset_count < 1
        or isinstance(session_count, bool)
        or not isinstance(session_count, int)
        or session_count < 1
    ):
        raise B1V3PreflightError("B1V3_PREFLIGHT_BUDGET_DIMENSIONS_INVALID")
    asset_days = asset_count * session_count
    fmp = asset_days
    uw = session_count
    massive_initial = asset_days
    massive_search_cap = asset_days * MAX_MASSIVE_SEARCH_PAGES
    reference = asset_days
    quote = asset_days
    return RequestBudget(
        asset_count=asset_count,
        session_count=session_count,
        fmp_requests=fmp,
        uw_requests=uw,
        massive_initial_search_requests=massive_initial,
        massive_search_request_cap=massive_search_cap,
        massive_reference_requests=reference,
        massive_quote_requests=quote,
        http_attempt_cap=fmp + uw + massive_search_cap + reference + quote,
    )


def validate_storage_gate(*, free_bytes: int) -> None:
    """Fail before network access when the Samsung data drive has under 80 GiB."""
    if (
        isinstance(free_bytes, bool)
        or not isinstance(free_bytes, int)
        or free_bytes < MIN_FREE_BYTES
    ):
        raise B1V3PreflightError("B1V3_PREFLIGHT_STORAGE_GATE_FAILED")


def validate_fmp_session(
    payload: object,
    *,
    session_date: str,
    expected_minutes: int,
    forecast_origin_utc: datetime,
) -> FmpSessionEvidence:
    """Validate an exact FMP session under the registered +1-minute rule.

    Extra provider dates are counted and excluded. The function does not claim
    that the provider has contractually confirmed bar-label or publication
    semantics.
    """
    if (
        not isinstance(payload, list)
        or not all(isinstance(row, Mapping) for row in payload)
        or isinstance(expected_minutes, bool)
        or not isinstance(expected_minutes, int)
        or expected_minutes < 1
        or forecast_origin_utc.tzinfo is None
    ):
        raise B1V3PreflightError("B1V3_PREFLIGHT_FMP_SCHEMA_INVALID")
    exact: list[tuple[datetime, float]] = []
    returned_timestamps: list[str] = []
    for row in payload:
        raw_timestamp = row.get("date")
        if not isinstance(raw_timestamp, str):
            raise B1V3PreflightError("B1V3_PREFLIGHT_FMP_TIMESTAMP_INVALID")
        returned_timestamps.append(raw_timestamp)
        if not raw_timestamp.startswith(f"{session_date} "):
            continue
        try:
            local_timestamp = datetime.strptime(raw_timestamp, "%Y-%m-%d %H:%M:%S").replace(
                tzinfo=NEW_YORK
            )
            open_value = _finite_number(row.get("open"))
            high = _finite_number(row.get("high"))
            low = _finite_number(row.get("low"))
            close = _finite_number(row.get("close"))
        except (TypeError, ValueError) as exc:
            raise B1V3PreflightError("B1V3_PREFLIGHT_FMP_ROW_INVALID") from exc
        if min(open_value, high, low, close) <= 0 or high < max(open_value, close, low):
            raise B1V3PreflightError("B1V3_PREFLIGHT_FMP_OHLC_INVALID")
        if low > min(open_value, close, high):
            raise B1V3PreflightError("B1V3_PREFLIGHT_FMP_OHLC_INVALID")
        exact.append((local_timestamp, close))
    unique_timestamp_count = len({timestamp for timestamp, _ in exact})
    duplicate_count = len(exact) - unique_timestamp_count
    if duplicate_count or len(exact) != expected_minutes:
        raise B1V3PreflightError("B1V3_PREFLIGHT_FMP_EXACT_SESSION_INCOMPLETE")
    origin_utc = forecast_origin_utc.astimezone(UTC)
    eligible = [
        (timestamp, close)
        for timestamp, close in exact
        if (timestamp + timedelta(minutes=1)).astimezone(UTC) <= origin_utc
    ]
    if not eligible:
        raise B1V3PreflightError("B1V3_PREFLIGHT_FMP_SPOT_UNAVAILABLE")
    _, spot = max(eligible, key=lambda item: item[0])
    return FmpSessionEvidence(
        status="PASS_EXACT_SESSION_AVAILABILITY",
        returned_row_count=len(returned_timestamps),
        exact_session_row_count=len(exact),
        provider_over_return_count=len(returned_timestamps) - len(exact),
        duplicate_timestamp_count=duplicate_count,
        spot=spot,
        bar_availability_assumption="timestamp_raw_plus_1_minute",
        pit_claim=False,
    )


def validate_uw_zip_headers(
    *,
    status_code: int,
    headers: Mapping[str, str],
    method: str,
    request_headers: Mapping[str, str],
) -> UwZipEvidence:
    """Validate documented UW Full Tape GET metadata without reading the ZIP body."""
    normalized_request = {key.lower(): value for key, value in request_headers.items()}
    if "range" in normalized_request or status_code == 206:
        raise B1V3PreflightError("B1V3_PREFLIGHT_UW_UNDOCUMENTED_RANGE")
    normalized = {key.lower(): value for key, value in headers.items()}
    content_type = normalized.get("content-type", "").split(";", maxsplit=1)[0].strip().lower()
    raw_length = normalized.get("content-length")
    try:
        content_length = int(raw_length) if raw_length is not None else 0
    except ValueError as exc:
        raise B1V3PreflightError("B1V3_PREFLIGHT_UW_CONTENT_LENGTH_INVALID") from exc
    if (
        method != "GET"
        or normalized_request.get("accept") != "application/json"
        or status_code != 200
        or content_type != "application/zip"
        or content_length <= 0
    ):
        raise B1V3PreflightError("B1V3_PREFLIGHT_UW_RESPONSE_INVALID")
    request_id = normalized.get("x-request-id") or normalized.get("request-id")
    return UwZipEvidence(
        status="PASS_TRANSPORT_METADATA_ONLY",
        content_length_bytes=content_length,
        content_type=content_type,
        request_id=request_id,
        full_tape_downloaded=False,
        pit_claim=False,
    )


def validate_massive_quote(
    payload: object,
    *,
    forecast_origin_ns: int,
    contract_id: str,
) -> MassiveQuoteEvidence:
    """Validate a source-time quote and report freshness filters separately.

    A technically valid historical NBBO proves contract/quote availability.
    The 60-second/25% primary and 300-second/50% sensitivity filters are
    downstream B1 coverage attributes; they do not redefine provider access.
    """
    if (
        not isinstance(payload, Mapping)
        or not contract_id.startswith("O:")
        or isinstance(forecast_origin_ns, bool)
        or not isinstance(forecast_origin_ns, int)
        or len(str(forecast_origin_ns)) != 19
    ):
        raise B1V3PreflightError("B1V3_PREFLIGHT_MASSIVE_QUOTE_SCHEMA_INVALID")
    results = payload.get("results")
    if not isinstance(results, list) or len(results) != 1 or not isinstance(results[0], Mapping):
        raise B1V3PreflightError("B1V3_PREFLIGHT_MASSIVE_QUOTE_MISSING")
    row = results[0]
    sip_timestamp = row.get("sip_timestamp")
    if isinstance(sip_timestamp, bool) or not isinstance(sip_timestamp, int):
        raise B1V3PreflightError("B1V3_PREFLIGHT_MASSIVE_SIP_TIMESTAMP_INVALID")
    if sip_timestamp > forecast_origin_ns:
        raise B1V3PreflightError("B1V3_PREFLIGHT_MASSIVE_FUTURE_QUOTE")
    try:
        bid = _finite_number(row.get("bid_price"))
        ask = _finite_number(row.get("ask_price"))
    except (TypeError, ValueError) as exc:
        raise B1V3PreflightError("B1V3_PREFLIGHT_MASSIVE_NBBO_INVALID") from exc
    if bid <= 0.0 or ask <= bid:
        raise B1V3PreflightError("B1V3_PREFLIGHT_MASSIVE_NBBO_INVALID")
    midpoint = (bid + ask) / 2.0
    relative_spread = (ask - bid) / midpoint
    quote_age = (forecast_origin_ns - sip_timestamp) / 1_000_000_000
    primary_filter_pass = (
        quote_age <= PRIMARY_QUOTE_AGE_SECONDS and relative_spread <= PRIMARY_RELATIVE_SPREAD
    )
    sensitivity_filter_pass = (
        quote_age <= SENSITIVITY_QUOTE_AGE_SECONDS
        and relative_spread <= SENSITIVITY_RELATIVE_SPREAD
    )
    return MassiveQuoteEvidence(
        status="PASS_QUOTE_ASOF_SOURCE_TIME",
        contract_id=contract_id,
        sip_timestamp_ns=sip_timestamp,
        quote_age_seconds=quote_age,
        relative_spread=relative_spread,
        bid=bid,
        ask=ask,
        primary_filter_pass=primary_filter_pass,
        sensitivity_filter_pass=sensitivity_filter_pass,
        pit_receipt_claim=False,
    )


def _candidate_session(raw: Mapping[str, object], *, role: str) -> CandidateSession:
    required_strings = ("date", "open_utc", "close_utc", "forecast_origin_utc")
    if not all(isinstance(raw.get(key), str) and raw.get(key) for key in required_strings):
        raise B1V3PreflightError("B1V3_PREFLIGHT_CALENDAR_SESSION_INVALID")
    origin_ns = raw.get("forecast_origin_ns")
    expected_minutes = raw.get("expected_regular_minutes")
    if (
        isinstance(origin_ns, bool)
        or not isinstance(origin_ns, int)
        or len(str(origin_ns)) != 19
        or isinstance(expected_minutes, bool)
        or not isinstance(expected_minutes, int)
        or expected_minutes not in {210, 390}
    ):
        raise B1V3PreflightError("B1V3_PREFLIGHT_CALENDAR_SESSION_INVALID")
    try:
        open_utc = datetime.fromisoformat(cast(str, raw["open_utc"])).astimezone(UTC)
        close_utc = datetime.fromisoformat(cast(str, raw["close_utc"])).astimezone(UTC)
        origin_utc = datetime.fromisoformat(cast(str, raw["forecast_origin_utc"])).astimezone(UTC)
    except ValueError as exc:
        raise B1V3PreflightError("B1V3_PREFLIGHT_CALENDAR_SESSION_INVALID") from exc
    derived_origin_ns = int(origin_utc.timestamp() * 1_000_000_000)
    if not open_utc < origin_utc < close_utc or derived_origin_ns != origin_ns:
        raise B1V3PreflightError("B1V3_PREFLIGHT_CALENDAR_SESSION_INVALID")
    return CandidateSession(
        date=cast(str, raw["date"]),
        role=role,
        open_utc=open_utc.isoformat(),
        close_utc=close_utc.isoformat(),
        forecast_origin_utc=origin_utc.isoformat(),
        forecast_origin_ns=origin_ns,
        expected_regular_minutes=expected_minutes,
    )


def _reject_forbidden_keys(value: object) -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            lowered = str(key).lower()
            permitted_control = lowered in {"outcome_read_count", "target_blind"}
            if not permitted_control and (
                lowered in _FORBIDDEN_KEYS
                or any(
                    lowered.startswith(f"{prefix}_")
                    for prefix in ("rv30", "qlike", "prediction", "residual", "outcome")
                )
            ):
                raise B1V3PreflightError("B1V3_PREFLIGHT_FORBIDDEN_FIELD")
            _reject_forbidden_keys(nested)
    elif isinstance(value, list | tuple):
        for nested in value:
            _reject_forbidden_keys(nested)


def _string_sequence(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise B1V3PreflightError("B1V3_PREFLIGHT_CONFIRMATION_PLAN_INVALID")
    return tuple(value)


def _finite_number(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError("not numeric")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("not finite")
    return number
