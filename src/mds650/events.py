"""Point-in-time corporate-event controls and optional-news gating."""

from __future__ import annotations

from collections.abc import Sequence

from mds650.contracts import CorporateEvent, ForecastOrigin
from mds650.errors import PITError

ETF_ASSETS = frozenset({"SPY", "QQQ"})


def earnings_instrument_contract(asset: str) -> dict[str, object]:
    """Return the frozen ex-ante earnings contract for an asset.

    Parameters
    ----------
    asset:
        Candidate underlying symbol.

    Returns
    -------
    dict[str, object]
        Instrument type and applicability fields. ETF earnings are never
        synthesized; dividends/distributions are separate IV inputs.

    Raises
    ------
    ValueError
        If ``asset`` is outside the ratified candidate universe.
    """
    if asset not in {"SPY", "QQQ", "AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "META"}:
        raise ValueError("ASSET_NOT_IN_CANDIDATE_UNIVERSE")
    if asset in ETF_ASSETS:
        return {
            "instrument_type": "ETF",
            "earnings_applicable": False,
            "earnings_bmo_today": 0,
            "earnings_amc_today": 0,
            "days_to_next_earnings": None,
        }
    return {
        "instrument_type": "equity",
        "earnings_applicable": True,
        "earnings_bmo_today": 0,
        "earnings_amc_today": 0,
        "days_to_next_earnings": None,
    }


def eligible_earnings_events(
    origin: ForecastOrigin,
    events: Sequence[CorporateEvent],
) -> tuple[CorporateEvent, ...]:
    """Return earnings records observable no later than an origin cutoff.

    Date-only and unresolved records are excluded rather than forward-filled,
    because they cannot establish an intraday point-in-time release.

    Parameters
    ----------
    origin:
        Forecast origin providing asset and predictor cutoff.
    events:
        Structured corporate events to screen.

    Returns
    -------
    tuple[CorporateEvent, ...]
        Chronologically ordered events eligible as controls.
    """
    if origin.asset in ETF_ASSETS:
        return ()
    eligible = [
        event
        for event in events
        if event.asset == origin.asset
        and event.event_type.lower() == "earnings"
        and event.timestamp_quality == "point_in_time"
        and event.event_time_utc is not None
        and event.available_at_utc is not None
        and event.event_time_utc <= origin.origin_start_utc
        and event.available_at_utc <= origin.predictor_cutoff_utc
    ]
    return tuple(
        sorted(eligible, key=lambda event: event.event_time_utc or origin.origin_start_utc)
    )


def validate_optional_news(
    events: Sequence[CorporateEvent],
    *,
    validated: bool,
) -> tuple[CorporateEvent, ...]:
    """Allow optional news only after explicit timestamp/PIT validation.

    Parameters
    ----------
    events:
        News-like structured records.
    validated:
        External audit result for timestamp, coverage, and reproducibility.

    Returns
    -------
    tuple[CorporateEvent, ...]
        Validated news records, preserving source order.

    Raises
    ------
    PITError
        If validation is absent or any record lacks a PIT timestamp.
    """
    if not validated:
        raise PITError("OPTIONAL_NEWS_PIT_UNVALIDATED")
    if any(
        event.timestamp_quality != "point_in_time"
        or event.event_time_utc is None
        or event.available_at_utc is None
        for event in events
    ):
        raise PITError("OPTIONAL_NEWS_TIMESTAMP_UNRESOLVED")
    return tuple(events)
