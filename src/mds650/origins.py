"""Construction of point-in-time five-minute forecast origins."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from mds650.contracts import ForecastOrigin
from mds650.time import align_five_minute_origin, is_regular_session_minute, to_new_york, to_utc


def build_forecast_origins(
    *,
    asset: str,
    timestamps: Sequence[datetime],
    run_id: str,
    source_trace_ids: Sequence[str],
    event_times: Sequence[datetime],
    event_window_minutes: int = 5,
) -> list[ForecastOrigin]:
    """Build unique five-minute origins using only information at the cutoff.

    Parameters
    ----------
    asset, run_id:
        Candidate asset and run provenance.
    timestamps:
        Aware market timestamps available for origin construction.
    source_trace_ids:
        Raw-response identifiers carried to every origin.
    event_times:
        Aware event timestamps. An event is present only in the interval ending
        at the origin and never because of a future observation.
    event_window_minutes:
        Positive lookback window used to label event presence.

    Returns
    -------
    list[ForecastOrigin]
        Chronologically sorted, deduplicated origins.

    Raises
    ------
    ValueError
        If a timestamp is naive, the event window is non-positive, or a supplied
        timestamp is outside a regular session/five-minute boundary.
    """
    if event_window_minutes <= 0:
        raise ValueError("ORIGIN_EVENT_WINDOW_INVALID")
    normalized_events = [to_utc(event) for event in event_times]
    origins: list[ForecastOrigin] = []
    seen: set[datetime] = set()
    trace_ids = list(source_trace_ids)
    source_response_id = trace_ids[0] if trace_ids else "derived"
    for timestamp in timestamps:
        aware_timestamp = to_utc(timestamp)
        local_timestamp = to_new_york(aware_timestamp)
        if not is_regular_session_minute(aware_timestamp):
            continue
        if (
            local_timestamp.minute % 5 != 0
            or local_timestamp.second != 0
            or local_timestamp.microsecond != 0
        ):
            continue
        origin = align_five_minute_origin(aware_timestamp).astimezone(UTC)
        if origin in seen:
            continue
        seen.add(origin)
        window_start = origin - timedelta(minutes=event_window_minutes)
        present = any(window_start < event <= origin for event in normalized_events)
        origins.append(
            ForecastOrigin(
                run_id=run_id,
                source_provider="derived",
                source_response_id=source_response_id,
                observed_at_utc=origin,
                origin_id=f"{asset}:{origin.isoformat()}",
                asset=asset,
                origin_start_utc=origin,
                predictor_cutoff_utc=origin,
                event_presence=present,
                source_trace_ids=trace_ids,
            )
        )
    return sorted(origins, key=lambda item: item.origin_start_utc)
