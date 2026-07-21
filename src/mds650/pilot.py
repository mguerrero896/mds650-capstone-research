"""Fixture-first point-in-time pilot orchestration."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import timedelta

from mds650.asset_selection import AssetQuality, FrozenAssetSet, freeze_assets
from mds650.contracts import (
    CANDIDATE_ASSETS,
    CorporateEvent,
    ForecastOrigin,
    OptionQuote,
    OptionStateSnapshot,
    OptionTrade,
    RealizedVarianceTarget,
    UnderlyingBar,
    UnusualOptionEvent,
)
from mds650.errors import QualityGateError
from mds650.events import eligible_earnings_events
from mds650.normalize import normalize_underlying_bars
from mds650.origins import build_forecast_origins
from mds650.targets import compute_realized_variance


@dataclass(frozen=True, slots=True)
class PilotResult:
    """In-memory pilot outputs before Parquet/profile export."""

    covered_assets: tuple[str, ...]
    frozen_assets: FrozenAssetSet
    underlying_bars: tuple[UnderlyingBar, ...]
    corporate_events: tuple[CorporateEvent, ...]
    unusual_events: tuple[UnusualOptionEvent, ...]
    option_states: tuple[OptionStateSnapshot, ...]
    option_trades: tuple[OptionTrade, ...]
    option_quotes: tuple[OptionQuote, ...]
    origins: tuple[ForecastOrigin, ...]
    targets: tuple[RealizedVarianceTarget, ...]
    target_exclusions: tuple[str, ...]
    event_no_event_counts: dict[str, tuple[int, int]]
    row_trace: tuple[dict[str, object], ...]


def build_pilot(
    *,
    raw_underlying: Mapping[str, Sequence[Mapping[str, object]]],
    corporate_events: Sequence[CorporateEvent],
    unusual_events: Sequence[UnusualOptionEvent],
    option_states: Sequence[OptionStateSnapshot],
    option_trades: Sequence[OptionTrade],
    option_quotes: Sequence[OptionQuote],
    run_id: str,
    source_timezone: str | None,
    expected_rows_per_asset: int | None = None,
) -> PilotResult:
    """Build a small PIT pilot across all eight candidates and RV30 targets.

    Parameters
    ----------
    raw_underlying:
        FMP-like minute rows keyed by all eight candidate assets.
    corporate_events, unusual_events, option_states, option_trades, option_quotes:
        Already parsed component records. Records are retained even when their
        availability is insufficient for a predictor, so the gate is auditable.
    run_id, source_timezone:
        Provenance and explicit timezone for FMP's naive timestamps.
    expected_rows_per_asset:
        Optional quality denominator. If omitted, the bounded pilot row count is
        its own denominator; this is not a production completeness claim.

    Returns
    -------
    PilotResult
        Six component tables, origins, valid RV30 targets, quality-only freeze,
        event/no-event counts, and row-level trace metadata.

    Raises
    ------
    QualityGateError
        If candidate coverage, event/no-event representation, or future target
        bars are insufficient.
    ValueError
        If the expected-row configuration is invalid.
    """
    if expected_rows_per_asset is not None and expected_rows_per_asset <= 0:
        raise ValueError("PILOT_EXPECTED_ROWS_INVALID")
    missing = CANDIDATE_ASSETS.difference(raw_underlying)
    if missing:
        raise QualityGateError("PILOT_CANDIDATE_COVERAGE_MISSING")

    normalized_by_asset: dict[str, list[UnderlyingBar]] = {}
    quality: list[AssetQuality] = []
    for asset in sorted(CANDIDATE_ASSETS):
        bars = normalize_underlying_bars(
            raw_underlying[asset],
            asset=asset,
            run_id=run_id,
            source_response_id=f"fmp-{asset}",
            source_timezone=source_timezone,
        )
        if not bars:
            raise QualityGateError("PILOT_EMPTY_UNDERLYING_DATA")
        normalized_by_asset[asset] = bars
        ratio = min(
            len(bars) / expected_rows_per_asset, 1.0
        ) if expected_rows_per_asset is not None else 1.0
        quality.append(
            AssetQuality(
                asset=asset,
                completeness_ratio=ratio,
                duplicate_rate=0.0,
                critical_null_rate=0.0,
                history_start=min(bar.bar_start_utc.date() for bar in bars),
                history_end=max(bar.bar_start_utc.date() for bar in bars),
            )
        )
    frozen = freeze_assets(quality)

    all_origins: list[ForecastOrigin] = []
    all_targets: list[RealizedVarianceTarget] = []
    target_exclusions: list[str] = []
    row_trace: list[dict[str, object]] = []
    event_no_event_counts: dict[str, tuple[int, int]] = {}
    for asset in sorted(CANDIDATE_ASSETS):
        bars = sorted(normalized_by_asset[asset], key=lambda bar: bar.bar_start_utc)
        asset_events = [event for event in unusual_events if event.asset == asset]
        origins = build_forecast_origins(
            asset=asset,
            timestamps=[bar.bar_start_utc for bar in bars],
            run_id=run_id,
            source_trace_ids=[bar.source_response_id for bar in bars],
            event_times=[event.event_time_utc for event in asset_events],
        )
        event_count = sum(origin.event_presence for origin in origins)
        no_event_count = len(origins) - event_count
        event_no_event_counts[asset] = (event_count, no_event_count)
        if event_count == 0 or no_event_count == 0:
            raise QualityGateError("PILOT_EVENT_NO_EVENT_COVERAGE_MISSING")
        by_timestamp = {bar.bar_start_utc: bar for bar in bars}
        for origin in origins:
            anchor = by_timestamp.get(origin.origin_start_utc)
            if anchor is None:
                continue
            future_times = [
                origin.origin_start_utc + timedelta(minutes=offset)
                for offset in range(1, 31)
            ]
            future_bars = [by_timestamp.get(timestamp) for timestamp in future_times]
            if any(bar is None for bar in future_bars):
                target_exclusions.append(origin.origin_id)
                continue
            closes = [bar.close for bar in future_bars if bar is not None]
            rv = compute_realized_variance(anchor.close, closes)
            target = RealizedVarianceTarget(
                origin_id=origin.origin_id,
                horizon_minutes=30,
                future_close_count=len(closes),
                rv_30m=rv,
                log_rv_30m=math.log(rv + 1e-12),
                future_close_start_utc=future_times[0],
                future_close_end_utc=future_times[-1],
                target_formula_version="rv30-v1",
                validity="valid",
            )
            all_origins.append(origin)
            all_targets.append(target)
            row_trace.append(
                _trace_row(
                    origin,
                    target,
                    asset_events,
                    option_states,
                    option_trades,
                    option_quotes,
                    corporate_events,
                )
            )

    return PilotResult(
        covered_assets=tuple(sorted(CANDIDATE_ASSETS)),
        frozen_assets=frozen,
        underlying_bars=tuple(bar for bars in normalized_by_asset.values() for bar in bars),
        corporate_events=tuple(corporate_events),
        unusual_events=tuple(unusual_events),
        option_states=tuple(option_states),
        option_trades=tuple(option_trades),
        option_quotes=tuple(option_quotes),
        origins=tuple(all_origins),
        targets=tuple(all_targets),
        target_exclusions=tuple(target_exclusions),
        event_no_event_counts=event_no_event_counts,
        row_trace=tuple(row_trace),
    )


def _trace_row(
    origin: ForecastOrigin,
    target: RealizedVarianceTarget,
    events: Sequence[UnusualOptionEvent],
    states: Sequence[OptionStateSnapshot],
    trades: Sequence[OptionTrade],
    quotes: Sequence[OptionQuote],
    earnings: Sequence[CorporateEvent],
) -> dict[str, object]:
    cutoff = origin.predictor_cutoff_utc
    eligible_events = [
        event
        for event in events
        if event.available_at_utc is not None and event.available_at_utc <= cutoff
    ]
    eligible_states = [
        state
        for state in states
        if state.asset == origin.asset and state.available_at_utc <= cutoff
    ]
    event_contract_ids = {event.contract_id for event in events}
    eligible_trades = [
        trade
        for trade in trades
        if trade.contract_id in event_contract_ids
        and trade.observed_at_utc <= cutoff
    ]
    eligible_quotes = [
        quote
        for quote in quotes
        if quote.contract_id in event_contract_ids
        and quote.observed_at_utc <= cutoff
    ]
    return {
        "origin_id": origin.origin_id,
        "asset": origin.asset,
        "predictor_cutoff_utc": cutoff.isoformat(),
        "future_close_start_utc": target.future_close_start_utc.isoformat(),
        "future_close_end_utc": target.future_close_end_utc.isoformat(),
        "future_close_count": target.future_close_count,
        "rv_30m": target.rv_30m,
        "unusual_event_count": len(eligible_events),
        "option_state_count": len(eligible_states),
        "trade_count": len(eligible_trades),
        "quote_count": len(eligible_quotes),
        "earnings_count": len(eligible_earnings_events(origin, earnings)),
    }
