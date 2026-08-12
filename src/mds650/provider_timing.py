"""Sanitized provider-timing evidence and local prospective-replay helpers.

This module deliberately has no provider HTTP client.  Its historical audit reads
only already-acquired, filtered Unusual Whales Full Tape Parquet files, and its
prospective utilities accept local replay payloads.  That separation prevents a
timing audit from silently becoming a new acquisition or a predictive experiment.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import numpy as np
import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.compute as pc  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

FMP_OFFICIAL_DOCUMENTATION_URL: Final[str] = (
    "https://site.financialmodelingprep.com/developer/docs/stable/intraday-1-min"
)
FMP_OFFICIAL_DOCUMENTATION_INDEX_URL: Final[str] = (
    "https://site.financialmodelingprep.com/developer/docs"
)
FMP_BAR_LABEL_SEMANTICS: Final[str] = "UNVERIFIED"
FMP_PROVIDER_CONFIRMED_LATENCY: Final[str] = "NOT_SUPPORTED"
FMP_RESEARCH_AVAILABILITY_RULE: Final[str] = "SUPPORTED_CONSERVATIVE_ASSUMPTION"
FMP_LIVE_PROBE_STATUS: Final[str] = "PENDING_PROSPECTIVE_MEASUREMENT_NOT_BLOCKING"
HISTORICAL_UW_CLASSIFICATION: Final[str] = "PROXY_ONLY"
UW_PERCENTILES: Final[tuple[int, ...]] = (1, 5, 50, 90, 95, 99)
UW_LATENCY_CUTOFF_SECONDS: Final[tuple[int, ...]] = (60, 120, 300)
_SESSION_PATTERN: Final[re.Pattern[str]] = re.compile(r"^date=(\d{4}-\d{2}-\d{2})$")
_ASSET_PATTERN: Final[re.Pattern[str]] = re.compile(r"^asset=([A-Za-z0-9._-]+)$")
_SECRET_FIELD_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(?:api[_-]?key|authorization|token|secret|password)", re.IGNORECASE
)
_UINT64_SPACE: Final[int] = 1 << 64


@dataclass(frozen=True)
class UWHistoricalTimingAudit:
    """Result of a sanitized audit over already-acquired Full Tape Parquet files.

    Attributes
    ----------
    payload:
        Deterministic JSON-compatible high-level audit payload.
    summary:
        Global and cohort-level rows for the summary CSV.
    by_session:
        One exact-latency row per cohort and XNYS session.
    by_asset:
        One deterministic-sample row per cohort and underlying asset.
    """

    payload: dict[str, Any]
    summary: list[dict[str, Any]]
    by_session: list[dict[str, Any]]
    by_asset: list[dict[str, Any]]


@dataclass(frozen=True)
class _FullTapeFile:
    """One sanitized Full Tape Parquet location and its partition identity."""

    cohort: str
    session_date: str
    asset: str
    path: Path
    logical_id: str
    row_count: int
    global_row_offset: int


@dataclass
class _LatencyAccumulator:
    """Streaming exact counts plus deterministic-sample latency values."""

    row_count: int = 0
    created_at_non_null_count: int = 0
    executed_at_non_null_count: int = 0
    both_timestamps_count: int = 0
    negative_latency_count: int = 0
    latency_min_seconds: float | None = None
    latency_max_seconds: float | None = None
    within_cutoff_counts: dict[int, int] = field(
        default_factory=lambda: {cutoff: 0 for cutoff in UW_LATENCY_CUTOFF_SECONDS}
    )
    sample_chunks: list[np.ndarray[Any, Any]] = field(default_factory=list)

    def add(
        self,
        *,
        row_count: int,
        created_at_non_null_count: int,
        executed_at_non_null_count: int,
        latency_microseconds: np.ndarray[Any, Any],
        sample_microseconds: np.ndarray[Any, Any],
    ) -> None:
        """Accumulate counts and optional deterministic-sample values."""
        self.row_count += row_count
        self.created_at_non_null_count += created_at_non_null_count
        self.executed_at_non_null_count += executed_at_non_null_count
        self.both_timestamps_count += int(latency_microseconds.size)
        if latency_microseconds.size == 0:
            return

        latency_seconds = latency_microseconds.astype(np.float64, copy=False) / 1_000_000.0
        self.negative_latency_count += int(np.count_nonzero(latency_microseconds < 0))
        minimum = float(np.min(latency_seconds))
        maximum = float(np.max(latency_seconds))
        self.latency_min_seconds = (
            minimum if self.latency_min_seconds is None else min(self.latency_min_seconds, minimum)
        )
        self.latency_max_seconds = (
            maximum if self.latency_max_seconds is None else max(self.latency_max_seconds, maximum)
        )
        for cutoff in UW_LATENCY_CUTOFF_SECONDS:
            self.within_cutoff_counts[cutoff] += int(
                np.count_nonzero(latency_seconds <= float(cutoff))
            )
        if sample_microseconds.size:
            sample_seconds = sample_microseconds.astype(np.float64, copy=False) / 1_000_000.0
            self.sample_chunks.append(sample_seconds)

    def summarize(self, *, percentile_method: str) -> dict[str, Any]:
        """Return the accumulated counts and sampled or exact quantiles."""
        if self.sample_chunks:
            values = np.concatenate(self.sample_chunks)
        else:
            values = np.array([], dtype=np.float64)
        summary = summarize_latency_seconds(
            row_count=self.row_count,
            created_at_non_null_count=self.created_at_non_null_count,
            executed_at_non_null_count=self.executed_at_non_null_count,
            latency_seconds=values.tolist(),
            percentile_method=percentile_method,
            both_timestamps_count=self.both_timestamps_count,
            negative_latency_count=self.negative_latency_count,
            latency_min_seconds=self.latency_min_seconds,
            latency_max_seconds=self.latency_max_seconds,
            within_cutoff_counts=self.within_cutoff_counts,
        )
        summary["quantile_sample_count"] = int(values.size)
        return summary


def summarize_latency_seconds(
    *,
    row_count: int,
    created_at_non_null_count: int,
    executed_at_non_null_count: int,
    latency_seconds: Sequence[float],
    percentile_method: str,
    both_timestamps_count: int | None = None,
    negative_latency_count: int | None = None,
    latency_min_seconds: float | None = None,
    latency_max_seconds: float | None = None,
    within_cutoff_counts: Mapping[int, int] | None = None,
) -> dict[str, Any]:
    """Summarize timestamp completeness and an observed latency distribution.

    Parameters
    ----------
    row_count:
        Number of Full Tape rows in scope.
    created_at_non_null_count, executed_at_non_null_count:
        Exact non-null counts for the two provider fields.
    latency_seconds:
        Valid ``created_at - executed_at`` values in seconds.  This sequence can
        be an exact group or a deterministic sample for a large group.
    percentile_method:
        A truthful label such as ``"exact_per_session"`` or
        ``"deterministic_hash_sample"``.
    both_timestamps_count, negative_latency_count, latency_min_seconds,
    latency_max_seconds, within_cutoff_counts:
        Optional exact streaming totals when ``latency_seconds`` is only a
        sample.

    Returns
    -------
    dict[str, Any]
        JSON-compatible counts, shares, requested percentiles and cutoff shares.

    Raises
    ------
    ValueError
        If counts are inconsistent or a latency is non-finite.

    Notes
    -----
    A latency cutoff share is an ingestion-delay diagnostic.  It is not the
    retention rate of a forecast-origin feature join, which additionally depends
    on the origin timestamps.
    """
    if row_count < 0 or created_at_non_null_count < 0 or executed_at_non_null_count < 0:
        raise ValueError("TIMING_COUNTS_MUST_BE_NON_NEGATIVE")
    if created_at_non_null_count > row_count or executed_at_non_null_count > row_count:
        raise ValueError("TIMING_NON_NULL_COUNT_EXCEEDS_ROWS")

    values = np.asarray(latency_seconds, dtype=np.float64)
    if not np.all(np.isfinite(values)):
        raise ValueError("TIMING_LATENCY_MUST_BE_FINITE")
    valid_count = values.size if both_timestamps_count is None else both_timestamps_count
    if valid_count < values.size:
        raise ValueError("TIMING_VALID_COUNT_SMALLER_THAN_SAMPLE")
    if valid_count > min(created_at_non_null_count, executed_at_non_null_count):
        raise ValueError("TIMING_BOTH_COUNT_EXCEEDS_FIELD_COMPLETENESS")

    negative_count = (
        int(np.count_nonzero(values < 0))
        if negative_latency_count is None
        else negative_latency_count
    )
    if negative_count < 0 or negative_count > valid_count:
        raise ValueError("TIMING_NEGATIVE_COUNT_INVALID")

    summary: dict[str, Any] = {
        "row_count": row_count,
        "created_at_non_null_count": created_at_non_null_count,
        "created_at_missing_count": row_count - created_at_non_null_count,
        "created_at_completeness": _ratio(created_at_non_null_count, row_count),
        "executed_at_non_null_count": executed_at_non_null_count,
        "executed_at_missing_count": row_count - executed_at_non_null_count,
        "executed_at_completeness": _ratio(executed_at_non_null_count, row_count),
        "both_timestamps_count": valid_count,
        "both_timestamps_completeness": _ratio(valid_count, row_count),
        "negative_latency_count": negative_count,
        "negative_latency_share": _ratio(negative_count, valid_count),
        "percentile_method": percentile_method,
        "latency_min_seconds": latency_min_seconds,
        "latency_max_seconds": latency_max_seconds,
    }
    if values.size:
        summary["latency_min_seconds"] = (
            float(np.min(values)) if latency_min_seconds is None else latency_min_seconds
        )
        summary["latency_max_seconds"] = (
            float(np.max(values)) if latency_max_seconds is None else latency_max_seconds
        )
        for percentile in UW_PERCENTILES:
            summary[f"latency_p{percentile}_seconds"] = float(
                np.quantile(values, percentile / 100.0, method="linear")
            )
    else:
        for percentile in UW_PERCENTILES:
            summary[f"latency_p{percentile}_seconds"] = None

    for cutoff in UW_LATENCY_CUTOFF_SECONDS:
        count = (
            int(np.count_nonzero(values <= float(cutoff)))
            if within_cutoff_counts is None
            else int(within_cutoff_counts.get(cutoff, 0))
        )
        if count < 0 or count > valid_count:
            raise ValueError("TIMING_CUTOFF_COUNT_INVALID")
        summary[f"latency_within_{cutoff}_seconds_count"] = count
        summary[f"latency_within_{cutoff}_seconds_share"] = _ratio(count, valid_count)
    return summary


def audit_uw_full_tape(
    cohort_roots: Mapping[str, Path],
    *,
    sample_size: int = 250_000,
    batch_size: int = 262_144,
) -> UWHistoricalTimingAudit:
    """Audit existing Full Tape timestamps without touching research targets.

    Parameters
    ----------
    cohort_roots:
        Mapping from a logical cohort name to its already-filtered Full Tape
        ``option_events`` root.  Physical roots are never emitted into outputs.
    sample_size:
        Approximate deterministic global sample size used for global, cohort and
        asset quantiles.  Per-session quantiles are exact.
    batch_size:
        Number of rows read from a Parquet batch at once.

    Returns
    -------
    UWHistoricalTimingAudit
        Sanitized global/cohort evidence plus rows for required CSV artifacts.

    Raises
    ------
    FileNotFoundError
        If a declared Full Tape cohort root is absent.
    ValueError
        If a partition does not expose a date and asset or expected timestamp
        fields are absent.

    Notes
    -----
    The audit measures provider-field deltas only.  It does not establish a
    client's receipt time, publication time or trading intent.
    """
    if sample_size <= 0 or batch_size <= 0:
        raise ValueError("TIMING_SAMPLE_AND_BATCH_SIZE_MUST_BE_POSITIVE")
    descriptors = _full_tape_descriptors(cohort_roots)
    total_rows = sum(descriptor.row_count for descriptor in descriptors)
    if not descriptors or total_rows == 0:
        raise ValueError("TIMING_FULL_TAPE_INPUT_EMPTY")
    threshold = _sample_threshold(sample_size, total_rows)

    global_accumulator = _LatencyAccumulator()
    cohort_accumulators = {cohort: _LatencyAccumulator() for cohort in sorted(cohort_roots)}
    asset_accumulators: dict[tuple[str, str], _LatencyAccumulator] = {}
    by_session: list[dict[str, Any]] = []
    current_session: tuple[str, str] | None = None
    session_accumulator = _LatencyAccumulator()

    for descriptor in descriptors:
        session_key = (descriptor.cohort, descriptor.session_date)
        if current_session is not None and session_key != current_session:
            by_session.append(
                _with_scope(
                    session_accumulator.summarize(percentile_method="exact_per_session"),
                    granularity="session",
                    cohort=current_session[0],
                    session_date=current_session[1],
                    asset=None,
                )
            )
            session_accumulator = _LatencyAccumulator()
        current_session = session_key

        file_accumulator, exact_file_chunks = _read_full_tape_file(
            descriptor,
            threshold=threshold,
            batch_size=batch_size,
        )
        exact_file_values = _concatenate(exact_file_chunks)
        session_accumulator.add(
            row_count=file_accumulator.row_count,
            created_at_non_null_count=file_accumulator.created_at_non_null_count,
            executed_at_non_null_count=file_accumulator.executed_at_non_null_count,
            latency_microseconds=exact_file_values,
            sample_microseconds=exact_file_values,
        )

        _merge_accumulator(global_accumulator, file_accumulator)
        _merge_accumulator(cohort_accumulators[descriptor.cohort], file_accumulator)
        asset_key = (descriptor.cohort, descriptor.asset)
        asset_accumulator = asset_accumulators.setdefault(asset_key, _LatencyAccumulator())
        _merge_accumulator(asset_accumulator, file_accumulator)

    if current_session is not None:
        by_session.append(
            _with_scope(
                session_accumulator.summarize(percentile_method="exact_per_session"),
                granularity="session",
                cohort=current_session[0],
                session_date=current_session[1],
                asset=None,
            )
        )

    global_summary = global_accumulator.summarize(percentile_method="deterministic_hash_sample")
    cohort_summaries = {
        cohort: accumulator.summarize(percentile_method="deterministic_hash_sample")
        for cohort, accumulator in cohort_accumulators.items()
    }
    by_asset = [
        _with_scope(
            accumulator.summarize(percentile_method="deterministic_hash_sample"),
            granularity="asset",
            cohort=cohort,
            session_date=None,
            asset=asset,
        )
        for (cohort, asset), accumulator in sorted(asset_accumulators.items())
    ]
    summary = [
        _with_scope(
            global_summary,
            granularity="global",
            cohort="all_existing_cohorts",
            session_date=None,
            asset=None,
        )
    ]
    summary.extend(
        _with_scope(
            cohort_summary,
            granularity="cohort",
            cohort=cohort,
            session_date=None,
            asset=None,
        )
        for cohort, cohort_summary in cohort_summaries.items()
    )
    payload = {
        "schema_version": "provider-timing-semantics-1.0",
        "scope": "existing_filtered_unusual_whales_full_tape_only",
        "historical_uw_classification": _classify_historical_uw(global_summary),
        "interpretation_boundary": (
            "created_at_minus_executed_at_measures_provider_fields_only; it does not prove "
            "client_receipt_time_or_publication_time"
        ),
        "quantile_method": {
            "global_and_cohort_and_asset": "deterministic_hash_sample",
            "session": "exact_per_session",
            "sample_size_target": sample_size,
        },
        "input": {
            "cohorts": {
                cohort: {
                    "file_count": sum(1 for item in descriptors if item.cohort == cohort),
                    "row_count": sum(
                        item.row_count for item in descriptors if item.cohort == cohort
                    ),
                }
                for cohort in sorted(cohort_roots)
            },
            "logical_file_manifest_sha256": _logical_file_manifest_sha256(descriptors),
        },
        "global": global_summary,
        "cohorts": cohort_summaries,
        "cohort_stability": _cohort_stability(cohort_summaries),
        "no_targets_or_predictive_metrics_read": True,
        "secret_values_emitted": False,
        "personal_paths_emitted": False,
    }
    payload["manifest_sha256"] = _canonical_sha256(payload)
    return UWHistoricalTimingAudit(
        payload=payload,
        summary=summary,
        by_session=by_session,
        by_asset=by_asset,
    )


def summarize_fmp_bar_replay(records: Sequence[Mapping[str, object]]) -> dict[str, Any]:
    """Validate a local FMP timing-probe replay without claiming live latency.

    Parameters
    ----------
    records:
        Replay records containing ``bar_timestamp``, ``request_started_at_utc``,
        ``request_completed_at_utc`` and ``received_at_utc``.  Extra fields are
        ignored so transport credentials cannot be emitted.

    Returns
    -------
    dict[str, Any]
        Sanitized replay-schema result with the non-blocking live-probe status.

    Raises
    ------
    ValueError
        If a required UTC timestamp is missing, malformed or causally ordered
        before the corresponding request start.
    """
    for record in records:
        bar_timestamp = _parse_utc_timestamp(record.get("bar_timestamp"), "bar_timestamp")
        request_started = _parse_utc_timestamp(
            record.get("request_started_at_utc"), "request_started_at_utc"
        )
        request_completed = _parse_utc_timestamp(
            record.get("request_completed_at_utc"), "request_completed_at_utc"
        )
        received = _parse_utc_timestamp(record.get("received_at_utc"), "received_at_utc")
        if request_completed < request_started or received < request_completed:
            raise ValueError("FMP_REPLAY_REQUEST_ORDER_INVALID")
        if bar_timestamp > received:
            raise ValueError("FMP_REPLAY_BAR_AFTER_RECEIPT")
    return {
        "schema_version": "provider-timing-fmp-replay-1.0",
        "status": FMP_LIVE_PROBE_STATUS,
        "replay_record_count": len(records),
        "fmp_bar_label_semantics": FMP_BAR_LABEL_SEMANTICS,
        "fmp_provider_confirmed_latency": FMP_PROVIDER_CONFIRMED_LATENCY,
        "fmp_research_availability_rule": FMP_RESEARCH_AVAILABILITY_RULE,
        "research_assumption_primary_seconds": 60,
        "research_assumption_sensitivity_seconds": 120,
        "publication_latency_proven": False,
        "live_market_capture_performed": False,
        "secret_values_emitted": False,
        "personal_paths_emitted": False,
    }


def build_uw_receipt_record(
    message: Mapping[str, object],
    *,
    received_at_utc: str,
    source: str,
    connection_type: str,
    local_clock_offset: str,
) -> dict[str, object]:
    """Build one sanitized receipt record from a local UW replay message.

    Parameters
    ----------
    message:
        Locally supplied replay payload.  It is never persisted by this helper.
    received_at_utc:
        UTC timestamp recorded by the local logger.
    source, connection_type, local_clock_offset:
        Explicit source and transport metadata for future prospective evidence.

    Returns
    -------
    dict[str, object]
        Receipt metadata plus a SHA-256 of a credential-redacted source payload.

    Raises
    ------
    ValueError
        If a supplied timestamp or required logger metadata is malformed.
    """
    if not source or not connection_type:
        raise ValueError("UW_RECEIPT_SOURCE_AND_CONNECTION_REQUIRED")
    received = _format_utc(_parse_utc_timestamp(received_at_utc, "received_at_utc"))
    sanitized_for_hash = _without_secret_fields(message)
    payload: dict[str, object] = {
        "event_id": _first_optional_string(message, "event_id", "id"),
        "trade_id": _first_optional_string(message, "trade_id"),
        "aggregated_trade_id": _first_optional_string(message, "aggregated_trade_id"),
        "executed_at": _optional_utc(message.get("executed_at"), "executed_at"),
        "created_at": _optional_utc(message.get("created_at"), "created_at"),
        "received_at_utc": received,
        "source": source,
        "connection_type": connection_type,
        "local_clock_offset": local_clock_offset,
        "raw_message_hash": hashlib.sha256(
            json.dumps(
                sanitized_for_hash,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
                default=str,
            ).encode("utf-8")
        ).hexdigest(),
    }
    return payload


def reconcile_uw_replay_records(
    receipt_records: Sequence[Mapping[str, object]],
    full_tape_records: Sequence[Mapping[str, object]],
) -> dict[str, Any]:
    """Reconcile local replay receipts to local Full Tape replay records.

    Parameters
    ----------
    receipt_records:
        Sanitized receipt records emitted by :func:`build_uw_receipt_record`.
    full_tape_records:
        Local replay rows from Full Tape with event, trade or aggregate IDs.

    Returns
    -------
    dict[str, Any]
        Match counts and a replay-only status.  No result is a proof of live
        receipt timing or provider publication time.
    """
    full_tape_keys: set[tuple[str, str]] = set()
    duplicate_full_tape_keys = 0
    for record in full_tape_records:
        for key in _record_identifier_keys(record, full_tape=True):
            if key in full_tape_keys:
                duplicate_full_tape_keys += 1
            full_tape_keys.add(key)

    matched_count = 0
    unmatched_receipt_count = 0
    for receipt in receipt_records:
        receipt_keys = _record_identifier_keys(receipt, full_tape=False)
        if any(key in full_tape_keys for key in receipt_keys):
            matched_count += 1
        else:
            unmatched_receipt_count += 1
    return {
        "schema_version": "provider-timing-uw-reconciliation-1.0",
        "status": "REPLAY_ONLY_NOT_LIVE",
        "receipt_record_count": len(receipt_records),
        "full_tape_record_count": len(full_tape_records),
        "matched_count": matched_count,
        "unmatched_receipt_count": unmatched_receipt_count,
        "duplicate_full_tape_identifier_count": duplicate_full_tape_keys,
        "publication_time_proven": False,
        "client_receipt_time_proven": False,
        "secret_values_emitted": False,
        "personal_paths_emitted": False,
    }


def provider_timing_gates() -> dict[str, str]:
    """Return the separated, evidence-scoped provider-timing gates.

    Returns
    -------
    dict[str, str]
        The approved conditional gates.  They are intentionally separate so an
        unmeasured prospective latency cannot retroactively invalidate frozen
        canonical evidence under its registered timing assumptions.
    """
    return {
        "EXISTING_CANONICAL_EVIDENCE": "VALID_UNDER_REGISTERED_TIMING_ASSUMPTIONS",
        "EXISTING_SCIENTIFIC_RECONCILIATION": "CONDITIONAL_GO_NOW",
        "NEW_HISTORICAL_SAMPLE": "GO_AFTER_DATE_LEVEL_PIT_PREFLIGHT",
        "NEW_PROSPECTIVE_SAMPLE": "GO_AFTER_RECEIPT_LOGGER_VALIDATED",
        "UNIVERSAL_PROVIDER_LATENCY_CLAIM": "NOT_SUPPORTED",
    }


def _full_tape_descriptors(cohort_roots: Mapping[str, Path]) -> list[_FullTapeFile]:
    """Build a stable logical manifest of existing Full Tape files."""
    descriptors_without_offset: list[tuple[str, str, str, Path, int]] = []
    for cohort, root in sorted(cohort_roots.items()):
        if not root.is_dir():
            raise FileNotFoundError(f"TIMING_FULL_TAPE_ROOT_MISSING:{cohort}")
        files = sorted(root.rglob("events.parquet"), key=lambda path: path.as_posix())
        for path in files:
            session_date, asset = _partition_identity(path, root)
            metadata = pq.ParquetFile(path).metadata
            descriptors_without_offset.append(
                (cohort, session_date, asset, path, metadata.num_rows)
            )
    descriptors_without_offset.sort(
        key=lambda item: (item[0], item[1], item[2], item[3].as_posix())
    )
    offset = 0
    descriptors: list[_FullTapeFile] = []
    for cohort, session_date, asset, path, row_count in descriptors_without_offset:
        logical_id = f"{cohort}/date={session_date}/asset={asset}/events.parquet"
        descriptors.append(
            _FullTapeFile(
                cohort=cohort,
                session_date=session_date,
                asset=asset,
                path=path,
                logical_id=logical_id,
                row_count=row_count,
                global_row_offset=offset,
            )
        )
        offset += row_count
    return descriptors


def _partition_identity(path: Path, root: Path) -> tuple[str, str]:
    """Extract required Hive-style session and asset partitions from a path."""
    session_date: str | None = None
    asset: str | None = None
    for part in path.relative_to(root).parts:
        session_match = _SESSION_PATTERN.match(part)
        asset_match = _ASSET_PATTERN.match(part)
        if session_match:
            session_date = session_match.group(1)
        if asset_match:
            asset = asset_match.group(1)
    if session_date is None or asset is None:
        raise ValueError("TIMING_FULL_TAPE_PARTITION_INVALID")
    return session_date, asset


def _read_full_tape_file(
    descriptor: _FullTapeFile,
    *,
    threshold: int,
    batch_size: int,
) -> tuple[_LatencyAccumulator, list[np.ndarray[Any, Any]]]:
    """Read timestamp columns once, retaining exact values only for one session."""
    parquet_file = pq.ParquetFile(descriptor.path)
    names = set(parquet_file.schema_arrow.names)
    if not {"created_at", "executed_at"}.issubset(names):
        raise ValueError("TIMING_FULL_TAPE_TIMESTAMP_SCHEMA_DRIFT")
    accumulator = _LatencyAccumulator()
    exact_chunks: list[np.ndarray[Any, Any]] = []
    batch_offset = 0
    for batch in parquet_file.iter_batches(
        batch_size=batch_size,
        columns=["created_at", "executed_at"],
    ):
        created = batch.column(0)
        executed = batch.column(1)
        row_count = batch.num_rows
        created_non_null = row_count - created.null_count
        executed_non_null = row_count - executed.null_count
        valid = pc.and_(pc.is_valid(created), pc.is_valid(executed))
        latency = pc.subtract(pc.cast(created, pa.int64()), pc.cast(executed, pa.int64()))
        valid_latency = pc.filter(latency, valid)
        latency_values = np.asarray(valid_latency.to_numpy(zero_copy_only=False), dtype=np.int64)
        sampled_latency_values = _sample_latency_values(
            latency,
            valid,
            start_index=descriptor.global_row_offset + batch_offset,
            row_count=row_count,
            threshold=threshold,
        )
        accumulator.add(
            row_count=row_count,
            created_at_non_null_count=created_non_null,
            executed_at_non_null_count=executed_non_null,
            latency_microseconds=latency_values,
            sample_microseconds=sampled_latency_values,
        )
        if latency_values.size:
            exact_chunks.append(latency_values)
        batch_offset += row_count
    return accumulator, exact_chunks


def _sample_latency_values(
    latency: pa.Array,
    valid: pa.BooleanArray,
    *,
    start_index: int,
    row_count: int,
    threshold: int,
) -> np.ndarray[Any, Any]:
    """Select a stable, uniform hash sample from one raw Parquet batch."""
    if threshold >= _UINT64_SPACE:
        selected = valid
    else:
        indices = np.arange(start_index, start_index + row_count, dtype=np.uint64)
        hash_values = _splitmix64(indices)
        hash_mask = pa.array(hash_values < np.uint64(threshold))
        selected = pc.and_(valid, hash_mask)
    sampled = pc.filter(latency, selected)
    return np.asarray(sampled.to_numpy(zero_copy_only=False), dtype=np.int64)


def _merge_accumulator(target: _LatencyAccumulator, source: _LatencyAccumulator) -> None:
    """Merge exact counts and source samples into a global aggregate."""
    target.row_count += source.row_count
    target.created_at_non_null_count += source.created_at_non_null_count
    target.executed_at_non_null_count += source.executed_at_non_null_count
    target.both_timestamps_count += source.both_timestamps_count
    target.negative_latency_count += source.negative_latency_count
    if source.latency_min_seconds is not None:
        target.latency_min_seconds = (
            source.latency_min_seconds
            if target.latency_min_seconds is None
            else min(target.latency_min_seconds, source.latency_min_seconds)
        )
    if source.latency_max_seconds is not None:
        target.latency_max_seconds = (
            source.latency_max_seconds
            if target.latency_max_seconds is None
            else max(target.latency_max_seconds, source.latency_max_seconds)
        )
    for cutoff in UW_LATENCY_CUTOFF_SECONDS:
        target.within_cutoff_counts[cutoff] += source.within_cutoff_counts[cutoff]
    target.sample_chunks.extend(source.sample_chunks)


def _with_scope(
    summary: Mapping[str, Any],
    *,
    granularity: str,
    cohort: str,
    session_date: str | None,
    asset: str | None,
) -> dict[str, Any]:
    """Add a stable scope prefix for a CSV-safe summary row."""
    return {
        "granularity": granularity,
        "cohort": cohort,
        "session_date": session_date,
        "asset": asset,
        **dict(summary),
    }


def _cohort_stability(cohort_summaries: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """Describe, without overclaiming, observed differences between cohorts."""
    names = sorted(cohort_summaries)
    comparisons: list[dict[str, Any]] = []
    for baseline, comparison in zip(names, names[1:], strict=False):
        first = cohort_summaries[baseline]
        second = cohort_summaries[comparison]
        comparisons.append(
            {
                "baseline_cohort": baseline,
                "comparison_cohort": comparison,
                "latency_p50_absolute_difference_seconds": _absolute_difference(
                    first.get("latency_p50_seconds"), second.get("latency_p50_seconds")
                ),
                "latency_p95_absolute_difference_seconds": _absolute_difference(
                    first.get("latency_p95_seconds"), second.get("latency_p95_seconds")
                ),
                "within_60_seconds_share_absolute_difference": _absolute_difference(
                    first.get("latency_within_60_seconds_share"),
                    second.get("latency_within_60_seconds_share"),
                ),
                "assessment": "DESCRIPTIVE_ONLY_NOT_A_PUBLICATION_LATENCY_PROOF",
            }
        )
    return {
        "cohort_count": len(names),
        "comparisons": comparisons,
        "interpretation": (
            "Cohort comparisons describe stability of provider-field deltas only; they do not "
            "verify universal provider latency or client receipt time."
        ),
    }


def _classify_historical_uw(summary: Mapping[str, Any]) -> str:
    """Apply the predeclared evidence boundary to Full Tape timestamp fields."""
    if int(summary["both_timestamps_count"]) == 0:
        return "INVALID"
    return HISTORICAL_UW_CLASSIFICATION


def _logical_file_manifest_sha256(descriptors: Sequence[_FullTapeFile]) -> str:
    """Hash logical partitions and immutable Parquet metadata, never physical paths."""
    payload = [
        {
            "logical_id": item.logical_id,
            "row_count": item.row_count,
            "file_size": item.path.stat().st_size,
        }
        for item in descriptors
    ]
    return _canonical_sha256({"files": payload})


def _sample_threshold(sample_size: int, total_rows: int) -> int:
    """Return a deterministic 64-bit hash threshold for an unbiased sample."""
    if sample_size >= total_rows:
        return _UINT64_SPACE
    return max(1, (sample_size * _UINT64_SPACE) // total_rows)


def _splitmix64(values: np.ndarray[Any, Any]) -> np.ndarray[Any, Any]:
    """Vectorize SplitMix64 for a stable hash-based sample mask."""
    z = values + np.uint64(0x9E3779B97F4A7C15)
    z = (z ^ (z >> np.uint64(30))) * np.uint64(0xBF58476D1CE4E5B9)
    z = (z ^ (z >> np.uint64(27))) * np.uint64(0x94D049BB133111EB)
    return z ^ (z >> np.uint64(31))


def _concatenate(chunks: Sequence[np.ndarray[Any, Any]]) -> np.ndarray[Any, Any]:
    """Concatenate chunks while preserving an empty numeric array."""
    if not chunks:
        return np.array([], dtype=np.int64)
    return np.concatenate(chunks)


def _ratio(numerator: int, denominator: int) -> float | None:
    """Compute a nullable ratio without silently treating an empty scope as zero."""
    if denominator == 0:
        return None
    return numerator / denominator


def _absolute_difference(first: object, second: object) -> float | None:
    """Return an absolute difference only when both values are numeric."""
    if not isinstance(first, (float, int)) or not isinstance(second, (float, int)):
        return None
    return abs(float(first) - float(second))


def _parse_utc_timestamp(value: object, name: str) -> datetime:
    """Parse one required ISO timestamp and normalize it to UTC."""
    if not isinstance(value, str) or not value:
        raise ValueError(f"TIMING_TIMESTAMP_MISSING:{name}")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"TIMING_TIMESTAMP_INVALID:{name}") from error
    if parsed.tzinfo is None:
        raise ValueError(f"TIMING_TIMESTAMP_NOT_UTC_AWARE:{name}")
    return parsed.astimezone(UTC)


def _optional_utc(value: object, name: str) -> str | None:
    """Normalize an optional source timestamp without fabricating a value."""
    if value is None:
        return None
    return _format_utc(_parse_utc_timestamp(value, name))


def _format_utc(value: datetime) -> str:
    """Serialize a UTC timestamp in a stable ISO-8601 representation."""
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _first_optional_string(message: Mapping[str, object], *keys: str) -> str | None:
    """Select the first non-empty string identifier without coercing values."""
    for key in keys:
        value = message.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _without_secret_fields(message: Mapping[str, object]) -> dict[str, object]:
    """Remove credential-shaped top-level fields before hashing a replay payload."""
    return {key: value for key, value in message.items() if not _SECRET_FIELD_PATTERN.search(key)}


def _record_identifier_keys(
    record: Mapping[str, object],
    *,
    full_tape: bool,
) -> list[tuple[str, str]]:
    """Generate stable reconciliation keys while retaining identifier provenance."""
    if full_tape:
        event_value = _first_optional_string(record, "id", "event_id")
    else:
        event_value = _first_optional_string(record, "event_id")
    candidates = (
        ("event_id", event_value),
        ("trade_id", _first_optional_string(record, "trade_id")),
        ("aggregated_trade_id", _first_optional_string(record, "aggregated_trade_id")),
    )
    return [(kind, value) for kind, value in candidates if value is not None]


def _canonical_sha256(payload: Mapping[str, Any]) -> str:
    """Hash sanitized JSON-like evidence using deterministic canonical serialization."""
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()
