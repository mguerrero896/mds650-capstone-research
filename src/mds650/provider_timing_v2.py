"""Offline, evidence-scoped point-in-time timing audit version 2.

This module deliberately reads only acquired provider records and B1 provenance.
It does not issue provider HTTP requests and never reads a target, forecast, or
predictive evaluation artifact.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any, Final

import numpy as np
import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.compute as pc  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

FEATURE_WINDOW_SECONDS: Final[int] = 300
NANOSECONDS_PER_SECOND: Final[int] = 1_000_000_000
MICROSECONDS_TO_NANOSECONDS: Final[int] = 1_000
DEFAULT_BUFFERS_SECONDS: Final[tuple[int, ...]] = (60, 120, 300)
EXTREME_TAIL_SECONDS: Final[tuple[int, ...]] = (300, 3_600, 86_400)

FMP_1MIN_URL: Final[str] = (
    "https://site.financialmodelingprep.com/developer/docs/stable/intraday-1-min"
)
FMP_CYCLE_TIMES_URL: Final[str] = (
    "https://site.financialmodelingprep.com/developer/docs/cycle-times-stable"
)
UW_OPTION_TRADE_URL: Final[str] = "https://api.unusualwhales.com/docs/kafka/types/OptionTrade"
MASSIVE_QUOTES_URL: Final[str] = "https://massive.com/docs/rest/options/trades-quotes/quotes"


def build_pit_claim_matrix_v2() -> list[dict[str, str]]:
    """Return the provider/PIT claim matrix with explicit evidence classes.

    Assumptions
    -----------
    The strings reproduce only claims supported by the cited official pages,
    observed local payload schema, or an explicitly labelled study rule.

    Returns
    -------
    list[dict[str, str]]
        Deterministically ordered claims. Each row contains a provider, field,
        claim class, evidence locator and permitted conclusion.

    Examples
    --------
    >>> rows = build_pit_claim_matrix_v2()
    >>> any(row["claim_key"] == "uw_created_at" for row in rows)
    True
    """
    rows = [
        {
            "claim_key": "fmp_1min_endpoint_scope",
            "provider": "FMP",
            "field_or_topic": "1-minute chart endpoint",
            "claim_class": "PROVIDER_DOCUMENTED",
            "evidence_locator": "fmp_1min_endpoint",
            "permitted_conclusion": (
                "The endpoint provides one-minute OHLCV data and is described "
                "as real-time or historical."
            ),
        },
        {
            "claim_key": "fmp_timestamp_timezone",
            "provider": "FMP",
            "field_or_topic": "raw date timestamp timezone",
            "claim_class": "UNVERIFIED",
            "evidence_locator": "fmp_1min_endpoint_and_local_payload",
            "permitted_conclusion": (
                "Do not state a provider-confirmed timezone for the naive raw date string."
            ),
        },
        {
            "claim_key": "fmp_raw_timestamp_payload",
            "provider": "FMP",
            "field_or_topic": "raw date timestamp",
            "claim_class": "PAYLOAD_OBSERVED",
            "evidence_locator": "authenticated_audit_and_fixture",
            "permitted_conclusion": (
                "Acquired bars expose a naive YYYY-MM-DD HH:mm:ss raw date field."
            ),
        },
        {
            "claim_key": "fmp_bar_bucket_label",
            "provider": "FMP",
            "field_or_topic": "raw date as bar start or close",
            "claim_class": "UNVERIFIED",
            "evidence_locator": "fmp_1min_endpoint_and_local_payload",
            "permitted_conclusion": (
                "Do not state that the provider documents whether the timestamp "
                "labels bar start or bar close."
            ),
        },
        {
            "claim_key": "fmp_cycle_time_label",
            "provider": "FMP",
            "field_or_topic": "1-minute chart cycle time",
            "claim_class": "PROVIDER_DOCUMENTED",
            "evidence_locator": "fmp_cycle_times",
            "permitted_conclusion": (
                "The cycle-times page labels the 1-minute chart Real-Time, "
                "without a numeric completed-bar availability SLA."
            ),
        },
        {
            "claim_key": "fmp_plus_one_minute",
            "provider": "FMP",
            "field_or_topic": "primary bar availability",
            "claim_class": "STUDY_CONSERVATIVE_RULE",
            "evidence_locator": "study_contract_v2",
            "permitted_conclusion": (
                "Use raw timestamp plus one minute only as a conservative study availability rule."
            ),
        },
        {
            "claim_key": "fmp_plus_two_minutes",
            "provider": "FMP",
            "field_or_topic": "bar availability sensitivity",
            "claim_class": "STUDY_CONSERVATIVE_RULE",
            "evidence_locator": "study_contract_v2",
            "permitted_conclusion": (
                "Use raw timestamp plus two minutes only as a prespecified "
                "conservative sensitivity."
            ),
        },
        {
            "claim_key": "uw_executed_at",
            "provider": "Unusual Whales",
            "field_or_topic": "executed_at",
            "claim_class": "PROVIDER_DOCUMENTED",
            "evidence_locator": "uw_option_trade",
            "permitted_conclusion": "The field is the trade execution time in Unix milliseconds.",
        },
        {
            "claim_key": "uw_created_at",
            "provider": "Unusual Whales",
            "field_or_topic": "created_at",
            "claim_class": "PROVIDER_DOCUMENTED",
            "evidence_locator": "uw_option_trade",
            "permitted_conclusion": (
                "The field is the time the trade record was created in Unix milliseconds."
            ),
        },
        {
            "claim_key": "uw_record_creation_lag",
            "provider": "Unusual Whales",
            "field_or_topic": "created_at minus executed_at",
            "claim_class": "PAYLOAD_OBSERVED",
            "evidence_locator": "existing_full_tape",
            "permitted_conclusion": (
                "This derived quantity is record-creation lag; it is not provider "
                "publication or client-receipt latency."
            ),
        },
        {
            "claim_key": "uw_timestamp_payload",
            "provider": "Unusual Whales",
            "field_or_topic": "persisted executed_at and created_at",
            "claim_class": "PAYLOAD_OBSERVED",
            "evidence_locator": "existing_full_tape",
            "permitted_conclusion": (
                "Acquired Full Tape persists both timestamp fields as UTC instants."
            ),
        },
        {
            "claim_key": "uw_publication_or_client_receipt",
            "provider": "Unusual Whales",
            "field_or_topic": "publication time and client receipt",
            "claim_class": "UNVERIFIED",
            "evidence_locator": "uw_option_trade",
            "permitted_conclusion": (
                "No historical publication-time or client-receipt field is "
                "established by this source."
            ),
        },
        {
            "claim_key": "uw_created_at_operational_proxy",
            "provider": "Unusual Whales",
            "field_or_topic": "B2 eligibility cutoff",
            "claim_class": "STUDY_CONSERVATIVE_RULE",
            "evidence_locator": "study_contract_v2",
            "permitted_conclusion": (
                "Use created_at only as an operational availability proxy with "
                "60/120/300-second buffers."
            ),
        },
        {
            "claim_key": "massive_sip_timestamp",
            "provider": "Massive",
            "field_or_topic": "sip_timestamp",
            "claim_class": "PROVIDER_DOCUMENTED",
            "evidence_locator": "massive_options_quotes",
            "permitted_conclusion": (
                "The field is the nanosecond Unix timestamp when SIP received "
                "the quote from the exchange."
            ),
        },
        {
            "claim_key": "massive_sequence_number",
            "provider": "Massive",
            "field_or_topic": "sequence_number",
            "claim_class": "PROVIDER_DOCUMENTED",
            "evidence_locator": "massive_options_quotes",
            "permitted_conclusion": (
                "The sequence number is increasing and unique per option ticker, "
                "but not necessarily sequential."
            ),
        },
        {
            "claim_key": "massive_cache_timestamp_lte",
            "provider": "Massive",
            "field_or_topic": "cached query upper bound",
            "claim_class": "PAYLOAD_OBSERVED",
            "evidence_locator": "existing_massive_v4_cache",
            "permitted_conclusion": (
                "The audited v4 cache stores a sanitized timestamp.lte request bound."
            ),
        },
        {
            "claim_key": "massive_rest_receipt_time",
            "provider": "Massive",
            "field_or_topic": "REST response arrival",
            "claim_class": "UNVERIFIED",
            "evidence_locator": "massive_options_quotes",
            "permitted_conclusion": (
                "The quote source timestamp does not prove REST response or client-receipt time."
            ),
        },
        {
            "claim_key": "massive_asof_selection",
            "provider": "Massive",
            "field_or_topic": "last quote at or before forecast origin",
            "claim_class": "STUDY_CONSERVATIVE_RULE",
            "evidence_locator": "study_contract_v2",
            "permitted_conclusion": (
                "Select the latest quote with sip_timestamp no later than the forecast origin."
            ),
        },
    ]
    return sorted(rows, key=lambda row: row["claim_key"])


def fmp_timing_evidence_v2() -> dict[str, Any]:
    """Return the evidence-scoped FMP timestamp contract.

    Assumptions
    -----------
    The payload observation is limited to the acquired authenticated audit and
    sanitized fixture. The FMP documentation reviewed for this contract does
    not resolve the raw timestamp timezone, bar label, or numerical completed-
    bar REST availability.

    Returns
    -------
    dict[str, Any]
        Separate provider-documentation, payload-observation and conservative
        study-rule objects. Neither unresolved fact is filled with an inferred
        provider specification.
    """
    return {
        "provider": "FMP",
        "component": "underlying_1min_ohlcv",
        "provider_documented": {
            "endpoint_scope": "one_minute_ohlcv_real_time_or_historical",
            "cycle_time_label": "REAL_TIME",
            "raw_timestamp_timezone": "UNVERIFIED",
            "bar_start_or_close": "UNVERIFIED",
            "completed_bar_rest_availability_seconds": "UNVERIFIED",
        },
        "payload_observed": {
            "raw_timestamp_field": "date",
            "raw_timestamp_format": "YYYY-MM-DD HH:mm:ss",
            "raw_timestamp_timezone": "naive_unverified",
            "bar_label_semantics": "start_versus_close_unresolved",
            "observed_ohlcv_fields": ["open", "high", "low", "close", "volume"],
        },
        "study_rules": {
            "market_timezone_convention": "America/New_York_under_XNYS_calendar",
            "primary_available_at": "raw_timestamp_plus_60_seconds",
            "sensitivity_available_at": "raw_timestamp_plus_120_seconds",
            "interpretation": "conservative_research_assumption_not_provider_sla",
        },
        "calendar_handling": {
            "regular_session": "XNYS_calendar",
            "dst": "XNYS_calendar",
            "early_close": "XNYS_calendar",
            "provider_calendar_semantics": "UNVERIFIED",
        },
    }


def official_source_records_v2() -> list[dict[str, Any]]:
    """Return compact archived metadata for the official documentation sources.

    Assumptions
    -----------
    A hash with ``source_content_sha256`` covers the HTTP body retrieved on the
    stated date. FMP's public pages were reviewed through an official browser
    rendering because a direct non-authenticated HTTP archival request returned
    HTTP 403; that access limitation is recorded rather than hidden.

    Returns
    -------
    list[dict[str, Any]]
        Deterministically ordered, compact records. The records contain no
        provider payload, key, request parameter value, or personal path.
    """
    records: list[dict[str, Any]] = [
        {
            "source_id": "fmp_1min_endpoint",
            "provider": "FMP",
            "title": "1 Min Interval Stock Chart API",
            "url": FMP_1MIN_URL,
            "official_domain": "site.financialmodelingprep.com",
            "reviewed_on_utc": "2026-08-11",
            "access_mode": "official_browser_documentation_review",
            "source_content_sha256": None,
            "source_content_hash_status": "DIRECT_HTTP_ARCHIVE_403_BROWSER_REVIEWED",
            "documented_excerpt": (
                "Retrieve real-time or historical stock data in one-minute intervals, "
                "including OHLC and volume."
            ),
            "documented_nonclaims": [
                "No raw date timezone is stated.",
                "No bar-start or bar-close label semantics are stated.",
                "No completed-bar REST availability SLA is stated.",
            ],
        },
        {
            "source_id": "fmp_cycle_times",
            "provider": "FMP",
            "title": "Cycle Times - FMP API",
            "url": FMP_CYCLE_TIMES_URL,
            "official_domain": "site.financialmodelingprep.com",
            "reviewed_on_utc": "2026-08-11",
            "access_mode": "official_browser_documentation_review",
            "source_content_sha256": None,
            "source_content_hash_status": "DIRECT_HTTP_ARCHIVE_403_BROWSER_REVIEWED",
            "documented_excerpt": "The 1 Min Interval Stock Chart is labelled Real-Time.",
            "documented_nonclaims": [
                "The page does not state a numeric completed-bar availability latency.",
            ],
        },
        {
            "source_id": "uw_option_trade",
            "provider": "Unusual Whales",
            "title": "OptionTrade - Kafka Streaming",
            "url": UW_OPTION_TRADE_URL,
            "official_domain": "api.unusualwhales.com",
            "reviewed_on_utc": "2026-08-11",
            "access_mode": "official_documentation_http_archive",
            "source_content_sha256": (
                "e1940f9ac46154a54c71ac5b367ba0b26cc98e1bb2a2dda45619fedd18647513"
            ),
            "source_content_hash_status": "HTTP_200_BODY_SHA256",
            "documented_excerpt": (
                "executed_at is trade execution time; created_at is trade-record "
                "creation time, both Unix milliseconds."
            ),
            "documented_nonclaims": [
                "No publication time is defined.",
                "No client-receipt time is defined.",
                "No trader-intention inference is defined.",
            ],
        },
        {
            "source_id": "massive_options_quotes",
            "provider": "Massive",
            "title": "Quotes | Options REST API",
            "url": MASSIVE_QUOTES_URL,
            "official_domain": "massive.com",
            "reviewed_on_utc": "2026-08-11",
            "access_mode": "official_documentation_http_archive",
            "source_content_sha256": (
                "069d36a78a92dd5a8dd7821041c028a9e8b0b29bb2797f2872f2e0536d928bf3"
            ),
            "source_content_hash_status": "HTTP_200_BODY_SHA256",
            "documented_excerpt": (
                "sip_timestamp is nanosecond SIP receipt time; sequence_number "
                "is increasing and unique per ticker."
            ),
            "documented_nonclaims": [
                "No REST response-arrival time is defined.",
                "No client-receipt time is defined.",
            ],
        },
    ]
    output: list[dict[str, Any]] = []
    for record in sorted(records, key=lambda item: str(item["source_id"])):
        output.append({**record, "archive_record_sha256": canonical_sha256(record)})
    return output


def audit_uw_b2_feature_windows(
    *,
    event_root: Path,
    origins_path: Path,
    buffers_seconds: Sequence[int] = DEFAULT_BUFFERS_SECONDS,
    batch_size: int = 131_072,
) -> dict[str, Any]:
    """Audit exact B2 eligibility over existing delayed five-minute windows.

    Each feature window is ``[origin - buffer - 5 minutes, origin - buffer)``.
    An event is eligible only if its execution time is in that half-open window
    and both ``executed_at`` and ``created_at`` are no later than the window
    end. The routine reads no target or model columns.

    Parameters
    ----------
    event_root:
        Root containing acquired Full Tape partitions named
        ``date=YYYY-MM-DD/asset=SYMBOL/events.parquet``.
    origins_path:
        Target-free origin projection with ``asset``, ``session_date`` and
        UTC ``forecast_origin_utc`` fields.
    buffers_seconds:
        Positive, strictly increasing conservative buffers in seconds.
    batch_size:
        Number of Full Tape rows read per Arrow batch.

    Returns
    -------
    dict[str, Any]
        Sanitized exact counts for record-creation-lag CDFs, tail diagnostics,
        and B2 feature-window eligibility. The lag CDF is mathematically
        nested; shifted feature windows are intentionally not claimed nested.

    Raises
    ------
    FileNotFoundError
        If the origin projection or an expected Full Tape root is unavailable.
    ValueError
        If required schema fields, UTC timestamps, partition identity, or
        buffer invariants are missing or invalid.

    Examples
    --------
    >>> isinstance(DEFAULT_BUFFERS_SECONDS, tuple)
    True
    """
    _validate_buffers(buffers_seconds)
    if batch_size <= 0:
        raise ValueError("TIMING_V2_BATCH_SIZE_MUST_BE_POSITIVE")
    if not event_root.is_dir():
        raise FileNotFoundError("TIMING_V2_FULL_TAPE_ROOT_MISSING")
    origin_groups = _load_origin_groups(origins_path)
    lag = _LagAccumulator(buffers_seconds)
    feature_rows: list[dict[str, Any]] = []
    missing_event_file_count = 0
    processed_event_file_count = 0

    for (asset, session_date), origin_ns in sorted(origin_groups.items()):
        event_path = event_root / f"date={session_date}" / f"asset={asset}" / "events.parquet"
        accumulators = {
            buffer: _FeatureWindowAccumulator(origin_ns=origin_ns, buffer_seconds=buffer)
            for buffer in buffers_seconds
        }
        if not event_path.is_file():
            missing_event_file_count += 1
            for accumulator in accumulators.values():
                feature_rows.append(
                    accumulator.as_row(
                        asset=asset,
                        session_date=session_date,
                        event_file_available=False,
                    )
                )
            continue

        processed_event_file_count += 1
        for executed_ns, created_ns, executed_valid, created_valid in _event_timestamp_batches(
            event_path, batch_size=batch_size
        ):
            lag.add(
                executed_ns=executed_ns,
                created_ns=created_ns,
                executed_valid=executed_valid,
                created_valid=created_valid,
            )
            for accumulator in accumulators.values():
                accumulator.add(
                    executed_ns=executed_ns,
                    created_ns=created_ns,
                    executed_valid=executed_valid,
                    created_valid=created_valid,
                )
        for accumulator in accumulators.values():
            feature_rows.append(
                accumulator.as_row(
                    asset=asset,
                    session_date=session_date,
                    event_file_available=True,
                )
            )

    feature_rows.sort(
        key=lambda row: (str(row["asset"]), str(row["session_date"]), int(row["buffer_seconds"]))
    )
    cdf = lag.cdf_rows()
    return {
        "schema_version": "provider-timing-v2.0",
        "scope": "existing_acquired_full_tape_and_target_free_phase6_origins",
        "no_provider_http_requests_performed": True,
        "no_targets_or_predictive_metrics_read": True,
        "feature_window_definition": "[origin-buffer-5m, origin-buffer)",
        "eligibility_rule": "max(executed_at, created_at) <= origin-buffer",
        "origin_group_count": len(origin_groups),
        "origin_count": int(sum(values.size for values in origin_groups.values())),
        "processed_event_file_count": processed_event_file_count,
        "missing_event_file_count": missing_event_file_count,
        "record_creation_lag_cdf": cdf,
        "record_creation_lag_cdf_monotonic": _is_monotonic(
            [
                float(row["within_buffer_share"])
                for row in cdf
                if row["within_buffer_share"] is not None
            ]
        ),
        "extreme_tail": lag.tail_summary(),
        "feature_window_eligibility": feature_rows,
        "feature_window_summary": _summarize_feature_rows(feature_rows, buffers_seconds),
    }


def audit_massive_selected_quotes(
    *,
    origin_matrix_path: Path,
    iv_attempts_path: Path,
) -> dict[str, Any]:
    """Audit existing B1 provenance for future quotes and timing sensitivities.

    Parameters
    ----------
    origin_matrix_path:
        Existing target-free B1 origin matrix containing final selected-quote
        provenance fields.
    iv_attempts_path:
        Existing target-free IV-attempt table. Only quote-time fields are read.

    Returns
    -------
    dict[str, Any]
        Exact selected-quote and attempt-level future-timestamp diagnostics,
        quote-age data-quality sensitivities, and source-time-delay feasibility
        counts. Source-time delays are study sensitivities, not provider latency
        measurements.

    Raises
    ------
    FileNotFoundError
        If a required existing provenance file is missing.
    ValueError
        If required fields have an incompatible type or schema.
    """
    matrix = _audit_massive_origin_matrix(origin_matrix_path)
    attempts = _audit_massive_iv_attempts(iv_attempts_path)
    selected_quote_future_free = (
        int(matrix["future_sip_timestamp_count"]) == 0
        and int(attempts["future_sip_timestamp_count"]) == 0
        and int(attempts["negative_quote_age_count"]) == 0
    )
    return {
        "schema_version": "provider-timing-v2.0",
        "scope": "existing_target_free_b1_quote_provenance",
        "no_provider_http_requests_performed": True,
        "no_targets_or_predictive_metrics_read": True,
        "source_timestamp_semantics": "sip_timestamp_is_provider_documented_SIP_receipt_time",
        "provider_rest_arrival_time": "UNVERIFIED",
        "origin_matrix": matrix,
        "iv_attempts": attempts,
        "selected_quote_future_free": selected_quote_future_free,
    }


def audit_massive_cache_sample(*, cache_root: Path, sample_size: int = 512) -> dict[str, Any]:
    """Validate a deterministic, sanitized schema sample of the Massive v4 cache.

    Parameters
    ----------
    cache_root:
        Directory containing existing v4 contract-day cache JSON files.
    sample_size:
        Maximum deterministic SHA-256-name-ranked files to inspect. A sample is
        used because a full raw-cache schema replay is unnecessary for the
        exact selected-quote provenance audit.

    Returns
    -------
    dict[str, Any]
        Aggregate schema, query-bound and field-presence counts without raw
        quote values, contracts, request identifiers, file names or paths.

    Raises
    ------
    FileNotFoundError
        If the cache root is absent.
    ValueError
        If ``sample_size`` is not positive.
    """
    if not cache_root.is_dir():
        raise FileNotFoundError("TIMING_V2_MASSIVE_CACHE_ROOT_MISSING")
    if sample_size <= 0:
        raise ValueError("TIMING_V2_CACHE_SAMPLE_SIZE_MUST_BE_POSITIVE")
    files = sorted(
        cache_root.glob("*.json"),
        key=lambda path: (hashlib.sha256(path.name.encode("utf-8")).hexdigest(), path.name),
    )
    sampled = files[:sample_size]
    counters: dict[str, int] = defaultdict(int)
    observed_request_parameter_keys: set[str] = set()
    observed_result_field_keys: set[str] = set()
    for path in sampled:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            counters["unreadable_or_invalid_json_count"] += 1
            continue
        if not isinstance(payload, dict):
            counters["invalid_top_level_count"] += 1
            continue
        schema_valid = True
        if payload.get("schema_version") != 4:
            counters["schema_version_invalid_count"] += 1
            schema_valid = False
        if payload.get("http_status") != 200:
            counters["http_status_invalid_count"] += 1
            schema_valid = False
        params = payload.get("request_params_sanitized")
        if not isinstance(params, dict):
            counters["request_parameters_invalid_count"] += 1
            schema_valid = False
            params = {}
        else:
            observed_request_parameter_keys.update(str(key) for key in params)
        upper_bound = _parse_optional_int(params.get("timestamp.lte"))
        if upper_bound is None:
            counters["timestamp_lte_missing_or_invalid_count"] += 1
            schema_valid = False
        results = payload.get("results")
        if not isinstance(results, list):
            counters["results_invalid_count"] += 1
            schema_valid = False
            results = []
        cache_keys: set[tuple[int, int]] = set()
        for row in results:
            counters["result_row_count"] += 1
            if not isinstance(row, dict):
                counters["result_row_invalid_count"] += 1
                schema_valid = False
                continue
            observed_result_field_keys.update(str(key) for key in row)
            sip_timestamp = row.get("sip_timestamp")
            sequence_number = row.get("sequence_number")
            if not isinstance(sip_timestamp, int):
                counters["sip_timestamp_missing_count"] += 1
                schema_valid = False
                continue
            if not 100_000_000_000_000_000 <= sip_timestamp < 10_000_000_000_000_000_000:
                counters["sip_timestamp_non_nanosecond_count"] += 1
                schema_valid = False
            if not isinstance(sequence_number, int):
                counters["sequence_number_missing_count"] += 1
                schema_valid = False
            else:
                event_key = (sip_timestamp, sequence_number)
                if event_key in cache_keys:
                    counters["duplicate_sip_sequence_key_count"] += 1
                    schema_valid = False
                cache_keys.add(event_key)
            if upper_bound is not None and sip_timestamp > upper_bound:
                counters["quote_after_request_upper_bound_count"] += 1
                schema_valid = False
        if schema_valid:
            counters["schema_valid_file_count"] += 1
    required_parameters = {"timestamp.lte", "sort", "order", "limit"}
    required_result_fields = {"sip_timestamp", "sequence_number", "bid_price", "ask_price"}
    return {
        "schema_version": "provider-timing-v2.0",
        "scope": "deterministic_schema_sample_of_existing_massive_v4_cache",
        "no_provider_http_requests_performed": True,
        "sample_selector": "sha256_of_logical_file_name_then_name",
        "cache_files_total": len(files),
        "sampled_file_count": len(sampled),
        "schema_valid_file_count": int(counters["schema_valid_file_count"]),
        "unreadable_or_invalid_json_count": int(counters["unreadable_or_invalid_json_count"]),
        "invalid_top_level_count": int(counters["invalid_top_level_count"]),
        "schema_version_invalid_count": int(counters["schema_version_invalid_count"]),
        "http_status_invalid_count": int(counters["http_status_invalid_count"]),
        "request_parameters_invalid_count": int(counters["request_parameters_invalid_count"]),
        "timestamp_lte_missing_or_invalid_count": int(
            counters["timestamp_lte_missing_or_invalid_count"]
        ),
        "results_invalid_count": int(counters["results_invalid_count"]),
        "result_row_count": int(counters["result_row_count"]),
        "result_row_invalid_count": int(counters["result_row_invalid_count"]),
        "sequence_number_missing_count": int(counters["sequence_number_missing_count"]),
        "sip_timestamp_missing_count": int(counters["sip_timestamp_missing_count"]),
        "sip_timestamp_non_nanosecond_count": int(counters["sip_timestamp_non_nanosecond_count"]),
        "duplicate_sip_sequence_key_count": int(counters["duplicate_sip_sequence_key_count"]),
        "quote_after_request_upper_bound_count": int(
            counters["quote_after_request_upper_bound_count"]
        ),
        "observed_request_parameter_keys": sorted(observed_request_parameter_keys),
        "required_request_parameter_keys_present": required_parameters.issubset(
            observed_request_parameter_keys
        ),
        "observed_result_field_keys": sorted(observed_result_field_keys),
        "required_result_field_keys_present": required_result_fields.issubset(
            observed_result_field_keys
        ),
    }


def build_provider_timing_gates_v2(
    *,
    uw_audit: dict[str, Any],
    massive_audit: dict[str, Any],
    massive_cache_audit: dict[str, Any],
) -> dict[str, str]:
    """Return separated v2 gates without replacing canonical research outcomes.

    Parameters
    ----------
    uw_audit, massive_audit, massive_cache_audit:
        Sanitized outputs from this module's offline audit functions.

    Returns
    -------
    dict[str, str]
        Existing-evidence, new-historical-sample and prospective-capture gates.

    Raises
    ------
    KeyError
        If a required audit status field is absent.
    """
    massive_existing = (
        "PASS"
        if massive_audit["selected_quote_future_free"] is True
        else "FAIL_FUTURE_QUOTE_EVIDENCE"
    )
    cache_invalid = sum(
        int(massive_cache_audit[key])
        for key in (
            "unreadable_or_invalid_json_count",
            "invalid_top_level_count",
            "schema_version_invalid_count",
            "http_status_invalid_count",
            "request_parameters_invalid_count",
            "timestamp_lte_missing_or_invalid_count",
            "results_invalid_count",
            "result_row_invalid_count",
            "sequence_number_missing_count",
            "sip_timestamp_missing_count",
            "sip_timestamp_non_nanosecond_count",
            "duplicate_sip_sequence_key_count",
            "quote_after_request_upper_bound_count",
        )
    )
    cache_existing = "PASS" if cache_invalid == 0 else "FAIL_CACHE_SCHEMA_OR_BOUND"
    uw_monotonic = uw_audit["record_creation_lag_cdf_monotonic"] is True
    return {
        "EXISTING_FMP_EVIDENCE": "CONDITIONAL_STUDY_RULE_ONLY",
        "EXISTING_UW_RECORD_CREATION_EVIDENCE": (
            "PASS_PROXY_ONLY" if uw_monotonic else "FAIL_NON_MONOTONIC_LAG_CDF"
        ),
        "EXISTING_MASSIVE_SELECTED_QUOTE_EVIDENCE": massive_existing,
        "EXISTING_MASSIVE_CACHE_SCHEMA_SAMPLE": cache_existing,
        "NEW_HISTORICAL_SAMPLE": "REQUIRES_DATE_LEVEL_PIT_PREFLIGHT",
        "NEW_PROSPECTIVE_CAPTURE": "REQUIRES_PROVIDER_RECEIPT_LOGGER",
        "UNIVERSAL_PROVIDER_PUBLICATION_OR_RECEIPT_LATENCY": "NOT_SUPPORTED",
    }


def canonical_sha256(value: object) -> str:
    """Return a stable SHA-256 hash for a JSON-compatible value.

    Parameters
    ----------
    value:
        JSON-compatible value to serialize with stable separators and key order.

    Returns
    -------
    str
        Lowercase hexadecimal SHA-256 digest.

    Raises
    ------
    TypeError
        If ``value`` is not JSON serializable.
    """
    serialized = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


class _LagAccumulator:
    """Streaming exact record-creation-lag counters."""

    def __init__(self, buffers_seconds: Sequence[int]) -> None:
        self._buffers_seconds = tuple(int(value) for value in buffers_seconds)
        self.row_count = 0
        self.executed_at_non_null_count = 0
        self.created_at_non_null_count = 0
        self.both_timestamps_count = 0
        self.nonnegative_lag_count = 0
        self.negative_lag_count = 0
        self.max_nonnegative_lag_seconds: float | None = None
        self.within_counts = {buffer: 0 for buffer in self._buffers_seconds}
        self.tail_counts = {threshold: 0 for threshold in EXTREME_TAIL_SECONDS}

    def add(
        self,
        *,
        executed_ns: np.ndarray[Any, Any],
        created_ns: np.ndarray[Any, Any],
        executed_valid: np.ndarray[Any, Any],
        created_valid: np.ndarray[Any, Any],
    ) -> None:
        """Accumulate one timestamp batch."""
        self.row_count += int(executed_ns.size)
        self.executed_at_non_null_count += int(np.count_nonzero(executed_valid))
        self.created_at_non_null_count += int(np.count_nonzero(created_valid))
        both = executed_valid & created_valid
        if not np.any(both):
            return
        lag_ns = created_ns[both] - executed_ns[both]
        self.both_timestamps_count += int(lag_ns.size)
        nonnegative = lag_ns >= 0
        self.negative_lag_count += int(np.count_nonzero(~nonnegative))
        if not np.any(nonnegative):
            return
        valid_lag_ns = lag_ns[nonnegative]
        self.nonnegative_lag_count += int(valid_lag_ns.size)
        maximum = float(np.max(valid_lag_ns)) / NANOSECONDS_PER_SECOND
        self.max_nonnegative_lag_seconds = (
            maximum
            if self.max_nonnegative_lag_seconds is None
            else max(self.max_nonnegative_lag_seconds, maximum)
        )
        for buffer in self._buffers_seconds:
            self.within_counts[buffer] += int(
                np.count_nonzero(valid_lag_ns <= buffer * NANOSECONDS_PER_SECOND)
            )
        for threshold in EXTREME_TAIL_SECONDS:
            self.tail_counts[threshold] += int(
                np.count_nonzero(valid_lag_ns > threshold * NANOSECONDS_PER_SECOND)
            )

    def cdf_rows(self) -> list[dict[str, Any]]:
        """Return exact monotonic lag-CDF rows."""
        return [
            {
                "buffer_seconds": buffer,
                "both_timestamps_count": self.both_timestamps_count,
                "nonnegative_record_creation_lag_count": self.nonnegative_lag_count,
                "within_buffer_count": self.within_counts[buffer],
                "within_buffer_share": _ratio(
                    self.within_counts[buffer], self.nonnegative_lag_count
                ),
            }
            for buffer in self._buffers_seconds
        ]

    def tail_summary(self) -> dict[str, Any]:
        """Return exact extreme-tail counts without retaining raw timestamps."""
        return {
            "row_count": self.row_count,
            "executed_at_non_null_count": self.executed_at_non_null_count,
            "created_at_non_null_count": self.created_at_non_null_count,
            "both_timestamps_count": self.both_timestamps_count,
            "nonnegative_record_creation_lag_count": self.nonnegative_lag_count,
            "negative_record_creation_lag_count": self.negative_lag_count,
            "max_nonnegative_record_creation_lag_seconds": self.max_nonnegative_lag_seconds,
            **{
                f"lag_over_{threshold}_seconds_count": count
                for threshold, count in self.tail_counts.items()
            },
        }


class _FeatureWindowAccumulator:
    """Exact B2 candidate and eligibility counts for one asset-date-buffer group."""

    def __init__(self, *, origin_ns: np.ndarray[Any, Any], buffer_seconds: int) -> None:
        self.origin_ns = origin_ns
        self.buffer_seconds = buffer_seconds
        self.window_end_ns = origin_ns - (buffer_seconds * NANOSECONDS_PER_SECOND)
        self.candidate_counts = np.zeros(origin_ns.size, dtype=np.int64)
        self.eligible_counts = np.zeros(origin_ns.size, dtype=np.int64)
        self.late_record_counts = np.zeros(origin_ns.size, dtype=np.int64)
        self.created_missing_counts = np.zeros(origin_ns.size, dtype=np.int64)

    def add(
        self,
        *,
        executed_ns: np.ndarray[Any, Any],
        created_ns: np.ndarray[Any, Any],
        executed_valid: np.ndarray[Any, Any],
        created_valid: np.ndarray[Any, Any],
    ) -> None:
        """Map one event batch into registered half-open origin windows."""
        if self.window_end_ns.size == 0:
            return
        positions = np.searchsorted(self.window_end_ns, executed_ns, side="right")
        in_bounds = executed_valid & (positions < self.window_end_ns.size)
        if not np.any(in_bounds):
            return
        row_indexes = np.nonzero(in_bounds)[0]
        origin_indexes = positions[row_indexes]
        starts = self.window_end_ns[origin_indexes] - (
            FEATURE_WINDOW_SECONDS * NANOSECONDS_PER_SECOND
        )
        row_indexes = row_indexes[executed_ns[row_indexes] >= starts]
        if row_indexes.size == 0:
            return
        origin_indexes = positions[row_indexes]
        np.add.at(self.candidate_counts, origin_indexes, 1)
        ends = self.window_end_ns[origin_indexes]
        created_is_valid = created_valid[row_indexes]
        created_is_late = created_is_valid & (created_ns[row_indexes] > ends)
        created_is_missing = ~created_is_valid
        eligible = created_is_valid & ~created_is_late
        if np.any(eligible):
            np.add.at(self.eligible_counts, origin_indexes[eligible], 1)
        if np.any(created_is_late):
            np.add.at(self.late_record_counts, origin_indexes[created_is_late], 1)
        if np.any(created_is_missing):
            np.add.at(self.created_missing_counts, origin_indexes[created_is_missing], 1)

    def as_row(
        self,
        *,
        asset: str,
        session_date: str,
        event_file_available: bool,
    ) -> dict[str, Any]:
        """Return aggregate-safe counts for one asset-date-buffer cohort."""
        candidate_trade_count = int(np.sum(self.candidate_counts))
        eligible_trade_count = int(np.sum(self.eligible_counts))
        return {
            "asset": asset,
            "session_date": session_date,
            "buffer_seconds": self.buffer_seconds,
            "event_file_available": event_file_available,
            "origin_count": int(self.origin_ns.size),
            "candidate_trade_count": candidate_trade_count,
            "eligible_trade_count": eligible_trade_count,
            "late_record_count": int(np.sum(self.late_record_counts)),
            "created_at_missing_candidate_count": int(np.sum(self.created_missing_counts)),
            "eligible_trade_retention_share": _ratio(eligible_trade_count, candidate_trade_count),
            "origins_with_candidate_activity": int(np.count_nonzero(self.candidate_counts)),
            "origins_with_eligible_activity": int(np.count_nonzero(self.eligible_counts)),
        }


def _validate_buffers(buffers_seconds: Sequence[int]) -> None:
    """Reject empty, nonpositive or nonincreasing timing buffers."""
    values = tuple(int(value) for value in buffers_seconds)
    if not values or any(value <= 0 for value in values):
        raise ValueError("TIMING_V2_BUFFERS_MUST_BE_POSITIVE")
    if values != tuple(sorted(set(values))):
        raise ValueError("TIMING_V2_BUFFERS_MUST_BE_STRICTLY_INCREASING")


def _load_origin_groups(origins_path: Path) -> dict[tuple[str, str], np.ndarray[Any, Any]]:
    """Load only target-free origin identifiers and UTC timestamps."""
    if not origins_path.is_file():
        raise FileNotFoundError("TIMING_V2_ORIGIN_PROJECTION_MISSING")
    required = ("asset", "session_date", "forecast_origin_utc")
    parquet_file = pq.ParquetFile(origins_path)
    _require_fields(parquet_file.schema_arrow.names, required, "TIMING_V2_ORIGIN_SCHEMA_DRIFT")
    table = pq.read_table(origins_path, columns=list(required)).combine_chunks()
    timestamp_field = table.schema.field("forecast_origin_utc")
    if not pa.types.is_timestamp(timestamp_field.type) or timestamp_field.type.tz != "UTC":
        raise ValueError("TIMING_V2_ORIGIN_TIMESTAMP_NOT_UTC")
    timestamps = _timestamp_ns(table.column("forecast_origin_utc"))
    timestamp_valid = _validity_mask(table.column("forecast_origin_utc"))
    assets = table.column("asset").to_pylist()
    session_dates = table.column("session_date").to_pylist()
    groups: dict[tuple[str, str], list[int]] = defaultdict(list)
    for asset, session_date, timestamp_ns, valid in zip(
        assets, session_dates, timestamps, timestamp_valid, strict=True
    ):
        if not valid or not isinstance(asset, str) or not isinstance(session_date, str):
            raise ValueError("TIMING_V2_ORIGIN_VALUE_INVALID")
        groups[(asset, session_date)].append(int(timestamp_ns))
    output: dict[tuple[str, str], np.ndarray[Any, Any]] = {}
    for key, values in groups.items():
        sorted_values = np.asarray(sorted(values), dtype=np.int64)
        if sorted_values.size != np.unique(sorted_values).size:
            raise ValueError("TIMING_V2_ORIGIN_DUPLICATE")
        output[key] = sorted_values
    return output


def _event_timestamp_batches(
    path: Path, *, batch_size: int
) -> Iterable[
    tuple[np.ndarray[Any, Any], np.ndarray[Any, Any], np.ndarray[Any, Any], np.ndarray[Any, Any]]
]:
    """Yield timestamp arrays without materializing Full Tape feature columns."""
    parquet_file = pq.ParquetFile(path)
    _require_fields(
        parquet_file.schema_arrow.names,
        ("executed_at", "created_at"),
        "TIMING_V2_FULL_TAPE_TIMESTAMP_SCHEMA_DRIFT",
    )
    for batch in parquet_file.iter_batches(
        batch_size=batch_size,
        columns=["executed_at", "created_at"],
    ):
        executed = batch.column(0)
        created = batch.column(1)
        yield (
            _timestamp_ns(executed),
            _timestamp_ns(created),
            _validity_mask(executed),
            _validity_mask(created),
        )


def _audit_massive_origin_matrix(path: Path) -> dict[str, Any]:
    """Audit final B1 origin quote provenance without outcome fields."""
    if not path.is_file():
        raise FileNotFoundError("TIMING_V2_B1_ORIGIN_MATRIX_MISSING")
    required = (
        "forecast_origin_utc",
        "b1q_max_sip_timestamp_ns",
        "b1q_quote_not_after_origin",
        "b1q_pit_evidence_valid",
    )
    parquet_file = pq.ParquetFile(path)
    _require_fields(parquet_file.schema_arrow.names, required, "TIMING_V2_B1_MATRIX_SCHEMA_DRIFT")
    table = pq.read_table(path, columns=list(required)).combine_chunks()
    origin_ns = _timestamp_ns(table.column("forecast_origin_utc"))
    origin_valid = _validity_mask(table.column("forecast_origin_utc"))
    sip = _int64_values(table.column("b1q_max_sip_timestamp_ns"))
    sip_valid = _validity_mask(table.column("b1q_max_sip_timestamp_ns"))
    pairs = origin_valid & sip_valid
    future = pairs & (sip > origin_ns)
    quote_not_after = table.column("b1q_quote_not_after_origin").to_pylist()
    pit_evidence = table.column("b1q_pit_evidence_valid").to_pylist()
    return {
        "row_count": int(table.num_rows),
        "origin_timestamp_non_null_count": int(np.count_nonzero(origin_valid)),
        "selected_quote_timestamp_count": int(np.count_nonzero(sip_valid)),
        "selected_quote_timestamp_missing_count": int(table.num_rows - np.count_nonzero(sip_valid)),
        "future_sip_timestamp_count": int(np.count_nonzero(future)),
        "reported_quote_not_after_origin_false_or_missing_count": int(
            sum(value is not True for value in quote_not_after)
        ),
        "reported_pit_evidence_false_or_missing_count": int(
            sum(value is not True for value in pit_evidence)
        ),
    }


def _audit_massive_iv_attempts(path: Path) -> dict[str, Any]:
    """Stream target-free quote timing fields from the existing IV attempt table."""
    if not path.is_file():
        raise FileNotFoundError("TIMING_V2_B1_IV_ATTEMPTS_MISSING")
    required = ("forecast_origin_ns", "sip_timestamp", "quote_age_seconds")
    parquet_file = pq.ParquetFile(path)
    _require_fields(parquet_file.schema_arrow.names, required, "TIMING_V2_IV_ATTEMPT_SCHEMA_DRIFT")
    row_count = 0
    origin_missing_count = 0
    sip_missing_count = 0
    pair_count = 0
    future_count = 0
    negative_age_count = 0
    stored_age_missing_count = 0
    age_mismatch_count = 0
    source_delay_counts = {delay: 0 for delay in (0, 60, 300)}
    max_age_counts = {maximum: 0 for maximum in (60, 300)}
    for batch in parquet_file.iter_batches(batch_size=131_072, columns=list(required)):
        origin = _int64_values(batch.column(0))
        sip = _int64_values(batch.column(1))
        origin_valid = _validity_mask(batch.column(0))
        sip_valid = _validity_mask(batch.column(1))
        stored_age = _float64_values(batch.column(2))
        stored_age_valid = _validity_mask(batch.column(2))
        row_count += batch.num_rows
        origin_missing_count += int(batch.num_rows - np.count_nonzero(origin_valid))
        sip_missing_count += int(batch.num_rows - np.count_nonzero(sip_valid))
        pairs = origin_valid & sip_valid
        pair_count += int(np.count_nonzero(pairs))
        if not np.any(pairs):
            stored_age_missing_count += int(np.count_nonzero(~stored_age_valid))
            continue
        age_seconds = (origin[pairs] - sip[pairs]).astype(np.float64) / NANOSECONDS_PER_SECOND
        future_count += int(np.count_nonzero(age_seconds < 0.0))
        negative_age_count += int(np.count_nonzero(age_seconds < 0.0))
        for delay in source_delay_counts:
            source_delay_counts[delay] += int(np.count_nonzero(age_seconds >= float(delay)))
        for maximum in max_age_counts:
            max_age_counts[maximum] += int(
                np.count_nonzero((age_seconds >= 0.0) & (age_seconds <= float(maximum)))
            )
        pair_indexes = np.nonzero(pairs)[0]
        stored_for_pairs = stored_age[pair_indexes]
        stored_valid_for_pairs = stored_age_valid[pair_indexes]
        stored_age_missing_count += int(np.count_nonzero(~stored_valid_for_pairs))
        if np.any(stored_valid_for_pairs):
            difference = np.abs(
                stored_for_pairs[stored_valid_for_pairs] - age_seconds[stored_valid_for_pairs]
            )
            age_mismatch_count += int(np.count_nonzero(difference > 1e-6))
    return {
        "row_count": row_count,
        "origin_timestamp_missing_count": origin_missing_count,
        "sip_timestamp_missing_count": sip_missing_count,
        "origin_sip_pair_count": pair_count,
        "future_sip_timestamp_count": future_count,
        "negative_quote_age_count": negative_age_count,
        "stored_quote_age_missing_count": stored_age_missing_count,
        "stored_quote_age_mismatch_count": age_mismatch_count,
        "source_time_delay_sensitivity": [
            {
                "delay_seconds": delay,
                "retained_quote_count": count,
                "retained_quote_share": _ratio(count, pair_count),
                "interpretation": "study_source_time_delay_sensitivity_not_provider_rest_latency",
            }
            for delay, count in source_delay_counts.items()
        ],
        "quote_age_maximum_sensitivity": [
            {
                "maximum_age_seconds": maximum,
                "retained_quote_count": count,
                "retained_quote_share": _ratio(count, pair_count),
                "interpretation": "quote_freshness_data_quality_filter_not_provider_rest_latency",
            }
            for maximum, count in max_age_counts.items()
        ],
    }


def _summarize_feature_rows(
    rows: Sequence[dict[str, Any]], buffers_seconds: Sequence[int]
) -> list[dict[str, Any]]:
    """Aggregate exact feature-window counts without changing their interpretation."""
    output: list[dict[str, Any]] = []
    for buffer in buffers_seconds:
        matching = [row for row in rows if row["buffer_seconds"] == buffer]
        origin_count = sum(int(row["origin_count"]) for row in matching)
        candidate_count = sum(int(row["candidate_trade_count"]) for row in matching)
        eligible_count = sum(int(row["eligible_trade_count"]) for row in matching)
        output.append(
            {
                "buffer_seconds": int(buffer),
                "origin_count": origin_count,
                "candidate_trade_count": candidate_count,
                "eligible_trade_count": eligible_count,
                "eligible_trade_retention_share": _ratio(eligible_count, candidate_count),
                "origins_with_candidate_activity": sum(
                    int(row["origins_with_candidate_activity"]) for row in matching
                ),
                "origins_with_eligible_activity": sum(
                    int(row["origins_with_eligible_activity"]) for row in matching
                ),
                "interpretation": (
                    "Exact shifted B2 windows are not expected to be monotonic across buffers."
                ),
            }
        )
    return output


def _timestamp_ns(values: Any) -> np.ndarray[Any, Any]:
    """Convert Arrow microsecond timestamps to integer nanoseconds.

    Null masks are preserved separately by the caller.
    """
    casted = pc.cast(values, pa.int64())
    filled = pc.fill_null(casted, 0)
    return np.asarray(filled.to_numpy(zero_copy_only=False), dtype=np.int64) * np.int64(
        MICROSECONDS_TO_NANOSECONDS
    )


def _int64_values(values: Any) -> np.ndarray[Any, Any]:
    """Return nullable Arrow integers as filled NumPy values with external validity masks."""
    casted = pc.cast(values, pa.int64())
    filled = pc.fill_null(casted, 0)
    return np.asarray(filled.to_numpy(zero_copy_only=False), dtype=np.int64)


def _float64_values(values: Any) -> np.ndarray[Any, Any]:
    """Return nullable Arrow numbers as floats, using NaN only behind a validity mask."""
    casted = pc.cast(values, pa.float64())
    filled = pc.fill_null(casted, float("nan"))
    return np.asarray(filled.to_numpy(zero_copy_only=False), dtype=np.float64)


def _validity_mask(values: Any) -> np.ndarray[Any, Any]:
    """Return a NumPy validity mask for an Arrow array or chunked array."""
    return np.asarray(pc.is_valid(values).to_numpy(zero_copy_only=False), dtype=bool)


def _parse_optional_int(value: object) -> int | None:
    """Parse an integer-like sanitized request value without accepting booleans."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _require_fields(names: Sequence[str], required: Sequence[str], error_code: str) -> None:
    """Fail closed when a source schema omits a required timing field."""
    if not set(required).issubset(names):
        raise ValueError(error_code)


def _ratio(numerator: int, denominator: int) -> float | None:
    """Return a finite ratio or ``None`` when no denominator exists."""
    return None if denominator == 0 else numerator / denominator


def _is_monotonic(values: Sequence[float]) -> bool:
    """Return whether a finite sequence is nondecreasing."""
    return all(left <= right for left, right in zip(values, values[1:], strict=False))
