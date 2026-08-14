"""Target-blind construction primitives for the B1v3 confirmation panel."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import timedelta
from typing import Any, Final
from zoneinfo import ZoneInfo

import exchange_calendars as xcals  # type: ignore[import-untyped]
import polars as pl

from mds650.b1v3 import B1V3_FEATURES
from mds650.b1v3_confirmation import canonical_sha256
from mds650.phase6 import B0V2_FEATURES, build_b0v2_features
from mds650.study_design import B2_FEATURE_NAMES

_NEW_YORK: Final[ZoneInfo] = ZoneInfo("America/New_York")
_TARGET_SCAFFOLDING: Final[frozenset[str]] = frozenset(
    {"rv30", "target_price_count", "target_return_count"}
)
_FORBIDDEN_COLUMN_FRAGMENTS: Final[tuple[str, ...]] = (
    "rv30",
    "qlike",
    "prediction",
    "outcome",
    "model_result",
)


def build_origin_grid(
    *,
    training_sessions: Sequence[str],
    confirmation_sessions: Sequence[str],
    assets: Sequence[str],
) -> pl.DataFrame:
    """Build every RV30-safe five-minute XNYS origin without reading outcomes.

    Parameters
    ----------
    training_sessions, confirmation_sessions:
        Disjoint, sorted XNYS session arrays frozen before outcome access.
    assets:
        Non-empty canonical asset allowlist.

    Returns
    -------
    polars.DataFrame
        Unique target-free origins from open plus five minutes through close
        minus thirty minutes, including early-close-aware session metadata.

    Raises
    ------
    ValueError
        If dates/assets are duplicated, unordered, overlapping or not XNYS.
    """
    training = tuple(str(value) for value in training_sessions)
    confirmation = tuple(str(value) for value in confirmation_sessions)
    symbols = tuple(str(value) for value in assets)
    if (
        not training
        or not confirmation
        or not symbols
        or training != tuple(sorted(set(training)))
        or confirmation != tuple(sorted(set(confirmation)))
        or symbols != tuple(sorted(set(symbols)))
        or set(training) & set(confirmation)
    ):
        raise ValueError("B1V3_ORIGIN_ALLOWLIST_INVALID")
    calendar = xcals.get_calendar("XNYS")
    rows: list[dict[str, Any]] = []
    roles = tuple((value, "training_warmup") for value in training) + tuple(
        (value, "confirmation") for value in confirmation
    )
    for session_date, role in roles:
        try:
            opened = calendar.session_open(session_date).to_pydatetime()
            closed = calendar.session_close(session_date).to_pydatetime()
        except Exception as exc:
            raise ValueError("B1V3_ORIGIN_NOT_XNYS_SESSION") from exc
        origin = opened + timedelta(minutes=5)
        last_origin = closed - timedelta(minutes=30)
        while origin <= last_origin:
            session_minute = int((origin - opened).total_seconds() // 60)
            session_tercile = (
                "first"
                if session_minute < 130
                else "middle"
                if session_minute < 260
                else "last"
            )
            for asset in symbols:
                rows.append(
                    {
                        "origin_id": f"{asset}:{origin.isoformat()}",
                        "asset": asset,
                        "session_date": session_date,
                        "forecast_origin_utc": origin,
                        "forecast_origin_ny": origin.astimezone(_NEW_YORK),
                        "forecast_origin_ns": int(origin.timestamp() * 1_000_000_000),
                        "role": role,
                        "session_minute": session_minute,
                        "session_tercile": session_tercile,
                        "session_segment": session_tercile,
                    }
                )
            origin += timedelta(minutes=5)
    frame = pl.DataFrame(rows, infer_schema_length=None).sort(
        "session_date", "forecast_origin_utc", "asset"
    )
    if frame.is_empty() or frame["origin_id"].n_unique() != frame.height:
        raise ValueError("B1V3_ORIGIN_GRID_INVALID")
    return frame


def validate_fmp_cache_document(
    document: Mapping[str, Any], report_record: Mapping[str, Any]
) -> list[dict[str, Any]]:
    """Validate one FMP cache envelope against its authenticated report row."""
    stored_hash = document.get("cache_self_hash")
    unsigned = {key: value for key, value in document.items() if key != "cache_self_hash"}
    if stored_hash != canonical_sha256(unsigned):
        raise ValueError("B1V3_FMP_CACHE_SELF_HASH_INVALID")
    if (
        document.get("schema_version") != "b1v3-provider-preflight-cache-2.0"
        or document.get("provider") != "fmp"
        or document.get("status_code") != 200
        or report_record.get("provider") != "fmp"
        or report_record.get("pass") is not True
        or document.get("request_fingerprint")
        != report_record.get("request_fingerprint")
        or document.get("response_sha256") != report_record.get("response_sha256")
    ):
        raise ValueError("B1V3_FMP_CACHE_REPORT_BINDING_INVALID")
    payload = document.get("payload")
    if not isinstance(payload, list) or not all(isinstance(row, dict) for row in payload):
        raise ValueError("B1V3_FMP_CACHE_PAYLOAD_INVALID")
    return payload


def build_spot_frame(bars: pl.DataFrame, origins: pl.DataFrame) -> pl.DataFrame:
    """Select the fully observed origin close under the FMP plus-one-minute rule."""
    required_bars = {
        "asset",
        "session_date",
        "bar_timestamp_raw_utc",
        "available_at_utc",
        "close",
    }
    if not required_bars.issubset(bars.columns) or not {
        "origin_id",
        "asset",
        "session_date",
        "forecast_origin_utc",
    }.issubset(origins.columns):
        raise ValueError("B1V3_SPOT_INPUT_SCHEMA_INVALID")
    source = bars.select(
        "asset",
        "session_date",
        pl.col("bar_timestamp_raw_utc").alias("spot_bar_timestamp_raw_utc"),
        pl.col("available_at_utc").alias("spot_available_at_utc"),
        pl.col("close").cast(pl.Float64).alias("spot"),
    )
    unique_bar_count = source.select(
        pl.struct("asset", "session_date", "spot_bar_timestamp_raw_utc").n_unique()
    ).item()
    if unique_bar_count != source.height:
        raise ValueError("B1V3_SPOT_DUPLICATE_BAR")
    frame = (
        origins.select("origin_id", "asset", "session_date", "forecast_origin_utc")
        .with_columns(
            (pl.col("forecast_origin_utc") - pl.duration(minutes=1)).alias(
                "spot_bar_timestamp_raw_utc"
            )
        )
        .join(
            source,
            on=["asset", "session_date", "spot_bar_timestamp_raw_utc"],
            how="left",
            validate="m:1",
        )
        .with_columns(
            (
                pl.col("spot").is_not_null()
                & pl.col("spot").is_finite()
                & (pl.col("spot") > 0)
                & (pl.col("spot_available_at_utc") <= pl.col("forecast_origin_utc"))
            ).alias("spot_available"),
        )
        .with_columns(
            pl.when(pl.col("spot_available"))
            .then(None)
            .otherwise(pl.lit("FMP_ORIGIN_SPOT_UNAVAILABLE"))
            .cast(pl.String)
            .alias("spot_missing_reason")
        )
    )
    if frame.filter(
        pl.col("spot_available")
        & (pl.col("spot_available_at_utc") > pl.col("forecast_origin_utc"))
    ).height:
        raise ValueError("B1V3_SPOT_FUTURE_BAR")
    return frame


def strip_target_columns(frame: pl.DataFrame) -> pl.DataFrame:
    """Remove target scaffolding from a predictor-only B0 frame."""
    cleaned = frame.drop(
        *[column for column in _TARGET_SCAFFOLDING if column in frame.columns]
    )
    if "drop_reason" in cleaned.columns:
        cleaned = cleaned.with_columns(
            pl.when(pl.col("drop_reason") == "RV30_ORIGIN_CLOSE_MISSING")
            .then(pl.lit("ORIGIN_CLOSE_MISSING"))
            .otherwise(pl.col("drop_reason"))
            .alias("drop_reason")
        )
    lowered = tuple(column.lower() for column in cleaned.columns)
    if any(
        fragment in column
        for fragment in _FORBIDDEN_COLUMN_FRAGMENTS
        for column in lowered
    ):
        raise ValueError("B1V3_B0_TARGET_COLUMN_REMAINS")
    return cleaned


def build_b0_target_blind(bars: pl.DataFrame, origins: pl.DataFrame) -> pl.DataFrame:
    """Build B0 predictors while making any incomplete history explicit."""
    frame = strip_target_columns(
        build_b0v2_features(bars, origins, delay_minutes=1, include_target=False)
    )
    numeric = [feature for feature in B0V2_FEATURES if feature != "b0v2_asset_identity"]
    return frame.with_columns(
        (
            pl.col("drop_reason").is_null()
            & pl.all_horizontal(pl.col(feature).is_not_null() for feature in numeric)
            & pl.all_horizontal(pl.col(feature).is_finite() for feature in numeric)
            & pl.col("b0v2_asset_identity").is_not_null()
        ).alias("b0_complete"),
        pl.col("drop_reason").alias("b0_missing_reason"),
    )


def apply_b2_availability_sidecar(
    canonical: pl.DataFrame,
    sidecar: pl.DataFrame,
    *,
    canonical_variant: str,
) -> pl.DataFrame:
    """Mask delayed-source B2 rows as missing, never as genuine zero activity."""
    required_canonical = {
        "origin_id",
        "b2v2_max_created_at_utc",
        "b2v2_cutoff_utc",
        *B2_FEATURE_NAMES,
    }
    required_sidecar = {
        "canonical_variant",
        "origin_id",
        "row_status",
        "eligible_for_corrected_pit_panel",
        "source_temporal_state",
    }
    if not required_canonical.issubset(canonical.columns) or not required_sidecar.issubset(
        sidecar.columns
    ):
        raise ValueError("B1V3_B2_AVAILABILITY_SCHEMA_INVALID")
    if canonical["origin_id"].n_unique() != canonical.height:
        raise ValueError("B1V3_B2_CANONICAL_DUPLICATE_ORIGIN")
    selected = sidecar.filter(pl.col("canonical_variant") == canonical_variant).select(
        "origin_id",
        pl.col("row_status").alias("b2v2_availability_status"),
        pl.col("eligible_for_corrected_pit_panel").alias(
            "b2v2_availability_eligible"
        ),
        "source_temporal_state",
    )
    if selected["origin_id"].n_unique() != selected.height:
        raise ValueError("B1V3_B2_SIDECAR_DUPLICATE_ORIGIN")
    frame = canonical.join(selected, on="origin_id", how="left", validate="1:1")
    if frame["b2v2_availability_eligible"].null_count():
        raise ValueError("B1V3_B2_SIDECAR_ORIGIN_MISSING")
    frame = frame.with_columns(
        pl.when(pl.col("b2v2_availability_eligible"))
        .then(pl.col(feature))
        .otherwise(None)
        .cast(pl.Float64)
        .alias(feature)
        for feature in B2_FEATURE_NAMES
    )
    if frame.filter(
        ~pl.col("b2v2_availability_eligible")
        & pl.any_horizontal(pl.col(feature).is_not_null() for feature in B2_FEATURE_NAMES)
    ).height:
        raise ValueError("B1V3_B2_EXCLUSION_NOT_NULL")
    if frame.filter(
        pl.col("b2v2_availability_eligible")
        & pl.col("b2v2_max_created_at_utc").is_not_null()
        & (pl.col("b2v2_max_created_at_utc") > pl.col("b2v2_cutoff_utc"))
    ).height:
        raise ValueError("B1V3_B2_FUTURE_CREATED_AT")
    return frame


def _component_columns(frame: pl.DataFrame, allowed: set[str]) -> list[str]:
    return [column for column in frame.columns if column == "origin_id" or column in allowed]


def assemble_predictor_panel(
    *,
    origins: pl.DataFrame,
    b0: pl.DataFrame,
    b1: pl.DataFrame,
    b2: pl.DataFrame,
) -> pl.DataFrame:
    """Left-join nested predictor sets while retaining every canonical origin."""
    for name, frame in (("ORIGINS", origins), ("B0", b0), ("B1", b1), ("B2", b2)):
        if "origin_id" not in frame.columns or frame["origin_id"].n_unique() != frame.height:
            raise ValueError(f"B1V3_PANEL_{name}_IDENTITY_INVALID")
    b0_allowed = {
        *B0V2_FEATURES,
        "b0_complete",
        "b0_missing_reason",
        "max_predictor_available_at_utc",
    }
    b1_allowed = {
        *B1V3_FEATURES,
        "b1v3a_complete",
        "b1v3b_complete",
        "b1v3c_complete",
        "b1v3_missing_reason",
        "max_sip_timestamp_ns",
        "source_request_hashes",
    }
    b2_allowed = {
        *B2_FEATURE_NAMES,
        "b2v2_availability_eligible",
        "b2v2_availability_status",
        "source_temporal_state",
        "b2v2_max_created_at_utc",
        "b2v2_cutoff_utc",
    }
    b1_prepared = b1
    if "b1v3_missing_reason" not in b1_prepared.columns:
        b1_prepared = b1_prepared.with_columns(
            pl.lit(None, dtype=pl.String).alias("b1v3_missing_reason")
        )
    panel = (
        origins.join(
            b0.select(_component_columns(b0, b0_allowed)).with_columns(
                pl.lit(True).alias("_b0_row_present")
            ),
            on="origin_id",
            how="left",
            validate="1:1",
        )
        .join(
            b1_prepared.select(_component_columns(b1_prepared, b1_allowed)).with_columns(
                pl.lit(True).alias("_b1_row_present")
            ),
            on="origin_id",
            how="left",
            validate="1:1",
        )
        .join(
            b2.select(_component_columns(b2, b2_allowed)).with_columns(
                pl.lit(True).alias("_b2_row_present")
            ),
            on="origin_id",
            how="left",
            validate="1:1",
        )
        .with_columns(
            pl.col("b0_complete").fill_null(False),
            pl.col("b1v3a_complete").fill_null(False),
            pl.col("b1v3b_complete").fill_null(False),
            pl.col("b1v3c_complete").fill_null(False),
            pl.col("b2v2_availability_eligible").fill_null(False),
            pl.when(pl.col("_b0_row_present").is_null())
            .then(pl.lit("B0_SOURCE_ROW_MISSING"))
            .otherwise(pl.col("b0_missing_reason"))
            .alias("b0_missing_reason"),
            pl.when(pl.col("_b1_row_present").is_null())
            .then(pl.lit("B1V3_SOURCE_ROW_MISSING"))
            .otherwise(pl.col("b1v3_missing_reason"))
            .alias("b1v3_missing_reason"),
            pl.when(pl.col("_b2_row_present").is_null())
            .then(pl.lit("B2_SOURCE_ROW_MISSING"))
            .otherwise(pl.col("b2v2_availability_status"))
            .alias("b2v2_availability_status"),
        )
        .drop("_b0_row_present", "_b1_row_present", "_b2_row_present")
        .sort("session_date", "forecast_origin_utc", "asset")
    )
    if panel.height != origins.height or panel["origin_id"].n_unique() != panel.height:
        raise ValueError("B1V3_PANEL_ORIGIN_PRESERVATION_FAILURE")
    if "max_predictor_available_at_utc" in panel.columns and panel.filter(
        pl.col("max_predictor_available_at_utc").is_not_null()
        & (pl.col("max_predictor_available_at_utc") > pl.col("forecast_origin_utc"))
    ).height:
        raise ValueError("B1V3_PANEL_FUTURE_B0")
    if "max_sip_timestamp_ns" in panel.columns and panel.filter(
        pl.col("max_sip_timestamp_ns").is_not_null()
        & (pl.col("max_sip_timestamp_ns") > pl.col("forecast_origin_ns"))
    ).height:
        raise ValueError("B1V3_PANEL_FUTURE_B1")
    if panel.filter(
        pl.col("b2v2_max_created_at_utc").is_not_null()
        & (pl.col("b2v2_max_created_at_utc") > pl.col("b2v2_cutoff_utc"))
    ).height:
        raise ValueError("B1V3_PANEL_FUTURE_B2")
    lowered = tuple(column.lower() for column in panel.columns)
    if any(
        fragment in column
        for fragment in _FORBIDDEN_COLUMN_FRAGMENTS
        for column in lowered
    ):
        raise ValueError("B1V3_PANEL_TARGET_COLUMN_FORBIDDEN")
    return panel
