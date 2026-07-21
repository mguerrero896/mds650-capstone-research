"""Validated records for the six point-in-time data components."""

from __future__ import annotations

import math
from datetime import UTC, date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator, model_validator

from mds650.time import to_new_york

CANDIDATE_ASSETS = frozenset({"SPY", "QQQ", "AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "META"})


def _require_aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("TIMESTAMP_TIMEZONE_REQUIRED")
    return value


def _require_finite_nonnegative(value: float | None, code: str) -> float | None:
    if value is not None and (not math.isfinite(value) or value < 0):
        raise ValueError(code)
    return value


class ProvenanceRecord(BaseModel):
    """Common provenance fields emitted by every normalized pilot table."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str
    source_provider: str
    source_response_id: str
    observed_at_utc: datetime

    @field_validator("observed_at_utc")
    @classmethod
    def validate_observed_at(cls, value: datetime) -> datetime:
        """Require the canonical observation timestamp to carry timezone data."""
        return _require_aware(value).astimezone(UTC)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def observed_at_ny(self) -> datetime:
        """Render ``observed_at_utc`` in ``America/New_York``."""
        return to_new_york(self.observed_at_utc)


class UnderlyingBar(ProvenanceRecord):
    """One-minute underlying OHLCV bar with an auditable deduplication key."""

    asset: str
    bar_start_utc: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float | None = None
    quality_flags: frozenset[str] = frozenset()

    @computed_field  # type: ignore[prop-decorator]
    @property
    def bar_start_ny(self) -> datetime:
        """Render the canonical bar start in ``America/New_York``."""
        return to_new_york(self.bar_start_utc)

    @field_validator("asset")
    @classmethod
    def validate_asset(cls, value: str) -> str:
        """Reject assets outside the ratified candidate universe."""
        if value not in CANDIDATE_ASSETS:
            raise ValueError("ASSET_NOT_IN_CANDIDATE_UNIVERSE")
        return value

    @field_validator("bar_start_utc")
    @classmethod
    def validate_bar_timestamp(cls, value: datetime) -> datetime:
        """Require an aware UTC bar timestamp."""
        return _require_aware(value).astimezone(UTC)

    @field_validator("open", "high", "low", "close")
    @classmethod
    def validate_price(cls, value: float) -> float:
        """Require finite positive OHLC values."""
        if not math.isfinite(value) or value <= 0:
            raise ValueError("PRICE_MUST_BE_POSITIVE")
        return value

    @field_validator("volume")
    @classmethod
    def validate_volume(cls, value: float | None) -> float | None:
        """Allow an explicit missing volume but reject negative values."""
        return _require_finite_nonnegative(value, "VOLUME_INVALID")

    @model_validator(mode="after")
    def validate_ohlc(self) -> UnderlyingBar:
        """Ensure high/low contain the open, close, and each other."""
        if self.low > min(self.open, self.close) or self.high < max(self.open, self.close):
            raise ValueError("OHLC_RELATION_INVALID")
        return self


class CorporateEvent(ProvenanceRecord):
    """Structured corporate event with an explicit timestamp precision label."""

    asset: str
    event_type: str
    event_time_utc: datetime | None = None
    available_at_utc: datetime | None = None
    event_date_ny: date | None = None
    timestamp_quality: Literal["point_in_time", "date_only", "unresolved"]

    @field_validator("event_time_utc", "available_at_utc")
    @classmethod
    def validate_optional_timestamp(cls, value: datetime | None) -> datetime | None:
        """Keep optional event timestamps timezone-aware when supplied."""
        return None if value is None else _require_aware(value).astimezone(UTC)


class UnusualOptionEvent(ProvenanceRecord):
    """Point-in-time unusual-options event without inferred trader intent."""

    event_id: str
    asset: str
    contract_id: str
    event_time_utc: datetime
    available_at_utc: datetime | None = None
    premium: float | None = None
    trade_price: float | None = None
    size: float | None = None
    volume: float | None = None
    open_interest: float | None = None
    volume_oi_ratio: float | None = None
    option_type: Literal["call", "put", "unknown"] = "unknown"
    strike: float
    expiry: date
    moneyness: float | None = None
    dte: int | None = None
    sweep: bool | None = None
    floor: bool | None = None
    multileg: bool | None = None
    execution_proxy: str | None = None
    iv_change: float | None = None
    iv: float | None = None
    skew: float | None = None

    @field_validator("event_time_utc", "available_at_utc")
    @classmethod
    def validate_event_timestamp(cls, value: datetime | None) -> datetime | None:
        """Require timezone information for event and availability timestamps."""
        return None if value is None else _require_aware(value).astimezone(UTC)

    @field_validator("premium", "trade_price", "size", "volume", "open_interest")
    @classmethod
    def validate_nonnegative_fields(cls, value: float | None) -> float | None:
        """Reject negative source measures without imputing missing values."""
        return _require_finite_nonnegative(value, "OPTION_MEASURE_INVALID")


class OptionStateSnapshot(ProvenanceRecord):
    """Ordinary option state available at a point-in-time cutoff."""

    asset: str
    contract_or_surface_key: str
    observed_at_utc: datetime
    available_at_utc: datetime
    iv: float | None = None
    skew: float | None = None
    term_structure_value: float | None = None
    interpolation_method: str | None = None
    coverage_flag: Literal["observed", "valid_interpolation", "missing", "blocked"]

    @field_validator("observed_at_utc", "available_at_utc")
    @classmethod
    def validate_state_timestamp(cls, value: datetime) -> datetime:
        """Require aware timestamps for observed and available option state."""
        return _require_aware(value).astimezone(UTC)

    @model_validator(mode="after")
    def validate_state_order(self) -> OptionStateSnapshot:
        """Prevent a state record from becoming available before it was observed."""
        if self.available_at_utc < self.observed_at_utc:
            raise ValueError("OPTION_STATE_AVAILABILITY_BEFORE_OBSERVATION")
        return self


class OptionTrade(ProvenanceRecord):
    """Directed historical option trade preserving provider condition codes."""

    contract_id: str
    trade_time_utc: datetime
    provider_timestamp_ns: int | None = None
    price: float
    size: float
    condition_codes: list[str] = Field(default_factory=list)

    @field_validator("trade_time_utc")
    @classmethod
    def validate_trade_timestamp(cls, value: datetime) -> datetime:
        """Require provider precision to remain timezone-aware."""
        return _require_aware(value).astimezone(UTC)

    @field_validator("price", "size")
    @classmethod
    def validate_trade_measure(cls, value: float) -> float:
        """Require non-negative finite trade measures."""
        checked = _require_finite_nonnegative(value, "OPTION_TRADE_MEASURE_INVALID")
        assert checked is not None
        return checked


class OptionQuote(ProvenanceRecord):
    """Directed consolidated bid/ask observation, retaining empty quotes."""

    contract_id: str
    quote_time_utc: datetime
    provider_timestamp_ns: int | None = None
    bid: float | None = None
    ask: float | None = None
    condition_codes: list[str] = Field(default_factory=list)
    consolidation_scope: str | None = None

    @field_validator("quote_time_utc")
    @classmethod
    def validate_quote_timestamp(cls, value: datetime) -> datetime:
        """Require an aware timestamp while preserving sub-second precision."""
        return _require_aware(value).astimezone(UTC)

    @field_validator("bid", "ask")
    @classmethod
    def validate_quote_measure(cls, value: float | None) -> float | None:
        """Keep null as missing and reject negative quote values."""
        return _require_finite_nonnegative(value, "OPTION_QUOTE_MEASURE_INVALID")

    @model_validator(mode="after")
    def validate_quote_spread(self) -> OptionQuote:
        """Reject an inverted bid/ask pair when both sides are present."""
        if self.bid is not None and self.ask is not None and self.bid > self.ask:
            raise ValueError("OPTION_QUOTE_SPREAD_INVALID")
        return self


class ForecastOrigin(ProvenanceRecord):
    """Five-minute forecast origin with an explicit predictor cutoff."""

    origin_id: str
    asset: str
    origin_start_utc: datetime
    predictor_cutoff_utc: datetime
    event_presence: bool
    source_trace_ids: list[str] = Field(default_factory=list)

    @field_validator("asset")
    @classmethod
    def validate_origin_asset(cls, value: str) -> str:
        """Reject an origin outside the ratified candidate universe."""
        if value not in CANDIDATE_ASSETS:
            raise ValueError("ASSET_NOT_IN_CANDIDATE_UNIVERSE")
        return value

    @field_validator("origin_start_utc", "predictor_cutoff_utc")
    @classmethod
    def validate_origin_timestamp(cls, value: datetime) -> datetime:
        """Require UTC-aware origin and cutoff timestamps."""
        return _require_aware(value).astimezone(UTC)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def origin_start_ny(self) -> datetime:
        """Render the origin boundary in ``America/New_York``."""
        return to_new_york(self.origin_start_utc)

    @model_validator(mode="after")
    def validate_cutoff(self) -> ForecastOrigin:
        """Prevent predictors from being available after the origin boundary."""
        if self.predictor_cutoff_utc > self.origin_start_utc:
            raise ValueError("PIT_CUTOFF_AFTER_ORIGIN")
        return self


class RealizedVarianceTarget(BaseModel):
    """Validated primary 30-minute realized-variance target record."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    origin_id: str
    horizon_minutes: int
    future_close_count: int
    rv_30m: float
    log_rv_30m: float
    future_close_start_utc: datetime
    future_close_end_utc: datetime
    target_formula_version: str
    validity: Literal["valid", "missing_future_bars", "invalid_price", "outside_session"]

    @field_validator("future_close_start_utc", "future_close_end_utc")
    @classmethod
    def validate_target_timestamp(cls, value: datetime) -> datetime:
        """Require future close boundaries to preserve timezone information."""
        return _require_aware(value).astimezone(UTC)

    @field_validator("rv_30m", "log_rv_30m")
    @classmethod
    def validate_target_value(cls, value: float) -> float:
        """Reject non-finite target values."""
        if not math.isfinite(value):
            raise ValueError("TARGET_VALUE_INVALID")
        return value

    @model_validator(mode="after")
    def validate_primary_target(self) -> RealizedVarianceTarget:
        """Enforce the sole primary horizon and its exact future-bar count."""
        if self.horizon_minutes != 30:
            raise ValueError("RV30_HORIZON_REQUIRED")
        if self.future_close_count != self.horizon_minutes:
            raise ValueError("RV30_FUTURE_CLOSE_COUNT_INVALID")
        if self.future_close_end_utc < self.future_close_start_utc:
            raise ValueError("TARGET_WINDOW_INVALID")
        return self
