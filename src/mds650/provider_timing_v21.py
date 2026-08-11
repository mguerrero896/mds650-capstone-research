"""Target-blind provider-timing amendment v2.1 utilities.

The module consumes only previously acquired provider records and B1/B2
provenance. It never opens targets, forecasts, predictions, or evaluation
artifacts, and it never issues a provider-data request.
"""

from __future__ import annotations

import hashlib
import json
import math
from array import array
from bisect import bisect_right
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Final

import exchange_calendars as xcals  # type: ignore[import-untyped]
import numpy as np
import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.compute as pc  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

NANOSECONDS_PER_SECOND: Final[int] = 1_000_000_000
REGULAR_RELATIVE_SPREAD_LIMIT: Final[float] = 0.25
RECORD_DELAY_SECONDS: Final[int] = 300
EXTREME_RECORD_DELAY_SECONDS: Final[int] = 3_600
DEFAULT_MASSIVE_CUTOFFS_SECONDS: Final[tuple[int, ...]] = (0, 60, 300)
MASSIVE_QUOTE_PAGE_LIMIT: Final[int] = 50_000
VALID_MASSIVE_CACHE_STATES: Final[frozenset[str]] = frozenset(
    {
        "OK",
        "OK_EARLY_CLOSE_REQUEST_OVEREXTENDED",
        "OK_EARLY_CLOSE_POST_CLOSE_QUOTES_EXCLUDED",
    }
)
B2_FEATURE_COLUMNS: Final[tuple[str, ...]] = (
    "option_trade_count_5m",
    "unique_contract_count_5m",
    "total_premium_5m",
    "max_trade_premium_5m",
    "call_premium_5m",
    "put_premium_5m",
    "repeated_contract_premium",
    "strike_concentration",
    "expiry_concentration",
    "ask_side_premium_share",
    "bid_side_premium_share",
)
OFFICIAL_SOURCE_HEADERS: Final[dict[str, str]] = {
    "User-Agent": "Mozilla/5.0 (compatible; MDS650-PIT-Audit/2.1)",
    "Accept": "text/plain, application/json;q=0.9, text/html;q=0.8",
}
OFFICIAL_SOURCE_SPECS: Final[tuple[dict[str, str], ...]] = (
    {
        "source_id": "fmp_faq_intraday_timezone",
        "provider": "FMP",
        "title": "FMP FAQ: API endpoint time zones",
        "url": "https://site.financialmodelingprep.com/faqs?code=commodity",
        "official_domain": "site.financialmodelingprep.com",
        "content_class": "FAQ_HTML",
        "documented_excerpt": (
            "FMP states that endpoint time zones correspond to the country or region "
            "of the exchange; the intraday endpoint follows the same convention."
        ),
        "documented_nonclaim": (
            "The FAQ does not establish exact IANA zone handling, DST implementation, "
            "bar start/close labels, or completed-bar latency."
        ),
    },
    {
        "source_id": "uw_full_tape_rest",
        "provider": "Unusual Whales",
        "title": "Full Tape REST operation",
        "url": "https://api.unusualwhales.com/docs/operations/PublicApi.OptionTradeController.full_tape",
        "official_domain": "api.unusualwhales.com",
        "content_class": "REST_OPERATION_HTML",
        "documented_excerpt": (
            "The REST operation downloads all option transactions for a required "
            "market date and returns an application/zip response."
        ),
        "documented_nonclaim": (
            "The operation page does not define the semantics of executed_at or "
            "created_at fields inside a historical ZIP payload."
        ),
    },
    {
        "source_id": "uw_openapi_full_tape",
        "provider": "Unusual Whales",
        "title": "Unusual Whales OpenAPI Full Tape contract",
        "url": "https://api.unusualwhales.com/api/openapi",
        "official_domain": "api.unusualwhales.com",
        "content_class": "OPENAPI_YAML",
        "documented_excerpt": (
            "OpenAPI describes GET /api/option-trades/full-tape/{date} as a full "
            "option-transaction ZIP for a market date."
        ),
        "documented_nonclaim": (
            "The OpenAPI response declaration does not define historical field-level "
            "created_at or executed_at semantics."
        ),
    },
    {
        "source_id": "uw_kafka_option_trade",
        "provider": "Unusual Whales",
        "title": "Unusual Whales Kafka OptionTrade type",
        "url": "https://api.unusualwhales.com/docs/kafka/types/OptionTrade",
        "official_domain": "api.unusualwhales.com",
        "content_class": "KAFKA_TYPE_HTML",
        "documented_excerpt": (
            "Kafka OptionTrade documents executed_at as execution time and created_at "
            "as trade-record creation time, in Unix milliseconds."
        ),
        "documented_nonclaim": (
            "Kafka documentation does not establish publication time, client receipt "
            "time, or identical semantics for a historical Full Tape ZIP."
        ),
    },
)


@dataclass(frozen=True)
class OfficialSourceResponse:
    """Minimal, sanitized response envelope for an official-document fetch.

    Parameters
    ----------
    status_code:
        HTTP response status from an allow-listed official documentation URL.
    content_type:
        Response media type without interpretation as a provider-data payload.
    body:
        Bytes whose hash is retained in evidence but whose body is never persisted.
    """

    status_code: int
    content_type: str
    body: bytes


@dataclass
class _SensitivityAccumulator:
    """Compact aggregate state for one Massive cutoff and optional asset."""

    attempt_count: int = 0
    cache_resolved_attempt_count: int = 0
    selected_quote_count: int = 0
    no_quote_count: int = 0
    future_quote_count: int = 0
    invalid_selected_spread_count: int = 0
    invalid_selected_nbbo_count: int = 0
    relative_spread_exceeds_limit_count: int = 0
    technical_iv_attempt_count: int = 0
    iv_success_count: int = 0
    iv_failure_count: int = 0
    iv_failure_reason_counts: Counter[str] = field(default_factory=Counter)
    age_from_origin: array[float] = field(default_factory=lambda: array("d"))
    age_from_cutoff: array[float] = field(default_factory=lambda: array("d"))

    def add_quote(
        self,
        *,
        origin_ns: int,
        cutoff_ns: int,
        quote: tuple[int, int, float, float],
        iv_result: Mapping[str, Any] | None,
    ) -> None:
        """Accumulate one quote selection under an already-validated cache."""
        sip_timestamp, _, bid, ask = quote
        self.selected_quote_count += 1
        if sip_timestamp > cutoff_ns or cutoff_ns > origin_ns:
            self.future_quote_count += 1
            return
        age_origin = (origin_ns - sip_timestamp) / NANOSECONDS_PER_SECOND
        age_cutoff = (cutoff_ns - sip_timestamp) / NANOSECONDS_PER_SECOND
        self.age_from_origin.append(age_origin)
        self.age_from_cutoff.append(age_cutoff)
        if (
            not math.isfinite(bid)
            or not math.isfinite(ask)
            or bid <= 0.0
            or ask <= bid
        ):
            self.invalid_selected_nbbo_count += 1
            self.invalid_selected_spread_count += 1
            return
        midpoint = (bid + ask) / 2.0
        relative_spread = (ask - bid) / midpoint
        if relative_spread > REGULAR_RELATIVE_SPREAD_LIMIT:
            self.relative_spread_exceeds_limit_count += 1
            return
        self.technical_iv_attempt_count += 1
        if iv_result is not None and bool(iv_result.get("success")):
            self.iv_success_count += 1
        else:
            self.iv_failure_count += 1
            failure_reason = (
                str(iv_result.get("failure_reason", "IV_NO_CONVERGENCE"))
                if iv_result is not None
                else "IV_NO_CONVERGENCE"
            )
            self.iv_failure_reason_counts[failure_reason] += 1

    def as_row(self, *, cutoff_delay_seconds: int, asset: str | None) -> dict[str, Any]:
        """Return a deterministic, sanitized metric row."""
        return {
            "cutoff_delay_seconds": cutoff_delay_seconds,
            "asset": asset,
            "attempt_count": self.attempt_count,
            "cache_resolved_attempt_count": self.cache_resolved_attempt_count,
            "selected_quote_count": self.selected_quote_count,
            "quote_coverage_rate": _rate(self.selected_quote_count, self.attempt_count),
            "no_quote_at_or_before_cutoff_count": self.no_quote_count,
            "future_quote_count": self.future_quote_count,
            "invalid_selected_spread_count": self.invalid_selected_spread_count,
            "invalid_selected_nbbo_count": self.invalid_selected_nbbo_count,
            "relative_spread_exceeds_25pct_count": self.relative_spread_exceeds_limit_count,
            "technical_iv_attempt_count": self.technical_iv_attempt_count,
            "iv_success_count": self.iv_success_count,
            "iv_available_rate": _rate(self.iv_success_count, self.attempt_count),
            "iv_success_rate_given_technical_attempt": _rate(
                self.iv_success_count, self.technical_iv_attempt_count
            ),
            "iv_failure_reason_counts": dict(sorted(self.iv_failure_reason_counts.items())),
            "median_quote_age_seconds": _median_array(self.age_from_origin),
            "median_quote_age_from_cutoff_seconds": _median_array(self.age_from_cutoff),
        }


@dataclass(frozen=True)
class _PreparedQuotes:
    """One cache's sorted SIP/sequence keys retained for repeated as-of joins."""

    rows: tuple[tuple[int, int, float, float], ...]
    keys: tuple[tuple[int, int], ...]


_EMPTY_PREPARED_QUOTES: Final[_PreparedQuotes] = _PreparedQuotes(rows=(), keys=())


def timestamp_array_to_ns(values: Any) -> tuple[list[int | None], list[bool]]:
    """Convert an Arrow timestamp array to nanoseconds without losing nulls.

    Parameters
    ----------
    values:
        A PyArrow timestamp array with any supported Arrow resolution: seconds,
        milliseconds, microseconds, or nanoseconds.

    Returns
    -------
    tuple[list[int | None], list[bool]]
        Nanosecond Unix instants and a parallel validity mask. Nulls remain
        ``None`` and are never treated as the Unix epoch.

    Raises
    ------
    ValueError
        If the input is not an Arrow timestamp type or has an unknown unit.

    Examples
    --------
    >>> array = pa.array([datetime(2025, 1, 1, tzinfo=UTC)], type=pa.timestamp("us", tz="UTC"))
    >>> timestamp_array_to_ns(array)[0][0] is not None
    True
    """
    value_type = values.type
    if not isinstance(value_type, pa.TimestampType):
        raise ValueError("TIMING_V21_TIMESTAMP_TYPE_REQUIRED")
    multiplier = _timestamp_multiplier(value_type)
    raw = pc.cast(values, pa.int64()).to_pylist()
    valid = [bool(item) for item in pc.is_valid(values).to_pylist()]
    result: list[int | None] = []
    for raw_value, is_valid in zip(raw, valid, strict=True):
        result.append(int(raw_value) * multiplier if is_valid and raw_value is not None else None)
    return result, valid


def _timestamp_array_numpy(values: Any) -> tuple[np.ndarray[Any, Any], np.ndarray[Any, Any]]:
    """Return UTC timestamp nanoseconds and validity masks without Python row loops."""
    value_type = values.type
    if not isinstance(value_type, pa.TimestampType):
        raise ValueError("TIMING_V21_TIMESTAMP_TYPE_REQUIRED")
    multiplier = _timestamp_multiplier(value_type)
    raw = np.asarray(
        pc.fill_null(pc.cast(values, pa.int64()), 0).to_numpy(zero_copy_only=False), dtype=np.int64
    )
    valid = np.asarray(pc.is_valid(values).to_numpy(zero_copy_only=False), dtype=bool)
    return raw * multiplier, valid


def _timestamp_multiplier(value_type: pa.TimestampType) -> int:
    multipliers = {"s": 1_000_000_000, "ms": 1_000_000, "us": 1_000, "ns": 1}
    multiplier = multipliers.get(value_type.unit)
    if multiplier is None:
        raise ValueError("TIMING_V21_TIMESTAMP_UNIT_UNSUPPORTED")
    return multiplier


def build_pit_claim_matrix_v21() -> list[dict[str, str]]:
    """Return the v2.1 provider claim matrix with explicit evidence classes.

    Returns
    -------
    list[dict[str, str]]
        Deterministically ordered claims. A Kafka statement and a Full Tape
        payload observation are distinct claims even when the field names match.
    """
    rows = [
        {
            "claim_key": "fmp_intraday_exchange_region_timezone",
            "provider": "FMP",
            "field_or_topic": "intraday endpoint timezone",
            "claim_class": "PROVIDER_DOCUMENTED",
            "evidence_locator": "fmp_faq_intraday_timezone",
            "permitted_conclusion": (
                "FMP documents endpoint time zones at the exchange country or region level."
            ),
        },
        {
            "claim_key": "fmp_exact_iana_timezone",
            "provider": "FMP",
            "field_or_topic": "exact IANA timezone",
            "claim_class": "UNVERIFIED",
            "evidence_locator": "fmp_faq_intraday_timezone",
            "permitted_conclusion": "Do not claim an exact provider IANA timezone implementation.",
        },
        {
            "claim_key": "fmp_dst_behavior",
            "provider": "FMP",
            "field_or_topic": "DST conversion behavior",
            "claim_class": "UNVERIFIED",
            "evidence_locator": "fmp_faq_intraday_timezone",
            "permitted_conclusion": "Do not claim provider-documented DST conversion behavior.",
        },
        {
            "claim_key": "fmp_bar_start_or_close",
            "provider": "FMP",
            "field_or_topic": "one-minute bar label",
            "claim_class": "UNVERIFIED",
            "evidence_locator": "fmp_faq_intraday_timezone",
            "permitted_conclusion": "Do not claim whether the raw bar label marks start or close.",
        },
        {
            "claim_key": "fmp_completed_bar_latency",
            "provider": "FMP",
            "field_or_topic": "completed-bar API latency",
            "claim_class": "UNVERIFIED",
            "evidence_locator": "fmp_faq_intraday_timezone",
            "permitted_conclusion": "Do not claim a numeric completed-bar availability latency.",
        },
        {
            "claim_key": "fmp_plus_one_minute",
            "provider": "FMP",
            "field_or_topic": "research availability convention",
            "claim_class": "STUDY_CONSERVATIVE_RULE",
            "evidence_locator": "study_contract_v21",
            "permitted_conclusion": "Use raw timestamp plus one minute as a conservative rule.",
        },
        {
            "claim_key": "uw_full_tape_endpoint",
            "provider": "Unusual Whales",
            "field_or_topic": "historical Full Tape endpoint",
            "claim_class": "PROVIDER_DOCUMENTED_REST",
            "evidence_locator": "uw_full_tape_rest_and_openapi",
            "permitted_conclusion": (
                "The documented endpoint returns a ZIP of transactions for a date."
            ),
        },
        {
            "claim_key": "uw_kafka_executed_at",
            "provider": "Unusual Whales",
            "field_or_topic": "Kafka executed_at",
            "claim_class": "PROVIDER_DOCUMENTED_KAFKA",
            "evidence_locator": "uw_kafka_option_trade",
            "permitted_conclusion": (
                "Kafka defines executed_at as trade execution time in Unix milliseconds."
            ),
        },
        {
            "claim_key": "uw_kafka_created_at",
            "provider": "Unusual Whales",
            "field_or_topic": "Kafka created_at",
            "claim_class": "PROVIDER_DOCUMENTED_KAFKA",
            "evidence_locator": "uw_kafka_option_trade",
            "permitted_conclusion": (
                "Kafka defines created_at as trade-record creation time in Unix milliseconds."
            ),
        },
        {
            "claim_key": "uw_full_tape_created_at_field",
            "provider": "Unusual Whales",
            "field_or_topic": "persisted Full Tape created_at field",
            "claim_class": "PAYLOAD_OBSERVED",
            "evidence_locator": "acquired_full_tape_schema_v21",
            "permitted_conclusion": "Acquired Full Tape partitions contain a UTC created_at field.",
        },
        {
            "claim_key": "uw_full_tape_created_at_semantics",
            "provider": "Unusual Whales",
            "field_or_topic": "Full Tape created_at semantics",
            "claim_class": "UNVERIFIED",
            "evidence_locator": "uw_full_tape_rest_and_openapi",
            "permitted_conclusion": (
                "Do not transfer Kafka field semantics to Full Tape REST solely from a "
                "field-name match."
            ),
        },
        {
            "claim_key": "uw_created_at_operational_proxy",
            "provider": "Unusual Whales",
            "field_or_topic": "B2 cutoff",
            "claim_class": "STUDY_CONSERVATIVE_RULE",
            "evidence_locator": "study_contract_v21",
            "permitted_conclusion": "Treat created_at only as an operational availability proxy.",
        },
        {
            "claim_key": "uw_zero_coding_availability",
            "provider": "Unusual Whales",
            "field_or_topic": "canonical B2 zero",
            "claim_class": "PAYLOAD_OBSERVED",
            "evidence_locator": "b2_traceability_v21",
            "permitted_conclusion": (
                "A numeric B2 zero is a coding state, not automatically no activity."
            ),
        },
        {
            "claim_key": "uw_zero_activity_semantics",
            "provider": "Unusual Whales",
            "field_or_topic": "true absence of activity",
            "claim_class": "NOT_PERMITTED_WITHOUT_AVAILABILITY_SIDECAR",
            "evidence_locator": "b2_traceability_v21",
            "permitted_conclusion": (
                "Do not interpret zero as no activity where source availability is confounded."
            ),
        },
        {
            "claim_key": "massive_shifted_asof_selection",
            "provider": "Massive",
            "field_or_topic": "source-time sensitivity",
            "claim_class": "STUDY_CONSERVATIVE_RULE",
            "evidence_locator": "massive_reselection_sensitivity_v21",
            "permitted_conclusion": (
                "Reselect the last SIP quote no later than each shifted cutoff."
            ),
        },
    ]
    return sorted(rows, key=lambda row: row["claim_key"])


def archive_official_source_records(
    *,
    output_dir: Path,
    fetch: Callable[[str, dict[str, str]], OfficialSourceResponse],
    reviewed_on_utc: str = "2026-08-11",
) -> list[dict[str, Any]]:
    """Archive hash-addressed metadata for a fixed official-document allow-list.

    Parameters
    ----------
    output_dir:
        Destination for compact JSON source records. Raw document bodies are
        not written.
    fetch:
        Credential-free function that retrieves an allow-listed documentation URL.
    reviewed_on_utc:
        ISO calendar date assigned to this documentation review.

    Returns
    -------
    list[dict[str, Any]]
        Deterministically ordered source records containing status, content type,
        byte count, SHA-256, documented excerpt, and non-claim boundary.

    Raises
    ------
    RuntimeError
        If an allow-listed source does not return HTTP 200.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    for spec in OFFICIAL_SOURCE_SPECS:
        response = fetch(spec["url"], dict(OFFICIAL_SOURCE_HEADERS))
        if response.status_code != 200:
            raise RuntimeError(
                f"TIMING_V21_OFFICIAL_SOURCE_HTTP_{response.status_code}:{spec['source_id']}"
            )
        record = {
            **spec,
            "reviewed_on_utc": reviewed_on_utc,
            "access_mode": "credential_free_official_documentation_http_archive",
            "http_status": response.status_code,
            "content_type": response.content_type,
            "source_byte_count": len(response.body),
            "source_content_sha256": hashlib.sha256(response.body).hexdigest(),
            "source_content_hash_status": "HTTP_200_BODY_SHA256",
        }
        record["archive_record_sha256"] = canonical_sha256(record)
        path = output_dir / f"{spec['source_id']}.json"
        path.write_text(_canonical_json(record), encoding="utf-8")
        records.append(record)
    return sorted(records, key=lambda row: str(row["source_id"]))


def audit_uw_session_asset_incidents(
    *,
    event_root: Path,
    session_dates: Sequence[str],
    assets: Sequence[str],
    batch_size: int = 131_072,
) -> list[dict[str, Any]]:
    """Audit Full Tape timing state per requested session and asset.

    Parameters
    ----------
    event_root:
        Root of acquired partitions named ``date=YYYY-MM-DD/asset=SYMBOL/events.parquet``.
    session_dates:
        Trading-session dates to inspect. The function never derives dates from
        a target or model artifact.
    assets:
        Symbols whose existing source partitions are audited.
    batch_size:
        Bounded Parquet batch size, limiting RAM while inspecting large payloads.

    Returns
    -------
    list[dict[str, Any]]
        One sanitized incident row per requested session-asset. The row names
        observed delay but does not invent a provider-internal root cause.

    Raises
    ------
    FileNotFoundError
        If the Full Tape root is not present.
    ValueError
        If the batch size is invalid or a requested date is malformed.
    """
    if not event_root.is_dir():
        raise FileNotFoundError("TIMING_V21_FULL_TAPE_ROOT_MISSING")
    if batch_size <= 0:
        raise ValueError("TIMING_V21_BATCH_SIZE_MUST_BE_POSITIVE")
    dates = tuple(sorted(set(session_dates)))
    symbols = tuple(sorted(set(assets)))
    if not dates or not symbols:
        raise ValueError("TIMING_V21_SESSION_AND_ASSET_SCOPE_REQUIRED")
    output: list[dict[str, Any]] = []
    for session_date in dates:
        bounds = _session_bounds_ns(session_date)
        for asset in symbols:
            path = event_root / f"date={session_date}" / f"asset={asset}" / "events.parquet"
            output.append(
                _audit_one_uw_partition(
                    path=path,
                    asset=asset,
                    session_date=session_date,
                    bounds=bounds,
                    batch_size=batch_size,
                )
            )
    return sorted(output, key=lambda row: (str(row["session_date"]), str(row["asset"])))


def audit_b2_canonical_traceability(
    *,
    matrix_root: Path,
    incidents: Sequence[Mapping[str, Any]],
    expected_origins_per_asset_date: int | None = None,
    expected_origins_path: Path | None = None,
) -> tuple[list[dict[str, Any]], str]:
    """Classify how canonical B2 matrices encode each session-asset condition.

    Parameters
    ----------
    matrix_root:
        Root of canonical B2 variants, each holding ``date=YYYY-MM-DD.parquet``.
    incidents:
        Source-state rows from :func:`audit_uw_session_asset_incidents`.
    expected_origins_per_asset_date:
        Test-only fixed expected count. Use ``None`` for production and supply
        ``expected_origins_path`` so early closes retain their shorter schedule.
    expected_origins_path:
        Target-free origin projection used to determine expected row count per
        session and asset without hard-coding 72 across early closes.

    Returns
    -------
    tuple[list[dict[str, Any]], str]
        Sanitized matrix-sidecar rows and the availability gate. The gate fails
        whenever a source issue can be represented as a numeric zero.

    Raises
    ------
    FileNotFoundError
        If the canonical matrix root is absent.
    ValueError
        If required B2 columns or expected-origin inputs are invalid.
    """
    if not matrix_root.is_dir():
        raise FileNotFoundError("TIMING_V21_B2_MATRIX_ROOT_MISSING")
    if expected_origins_per_asset_date is not None and expected_origins_per_asset_date <= 0:
        raise ValueError("TIMING_V21_EXPECTED_ORIGIN_COUNT_MUST_BE_POSITIVE")
    expected = _expected_origin_counts(
        expected_origins_per_asset_date=expected_origins_per_asset_date,
        expected_origins_path=expected_origins_path,
    )
    incident_by_key = {(str(row["session_date"]), str(row["asset"])): row for row in incidents}
    groups: dict[tuple[str, str, str], dict[str, Any]] = {}
    for matrix_dir in sorted(path for path in matrix_root.iterdir() if path.is_dir()):
        for path in sorted(matrix_dir.glob("date=*.parquet")):
            table = pq.read_table(path)
            required = {"asset", "session_date", "origin_id", *B2_FEATURE_COLUMNS}
            if not required.issubset(table.column_names):
                raise ValueError("TIMING_V21_B2_REQUIRED_COLUMNS_MISSING")
            logical_file_hash = hashlib.sha256(path.read_bytes()).hexdigest()
            for row in table.select(
                ["asset", "session_date", "origin_id", *B2_FEATURE_COLUMNS]
            ).to_pylist():
                asset = str(row["asset"])
                session_date = str(row["session_date"])
                key = (matrix_dir.name, session_date, asset)
                group = groups.setdefault(
                    key,
                    {
                        "canonical_variant": matrix_dir.name,
                        "session_date": session_date,
                        "asset": asset,
                        "observed_origin_count": 0,
                        "numeric_feature_null_count": 0,
                        "all_zero_feature_origin_count": 0,
                        "nonzero_feature_origin_count": 0,
                        "canonical_file_sha256": logical_file_hash,
                    },
                )
                group["observed_origin_count"] += 1
                values = [row[column] for column in B2_FEATURE_COLUMNS]
                if any(value is None for value in values):
                    group["numeric_feature_null_count"] += sum(value is None for value in values)
                elif all(float(value) == 0.0 for value in values):
                    group["all_zero_feature_origin_count"] += 1
                else:
                    group["nonzero_feature_origin_count"] += 1
    output: list[dict[str, Any]] = []
    for key in sorted(groups):
        group = groups[key]
        incident = incident_by_key.get((str(group["session_date"]), str(group["asset"])))
        source_temporal_state = (
            str(incident["source_temporal_state"])
            if incident is not None
            else "SOURCE_INCIDENT_NOT_AUDITED"
        )
        expected_count = expected.get(
            (str(group["session_date"]), str(group["asset"])),
            expected_origins_per_asset_date,
        )
        observed_count = int(group["observed_origin_count"])
        zero_origin_count = int(group["all_zero_feature_origin_count"])
        all_zero = observed_count > 0 and zero_origin_count == observed_count
        if expected_count is None:
            row_presence_status = "EXPECTED_COUNT_UNRESOLVED"
        elif observed_count < expected_count:
            row_presence_status = "ROW_ABSENT"
        elif observed_count == expected_count:
            row_presence_status = "ALL_EXPECTED_ROWS_PRESENT"
        else:
            row_presence_status = "UNEXPECTED_EXTRA_ROWS"
        if row_presence_status == "ROW_ABSENT":
            coding_status = "ROW_EXCLUDED_OR_MISSING"
        elif int(group["numeric_feature_null_count"]) > 0:
            coding_status = "MISSING_FEATURE_VALUES"
        elif zero_origin_count > 0 and source_temporal_state == "SOURCE_UNAVAILABLE":
            coding_status = "ZERO_CODING_SOURCE_UNAVAILABLE"
        elif zero_origin_count > 0 and source_temporal_state == "RECORD_CREATION_DELAY_OBSERVED":
            coding_status = "ZERO_CODING_POTENTIALLY_CONFOUNDED"
        elif all_zero:
            coding_status = "ZERO_CODING_SOURCE_AVAILABLE"
        else:
            coding_status = "NUMERIC_NONZERO_FEATURE_VALUES"
        output.append(
            {
                **group,
                "expected_origin_count": expected_count,
                "row_presence_status": row_presence_status,
                "source_temporal_state": source_temporal_state,
                "availability_indicator_status": "ABSENT",
                "max_created_at_is_provenance_not_availability_indicator": True,
                "canonical_value_coding": _canonical_value_coding(
                    observed_count=observed_count,
                    zero_origin_count=zero_origin_count,
                    nonzero_origin_count=int(group["nonzero_feature_origin_count"]),
                    null_count=int(group["numeric_feature_null_count"]),
                ),
                "coding_status": coding_status,
                "zero_interpretation": _zero_interpretation(coding_status),
            }
        )
    gate = (
        "FAIL_ZERO_ACTIVITY_NOT_DISAMBIGUATED"
        if any(
            row["coding_status"]
            in {"ZERO_CODING_POTENTIALLY_CONFOUNDED", "ZERO_CODING_SOURCE_UNAVAILABLE"}
            for row in output
        )
        else "PASS_NO_CONFOUNDED_ZERO_OBSERVED"
    )
    return output, gate


def audit_forecast_origin_session_bounds(
    *, origins_path: Path, batch_size: int = 131_072
) -> dict[str, Any]:
    """Verify that existing forecast origins remain inside XNYS session bounds.

    Parameters
    ----------
    origins_path
    Target-free forecast-origin Parquet sidecar containing ``asset``,
        ``session_date``, and either a nanosecond ``forecast_origin_ns`` field
        or a timezone-aware UTC ``forecast_origin_utc`` Arrow timestamp.
    batch_size
        Maximum number of rows decoded per batch.

    Returns
    -------
    dict[str, Any]
        Sanitized origin/session boundary summary. The status is ``PASS`` only
        when every decoded origin lies inside its official XNYS session bounds.

    Raises
    ------
    FileNotFoundError
        If the requested target-free sidecar is absent.
    ValueError
        If ``batch_size`` is non-positive.
    """
    if not origins_path.is_file():
        raise FileNotFoundError("TIMING_V21_FORECAST_ORIGINS_MISSING")
    if batch_size <= 0:
        raise ValueError("TIMING_V21_BATCH_SIZE_MUST_BE_POSITIVE")
    reader = pq.ParquetFile(origins_path)
    schema = reader.schema_arrow
    base_required_columns = {"asset", "session_date"}
    missing_columns = sorted(base_required_columns.difference(schema.names))
    has_ns = "forecast_origin_ns" in schema.names
    has_utc = "forecast_origin_utc" in schema.names
    if missing_columns or (not has_ns and not has_utc):
        return {
            "status": "FAIL_ORIGIN_TIMESTAMP_SCHEMA",
            "missing_columns": sorted(
                set(missing_columns).union(
                    {"forecast_origin_ns_or_forecast_origin_utc"}
                    if not has_ns and not has_utc
                    else set()
                )
            ),
            "origin_timestamp_column": None,
            "origin_row_count": 0,
            "session_asset_group_count": 0,
            "origin_before_open_count": 0,
            "origin_after_close_count": 0,
            "unresolved_session_date_count": 0,
            "early_close_session_date_count": 0,
            "early_close_session_asset_group_count": 0,
            "early_close_origin_count": 0,
        }
    origin_timestamp_column = "forecast_origin_ns" if has_ns else "forecast_origin_utc"
    if origin_timestamp_column == "forecast_origin_utc":
        timestamp_type = schema.field(origin_timestamp_column).type
        if not isinstance(timestamp_type, pa.TimestampType) or timestamp_type.tz != "UTC":
            return {
                "status": "FAIL_ORIGIN_TIMESTAMP_SCHEMA",
                "missing_columns": [],
                "origin_timestamp_column": origin_timestamp_column,
                "origin_row_count": 0,
                "session_asset_group_count": 0,
                "origin_before_open_count": 0,
                "origin_after_close_count": 0,
                "unresolved_session_date_count": 0,
                "early_close_session_date_count": 0,
                "early_close_session_asset_group_count": 0,
                "early_close_origin_count": 0,
            }
    group_counts: Counter[tuple[str, str]] = Counter()
    early_close_groups: set[tuple[str, str]] = set()
    early_close_dates: set[str] = set()
    origin_count = 0
    before_open_count = 0
    after_close_count = 0
    unresolved_dates: set[str] = set()
    bounds_by_date: dict[str, Mapping[str, int]] = {}
    for batch in reader.iter_batches(
        batch_size=batch_size,
        columns=["asset", "session_date", origin_timestamp_column],
    ):
        assets = batch.column(0).to_pylist()
        session_dates = batch.column(1).to_pylist()
        if origin_timestamp_column == "forecast_origin_ns":
            origin_values = batch.column(2).to_pylist()
            origin_valid = [isinstance(value, int) for value in origin_values]
            origin_ns_values = [int(value) if valid else 0 for value, valid in zip(
                origin_values, origin_valid, strict=True
            )]
        else:
            origin_ns_values_array, origin_valid_array = _timestamp_array_numpy(batch.column(2))
            origin_ns_values = origin_ns_values_array.tolist()
            origin_valid = origin_valid_array.tolist()
        for asset_value, session_date_value, origin_value, is_valid in zip(
            assets, session_dates, origin_ns_values, origin_valid, strict=True
        ):
            asset = str(asset_value)
            session_date = str(session_date_value)
            group_key = (asset, session_date)
            group_counts[group_key] += 1
            origin_count += 1
            if session_date not in bounds_by_date:
                try:
                    bounds_by_date[session_date] = _session_bounds_ns(session_date)
                except ValueError:
                    unresolved_dates.add(session_date)
                    continue
            bounds = bounds_by_date.get(session_date)
            if bounds is None:
                continue
            session_day = date.fromisoformat(session_date)
            nominal_regular_close_ns = _datetime_to_ns(
                datetime.combine(session_day, time(hour=16), tzinfo=_new_york_zone())
            )
            if bounds["close_ns"] < nominal_regular_close_ns:
                early_close_dates.add(session_date)
                early_close_groups.add(group_key)
            if not is_valid:
                unresolved_dates.add(session_date)
                continue
            origin_ns = int(origin_value)
            if origin_ns < bounds["open_ns"]:
                before_open_count += 1
            if origin_ns > bounds["close_ns"]:
                after_close_count += 1
    early_close_origin_count = sum(group_counts[key] for key in early_close_groups)
    status = (
        "PASS"
        if not unresolved_dates and before_open_count == 0 and after_close_count == 0
        else "FAIL_ORIGIN_OUTSIDE_XNYS_SESSION"
    )
    return {
        "status": status,
        "origin_timestamp_column": origin_timestamp_column,
        "origin_row_count": origin_count,
        "session_asset_group_count": len(group_counts),
        "origin_before_open_count": before_open_count,
        "origin_after_close_count": after_close_count,
        "unresolved_session_date_count": len(unresolved_dates),
        "early_close_session_date_count": len(early_close_dates),
        "early_close_session_asset_group_count": len(early_close_groups),
        "early_close_origin_count": early_close_origin_count,
    }


def reselect_last_quote_asof(
    *, quotes: Sequence[Mapping[str, Any]], cutoff_ns: int
) -> dict[str, int | float] | None:
    """Select the last raw Massive quote at or before a cutoff.

    Parameters
    ----------
    quotes:
        Raw cache quote mappings with SIP nanoseconds, sequence number, bid and ask.
    cutoff_ns:
        Inclusive as-of cutoff in Unix nanoseconds.

    Returns
    -------
    dict[str, int | float] | None
        The last quote under ``(sip_timestamp, sequence_number)`` order, or
        ``None`` when no valid timestamp/sequence pair precedes the cutoff.

    Notes
    -----
    This intentionally does not walk backward to find a prior valid spread. The
    selected quote's NBBO validity is a separate, explicit quality decision.
    """
    prepared = _prepare_quotes(quotes)
    selected = _select_prepared_quote(prepared, cutoff_ns)
    if selected is None:
        return None
    sip_timestamp, sequence_number, bid, ask = selected
    return {
        "sip_timestamp": sip_timestamp,
        "sequence_number": sequence_number,
        "bid_price": bid,
        "ask_price": ask,
    }


def audit_massive_reselection(
    *,
    attempts_path: Path,
    cache_root: Path,
    cutoffs_seconds: Sequence[int] = DEFAULT_MASSIVE_CUTOFFS_SECONDS,
    batch_size: int = 65_536,
) -> dict[str, Any]:
    """Re-select cached Massive quotes at each shifted as-of cutoff.

    Parameters
    ----------
    attempts_path:
        Target-free B1 IV-attempt Parquet. Only contract, timestamp, spot,
        option, rate, and dividend fields are selected.
    cache_root:
        Existing Massive v4 cache root. One envelope is decoded at a time.
    cutoffs_seconds:
        Non-negative source-time delays. Default is origin, origin-60, and
        origin-300 seconds.
    batch_size:
        Parquet batch size used to bound attempt-row memory.

    Returns
    -------
    dict[str, Any]
        Aggregate coverage, quote-age, IV availability, cache identity failures,
        and monotonic quote-existence check. No raw quote, contract, request ID,
        path, target, or model field is emitted.

    Raises
    ------
    FileNotFoundError
        If the target-free attempt table or cache root is missing.
    ValueError
        If required schema fields, cutoff ordering, or batch size is invalid.
    """
    if not attempts_path.is_file():
        raise FileNotFoundError("TIMING_V21_B1_ATTEMPTS_MISSING")
    if not cache_root.is_dir():
        raise FileNotFoundError("TIMING_V21_MASSIVE_CACHE_ROOT_MISSING")
    _validate_cutoffs(cutoffs_seconds)
    if batch_size <= 0:
        raise ValueError("TIMING_V21_BATCH_SIZE_MUST_BE_POSITIVE")
    cutoffs = tuple(cutoffs_seconds)
    cache_index = _massive_cache_index(cache_root)
    global_accumulators = {delay: _SensitivityAccumulator() for delay in cutoffs}
    asset_accumulators: dict[tuple[int, str], _SensitivityAccumulator] = {}
    cache_identity_failures: Counter[str] = Counter()
    attempt_identity_failures: Counter[str] = Counter()
    cache_scope_warnings: Counter[str] = Counter()
    processing_counts = {
        "asset_day_group_count": 0,
        "contract_day_group_count": 0,
        "cache_envelope_decode_count": 0,
        "max_pending_attempt_rows": 0,
    }
    required_columns = [
        "asset",
        "session_date",
        "contract",
        "source_request_hash",
        "forecast_origin_ns",
        "spot",
        "strike",
        "dte",
        "rate",
        "dividend_yield",
        "option_type",
    ]
    reader = pq.ParquetFile(attempts_path)
    if not set(required_columns).issubset(reader.schema_arrow.names):
        raise ValueError("TIMING_V21_B1_ATTEMPT_COLUMNS_MISSING")
    def _asset_accumulator(delay: int, asset: str) -> _SensitivityAccumulator:
        return asset_accumulators.setdefault((delay, asset), _SensitivityAccumulator())

    def _record_attempt_count(*, asset: str) -> None:
        for delay in cutoffs:
            global_accumulators[delay].attempt_count += 1
            _asset_accumulator(delay, asset).attempt_count += 1

    def _process_asset_day(
        *, asset: str, session_date: str, rows: list[dict[str, Any]]
    ) -> None:
        """Process one contiguous asset-day, decoding each cache once."""
        processing_counts["asset_day_group_count"] += 1
        processing_counts["max_pending_attempt_rows"] = max(
            processing_counts["max_pending_attempt_rows"], len(rows)
        )
        by_contract: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(
            lambda: defaultdict(list)
        )
        for row in rows:
            by_contract[str(row["contract"])][str(row["source_request_hash"])].append(row)
        for contract in sorted(by_contract):
            by_source_hash = by_contract[contract]
            processing_counts["contract_day_group_count"] += 1
            contract_rows = [
                row
                for source_hash in sorted(by_source_hash)
                for row in by_source_hash[source_hash]
            ]
            for _row in contract_rows:
                _record_attempt_count(asset=asset)
            if len(by_source_hash) != 1:
                attempt_identity_failures["ATTEMPT_SOURCE_HASH_AMBIGUOUS"] += 1
                continue
            source_request_hash, resolved_rows = next(iter(by_source_hash.items()))
            processing_counts["cache_envelope_decode_count"] += 1
            cache_state, quotes = _load_and_validate_massive_cache(
                cache_index=cache_index,
                cache_root=cache_root,
                asset=asset,
                session_date=session_date,
                contract=contract,
                source_request_hash=source_request_hash,
            )
            if cache_state not in VALID_MASSIVE_CACHE_STATES:
                cache_identity_failures[cache_state] += 1
                continue
            if cache_state != "OK":
                cache_scope_warnings[cache_state] += 1
            for row in resolved_rows:
                origin_ns = int(row["forecast_origin_ns"])
                for delay in cutoffs:
                    global_acc = global_accumulators[delay]
                    asset_acc = _asset_accumulator(delay, asset)
                    global_acc.cache_resolved_attempt_count += 1
                    asset_acc.cache_resolved_attempt_count += 1
                    cutoff_ns = origin_ns - delay * NANOSECONDS_PER_SECOND
                    selected = _select_prepared_quote(quotes, cutoff_ns)
                    if selected is None:
                        global_acc.no_quote_count += 1
                        asset_acc.no_quote_count += 1
                        continue
                    iv_result = _iv_from_reselected_quote(row=row, quote=selected)
                    global_acc.add_quote(
                        origin_ns=origin_ns,
                        cutoff_ns=cutoff_ns,
                        quote=selected,
                        iv_result=iv_result,
                    )
                    asset_acc.add_quote(
                        origin_ns=origin_ns,
                        cutoff_ns=cutoff_ns,
                        quote=selected,
                        iv_result=iv_result,
                    )

    closed_asset_days: set[tuple[str, str]] = set()
    current_asset_day: tuple[str, str] | None = None
    current_rows: list[dict[str, Any]] = []
    for batch in reader.iter_batches(batch_size=batch_size, columns=required_columns):
        for row in pa.Table.from_batches([batch]).to_pylist():
            asset_day = (str(row["asset"]), str(row["session_date"]))
            if current_asset_day is None:
                current_asset_day = asset_day
            elif asset_day != current_asset_day:
                _process_asset_day(
                    asset=current_asset_day[0],
                    session_date=current_asset_day[1],
                    rows=current_rows,
                )
                closed_asset_days.add(current_asset_day)
                if asset_day in closed_asset_days:
                    raise ValueError("TIMING_V21_ATTEMPT_ASSET_DAY_NONCONTIGUOUS")
                current_asset_day = asset_day
                current_rows = []
            current_rows.append(row)
    if current_asset_day is not None:
        _process_asset_day(
            asset=current_asset_day[0], session_date=current_asset_day[1], rows=current_rows
        )
    global_rows = [
        global_accumulators[delay].as_row(cutoff_delay_seconds=delay, asset=None)
        for delay in cutoffs
    ]
    asset_rows = [
        accumulator.as_row(cutoff_delay_seconds=delay, asset=asset)
        for (delay, asset), accumulator in sorted(asset_accumulators.items())
    ]
    selection_counts = [int(row["selected_quote_count"]) for row in global_rows]
    quote_coverage_monotonic = all(
        earlier >= later
        for earlier, later in zip(selection_counts, selection_counts[1:], strict=False)
    )
    return {
        "schema_version": "provider-timing-v2.1",
        "status": (
            "PASS"
            if (
                not cache_identity_failures
                and not attempt_identity_failures
                and quote_coverage_monotonic
            )
            else "FAIL_CACHE_IDENTITY_OR_MONOTONICITY"
        ),
        "scope": "existing_target_free_b1_attempts_and_existing_massive_v4_cache",
        "no_provider_http_requests_performed": True,
        "no_targets_or_predictive_metrics_read": True,
        "selection_rule": (
            "last_quote_by_sip_timestamp_then_sequence_at_or_before_origin_minus_delay"
        ),
        "quote_age_reference": "reported_relative_to_original_origin_and_shifted_cutoff",
        "technical_iv_definition": (
            "recomputed_BSM_from_reselected_midpoint_and_existing_PIT_inputs"
        ),
        "attempt_group_count": processing_counts["contract_day_group_count"],
        **processing_counts,
        "cache_identity_failures": dict(sorted(cache_identity_failures.items())),
        "attempt_identity_failures": dict(sorted(attempt_identity_failures.items())),
        "cache_scope_warnings": dict(sorted(cache_scope_warnings.items())),
        "summary_by_cutoff": global_rows,
        "summary_by_cutoff_asset": asset_rows,
        "quote_existence_coverage_monotonic_nonincreasing": quote_coverage_monotonic,
        "iv_coverage_not_required_monotonic": True,
    }


def canonical_sha256(value: Any) -> str:
    """Return SHA-256 over deterministic compact JSON.

    Parameters
    ----------
    value:
        JSON-serializable sanitized content.

    Returns
    -------
    str
        Lowercase hexadecimal SHA-256 digest.
    """
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _audit_one_uw_partition(
    *, path: Path, asset: str, session_date: str, bounds: Mapping[str, int], batch_size: int
) -> dict[str, Any]:
    if not path.is_file():
        return _empty_incident(asset=asset, session_date=session_date, state="SOURCE_UNAVAILABLE")
    reader = pq.ParquetFile(path)
    if not {"executed_at", "created_at"}.issubset(reader.schema_arrow.names):
        return _empty_incident(
            asset=asset, session_date=session_date, state="TIMESTAMP_SCHEMA_INVALID"
        )
    source_row_count = int(reader.metadata.num_rows) if reader.metadata is not None else 0
    if source_row_count == 0:
        return _empty_incident(asset=asset, session_date=session_date, state="SOURCE_EMPTY")
    executed_valid_count = 0
    created_valid_count = 0
    valid_pair_count = 0
    executed_in_regular_count = 0
    created_in_regular_count = 0
    executed_local_date_match_count = 0
    created_local_date_match_count = 0
    negative_lag_count = 0
    lag_over_300_count = 0
    lag_over_3600_count = 0
    min_executed_ns: int | None = None
    max_executed_ns: int | None = None
    min_created_ns: int | None = None
    max_created_ns: int | None = None
    lag_chunks: list[np.ndarray[Any, Any]] = []
    try:
        for batch in reader.iter_batches(
            batch_size=batch_size, columns=["executed_at", "created_at"]
        ):
            executed, executed_valid = _timestamp_array_numpy(batch.column(0))
            created, created_valid = _timestamp_array_numpy(batch.column(1))
            executed_valid_count += int(executed_valid.sum())
            created_valid_count += int(created_valid.sum())
            if bool(executed_valid.any()):
                valid_executed = executed[executed_valid]
                min_executed_ns = _min_optional(min_executed_ns, int(valid_executed.min()))
                max_executed_ns = _max_optional(max_executed_ns, int(valid_executed.max()))
                executed_in_regular_count += int(
                    (
                        (valid_executed >= bounds["open_ns"])
                        & (valid_executed <= bounds["close_ns"])
                    ).sum()
                )
                executed_local_date_match_count += int(
                    (
                        (valid_executed >= bounds["local_start_ns"])
                        & (valid_executed < bounds["local_next_start_ns"])
                    ).sum()
                )
            if bool(created_valid.any()):
                valid_created = created[created_valid]
                min_created_ns = _min_optional(min_created_ns, int(valid_created.min()))
                max_created_ns = _max_optional(max_created_ns, int(valid_created.max()))
                created_in_regular_count += int(
                    (
                        (valid_created >= bounds["open_ns"]) & (valid_created <= bounds["close_ns"])
                    ).sum()
                )
                created_local_date_match_count += int(
                    (
                        (valid_created >= bounds["local_start_ns"])
                        & (valid_created < bounds["local_next_start_ns"])
                    ).sum()
                )
            paired = executed_valid & created_valid
            if bool(paired.any()):
                lag = (created[paired] - executed[paired]).astype(
                    np.float64
                ) / NANOSECONDS_PER_SECOND
                valid_pair_count += int(paired.sum())
                lag_chunks.append(lag)
                negative_lag_count += int((lag < 0.0).sum())
                lag_over_300_count += int((lag > RECORD_DELAY_SECONDS).sum())
                lag_over_3600_count += int((lag > EXTREME_RECORD_DELAY_SECONDS).sum())
    except (pa.ArrowInvalid, pa.ArrowTypeError, ValueError):
        return _empty_incident(
            asset=asset, session_date=session_date, state="TIMESTAMP_SCHEMA_INVALID"
        )
    if valid_pair_count == 0:
        return _empty_incident(
            asset=asset, session_date=session_date, state="TIMESTAMP_SCHEMA_INVALID"
        )
    source_state = (
        "RECORD_CREATION_DELAY_OBSERVED" if lag_over_300_count > 0 else "SOURCE_AVAILABLE"
    )
    lag_values = np.concatenate(lag_chunks)
    return {
        "session_date": session_date,
        "asset": asset,
        "raw_source_status": "PRESENT_NONEMPTY",
        "source_temporal_state": source_state,
        "cause_classification": (
            "RECORD_CREATION_DELAY_OBSERVED_PROVIDER_CAUSE_UNRESOLVED"
            if source_state == "RECORD_CREATION_DELAY_OBSERVED"
            else "NO_TEMPORAL_ANOMALY_OBSERVED"
        ),
        "source_row_count": source_row_count,
        "timestamp_schema": "executed_at_and_created_at_timestamp",
        "timestamp_unit": "nanoseconds_normalized_from_arrow_unit",
        "executed_valid_count": executed_valid_count,
        "created_valid_count": created_valid_count,
        "valid_timestamp_pair_count": valid_pair_count,
        "executed_local_date_match_count": executed_local_date_match_count,
        "created_local_date_match_count": created_local_date_match_count,
        "executed_regular_session_count": executed_in_regular_count,
        "created_regular_session_count": created_in_regular_count,
        "negative_lag_count": negative_lag_count,
        "lag_seconds_min": _as_float(lag_values.min()),
        "lag_seconds_p50": _as_float(np.percentile(lag_values, 50)),
        "lag_seconds_p95": _as_float(np.percentile(lag_values, 95)),
        "lag_seconds_p99": _as_float(np.percentile(lag_values, 99)),
        "lag_seconds_max": _as_float(lag_values.max()),
        "lag_over_300_seconds_count": lag_over_300_count,
        "lag_over_3600_seconds_count": lag_over_3600_count,
        "min_executed_at_utc": _ns_to_iso(min_executed_ns),
        "max_executed_at_utc": _ns_to_iso(max_executed_ns),
        "min_created_at_utc": _ns_to_iso(min_created_ns),
        "max_created_at_utc": _ns_to_iso(max_created_ns),
        "all_created_after_regular_close": bool(
            min_created_ns is not None and min_created_ns > bounds["close_ns"]
        ),
        "regular_session_open_utc": _ns_to_iso(bounds["open_ns"]),
        "regular_session_close_utc": _ns_to_iso(bounds["close_ns"]),
    }


def _empty_incident(*, asset: str, session_date: str, state: str) -> dict[str, Any]:
    return {
        "session_date": session_date,
        "asset": asset,
        "raw_source_status": "MISSING" if state == "SOURCE_UNAVAILABLE" else state,
        "source_temporal_state": state,
        "cause_classification": "RAW_SOURCE_UNAVAILABLE"
        if state == "SOURCE_UNAVAILABLE"
        else state,
        "source_row_count": 0,
        "timestamp_schema": None,
        "timestamp_unit": None,
        "executed_valid_count": 0,
        "created_valid_count": 0,
        "valid_timestamp_pair_count": 0,
        "executed_local_date_match_count": 0,
        "created_local_date_match_count": 0,
        "executed_regular_session_count": 0,
        "created_regular_session_count": 0,
        "negative_lag_count": 0,
        "lag_seconds_min": None,
        "lag_seconds_p50": None,
        "lag_seconds_p95": None,
        "lag_seconds_p99": None,
        "lag_seconds_max": None,
        "lag_over_300_seconds_count": 0,
        "lag_over_3600_seconds_count": 0,
        "min_executed_at_utc": None,
        "max_executed_at_utc": None,
        "min_created_at_utc": None,
        "max_created_at_utc": None,
        "all_created_after_regular_close": False,
        "regular_session_open_utc": None,
        "regular_session_close_utc": None,
    }


def _session_bounds_ns(session_date: str) -> dict[str, int]:
    try:
        day = date.fromisoformat(session_date)
    except ValueError as exc:
        raise ValueError("TIMING_V21_SESSION_DATE_INVALID") from exc
    calendar = xcals.get_calendar("XNYS")
    try:
        open_time = calendar.session_open(session_date).to_pydatetime()
        close_time = calendar.session_close(session_date).to_pydatetime()
    except Exception as exc:  # exchange-calendar API raises varied date exceptions
        raise ValueError("TIMING_V21_XNYS_SESSION_UNAVAILABLE") from exc
    local_start = datetime.combine(day, time.min, tzinfo=_new_york_zone())
    local_next = local_start + timedelta(days=1)
    return {
        "open_ns": _datetime_to_ns(open_time),
        "close_ns": _datetime_to_ns(close_time),
        "local_start_ns": _datetime_to_ns(local_start),
        "local_next_start_ns": _datetime_to_ns(local_next),
    }


def _new_york_zone() -> Any:
    from zoneinfo import ZoneInfo

    return ZoneInfo("America/New_York")


def _expected_origin_counts(
    *, expected_origins_per_asset_date: int | None, expected_origins_path: Path | None
) -> dict[tuple[str, str], int]:
    if expected_origins_path is None:
        return {}
    if not expected_origins_path.is_file():
        raise FileNotFoundError("TIMING_V21_EXPECTED_ORIGIN_PROJECTION_MISSING")
    table = pq.read_table(expected_origins_path, columns=["asset", "session_date"])
    output: Counter[tuple[str, str]] = Counter()
    for row in table.to_pylist():
        output[(str(row["session_date"]), str(row["asset"]))] += 1
    if not output:
        raise ValueError("TIMING_V21_EXPECTED_ORIGIN_PROJECTION_EMPTY")
    return dict(output)


def _zero_interpretation(coding_status: str) -> str:
    if coding_status in {"ZERO_CODING_POTENTIALLY_CONFOUNDED", "ZERO_CODING_SOURCE_UNAVAILABLE"}:
        return "ZERO_NOT_INTERPRETABLE_AS_NO_ACTIVITY"
    if coding_status == "ZERO_CODING_SOURCE_AVAILABLE":
        return "NO_ELIGIBLE_RECORD_OBSERVED_NOT_PROVIDER_ACTIVITY_CONFIRMATION"
    if coding_status == "ROW_EXCLUDED_OR_MISSING":
        return "ROW_NOT_PRESENT"
    if coding_status == "MISSING_FEATURE_VALUES":
        return "NUMERIC_MISSING"
    return "NOT_APPLICABLE"


def _canonical_value_coding(
    *, observed_count: int, zero_origin_count: int, nonzero_origin_count: int, null_count: int
) -> str:
    if observed_count == 0:
        return "ROW_ABSENT"
    if null_count > 0:
        return "NUMERIC_MISSING"
    if zero_origin_count == observed_count:
        return "NUMERIC_ZERO"
    if zero_origin_count > 0 and nonzero_origin_count > 0:
        return "MIXED_NUMERIC_ZERO_AND_NONZERO"
    if nonzero_origin_count == observed_count:
        return "NUMERIC_NONZERO"
    return "UNCLASSIFIED_NUMERIC_CODING"


def _massive_cache_index(cache_root: Path) -> dict[str, list[Path]]:
    index: dict[str, list[Path]] = defaultdict(list)
    for path in cache_root.glob("*.json"):
        parts = path.stem.rsplit("_", maxsplit=1)
        if len(parts) == 2:
            index[parts[0]].append(path)
    return {key: sorted(value) for key, value in index.items()}


def _load_and_validate_massive_cache(
    *,
    cache_index: Mapping[str, Sequence[Path]],
    cache_root: Path,
    asset: str,
    session_date: str,
    contract: str,
    source_request_hash: str,
) -> tuple[str, _PreparedQuotes]:
    del cache_root  # Identity is resolved from the prebuilt logical cache index.
    prefix = f"{asset}_{session_date}_{contract.replace(':', '_')}"
    candidates = cache_index.get(prefix, ())
    if not candidates:
        return "CACHE_FILE_MISSING", _EMPTY_PREPARED_QUOTES
    if len(candidates) != 1:
        return "CACHE_FILE_AMBIGUOUS", _EMPTY_PREPARED_QUOTES
    try:
        payload = json.loads(candidates[0].read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return "CACHE_JSON_INVALID", _EMPTY_PREPARED_QUOTES
    if not isinstance(payload, dict):
        return "CACHE_ENVELOPE_INVALID", _EMPTY_PREPARED_QUOTES
    nested_contract = payload.get("contract")
    if (
        payload.get("asset") != asset
        or payload.get("day") != session_date
        or payload.get("route") != "B1Q"
        or payload.get("schema_version") != 4
        or payload.get("http_status") != 200
        or not isinstance(nested_contract, dict)
        or nested_contract.get("contract") != contract
    ):
        return "CACHE_ENVELOPE_IDENTITY_INVALID", _EMPTY_PREPARED_QUOTES
    if payload.get("source_request_hash") != source_request_hash:
        return "CACHE_SOURCE_HASH_MISMATCH", _EMPTY_PREPARED_QUOTES
    try:
        expected_cache_key = _expected_massive_cache_key(
            asset=asset,
            session_date=session_date,
            contract=contract,
            contract_metadata=nested_contract,
        )
    except ValueError:
        return "CACHE_CONTRACT_METADATA_INVALID", _EMPTY_PREPARED_QUOTES
    expected_file_name = (
        f"{asset}_{session_date}_{contract.replace(':', '_')}_"
        f"{hashlib.sha256(expected_cache_key.encode('utf-8')).hexdigest()[:16]}.json"
    )
    expected_quote_cache_key = (
        f"provider=massive|contract={contract}|session_date={session_date}|"
        "route=B1Q|schema_version=4"
    )
    if (
        candidates[0].name != expected_file_name
        or payload.get("cache_key") != expected_cache_key
        or payload.get("quote_cache_key") != expected_quote_cache_key
    ):
        return "CACHE_KEY_DIGEST_MISMATCH", _EMPTY_PREPARED_QUOTES
    request_params = payload.get("request_params_sanitized")
    if not isinstance(request_params, dict):
        return "CACHE_REQUEST_PARAMETERS_INVALID", _EMPTY_PREPARED_QUOTES
    expected_request_hash = _expected_massive_source_request_hash(
        contract=contract, request_params=request_params
    )
    if expected_request_hash != source_request_hash:
        return "CACHE_REQUEST_HASH_RECOMPUTE_MISMATCH", _EMPTY_PREPARED_QUOTES
    request_scope_status, session_bounds = _massive_request_parameters_status(
        request_params=request_params, session_date=session_date
    )
    if request_scope_status == "INVALID":
        return "CACHE_REQUEST_BOUNDS_INVALID", _EMPTY_PREPARED_QUOTES
    if not isinstance(payload.get("pages"), int) or int(payload["pages"]) <= 0:
        return "CACHE_PAGINATION_METADATA_INVALID", _EMPTY_PREPARED_QUOTES
    rows = payload.get("results")
    if not isinstance(rows, list):
        return "CACHE_RESULTS_INVALID", _EMPTY_PREPARED_QUOTES
    if not _massive_pagination_verified(payload=payload, rows=rows):
        return "CACHE_PAGINATION_UNVERIFIED", _EMPTY_PREPARED_QUOTES
    try:
        quotes = _prepare_quotes(rows)
    except ValueError:
        return "CACHE_QUOTE_SCHEMA_INVALID", _EMPTY_PREPARED_QUOTES
    if request_scope_status == "EARLY_CLOSE_REQUEST_OVEREXTENDED":
        in_session_rows = tuple(
            quote for quote in quotes.rows if quote[0] <= session_bounds["close_ns"]
        )
        if len(in_session_rows) != len(quotes.rows):
            return (
                "OK_EARLY_CLOSE_POST_CLOSE_QUOTES_EXCLUDED",
                _PreparedQuotes(
                    rows=in_session_rows,
                    keys=tuple((quote[0], quote[1]) for quote in in_session_rows),
                ),
            )
    return (
        "OK_EARLY_CLOSE_REQUEST_OVEREXTENDED"
        if request_scope_status == "EARLY_CLOSE_REQUEST_OVEREXTENDED"
        else "OK",
        quotes,
    )


def _expected_massive_cache_key(
    *,
    asset: str,
    session_date: str,
    contract: str,
    contract_metadata: Mapping[str, Any],
) -> str:
    """Derive the v4 cache key from validated contract metadata.

    This reproduces the key construction used by the original B1Q acquisition
    without exposing an endpoint credential or a local cache path.
    """
    expiry = contract_metadata.get("expiry")
    strike = contract_metadata.get("strike")
    option_type = contract_metadata.get("option_type")
    if not isinstance(expiry, str) or not isinstance(strike, int | float) or not isinstance(
        option_type, str
    ):
        raise ValueError("TIMING_V21_CACHE_CONTRACT_METADATA_INVALID")
    return (
        f"provider=massive|asset={asset}|session_date={session_date}|expiry={expiry}|"
        f"strike={strike}|option_type={option_type}|contract={contract}|route=B1Q|"
        "schema_version=4"
    )


def _expected_massive_source_request_hash(
    *, contract: str, request_params: Mapping[str, Any]
) -> str:
    """Return the original sanitized B1Q request identity digest."""
    return hashlib.sha256(
        (
            f"https://api.massive.com/v3/quotes/{contract}|"
            f"{json.dumps(dict(request_params), sort_keys=True)}|route=B1Q|schema_version=4"
        ).encode()
    ).hexdigest()


def _massive_request_parameters_status(
    *, request_params: Mapping[str, Any], session_date: str
) -> tuple[str, Mapping[str, int]]:
    """Classify exact versus overextended early-close cache request bounds.

    An early-close cache queried through the nominal 16:00 New York close can
    still be usable for earlier forecast origins only when the cached quotes
    themselves contain no post-close observation. Any other parameter drift
    remains invalid.
    """
    try:
        bounds = _session_bounds_ns(session_date)
    except ValueError:
        return "INVALID", {}
    exact = {
        "timestamp.gte": str(bounds["open_ns"]),
        "timestamp.lte": str(bounds["close_ns"]),
        "sort": "timestamp",
        "order": "asc",
        "limit": "50000",
    }
    if request_params == exact:
        return "EXACT_XNYS_SESSION", bounds
    session_day = date.fromisoformat(session_date)
    nominal_regular_close_ns = _datetime_to_ns(
        datetime.combine(session_day, time(hour=16), tzinfo=_new_york_zone())
    )
    extended = {**exact, "timestamp.lte": str(nominal_regular_close_ns)}
    if bounds["close_ns"] < nominal_regular_close_ns and request_params == extended:
        return "EARLY_CLOSE_REQUEST_OVEREXTENDED", bounds
    return "INVALID", bounds


def _massive_pagination_verified(*, payload: Mapping[str, Any], rows: Sequence[Any]) -> bool:
    """Return whether cache pagination is explicit or safely inferable.

    Older v4 cache envelopes can omit ``pagination_complete``. They are accepted
    only when their pre-deduplication row count proves a terminal partial page;
    an explicit incomplete flag never qualifies.
    """
    pagination_complete = payload.get("pagination_complete")
    if pagination_complete is True or pagination_complete == "INFERRED_TERMINAL_PARTIAL_PAGE":
        return True
    if pagination_complete is not None:
        return False
    removed = payload.get("provider_duplicate_rows_removed", 0)
    if isinstance(removed, bool) or not isinstance(removed, int) or removed < 0:
        return False
    removed_count: int = int(removed)
    original_count = len(rows) + removed_count
    return original_count == 0 or original_count % MASSIVE_QUOTE_PAGE_LIMIT != 0


def _prepare_quotes(quotes: Iterable[Mapping[str, Any]]) -> _PreparedQuotes:
    prepared: list[tuple[int, int, float, float]] = []
    seen: set[tuple[int, int]] = set()
    for row in quotes:
        sip_timestamp = row.get("sip_timestamp")
        sequence_number = row.get("sequence_number")
        bid = row.get("bid_price")
        ask = row.get("ask_price")
        if not isinstance(sip_timestamp, int) or not isinstance(sequence_number, int):
            raise ValueError("TIMING_V21_CACHE_QUOTE_TIMESTAMP_OR_SEQUENCE_INVALID")
        if not isinstance(bid, int | float) or not isinstance(ask, int | float):
            raise ValueError("TIMING_V21_CACHE_QUOTE_PRICE_INVALID")
        key = (sip_timestamp, sequence_number)
        if key in seen:
            raise ValueError("TIMING_V21_CACHE_QUOTE_DUPLICATE")
        seen.add(key)
        prepared.append((sip_timestamp, sequence_number, float(bid), float(ask)))
    rows = tuple(sorted(prepared, key=lambda quote: (quote[0], quote[1])))
    return _PreparedQuotes(rows=rows, keys=tuple((quote[0], quote[1]) for quote in rows))


def _select_prepared_quote(
    quotes: _PreparedQuotes, cutoff_ns: int
) -> tuple[int, int, float, float] | None:
    index = bisect_right(quotes.keys, (cutoff_ns, 2**63 - 1)) - 1
    return quotes.rows[index] if index >= 0 else None


def _iv_from_reselected_quote(
    *, row: Mapping[str, Any], quote: tuple[int, int, float, float]
) -> dict[str, Any] | None:
    _, _, bid, ask = quote
    if (
        not math.isfinite(bid)
        or not math.isfinite(ask)
        or bid <= 0.0
        or ask <= bid
    ):
        return {"success": False, "failure_reason": "INVALID_SELECTED_NBBO"}
    midpoint = (bid + ask) / 2.0
    relative_spread = (ask - bid) / midpoint
    if not math.isfinite(midpoint) or not math.isfinite(relative_spread):
        return {"success": False, "failure_reason": "IV_INPUT_INVALID"}
    if relative_spread > REGULAR_RELATIVE_SPREAD_LIMIT:
        return {"success": False, "failure_reason": "RELATIVE_SPREAD_EXCEEDS_LIMIT"}
    return _invert_iv(
        spot=float(row["spot"]),
        strike=float(row["strike"]),
        time_years=float(row["dte"]) / 365.0,
        rate=float(row["rate"]),
        dividend=float(row["dividend_yield"]),
        midpoint=midpoint,
        option_type=str(row["option_type"]),
    )


def _invert_iv(
    *,
    spot: float,
    strike: float,
    time_years: float,
    rate: float,
    dividend: float,
    midpoint: float,
    option_type: str,
) -> dict[str, Any]:
    if option_type not in {"call", "put"}:
        return {"success": False, "failure_reason": "INVALID_OPTION_TYPE"}
    if (
        not all(
            math.isfinite(value)
            for value in (spot, strike, time_years, rate, dividend, midpoint)
        )
        or spot <= 0.0
        or strike <= 0.0
        or time_years <= 0.0
    ):
        return {"success": False, "failure_reason": "IV_INPUT_INVALID"}
    lower = max(
        0.0,
        (spot * math.exp(-dividend * time_years) - strike * math.exp(-rate * time_years))
        if option_type == "call"
        else (strike * math.exp(-rate * time_years) - spot * math.exp(-dividend * time_years)),
    )
    upper = (
        spot * math.exp(-dividend * time_years)
        if option_type == "call"
        else strike * math.exp(-rate * time_years)
    )
    if not lower <= midpoint <= upper or midpoint <= 0.0:
        return {"success": False, "failure_reason": "ARBITRAGE_BOUND"}
    low, high = 1e-6, 5.0
    if _bsm_price(spot, strike, time_years, rate, dividend, high, option_type) < midpoint:
        return {"success": False, "failure_reason": "IV_UPPER_BOUND"}
    for _ in range(100):
        middle = (low + high) / 2.0
        value = _bsm_price(spot, strike, time_years, rate, dividend, middle, option_type)
        if abs(value - midpoint) <= 1e-6:
            return {"success": True, "iv": middle}
        if value > midpoint:
            high = middle
        else:
            low = middle
    return {"success": True, "iv": (low + high) / 2.0}


def _bsm_price(
    spot: float,
    strike: float,
    time_years: float,
    rate: float,
    dividend: float,
    sigma: float,
    option_type: str,
) -> float:
    if min(spot, strike, time_years, sigma) <= 0.0:
        return 0.0
    root_time = math.sqrt(time_years)
    d1 = (math.log(spot / strike) + (rate - dividend + sigma * sigma / 2.0) * time_years) / (
        sigma * root_time
    )
    d2 = d1 - sigma * root_time
    if option_type == "call":
        return spot * math.exp(-dividend * time_years) * _normal_cdf(d1) - strike * math.exp(
            -rate * time_years
        ) * _normal_cdf(d2)
    return strike * math.exp(-rate * time_years) * _normal_cdf(-d2) - spot * math.exp(
        -dividend * time_years
    ) * _normal_cdf(-d1)


def _normal_cdf(value: float) -> float:
    return 0.5 * (1.0 + math.erf(value / math.sqrt(2.0)))


def _validate_cutoffs(cutoffs_seconds: Sequence[int]) -> None:
    if not cutoffs_seconds or tuple(cutoffs_seconds) != tuple(sorted(set(cutoffs_seconds))):
        raise ValueError("TIMING_V21_CUTOFFS_MUST_BE_UNIQUE_ASCENDING")
    if any(not isinstance(value, int) or value < 0 for value in cutoffs_seconds):
        raise ValueError("TIMING_V21_CUTOFFS_MUST_BE_NONNEGATIVE_INTEGERS")


def _datetime_to_ns(value: datetime) -> int:
    utc_value = value.astimezone(UTC)
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    delta = utc_value - epoch
    return (
        delta.days * 86_400 * NANOSECONDS_PER_SECOND
        + delta.seconds * NANOSECONDS_PER_SECOND
        + delta.microseconds * 1_000
    )


def _ns_to_iso(value: int | None) -> str | None:
    if value is None:
        return None
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    return (epoch + timedelta(microseconds=value // 1_000)).isoformat().replace("+00:00", "Z")


def _min_optional(current: int | None, candidate: int) -> int:
    return candidate if current is None or candidate < current else current


def _max_optional(current: int | None, candidate: int) -> int:
    return candidate if current is None or candidate > current else current


def _as_float(value: np.floating[Any]) -> float:
    return float(value)


def _median_array(values: array[float]) -> float | None:
    if not values:
        return None
    return float(np.median(np.frombuffer(values, dtype=np.float64)))


def _rate(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    )
