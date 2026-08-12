"""Target-free source controls for the corrected development panel.

This module is deliberately limited to origin identity and B1Q provenance.  It
does not read prices, option trades, targets, metrics, models, or holdout data.
"""

from __future__ import annotations

import json
import re
from collections.abc import Collection, Iterable, Mapping, Sequence
from datetime import date, datetime, timedelta
from importlib import import_module
from pathlib import Path
from types import ModuleType
from typing import Any, Protocol, cast

import polars as pl

from mds650.study_design import canonical_sha256
from mds650.target_blind_panel_v22 import KEY_COLUMNS

B1Q_EXOGENOUS_INPUT_PROVENANCE_UNRESOLVED = (
    "B1Q_EXOGENOUS_INPUT_PROVENANCE_UNRESOLVED"
)
B1Q_SOURCE_ROW_MISSING = "B1Q_SOURCE_ROW_MISSING"
_ALLOWED_DIVIDEND_ASSUMPTIONS = frozenset(
    {"NO_PRE_ORIGIN_DIVIDEND_Q_ZERO", "PRE_ORIGIN_TRAILING_DECLARATIONS"}
)
_EXOGENOUS_EVIDENCE_COLUMNS = (
    "rate_source_available_at_utc",
    "rate_source_payload_sha256",
    "dividend_source_available_at_utc",
    "dividend_source_payload_sha256",
)
_B1Q_SOURCE_COLUMNS = (
    *KEY_COLUMNS,
    "rate",
    "rate_source_date",
    "dividend_yield",
    "dividend_assumption",
    *_EXOGENOUS_EVIDENCE_COLUMNS,
    "b1a_complete",
    "b1b_complete",
    "b1c_complete",
    "b1q_atm_iv",
    "b1q_skew",
    "b1q_term_structure",
    "b1q_max_sip_timestamp_ns",
    "b1q_quote_not_after_origin",
    "b1q_pit_evidence_valid",
)
_SHA256_PATTERN = r"^[0-9a-f]{64}$"
_B1Q_NULLABLE_ON_UNRESOLVED = (
    "rate",
    "rate_source_date",
    "dividend_yield",
    "dividend_assumption",
    "b1q_atm_iv",
    "b1q_skew",
    "b1q_term_structure",
    "b1q_max_sip_timestamp_ns",
)
_B1Q_BOOLEAN_ON_UNRESOLVED = (
    "b1a_complete",
    "b1b_complete",
    "b1c_complete",
    "b1q_quote_not_after_origin",
    "b1q_pit_evidence_valid",
)


class _CalendarTimestamp(Protocol):
    """Minimal exchange-calendar timestamp surface used by this module."""

    def to_pydatetime(self) -> datetime:
        """Convert the exchange-calendar timestamp to a timezone-aware datetime."""


class _XnysCalendar(Protocol):
    """Minimal XNYS calendar surface used for deterministic origin construction."""

    def session_open(self, session: date) -> _CalendarTimestamp:
        """Return the UTC open timestamp for one XNYS session."""

    def session_close(self, session: date) -> _CalendarTimestamp:
        """Return the UTC close timestamp for one XNYS session."""


class _ExchangeCalendarsModule(Protocol):
    """Typed boundary for the installed but untyped exchange-calendars package."""

    def get_calendar(self, name: str) -> _XnysCalendar:
        """Return the requested exchange calendar."""


class _JsonSchemaValidator(Protocol):
    """Minimal JSON-Schema validator surface used by the source contract."""

    def iter_errors(self, instance: object) -> Iterable[object]:
        """Yield schema errors for one JSON-compatible document."""


class _Draft202012ValidatorFactory(Protocol):
    """Typed boundary for the installed JSON-Schema Draft 2020-12 runtime."""

    def __call__(self, schema: Mapping[str, object]) -> _JsonSchemaValidator:
        """Build a validator for one Draft 2020-12 schema."""

    def check_schema(self, schema: Mapping[str, object]) -> None:
        """Raise when a schema is invalid."""


def build_exact_development_origins(
    session_dates: Sequence[str],
    *,
    assets: Sequence[str],
) -> pl.DataFrame:
    """Build the existing Phase 5 five-minute, RV30-safe origin grid.

    Parameters
    ----------
    session_dates:
        Strictly ascending XNYS session dates in ISO-8601 form.
    assets:
        Non-empty selected asset symbols to cross with every origin.

    Returns
    -------
    polars.DataFrame
        Target-free origin rows from five minutes after the session open through
        35 minutes before the actual exchange close.  A normal session has 71
        origins per asset, matching the already-acquired Phase 5 B1Q grid.

    Raises
    ------
    ValueError
        If a session is duplicated, unordered, unavailable on XNYS, or an asset
        symbol is blank.

    Notes
    -----
    The final 35-minute margin preserves the frozen existing grid while leaving
    the origin close and the following 30 one-minute closes available for a
    later, separately authorised RV30 binding step.
    """
    normalized_sessions = tuple(session_dates)
    normalized_assets = tuple(assets)
    if not normalized_sessions or len(normalized_sessions) != len(set(normalized_sessions)):
        raise ValueError("CORRECTED_DEVELOPMENT_ORIGIN_SESSION_INVALID")
    if normalized_sessions != tuple(sorted(normalized_sessions)):
        raise ValueError("CORRECTED_DEVELOPMENT_ORIGIN_SESSION_ORDER_INVALID")
    if not normalized_assets or any(
        not asset or asset != asset.strip() for asset in normalized_assets
    ):
        raise ValueError("CORRECTED_DEVELOPMENT_ORIGIN_ASSET_INVALID")
    if len(normalized_assets) != len(set(normalized_assets)):
        raise ValueError("CORRECTED_DEVELOPMENT_ORIGIN_ASSET_DUPLICATE")

    calendar = _xnys_calendar()
    rows: list[dict[str, Any]] = []
    for day_text in normalized_sessions:
        try:
            session_day = date.fromisoformat(day_text)
            session_open = calendar.session_open(session_day).to_pydatetime()
            session_close = calendar.session_close(session_day).to_pydatetime()
        except (TypeError, ValueError) as exc:
            raise ValueError("CORRECTED_DEVELOPMENT_ORIGIN_SESSION_UNAVAILABLE") from exc
        origin = session_open + timedelta(minutes=5)
        last_origin = session_close - timedelta(minutes=35)
        while origin <= last_origin:
            session_minute = int((origin - session_open).total_seconds() // 60)
            segment = (
                "first"
                if session_minute < 130
                else "middle"
                if session_minute < 260
                else "last"
            )
            for asset in normalized_assets:
                rows.append(
                    {
                        "origin_id": f"{asset}:{origin.isoformat()}",
                        "asset": asset,
                        "session_date": day_text,
                        "forecast_origin_utc": origin,
                        "session_minute": session_minute,
                        "session_segment": segment,
                    }
                )
            origin += timedelta(minutes=5)
    return pl.DataFrame(rows, infer_schema_length=None).sort(
        ["session_date", "forecast_origin_utc", "asset"]
    )


def prepare_b1q_source(
    origins: pl.DataFrame,
    source: pl.DataFrame,
    *,
    retained_cache_asset_dates: Collection[tuple[str, str]] = (),
) -> pl.DataFrame:
    """Fail closed on unresolved B1Q rate or dividend provenance.

    Parameters
    ----------
    origins:
        Target-free canonical origins with the four B1Q join keys.
    source:
        Target-free source-state rows.  A rate observation must be dated
        strictly before the associated session, and the dividend assumption
        must be one of the registered pre-origin assumptions.
    retained_cache_asset_dates:
        Asset-date pairs with a retained quote cache but no re-derived B1Q
        source state.  They receive the explicit exogenous-provenance code.

    Returns
    -------
    polars.DataFrame
        One row per origin.  Rows with missing or invalid exogenous provenance
        retain their keys but have every B1Q state and exogenous input set to
        null (or ``False`` for B1Q booleans); no prior state is carried forward.

    Raises
    ------
    ValueError
        If keys are duplicated, source rows lie outside the origin grid, or a
        required target-free B1Q source column is absent.

    Examples
    --------
    ``prepare_b1q_source(origins, source)`` preserves a valid prior-date rate
    but replaces a same-day rate with
    ``B1Q_EXOGENOUS_INPUT_PROVENANCE_UNRESOLVED``.
    """
    _require_columns("origins", origins, KEY_COLUMNS)
    source = _with_exogenous_evidence_columns(source)
    _require_columns("b1q_source", source, _B1Q_SOURCE_COLUMNS)
    _assert_unique_keys("origins", origins)
    _assert_unique_keys("b1q_source", source)

    origin_keys = origins.select(*KEY_COLUMNS)
    source_rows = source.select(*_B1Q_SOURCE_COLUMNS)
    if source_rows.join(origin_keys, on=list(KEY_COLUMNS), how="anti").height:
        raise ValueError("CORRECTED_DEVELOPMENT_B1Q_SOURCE_KEY_UNEXPECTED")

    retained = pl.DataFrame(
        [
            {"asset": asset, "session_date": session_date, "_retained_cache_date": True}
            for asset, session_date in sorted(retained_cache_asset_dates)
        ],
        schema={
            "asset": pl.String,
            "session_date": pl.String,
            "_retained_cache_date": pl.Boolean,
        },
    )
    joined = (
        origins.join(retained, on=["asset", "session_date"], how="left", validate="m:1")
        .join(
            source_rows.with_columns(pl.lit(True).alias("_source_row_present")),
            on=list(KEY_COLUMNS),
            how="left",
            validate="1:1",
        )
    )
    provenance_verified = (
        pl.col("_source_row_present").fill_null(False)
        & pl.col("rate_source_date").is_not_null()
        & (
            pl.col("rate_source_date").cast(pl.String)
            < pl.col("session_date").cast(pl.String)
        ).fill_null(False)
        & pl.col("dividend_assumption").is_in(_ALLOWED_DIVIDEND_ASSUMPTIONS).fill_null(False)
        & _evidence_available_by_origin("rate_source_available_at_utc")
        & _evidence_available_by_origin("dividend_source_available_at_utc")
        & _payload_hash_is_valid("rate_source_payload_sha256")
        & _payload_hash_is_valid("dividend_source_payload_sha256")
    )
    reason = (
        pl.when(provenance_verified)
        .then(pl.lit(None, dtype=pl.String))
        .when(
            ~pl.col("_source_row_present").fill_null(False)
            & pl.col("_retained_cache_date").fill_null(False)
        )
        .then(pl.lit(B1Q_EXOGENOUS_INPUT_PROVENANCE_UNRESOLVED))
        .when(~pl.col("_source_row_present").fill_null(False))
        .then(pl.lit(B1Q_SOURCE_ROW_MISSING))
        .otherwise(pl.lit(B1Q_EXOGENOUS_INPUT_PROVENANCE_UNRESOLVED))
    )
    nullable_expressions = [
        pl.when(provenance_verified)
        .then(pl.col(column))
        .otherwise(pl.lit(None, dtype=source_rows.schema[column]))
        .alias(column)
        for column in _B1Q_NULLABLE_ON_UNRESOLVED
    ]
    boolean_expressions = [
        pl.when(provenance_verified)
        .then(pl.col(column).fill_null(False))
        .otherwise(pl.lit(False))
        .alias(column)
        for column in _B1Q_BOOLEAN_ON_UNRESOLVED
    ]
    return (
        joined.with_columns(
            provenance_verified.alias("b1q_exogenous_provenance_verified"),
            reason.alias("b1q_source_missing_reason"),
            *nullable_expressions,
            *boolean_expressions,
        )
        .select(
            *KEY_COLUMNS,
            "rate",
            "rate_source_date",
            "dividend_yield",
            "dividend_assumption",
            *_EXOGENOUS_EVIDENCE_COLUMNS,
            "b1a_complete",
            "b1b_complete",
            "b1c_complete",
            "b1q_atm_iv",
            "b1q_skew",
            "b1q_term_structure",
            "b1q_max_sip_timestamp_ns",
            "b1q_quote_not_after_origin",
            "b1q_pit_evidence_valid",
            "b1q_exogenous_provenance_verified",
            "b1q_source_missing_reason",
        )
        .sort(["session_date", "forecast_origin_utc", "asset"])
    )


def _with_exogenous_evidence_columns(source: pl.DataFrame) -> pl.DataFrame:
    """Add null audit columns when a legacy B1Q source lacks payload evidence."""
    additions: list[pl.Expr] = []
    if "rate_source_available_at_utc" not in source.columns:
        additions.append(
            pl.lit(None, dtype=pl.Datetime(time_zone="UTC")).alias(
                "rate_source_available_at_utc"
            )
        )
    if "rate_source_payload_sha256" not in source.columns:
        additions.append(pl.lit(None, dtype=pl.String).alias("rate_source_payload_sha256"))
    if "dividend_source_available_at_utc" not in source.columns:
        additions.append(
            pl.lit(None, dtype=pl.Datetime(time_zone="UTC")).alias(
                "dividend_source_available_at_utc"
            )
        )
    if "dividend_source_payload_sha256" not in source.columns:
        additions.append(
            pl.lit(None, dtype=pl.String).alias("dividend_source_payload_sha256")
        )
    return source.with_columns(*additions) if additions else source


def _evidence_available_by_origin(column: str) -> pl.Expr:
    """Return whether one timestamped evidence record was available by origin."""
    available_at = pl.col(column).cast(pl.Datetime(time_zone="UTC"), strict=False)
    origin = pl.col("forecast_origin_utc").cast(pl.Datetime(time_zone="UTC"), strict=False)
    return available_at.is_not_null() & origin.is_not_null() & (available_at <= origin)


def _payload_hash_is_valid(column: str) -> pl.Expr:
    """Return whether one local raw-payload identity is a SHA-256 digest."""
    return (
        pl.col(column)
        .cast(pl.String, strict=False)
        .str.contains(_SHA256_PATTERN)
        .fill_null(False)
    )


def build_source_coverage_ledger(
    origins: pl.DataFrame,
    *,
    b0_asset_dates: pl.DataFrame,
    b2_asset_dates: pl.DataFrame,
    b1q_source: pl.DataFrame,
    source_hashes: Mapping[str, str],
) -> dict[str, Any]:
    """Summarize exact, target-free B0/B1Q/B2 source coverage.

    Parameters
    ----------
    origins:
        The exact target-free development origin grid.
    b0_asset_dates:
        FMP asset-date identities after exact-session filtering.
    b2_asset_dates:
        Full Tape asset-date identities after raw partition validation.
    b1q_source:
        Output from :func:`prepare_b1q_source` for the same origin grid.
    source_hashes:
        Named SHA-256 digests binding the compact source manifests and local
        target-free source files used for this ledger.

    Returns
    -------
    dict[str, object]
        Deterministic coverage facts.  ``BLOCKED_SOURCE_COVERAGE`` means no
        target binding may begin; this function never reads outcome data.

    Raises
    ------
    ValueError
        If an input has duplicate identities, lacks mandatory keys, or B1Q
        contains keys outside the exact origin grid.

    Notes
    -----
    A technically present quote row is not enough: B1Q is blocked when its
    pre-origin rate or dividend provenance remains unresolved.
    """
    _require_columns("origins", origins, KEY_COLUMNS)
    _require_columns("b0_asset_dates", b0_asset_dates, ("asset", "session_date"))
    _require_columns("b2_asset_dates", b2_asset_dates, ("asset", "session_date"))
    _require_columns(
        "b1q_source",
        b1q_source,
        (*KEY_COLUMNS, "b1q_exogenous_provenance_verified", "b1q_source_missing_reason"),
    )
    _assert_unique_keys("origins", origins)
    _assert_unique_asset_dates("b0_asset_dates", b0_asset_dates)
    _assert_unique_asset_dates("b2_asset_dates", b2_asset_dates)
    _assert_unique_keys("b1q_source", b1q_source)
    validated_hashes = _validated_source_hashes(source_hashes)

    expected_asset_dates = origins.select("asset", "session_date").unique().sort(
        ["session_date", "asset"]
    )
    b0 = _asset_date_coverage(expected_asset_dates, b0_asset_dates, "B0")
    b2 = _asset_date_coverage(expected_asset_dates, b2_asset_dates, "B2")
    b1 = _b1q_coverage(origins, b1q_source)
    status = (
        "PASS_SOURCE_COVERAGE"
        if all(component["status"] == "PASS" for component in (b0, b1, b2))
        else "BLOCKED_SOURCE_COVERAGE"
    )
    ledger: dict[str, Any] = {
        "schema_version": "corrected-development-source-coverage-v1",
        "status": status,
        "expected_origin_count": origins.height,
        "expected_asset_date_count": expected_asset_dates.height,
        "components": {"B0": b0, "B1Q": b1, "B2": b2},
        "source_hashes": validated_hashes,
        "target_binding_permitted": status == "PASS_SOURCE_COVERAGE",
        "no_target_or_metric_payload_read": True,
        "safe_to_open_or_evaluate_oos": "NO",
    }
    ledger["ledger_sha256"] = canonical_sha256(ledger)
    return ledger


def validate_source_coverage_ledger(
    ledger: Mapping[str, Any],
    schema_path: Path,
) -> None:
    """Validate a source ledger against its schema and canonical self-hash.

    Parameters
    ----------
    ledger:
        JSON-compatible result from :func:`build_source_coverage_ledger`.
    schema_path:
        Local Draft 2020-12 schema for the source-coverage contract.

    Raises
    ------
    ValueError
        If the schema is unreadable, the ledger violates it, or the canonical
        self-hash does not match its unsigned content.
    """
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        if not isinstance(schema, dict):
            raise ValueError("schema must be an object")
        validator = _draft202012_validator()
        validator.check_schema(schema)
        errors = list(validator(schema).iter_errors(dict(ledger)))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise ValueError("CORRECTED_DEVELOPMENT_SOURCE_COVERAGE_SCHEMA_INVALID") from exc
    if errors:
        raise ValueError("CORRECTED_DEVELOPMENT_SOURCE_COVERAGE_SCHEMA_VIOLATION")
    recorded_hash = ledger.get("ledger_sha256")
    unsigned = dict(ledger)
    unsigned.pop("ledger_sha256", None)
    if not isinstance(recorded_hash, str) or canonical_sha256(unsigned) != recorded_hash:
        raise ValueError("CORRECTED_DEVELOPMENT_SOURCE_COVERAGE_SELF_HASH_MISMATCH")


def _asset_date_coverage(
    expected: pl.DataFrame,
    available: pl.DataFrame,
    component: str,
) -> dict[str, Any]:
    """Return missing and unexpected asset-date identities for one raw source."""
    actual = available.select("asset", "session_date").unique().sort(["session_date", "asset"])
    missing = expected.join(actual, on=["asset", "session_date"], how="anti")
    unexpected = actual.join(expected, on=["asset", "session_date"], how="anti")
    return {
        "status": "PASS" if missing.is_empty() and unexpected.is_empty() else "BLOCKED",
        "expected_asset_date_count": expected.height,
        "available_asset_date_count": actual.height,
        "missing_asset_dates": missing.to_dicts(),
        "unexpected_asset_dates": unexpected.to_dicts(),
        "component": component,
    }


def _validated_source_hashes(source_hashes: Mapping[str, str]) -> dict[str, str]:
    """Return sorted SHA-256 input identities or reject an unbound source."""
    if not source_hashes:
        raise ValueError("CORRECTED_DEVELOPMENT_SOURCE_HASH_INVALID")
    validated: dict[str, str] = {}
    for name, digest in source_hashes.items():
        if not name or not re.fullmatch(r"[a-f0-9]{64}", digest):
            raise ValueError("CORRECTED_DEVELOPMENT_SOURCE_HASH_INVALID")
        validated[name] = digest
    return {name: validated[name] for name in sorted(validated)}


def _b1q_coverage(origins: pl.DataFrame, source: pl.DataFrame) -> dict[str, Any]:
    """Return exact B1Q key and exogenous-provenance coverage without imputation."""
    expected = origins.select(*KEY_COLUMNS)
    actual = source.select(*KEY_COLUMNS)
    missing = expected.join(actual, on=list(KEY_COLUMNS), how="anti")
    unexpected = actual.join(expected, on=list(KEY_COLUMNS), how="anti")
    unresolved = source.filter(
        ~pl.col("b1q_exogenous_provenance_verified").fill_null(False)
        | pl.col("b1q_source_missing_reason").is_not_null()
    )
    reasons = (
        unresolved.filter(pl.col("b1q_source_missing_reason").is_not_null())
        .group_by("b1q_source_missing_reason")
        .len()
        .sort("b1q_source_missing_reason")
        .to_dicts()
    )
    return {
        "status": (
            "PASS"
            if missing.is_empty() and unexpected.is_empty() and unresolved.is_empty()
            else "BLOCKED"
        ),
        "expected_origin_count": expected.height,
        "available_origin_count": actual.height,
        "missing_origin_count": missing.height,
        "unexpected_origin_count": unexpected.height,
        "unresolved_origin_count": unresolved.height,
        "unresolved_reason_counts": reasons,
    }


def _require_columns(name: str, frame: pl.DataFrame, columns: Sequence[str]) -> None:
    """Reject a target-free input whose contract columns are incomplete."""
    missing = sorted(set(columns) - set(frame.columns))
    if missing:
        raise ValueError(f"CORRECTED_DEVELOPMENT_{name.upper()}_COLUMNS_MISSING")


def _xnys_calendar() -> _XnysCalendar:
    """Load the installed XNYS calendar through one checked typing boundary."""
    module = import_module("exchange_calendars")
    if not isinstance(module, ModuleType) or not callable(getattr(module, "get_calendar", None)):
        raise RuntimeError("CORRECTED_DEVELOPMENT_XNYS_CALENDAR_UNAVAILABLE")
    return cast(_ExchangeCalendarsModule, module).get_calendar("XNYS")


def _draft202012_validator() -> _Draft202012ValidatorFactory:
    """Load the installed JSON-Schema runtime behind one checked type boundary."""
    module = import_module("jsonschema")
    candidate = cast(object, getattr(module, "Draft202012Validator", None))
    if not callable(candidate) or not callable(getattr(candidate, "check_schema", None)):
        raise RuntimeError("CORRECTED_DEVELOPMENT_JSONSCHEMA_VALIDATOR_UNAVAILABLE")
    return cast(_Draft202012ValidatorFactory, candidate)


def _assert_unique_keys(name: str, frame: pl.DataFrame) -> None:
    """Reject duplicate B1Q identity keys before any left join can hide them."""
    duplicates = (
        frame.group_by(list(KEY_COLUMNS))
        .len()
        .filter(pl.col("len") > 1)
        .height
    )
    if duplicates:
        raise ValueError(f"CORRECTED_DEVELOPMENT_{name.upper()}_KEY_DUPLICATE")


def _assert_unique_asset_dates(name: str, frame: pl.DataFrame) -> None:
    """Reject duplicate raw-source partitions before comparing source coverage."""
    duplicates = frame.group_by(["asset", "session_date"]).len().filter(pl.col("len") > 1).height
    if duplicates:
        raise ValueError(f"CORRECTED_DEVELOPMENT_{name.upper()}_KEY_DUPLICATE")
