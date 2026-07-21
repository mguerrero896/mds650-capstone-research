"""Timezone and regular-session invariants for market timestamps."""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

NEW_YORK = ZoneInfo("America/New_York")
SESSION_OPEN = time(9, 30)
SESSION_CLOSE = time(16, 0)


def parse_market_timestamp(
    value: str | datetime,
    source_timezone: str | None = None,
) -> datetime:
    """Parse a provider timestamp and return a timezone-aware datetime.

    Parameters
    ----------
    value:
        ISO-8601 or ``YYYY-MM-DD HH:MM:SS`` string, or an aware datetime.
    source_timezone:
        IANA timezone required when ``value`` is naive. It must not be guessed.

    Returns
    -------
    datetime
        The original instant with timezone information attached.

    Raises
    ------
    ValueError
        If parsing fails or a naive value lacks an explicit source timezone.
    """
    if isinstance(value, str):
        normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError as exc:
            raise ValueError("TIMESTAMP_INVALID_FORMAT") from exc
    else:
        parsed = value
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        if source_timezone is None:
            raise ValueError("TIMESTAMP_TIMEZONE_REQUIRED")
        try:
            parsed = parsed.replace(tzinfo=ZoneInfo(source_timezone))
        except Exception as exc:  # zoneinfo raises different platform errors
            raise ValueError("TIMESTAMP_INVALID_TIMEZONE") from exc
    return parsed


def to_utc(value: datetime) -> datetime:
    """Convert an aware datetime to UTC without changing the instant.

    Raises
    ------
    ValueError
        If ``value`` is naive.
    """
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("TIMESTAMP_TIMEZONE_REQUIRED")
    return value.astimezone(UTC)


def to_new_york(value: datetime) -> datetime:
    """Render an aware datetime in ``America/New_York``.

    Raises
    ------
    ValueError
        If ``value`` is naive.
    """
    return to_utc(value).astimezone(NEW_YORK)


def is_regular_session_minute(value: datetime) -> bool:
    """Return whether a timestamp falls in a weekday regular session.

    Notes
    -----
    This pure clock check does not encode exchange holidays. Holiday validation
    belongs to the provider calendar contract.
    """
    local = to_new_york(value)
    return local.weekday() < 5 and SESSION_OPEN <= local.time() < SESSION_CLOSE


def align_five_minute_origin(value: datetime) -> datetime:
    """Validate and return a five-minute regular-session forecast origin.

    Raises
    ------
    ValueError
        If the timestamp is outside regular hours or not on a five-minute
        boundary with zero seconds and microseconds.
    """
    local = to_new_york(value)
    if not is_regular_session_minute(value):
        raise ValueError("ORIGIN_OUTSIDE_REGULAR_SESSION")
    if local.minute % 5 != 0 or local.second != 0 or local.microsecond != 0:
        raise ValueError("ORIGIN_NOT_FIVE_MINUTE_BOUNDARY")
    return value


def session_date(value: datetime) -> date:
    """Return the New York exchange session date for an aware timestamp."""
    return to_new_york(value).date()
