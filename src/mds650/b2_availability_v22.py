"""Target-blind B2 availability sidecar construction for PIT remediation v2.2.

This module never opens RV30, forecasts, predictions, model artefacts, or
evaluation results.  It reads immutable canonical B2 matrices only to verify
their identity and determine whether a row was numerically zero or nonzero.
The output is an eligibility sidecar; it does not rewrite a canonical matrix.
"""

from __future__ import annotations

import hashlib
import math
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import polars as pl

from mds650.provider_timing_v21 import B2_FEATURE_COLUMNS


@dataclass(frozen=True)
class B2AvailabilityVariant:
    """Registered target-blind B2 availability variant.

    Parameters
    ----------
    name
        Immutable directory name of the canonical B2 matrix variant.
    window_minutes
        Execution-time lookback window ending at the delayed cutoff.
    delay_seconds
        Registered operational ``created_at`` delay.
    """

    name: str
    window_minutes: int
    delay_seconds: int


B2_AVAILABILITY_VARIANTS: Final[dict[str, B2AvailabilityVariant]] = {
    "primary_5m_60s": B2AvailabilityVariant("primary_5m_60s", 5, 60),
    "latency_5m_120s": B2AvailabilityVariant("latency_5m_120s", 5, 120),
    "latency_5m_300s": B2AvailabilityVariant("latency_5m_300s", 5, 300),
    "window_15m_60s": B2AvailabilityVariant("window_15m_60s", 15, 60),
    "window_30m_60s": B2AvailabilityVariant("window_30m_60s", 30, 60),
}

_CONFOUNDED_STATE: Final[str] = "RECORD_CREATION_DELAY_OBSERVED"
_ORIGIN_COLUMNS: Final[tuple[str, ...]] = (
    "origin_id",
    "asset",
    "session_date",
    "forecast_origin_utc",
)
_RAW_COLUMNS: Final[tuple[str, ...]] = (
    "underlying_symbol",
    "executed_at",
    "created_at",
)


def build_b2_availability_sidecar(
    *,
    event_root: Path,
    matrix_root: Path,
    expected_origins_path: Path,
    traceability_rows: Sequence[Mapping[str, Any]],
) -> tuple[pl.DataFrame, dict[str, Any]]:
    """Build a deterministic, target-free B2 row-eligibility sidecar.

    Canonical B2 matrices are verified by SHA-256 and never modified.  Raw
    Full Tape timestamps are recomputed only for asset-date groups previously
    identified by v2.1 as having record-creation delay.  A numerically-zero
    canonical row with delayed raw candidates is excluded rather than silently
    treated as a true activity zero.

    Parameters
    ----------
    event_root
        Root containing ``date=YYYY-MM-DD/asset=SYMBOL/events.parquet`` Full
        Tape partitions.  The function reads only confounded partitions.
    matrix_root
        Root of immutable raw B2 canonical variant directories.
    expected_origins_path
        Parquet projection containing only ``origin_id``, asset, session date,
        and UTC forecast-origin timestamp.
    traceability_rows
        Sanitized v2.1 traceability mappings with one row per
        variant/date/asset and a canonical-file SHA-256.

    Returns
    -------
    tuple[polars.DataFrame, dict[str, Any]]
        Sorted row sidecar and compact aggregate diagnostics.  Each row has an
        explicit eligibility status and no target, forecast, prediction, or
        evaluation value.

    Raises
    ------
    ValueError
        If input keys, schemas, canonical hashes, or origin identities are
        inconsistent.  These failures are intentionally fail-closed.

    Examples
    --------
    ``sidecar, summary = build_b2_availability_sidecar(...)``
    """
    origins = _load_expected_origins(expected_origins_path)
    trace_index = _traceability_index(traceability_rows)
    rows: list[dict[str, Any]] = []
    observed_variants: list[str] = []

    for variant_path in sorted(path for path in matrix_root.iterdir() if path.is_dir()):
        variant = B2_AVAILABILITY_VARIANTS.get(variant_path.name)
        if variant is None:
            continue
        observed_variants.append(variant.name)
        for matrix_path in sorted(variant_path.glob("date=*.parquet")):
            session_date = _session_date_from_matrix_path(matrix_path)
            canonical = _load_canonical_matrix(matrix_path)
            matrix_hash = _sha256_file(matrix_path)
            for asset in sorted(str(value) for value in canonical["asset"].unique().to_list()):
                trace = _trace_for(
                    trace_index,
                    variant=variant.name,
                    session_date=session_date,
                    asset=asset,
                )
                if str(trace["canonical_file_sha256"]) != matrix_hash:
                    raise ValueError("B2_AVAILABILITY_CANONICAL_HASH_MISMATCH")
                origin_group = origins.filter(
                    (pl.col("session_date") == session_date) & (pl.col("asset") == asset)
                )
                canonical_group = canonical.filter(
                    (pl.col("session_date") == session_date) & (pl.col("asset") == asset)
                )
                _validate_group_keys(origin_group, canonical_group)
                state = str(trace["source_temporal_state"])
                if state == _CONFOUNDED_STATE:
                    diagnostic = _raw_window_diagnostics(
                        event_root=event_root,
                        asset=asset,
                        session_date=session_date,
                        origins=origin_group,
                        variant=variant,
                    )
                    rows.extend(
                        _classify_confounded_group(
                            canonical=canonical_group,
                            origins=origin_group,
                            variant=variant,
                            source_state=state,
                            diagnostic=diagnostic,
                        )
                    )
                else:
                    rows.extend(
                        _classify_clean_group(
                            canonical=canonical_group,
                            origins=origin_group,
                            variant=variant,
                            source_state=state,
                        )
                    )

    if not rows:
        raise ValueError("B2_AVAILABILITY_NO_CANONICAL_ROWS")
    sidecar = pl.DataFrame(rows, infer_schema_length=None).sort(
        "canonical_variant", "session_date", "asset", "forecast_origin_utc", "origin_id"
    )
    _validate_sidecar(sidecar, observed_variants=observed_variants)
    return sidecar, _summarize_sidecar(sidecar)


def _load_expected_origins(path: Path) -> pl.DataFrame:
    """Read and validate the target-free forecast-origin projection."""
    if not path.is_file():
        raise ValueError("B2_AVAILABILITY_EXPECTED_ORIGINS_MISSING")
    try:
        frame = pl.read_parquet(path, columns=list(_ORIGIN_COLUMNS))
    except (OSError, pl.exceptions.PolarsError) as exc:
        raise ValueError("B2_AVAILABILITY_EXPECTED_ORIGINS_SCHEMA_INVALID") from exc
    frame = frame.with_columns(pl.col("session_date").cast(pl.Utf8))
    if frame.height == 0 or frame["origin_id"].n_unique() != frame.height:
        raise ValueError("B2_AVAILABILITY_EXPECTED_ORIGINS_KEY_INVALID")
    if frame.select(pl.col("forecast_origin_utc").is_null().any()).item():
        raise ValueError("B2_AVAILABILITY_EXPECTED_ORIGIN_TIMESTAMP_MISSING")
    return frame.select(*_ORIGIN_COLUMNS)


def _load_canonical_matrix(path: Path) -> pl.DataFrame:
    """Read only target-free B2 values needed for availability classification."""
    columns = ["origin_id", "asset", "session_date", *B2_FEATURE_COLUMNS]
    try:
        frame = pl.read_parquet(path, columns=columns)
    except (OSError, pl.exceptions.PolarsError) as exc:
        raise ValueError("B2_AVAILABILITY_CANONICAL_SCHEMA_INVALID") from exc
    frame = frame.with_columns(pl.col("session_date").cast(pl.Utf8))
    if frame.height == 0 or frame["origin_id"].n_unique() != frame.height:
        raise ValueError("B2_AVAILABILITY_CANONICAL_KEY_INVALID")
    return frame


def _traceability_index(
    rows: Sequence[Mapping[str, Any]],
) -> dict[tuple[str, str, str], Mapping[str, Any]]:
    """Return a unique traceability mapping indexed by canonical group."""
    index: dict[tuple[str, str, str], Mapping[str, Any]] = {}
    for row in rows:
        try:
            key = (
                str(row["canonical_variant"]),
                str(row["session_date"]),
                str(row["asset"]),
            )
            if not row["canonical_file_sha256"] or not row["source_temporal_state"]:
                raise KeyError
        except KeyError as exc:
            raise ValueError("B2_AVAILABILITY_TRACEABILITY_SCHEMA_INVALID") from exc
        if key in index:
            raise ValueError("B2_AVAILABILITY_TRACEABILITY_DUPLICATE")
        index[key] = row
    return index


def _trace_for(
    index: Mapping[tuple[str, str, str], Mapping[str, Any]],
    *,
    variant: str,
    session_date: str,
    asset: str,
) -> Mapping[str, Any]:
    """Retrieve exactly one v2.1 trace row for a canonical group."""
    try:
        return index[(variant, session_date, asset)]
    except KeyError as exc:
        raise ValueError("B2_AVAILABILITY_TRACEABILITY_KEY_INVALID") from exc


def _validate_group_keys(origins: pl.DataFrame, canonical: pl.DataFrame) -> None:
    """Fail when an immutable canonical group no longer matches its origins."""
    if origins.height == 0 or canonical.height == 0:
        raise ValueError("B2_AVAILABILITY_ORIGIN_OR_CANONICAL_GROUP_EMPTY")
    origin_ids = set(str(value) for value in origins["origin_id"].to_list())
    canonical_ids = set(str(value) for value in canonical["origin_id"].to_list())
    if origin_ids != canonical_ids:
        raise ValueError("B2_AVAILABILITY_ORIGIN_CANONICAL_KEY_MISMATCH")


def _raw_window_diagnostics(
    *,
    event_root: Path,
    asset: str,
    session_date: str,
    origins: pl.DataFrame,
    variant: B2AvailabilityVariant,
) -> pl.DataFrame | None:
    """Recompute raw candidate/eligible/delayed counts for one confounded group."""
    path = event_root / f"date={session_date}" / f"asset={asset}" / "events.parquet"
    if not path.is_file():
        return None
    try:
        events = pl.read_parquet(path, columns=list(_RAW_COLUMNS))
    except (OSError, pl.exceptions.PolarsError):
        return None
    if not set(_RAW_COLUMNS).issubset(events.columns):
        return None
    origin_key = origins.select("origin_id", "forecast_origin_utc")
    candidate_offsets = [
        pl.col("_first_candidate_origin") + pl.duration(minutes=offset)
        for offset in range(0, variant.window_minutes, 5)
    ]
    candidates = (
        events.filter(pl.col("underlying_symbol") == asset)
        .with_columns(
            (
                (pl.col("executed_at") + pl.duration(seconds=variant.delay_seconds)).dt.truncate(
                    "5m"
                )
                + pl.duration(minutes=5)
            ).alias("_first_candidate_origin")
        )
        .with_columns(pl.concat_list(candidate_offsets).alias("_candidate_origin"))
        .explode("_candidate_origin", empty_as_null=True)
        .join(
            origin_key,
            left_on="_candidate_origin",
            right_on="forecast_origin_utc",
            how="inner",
        )
        .with_columns(pl.col("_candidate_origin").alias("forecast_origin_utc"))
        .filter(
            (
                pl.col("executed_at")
                >= pl.col("forecast_origin_utc")
                - pl.duration(seconds=variant.delay_seconds, minutes=variant.window_minutes)
            )
            & (
                pl.col("executed_at")
                < pl.col("forecast_origin_utc") - pl.duration(seconds=variant.delay_seconds)
            )
        )
        .with_columns(
            pl.col("created_at").is_null().cast(pl.Int64).alias("_missing_created"),
            (
                pl.col("created_at").is_not_null()
                & (
                    pl.col("created_at")
                    <= pl.col("forecast_origin_utc") - pl.duration(seconds=variant.delay_seconds)
                )
            )
            .cast(pl.Int64)
            .alias("_eligible"),
            (
                pl.col("created_at").is_not_null()
                & (
                    pl.col("created_at")
                    > pl.col("forecast_origin_utc") - pl.duration(seconds=variant.delay_seconds)
                )
            )
            .cast(pl.Int64)
            .alias("_delayed"),
        )
    )
    counts = candidates.group_by("origin_id").agg(
        pl.len().cast(pl.Int64).alias("raw_window_trade_count"),
        pl.col("_eligible").sum().cast(pl.Int64).alias("eligible_raw_window_trade_count"),
        pl.col("_delayed").sum().cast(pl.Int64).alias("delayed_raw_window_trade_count"),
        pl.col("_missing_created").sum().cast(pl.Int64).alias("missing_created_at_trade_count"),
    )
    return origin_key.join(counts, on="origin_id", how="left").with_columns(
        pl.col("raw_window_trade_count").fill_null(0).cast(pl.Int64),
        pl.col("eligible_raw_window_trade_count").fill_null(0).cast(pl.Int64),
        pl.col("delayed_raw_window_trade_count").fill_null(0).cast(pl.Int64),
        pl.col("missing_created_at_trade_count").fill_null(0).cast(pl.Int64),
    )


def _classify_clean_group(
    *,
    canonical: pl.DataFrame,
    origins: pl.DataFrame,
    variant: B2AvailabilityVariant,
    source_state: str,
) -> list[dict[str, Any]]:
    """Classify a group without a v2.1 record-creation-delay incident."""
    joined = origins.join(canonical, on="origin_id", how="left", validate="1:1")
    records: list[dict[str, Any]] = []
    for row in joined.sort("forecast_origin_utc", "origin_id").to_dicts():
        status = _clean_status(row)
        records.append(
            _base_record(
                row=row,
                variant=variant,
                source_state=source_state,
                status=status,
                eligible=status.startswith("PIT_USABLE_"),
                raw_counts=None,
            )
        )
    return records


def _classify_confounded_group(
    *,
    canonical: pl.DataFrame,
    origins: pl.DataFrame,
    variant: B2AvailabilityVariant,
    source_state: str,
    diagnostic: pl.DataFrame | None,
) -> list[dict[str, Any]]:
    """Classify a delayed-source group using raw event-window diagnostics."""
    joined = origins.join(canonical, on="origin_id", how="left", validate="1:1")
    if diagnostic is None:
        return [
            _base_record(
                row=row,
                variant=variant,
                source_state=source_state,
                status="PIT_EXCLUDED_SOURCE_UNAVAILABLE_OR_SCHEMA_INVALID",
                eligible=False,
                raw_counts=None,
            )
            for row in joined.sort("forecast_origin_utc", "origin_id").to_dicts()
        ]
    joined = joined.join(
        diagnostic.drop("forecast_origin_utc"), on="origin_id", how="left", validate="1:1"
    )
    records: list[dict[str, Any]] = []
    for row in joined.sort("forecast_origin_utc", "origin_id").to_dicts():
        counts = {
            name: int(row[name])
            for name in (
                "raw_window_trade_count",
                "eligible_raw_window_trade_count",
                "delayed_raw_window_trade_count",
                "missing_created_at_trade_count",
            )
        }
        status = _confounded_status(row, counts)
        records.append(
            _base_record(
                row=row,
                variant=variant,
                source_state=source_state,
                status=status,
                eligible=status.startswith("PIT_USABLE_"),
                raw_counts=counts,
            )
        )
    return records


def _clean_status(row: Mapping[str, Any]) -> str:
    """Return strict availability status from canonical numeric state alone."""
    state = _canonical_feature_state(row)
    if state == "ZERO":
        return "PIT_USABLE_ZERO_NO_DELAY_INCIDENT"
    if state == "NONZERO":
        return "PIT_USABLE_ELIGIBLE_ACTIVITY"
    return "PIT_EXCLUDED_CANONICAL_FEATURE_INVALID"


def _confounded_status(row: Mapping[str, Any], counts: Mapping[str, int]) -> str:
    """Return fail-closed status for a raw-delay-context origin."""
    state = _canonical_feature_state(row)
    if state == "INVALID":
        return "PIT_EXCLUDED_CANONICAL_FEATURE_INVALID"
    if counts["missing_created_at_trade_count"]:
        return "PIT_EXCLUDED_MISSING_CREATED_AT"
    if state == "ZERO":
        if counts["delayed_raw_window_trade_count"]:
            return "PIT_EXCLUDED_DELAYED_RAW_WINDOW_TRADES"
        if counts["raw_window_trade_count"] == 0:
            return "PIT_EXCLUDED_SOURCE_DELAY_CONTEXT_ZERO"
        return "PIT_EXCLUDED_CANONICAL_RAW_COUNT_MISMATCH"
    canonical_count = _canonical_trade_count(row)
    if canonical_count is None or canonical_count != counts["eligible_raw_window_trade_count"]:
        return "PIT_EXCLUDED_CANONICAL_RAW_COUNT_MISMATCH"
    return "PIT_USABLE_ELIGIBLE_ACTIVITY_DELAY_CONTEXT"


def _canonical_feature_state(row: Mapping[str, Any]) -> str:
    """Classify all canonical B2 features without exposing their values."""
    values: list[float] = []
    for column in B2_FEATURE_COLUMNS:
        value = row.get(column)
        if value is None:
            return "INVALID"
        number = float(value)
        if not math.isfinite(number):
            return "INVALID"
        values.append(number)
    return "ZERO" if all(value == 0.0 for value in values) else "NONZERO"


def _canonical_trade_count(row: Mapping[str, Any]) -> int | None:
    """Return an integral canonical count or ``None`` when it is invalid."""
    value = row.get("option_trade_count_5m")
    if value is None:
        return None
    number = float(value)
    rounded = round(number)
    if number < 0.0 or not math.isfinite(number) or not math.isclose(number, rounded):
        return None
    return int(rounded)


def _base_record(
    *,
    row: Mapping[str, Any],
    variant: B2AvailabilityVariant,
    source_state: str,
    status: str,
    eligible: bool,
    raw_counts: Mapping[str, int] | None,
) -> dict[str, Any]:
    """Build one compact, target-free deterministic sidecar record."""
    counts = raw_counts or {}
    return {
        "canonical_variant": variant.name,
        "window_minutes": variant.window_minutes,
        "delay_seconds": variant.delay_seconds,
        "origin_id": str(row["origin_id"]),
        "asset": str(row["asset"]),
        "session_date": str(row["session_date"]),
        "forecast_origin_utc": row["forecast_origin_utc"],
        "canonical_feature_state": _canonical_feature_state(row),
        "canonical_trade_count": _canonical_trade_count(row),
        "raw_window_trade_count": counts.get("raw_window_trade_count"),
        "eligible_raw_window_trade_count": counts.get("eligible_raw_window_trade_count"),
        "delayed_raw_window_trade_count": counts.get("delayed_raw_window_trade_count"),
        "missing_created_at_trade_count": counts.get("missing_created_at_trade_count"),
        "source_temporal_state": source_state,
        "row_status": status,
        "eligible_for_corrected_pit_panel": eligible,
    }


def _validate_sidecar(sidecar: pl.DataFrame, *, observed_variants: Sequence[str]) -> None:
    """Enforce uniqueness and fail-closed row-level availability invariants."""
    if (
        sidecar.select(pl.struct("canonical_variant", "origin_id").n_unique()).item()
        != sidecar.height
    ):
        raise ValueError("B2_AVAILABILITY_SIDECAR_DUPLICATE")
    if sorted(set(observed_variants)) != sorted(sidecar["canonical_variant"].unique().to_list()):
        raise ValueError("B2_AVAILABILITY_VARIANT_COVERAGE_INVALID")
    invalid = sidecar.filter(
        pl.col("eligible_for_corrected_pit_panel")
        & (pl.col("row_status").str.starts_with("PIT_EXCLUDED_"))
    )
    if invalid.height:
        raise ValueError("B2_AVAILABILITY_ELIGIBILITY_STATUS_CONTRADICTION")
    delayed_zero = sidecar.filter(
        pl.col("eligible_for_corrected_pit_panel")
        & (pl.col("canonical_feature_state") == "ZERO")
        & (pl.col("delayed_raw_window_trade_count").fill_null(0) > 0)
    )
    if delayed_zero.height:
        raise ValueError("B2_AVAILABILITY_DELAYED_ZERO_NOT_EXCLUDED")


def _summarize_sidecar(sidecar: pl.DataFrame) -> dict[str, Any]:
    """Produce compact target-free counts used by the remediation gate."""
    statuses = Counter(str(value) for value in sidecar["row_status"].to_list())
    variant_rows: list[dict[str, Any]] = []
    for variant, frame in sidecar.group_by("canonical_variant", maintain_order=True):
        name = str(variant[0])
        variant_rows.append(
            {
                "canonical_variant": name,
                "row_count": frame.height,
                "eligible_row_count": int(frame["eligible_for_corrected_pit_panel"].sum()),
                "excluded_row_count": int((~frame["eligible_for_corrected_pit_panel"]).sum()),
            }
        )
    primary_delayed_zero_count = sidecar.filter(
        (pl.col("canonical_variant") == "primary_5m_60s")
        & (pl.col("row_status") == "PIT_EXCLUDED_DELAYED_RAW_WINDOW_TRADES")
    ).height
    return {
        "schema_version": "2.2",
        "row_count": sidecar.height,
        "eligible_row_count": int(sidecar["eligible_for_corrected_pit_panel"].sum()),
        "excluded_row_count": int((~sidecar["eligible_for_corrected_pit_panel"]).sum()),
        "primary_delayed_raw_zero_exclusion_count": primary_delayed_zero_count,
        "canonical_raw_count_mismatch_count": statuses["PIT_EXCLUDED_CANONICAL_RAW_COUNT_MISMATCH"],
        "row_status_counts": dict(sorted(statuses.items())),
        "variant_totals": sorted(variant_rows, key=lambda row: str(row["canonical_variant"])),
    }


def _session_date_from_matrix_path(path: Path) -> str:
    """Parse the immutable date partition name strictly."""
    stem = path.stem
    if not stem.startswith("date="):
        raise ValueError("B2_AVAILABILITY_MATRIX_DATE_PARTITION_INVALID")
    return stem.removeprefix("date=")


def _sha256_file(path: Path) -> str:
    """Return a streaming SHA-256 without materializing a large file in memory."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1_048_576), b""):
            digest.update(block)
    return digest.hexdigest()
