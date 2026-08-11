"""Target-blind common B0/B1/B2 predictor inputs under the PIT v2.2 contract.

This module deliberately does not accept outcomes, forecasts, losses, model
objects, or evaluation artefacts.  It is a one-way preparation layer for a
future, separately authorised analysis and must never be used to reconcile a
sealed result generated before the v2.2 B2 availability correction.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any

import polars as pl

from mds650.phase6 import (
    B0V2_FEATURES,
    B1V2A_FEATURES,
    B1V2B_FEATURES,
    B1V2C_FEATURES,
    B2V2_FEATURES,
    build_b0v2_features,
)

B2_PRIMARY_VARIANT = "primary_5m_60s"
KEY_COLUMNS: tuple[str, ...] = (
    "origin_id",
    "asset",
    "session_date",
    "forecast_origin_utc",
)
_FORBIDDEN_EXACT = frozenset({"rv30", "qlike", "target", "prediction", "outcome"})
_FORBIDDEN_PREFIXES = ("rv30_", "target_", "prediction_", "outcome_")


def build_target_blind_b0_v22(
    bars: pl.DataFrame,
    origins: pl.DataFrame,
    *,
    delay_minutes: int = 1,
) -> pl.DataFrame:
    """Build B0 predictors while deliberately excluding the RV30 target.

    Parameters
    ----------
    bars:
        FMP one-minute bars carrying registered availability timestamps.
    origins:
        Canonical forecast origins with no outcome fields.
    delay_minutes:
        Registered FMP conservative availability rule, either one or two
        minutes.

    Returns
    -------
    polars.DataFrame
        One target-free B0 row per origin.  No target, forecast, loss, or model
        field is returned.

    Raises
    ------
    ValueError
        If an outcome-like column is supplied or a B0 PIT invariant fails.

    Notes
    -----
    ``build_b0v2_features`` retains an internal null target placeholder even
    with ``include_target=False`` for backwards-compatible schemas.  This
    wrapper removes it before returning so callers cannot accidentally consume
    an outcome-like column.
    """
    _assert_target_blind_columns({"bars": bars, "origins": origins})
    source = build_b0v2_features(
        bars,
        origins,
        delay_minutes=delay_minutes,
        include_target=False,
    )
    _require_columns(
        "b0_source",
        source,
        (*KEY_COLUMNS, "max_predictor_available_at_utc", "drop_reason", *B0V2_FEATURES),
    )
    _assert_unique_origin_ids("b0_source", source)
    return (
        source.with_columns(
            pl.when(pl.col("drop_reason") == "RV30_ORIGIN_CLOSE_MISSING")
            .then(pl.lit("B0V2_ANCHOR_CLOSE_MISSING"))
            .otherwise(pl.col("drop_reason"))
            .alias("b0v2_predictor_missing_reason")
        )
        .select(
            *KEY_COLUMNS,
            *B0V2_FEATURES,
            pl.col("max_predictor_available_at_utc").alias(
                "b0v2_max_predictor_available_at_utc"
            ),
            "b0v2_predictor_missing_reason",
        )
        .sort("origin_id")
    )


def adapt_b1q_source_to_v22(
    origins: pl.DataFrame,
    source: pl.DataFrame,
) -> pl.DataFrame:
    """Adapt target-free B1Q ATM/skew/term states into nested v2.2 features.

    Parameters
    ----------
    origins:
        Canonical target-free forecast origins.
    source:
        One Massive B1Q source-state row per origin.  The source must already
        enforce SIP-as-of-origin, the 60-second freshness filter, and the
        primary relative-spread filter.

    Returns
    -------
    polars.DataFrame
        B1v2a/B1v2b/B1v2c features, nested completeness flags, and PIT
        diagnostics.  Changes are only populated when the required earlier
        state exists; they are never imputed as zero.

    Raises
    ------
    ValueError
        If keys are inconsistent, a future quote is supplied, an outcome field
        is present, or nested B1 completion is violated.

    Notes
    -----
    The source-time 60/300-second Massive re-selection remains a separately
    audited sensitivity.  This adapter preserves the registered primary B1Q
    state: last SIP quote at or before the forecast origin, subject to the
    source's 60-second quote-age quality filter.
    """
    _assert_target_blind_columns({"origins": origins, "b1_source": source})
    _require_columns("origins", origins, KEY_COLUMNS)
    _require_columns(
        "b1_source",
        source,
        (
            *KEY_COLUMNS,
            "b1a_complete",
            "b1b_complete",
            "b1c_complete",
            "b1q_atm_iv",
            "b1q_skew",
            "b1q_term_structure",
            "b1q_max_sip_timestamp_ns",
            "b1q_quote_not_after_origin",
            "b1q_pit_evidence_valid",
        ),
    )
    _assert_key_alignment({"origins": origins, "b1_source": source})

    levels: dict[tuple[str, str, datetime], dict[str, Any]] = {}
    for row in source.select(
        *KEY_COLUMNS,
        "b1a_complete",
        "b1b_complete",
        "b1c_complete",
        "b1q_atm_iv",
        "b1q_skew",
        "b1q_term_structure",
        "b1q_max_sip_timestamp_ns",
        "b1q_quote_not_after_origin",
        "b1q_pit_evidence_valid",
    ).iter_rows(named=True):
        origin = _require_utc_datetime(row["forecast_origin_utc"], "B1Q_ORIGIN_TIMESTAMP_INVALID")
        origin_ns = int(origin.timestamp() * 1_000_000_000)
        max_sip = _optional_int(row["b1q_max_sip_timestamp_ns"])
        if max_sip is not None and max_sip > origin_ns:
            raise ValueError("TARGET_BLIND_V22_B1_FUTURE_QUOTE")
        source_pit_valid = bool(row["b1q_pit_evidence_valid"]) and bool(
            row["b1q_quote_not_after_origin"]
        ) and max_sip is not None
        atm = _positive_float_or_none(row["b1q_atm_iv"])
        skew = _finite_float_or_none(row["b1q_skew"])
        term = _term_values(row["b1q_term_structure"])
        key = (str(row["asset"]), str(row["session_date"]), origin)
        levels[key] = {
            **{column: row[column] for column in KEY_COLUMNS},
            "forecast_origin_ns": origin_ns,
            "max_sip_timestamp_ns": max_sip,
            "source_pit_valid": source_pit_valid,
            "atm": atm if bool(row["b1a_complete"]) and source_pit_valid else None,
            "skew": (
                skew
                if bool(row["b1b_complete"])
                and bool(row["b1a_complete"])
                and source_pit_valid
                else None
            ),
            "term_short_to_medium": (
                term["short_to_medium"]
                if bool(row["b1c_complete"])
                and bool(row["b1b_complete"])
                and source_pit_valid
                else None
            ),
            "term_medium_to_long": (
                term["medium_to_long"]
                if bool(row["b1c_complete"])
                and bool(row["b1b_complete"])
                and source_pit_valid
                else None
            ),
        }

    output: list[dict[str, Any]] = []
    for key in sorted(levels, key=lambda item: (item[0], item[1], item[2])):
        row = levels[key]
        origin = _require_utc_datetime(row["forecast_origin_utc"], "B1Q_ORIGIN_TIMESTAMP_INVALID")
        prior_5 = levels.get((key[0], key[1], origin - timedelta(minutes=5)))
        prior_30 = levels.get((key[0], key[1], origin - timedelta(minutes=30)))
        atm = row["atm"]
        atm_change_5 = _difference(atm, prior_5, "atm")
        atm_change_30 = _difference(atm, prior_30, "atm")
        b1a_complete = all(value is not None for value in (atm, atm_change_5, atm_change_30))
        skew = row["skew"]
        skew_change_30 = _difference(skew, prior_30, "skew")
        b1b_complete = bool(b1a_complete) and all(
            value is not None for value in (skew, skew_change_30)
        )
        short_to_medium = row["term_short_to_medium"]
        medium_to_long = row["term_medium_to_long"]
        short_change = _difference(short_to_medium, prior_30, "term_short_to_medium")
        medium_change = _difference(medium_to_long, prior_30, "term_medium_to_long")
        b1c_complete = bool(b1b_complete) and all(
            value is not None
            for value in (
                short_to_medium,
                medium_to_long,
                short_change,
                medium_change,
            )
        )
        output.append(
            {
                **{column: row[column] for column in KEY_COLUMNS},
                "forecast_origin_ns": row["forecast_origin_ns"],
                "max_sip_timestamp_ns": row["max_sip_timestamp_ns"],
                "b1v2_atm_iv_30_60_dte": atm,
                "b1v2_atm_iv_change_5m": atm_change_5,
                "b1v2_atm_iv_change_30m": atm_change_30,
                "b1v2_skew_symmetric_moneyness": skew,
                "b1v2_skew_change_30m": skew_change_30,
                "b1v2_term_short_to_medium": short_to_medium,
                "b1v2_term_medium_to_long": medium_to_long,
                "b1v2_term_short_to_medium_change_30m": short_change,
                "b1v2_term_medium_to_long_change_30m": medium_change,
                "b1v2a_complete": b1a_complete,
                "b1v2b_complete": b1b_complete,
                "b1v2c_complete": b1c_complete,
                "b1q_source_time_rule": "SIP_ASOF_ORIGIN_MAX_AGE_60S",
                "b1v2_predictor_missing_reason": _b1_missing_reason(
                    source_pit_valid=bool(row["source_pit_valid"]),
                    atm=atm,
                    atm_change_5=atm_change_5,
                    atm_change_30=atm_change_30,
                ),
            }
        )
    frame = pl.DataFrame(output, infer_schema_length=None, strict=False).sort("origin_id")
    if frame.filter(pl.col("b1v2b_complete") & ~pl.col("b1v2a_complete")).height:
        raise ValueError("TARGET_BLIND_V22_B1_NESTED_INVARIANT_FAILURE")
    if frame.filter(pl.col("b1v2c_complete") & ~pl.col("b1v2b_complete")).height:
        raise ValueError("TARGET_BLIND_V22_B1_NESTED_INVARIANT_FAILURE")
    return frame


def apply_b2_availability_mask_v22(
    b2: pl.DataFrame,
    availability: pl.DataFrame,
    *,
    canonical_variant: str = B2_PRIMARY_VARIANT,
) -> pl.DataFrame:
    """Mask B2 rows whose raw activity cannot be treated as PIT-available.

    Parameters
    ----------
    b2:
        Target-free normalized B2v2 rows for one origin grid.
    availability:
        v2.2 per-origin availability sidecar covering all registered variants.
    canonical_variant:
        Variant used by the primary information set.  The default is five
        minutes with the registered 60-second operational availability proxy.

    Returns
    -------
    polars.DataFrame
        B2 data augmented with v2.2 availability evidence.  Features in an
        excluded or insufficient-history row are set to null rather than zero.

    Raises
    ------
    ValueError
        If keys, schema, variant coverage, or target-blind constraints fail.

    Notes
    -----
    A delayed source record is an exclusion, not proof of no activity.  This
    function therefore prevents the old zero-coding failure from propagating
    into a future model matrix.
    """
    _assert_target_blind_columns({"b2": b2, "availability": availability})
    _require_columns(
        "b2",
        b2,
        (
            *KEY_COLUMNS,
            *B2V2_FEATURES,
            "b2v2_complete",
            "b2v2_cutoff_utc",
            "b2v2_max_created_at_utc",
        ),
    )
    _require_columns(
        "availability",
        availability,
        (
            *KEY_COLUMNS,
            "canonical_variant",
            "row_status",
            "eligible_for_corrected_pit_panel",
        ),
    )
    selected = availability.filter(pl.col("canonical_variant") == canonical_variant)
    if selected.is_empty():
        raise ValueError("TARGET_BLIND_V22_B2_VARIANT_MISSING")
    _assert_key_alignment({"b2": b2, "availability": selected})
    selected = selected.select(
        "origin_id",
        pl.col("row_status").alias("b2v2_availability_status"),
        pl.col("eligible_for_corrected_pit_panel").alias("b2v2_availability_eligible"),
    )
    joined = b2.join(selected, on="origin_id", how="left", validate="1:1")
    valid_source = (
        pl.col("b2v2_complete").fill_null(False)
        & pl.col("b2v2_availability_eligible").fill_null(False)
    )
    mask_expressions = [
        pl.when(valid_source)
        .then(pl.col(feature).cast(pl.Float64))
        .otherwise(pl.lit(None, dtype=pl.Float64))
        .alias(feature)
        for feature in B2V2_FEATURES
    ]
    return (
        joined.with_columns(mask_expressions)
        .with_columns(
            valid_source.alias("b2v2_corrected_pit_complete"),
            pl.when(~pl.col("b2v2_availability_eligible").fill_null(False))
            .then(pl.lit("B2V2_DELAYED_OR_UNAVAILABLE_ACTIVITY"))
            .when(~pl.col("b2v2_complete").fill_null(False))
            .then(pl.lit("B2V2_NORMALIZATION_HISTORY_INSUFFICIENT"))
            .otherwise(pl.lit(None, dtype=pl.String))
            .alias("b2v2_predictor_missing_reason"),
        )
        .sort("origin_id")
    )


def build_target_blind_common_predictor_panel_v22(
    origins: pl.DataFrame,
    b0: pl.DataFrame,
    b1: pl.DataFrame,
    b2: pl.DataFrame,
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Join target-free B0, B1Q, and v2.2-masked B2 on one origin grid.

    Parameters
    ----------
    origins:
        Canonical forecast-origin keys, without outcomes.
    b0:
        Target-free B0 rows built under the registered FMP timing rule.
    b1:
        Target-free B1Q rows adapted by :func:`adapt_b1q_source_to_v22`.
    b2:
        Target-free B2 rows masked by :func:`apply_b2_availability_mask_v22`.

    Returns
    -------
    tuple[polars.DataFrame, polars.DataFrame]
        Complete origin-preserving predictor panel followed by the subset with
        B0, B1a, and B2 primary predictor completeness.  Neither frame carries
        a target, forecast, loss, model output, or evaluation result.

    Raises
    ------
    ValueError
        If source keys differ, a PIT timestamp is after its origin, a nested B1
        invariant fails, or an outcome-like column is observed.
    """
    _assert_target_blind_columns(
        {"origins": origins, "b0": b0, "b1": b1, "b2": b2}
    )
    _require_columns("origins", origins, KEY_COLUMNS)
    _require_columns(
        "b0",
        b0,
        (
            *KEY_COLUMNS,
            *B0V2_FEATURES,
            "b0v2_max_predictor_available_at_utc",
            "b0v2_predictor_missing_reason",
        ),
    )
    _require_columns(
        "b1",
        b1,
        (
            *KEY_COLUMNS,
            "forecast_origin_ns",
            "max_sip_timestamp_ns",
            *B1V2A_FEATURES,
            *B1V2B_FEATURES,
            *B1V2C_FEATURES,
            "b1v2a_complete",
            "b1v2b_complete",
            "b1v2c_complete",
        ),
    )
    _require_columns(
        "b2",
        b2,
        (
            *KEY_COLUMNS,
            *B2V2_FEATURES,
            "b2v2_corrected_pit_complete",
            "b2v2_availability_eligible",
            "b2v2_cutoff_utc",
            "b2v2_max_created_at_utc",
            "b2v2_predictor_missing_reason",
        ),
    )
    _assert_key_alignment({"origins": origins, "b0": b0, "b1": b1, "b2": b2})
    if b0.filter(
        pl.col("b0v2_max_predictor_available_at_utc").is_not_null()
        & (pl.col("b0v2_max_predictor_available_at_utc") > pl.col("forecast_origin_utc"))
    ).height:
        raise ValueError("TARGET_BLIND_V22_B0_AFTER_ORIGIN")
    if b1.filter(
        pl.col("max_sip_timestamp_ns").is_not_null()
        & (pl.col("max_sip_timestamp_ns") > pl.col("forecast_origin_ns"))
    ).height:
        raise ValueError("TARGET_BLIND_V22_B1_AFTER_ORIGIN")
    if b2.filter(
        pl.col("b2v2_cutoff_utc").is_not_null()
        & (pl.col("b2v2_cutoff_utc") > pl.col("forecast_origin_utc"))
    ).height:
        raise ValueError("TARGET_BLIND_V22_B2_CUTOFF_AFTER_ORIGIN")
    if b2.filter(
        pl.col("b2v2_max_created_at_utc").is_not_null()
        & pl.col("b2v2_cutoff_utc").is_not_null()
        & (pl.col("b2v2_max_created_at_utc") > pl.col("b2v2_cutoff_utc"))
        & pl.col("b2v2_corrected_pit_complete").fill_null(False)
    ).height:
        raise ValueError("TARGET_BLIND_V22_B2_AFTER_CUTOFF")
    if b1.filter(pl.col("b1v2b_complete") & ~pl.col("b1v2a_complete")).height:
        raise ValueError("TARGET_BLIND_V22_B1_NESTED_INVARIANT_FAILURE")
    if b1.filter(pl.col("b1v2c_complete") & ~pl.col("b1v2b_complete")).height:
        raise ValueError("TARGET_BLIND_V22_B1_NESTED_INVARIANT_FAILURE")

    panel = origins.select(*KEY_COLUMNS)
    for source in (b0, b1, b2):
        additions = [column for column in source.columns if column not in KEY_COLUMNS]
        panel = panel.join(
            source.select("origin_id", *additions),
            on="origin_id",
            how="left",
            validate="1:1",
        )
    numeric_b0 = [feature for feature in B0V2_FEATURES if feature != "b0v2_asset_identity"]
    b0_complete = pl.all_horizontal(
        [pl.col(feature).cast(pl.Float64).is_finite() for feature in numeric_b0]
        + [
            pl.col("b0v2_asset_identity").is_not_null(),
            pl.col("b0v2_asset_identity") != "",
            pl.col("b0v2_max_predictor_available_at_utc").is_not_null(),
            pl.col("b0v2_max_predictor_available_at_utc") <= pl.col("forecast_origin_utc"),
            pl.col("b0v2_predictor_missing_reason").is_null(),
        ]
    ).fill_null(False)
    b1a_complete = b0_complete & pl.all_horizontal(
        [pl.col(feature).cast(pl.Float64).is_finite() for feature in B1V2A_FEATURES]
        + [
            pl.col("b1v2a_complete").fill_null(False),
            pl.col("max_sip_timestamp_ns").is_not_null(),
            pl.col("max_sip_timestamp_ns") <= pl.col("forecast_origin_ns"),
        ]
    ).fill_null(False)
    b1b_complete = b1a_complete & pl.all_horizontal(
        [pl.col(feature).cast(pl.Float64).is_finite() for feature in B1V2B_FEATURES]
        + [pl.col("b1v2b_complete").fill_null(False)]
    ).fill_null(False)
    b1c_complete = b1b_complete & pl.all_horizontal(
        [pl.col(feature).cast(pl.Float64).is_finite() for feature in B1V2C_FEATURES]
        + [pl.col("b1v2c_complete").fill_null(False)]
    ).fill_null(False)
    b2_complete = b1a_complete & pl.all_horizontal(
        [pl.col(feature).cast(pl.Float64).is_finite() for feature in B2V2_FEATURES]
        + [
            pl.col("b2v2_corrected_pit_complete").fill_null(False),
            pl.col("b2v2_availability_eligible").fill_null(False),
            pl.col("b2v2_cutoff_utc").is_not_null(),
            pl.col("b2v2_cutoff_utc") <= pl.col("forecast_origin_utc"),
            pl.col("b2v2_max_created_at_utc").is_null()
            | (pl.col("b2v2_max_created_at_utc") <= pl.col("b2v2_cutoff_utc")),
        ]
    ).fill_null(False)
    panel = panel.with_columns(
        b0_complete.alias("b0v2_predictor_complete"),
        b1a_complete.alias("b1v2a_predictor_complete"),
        b1b_complete.alias("b1v2b_predictor_complete"),
        b1c_complete.alias("b1v2c_predictor_complete"),
        b2_complete.alias("b2v2_predictor_complete"),
    ).with_columns(
        pl.col("b2v2_predictor_complete").alias("common_predictor_complete")
    ).with_columns(
        pl.when(~pl.col("b0v2_predictor_complete"))
        .then(pl.lit("B0V2_PREDICTOR_MISSING_OR_PIT_FAILURE"))
        .when(~pl.col("b1v2a_predictor_complete"))
        .then(pl.lit("B1V2A_PREDICTOR_MISSING_OR_PIT_FAILURE"))
        .when(~pl.col("b2v2_predictor_complete"))
        .then(
            pl.coalesce(
                [
                    pl.col("b2v2_predictor_missing_reason"),
                    pl.lit("B2V2_PREDICTOR_MISSING_OR_PIT_FAILURE"),
                ]
            )
        )
        .otherwise(pl.lit("NONE"))
        .alias("predictor_exclusion_reason")
    ).sort("origin_id")
    _assert_target_blind_columns({"common_panel": panel})
    return panel, panel.filter(pl.col("common_predictor_complete"))


def summarize_target_blind_common_predictor_panel_v22(panel: pl.DataFrame) -> dict[str, Any]:
    """Return non-evaluative coverage metadata for a target-free panel.

    Parameters
    ----------
    panel:
        Output from :func:`build_target_blind_common_predictor_panel_v22`.

    Returns
    -------
    dict[str, Any]
        Deterministic counts and completeness rates only.  The result contains
        no outcomes, predictions, losses, model fits, or statistical claims.

    Raises
    ------
    ValueError
        If the common-panel completeness fields are absent.
    """
    required = {
        "asset",
        "session_date",
        "b0v2_predictor_complete",
        "b1v2a_predictor_complete",
        "b1v2b_predictor_complete",
        "b1v2c_predictor_complete",
        "b2v2_predictor_complete",
        "b2v2_availability_eligible",
        "b2v2_availability_status",
        "b2v2_corrected_pit_complete",
        "common_predictor_complete",
        "predictor_exclusion_reason",
    }
    _require_columns("panel", panel, tuple(sorted(required)))
    _assert_target_blind_columns({"panel": panel})
    count = panel.height
    if count == 0:
        raise ValueError("TARGET_BLIND_V22_PANEL_EMPTY")
    complete_columns = (
        "b0v2_predictor_complete",
        "b1v2a_predictor_complete",
        "b1v2b_predictor_complete",
        "b1v2c_predictor_complete",
        "b2v2_predictor_complete",
        "common_predictor_complete",
    )
    counts = {
        column: int(panel.filter(pl.col(column)).height) for column in complete_columns
    }
    return {
        "schema_version": "target-blind-common-predictor-panel-v2.2",
        "status": "PASS_TARGET_BLIND_INPUTS_RECONCILIATION_REMAINS_BLOCKED",
        "scope": "offline_target_blind_predictor_construction_only",
        "no_target_or_metric_payload_read": True,
        "model_fit_performed": False,
        "row_count": count,
        "asset_count": int(panel["asset"].n_unique()),
        "session_count": int(panel["session_date"].n_unique()),
        "completion_counts": counts,
        "completion_rates": {
            column: counts[column] / count for column in complete_columns
        },
        "exclusion_reason_counts": {
            str(row["predictor_exclusion_reason"]): int(row["len"])
            for row in panel.group_by("predictor_exclusion_reason")
            .len()
            .sort("predictor_exclusion_reason")
            .iter_rows(named=True)
        },
        "b2_availability": {
            "eligible_row_count": int(
                panel.filter(pl.col("b2v2_availability_eligible").fill_null(False)).height
            ),
            "excluded_row_count": int(
                panel.filter(~pl.col("b2v2_availability_eligible").fill_null(False)).height
            ),
            "corrected_pit_complete_row_count": int(
                panel.filter(pl.col("b2v2_corrected_pit_complete").fill_null(False)).height
            ),
            "row_status_counts": {
                str(row["b2v2_availability_status"]): int(row["len"])
                for row in panel.group_by("b2v2_availability_status")
                .len()
                .sort("b2v2_availability_status")
                .iter_rows(named=True)
            },
        },
        "safe_to_reconcile_existing_results": "NO",
    }


def _assert_target_blind_columns(frames: Mapping[str, pl.DataFrame]) -> None:
    """Fail closed if any input or output exposes an outcome-like column."""
    for label, frame in frames.items():
        for column in frame.columns:
            normalised = column.lower()
            if normalised in _FORBIDDEN_EXACT or normalised.startswith(_FORBIDDEN_PREFIXES):
                raise ValueError(f"TARGET_BLIND_V22_FORBIDDEN_COLUMN:{label}:{column}")


def _require_columns(label: str, frame: pl.DataFrame, required: tuple[str, ...]) -> None:
    """Require a named target-free frame schema."""
    missing = sorted(set(required) - set(frame.columns))
    if missing:
        raise ValueError(f"TARGET_BLIND_V22_REQUIRED_COLUMNS_MISSING:{label}:{','.join(missing)}")


def _assert_unique_origin_ids(label: str, frame: pl.DataFrame) -> None:
    """Require exactly one non-null row per origin identifier."""
    if frame["origin_id"].null_count() or frame["origin_id"].n_unique() != frame.height:
        raise ValueError(f"TARGET_BLIND_V22_DUPLICATE_ORIGIN:{label}")


def _assert_key_alignment(frames: Mapping[str, pl.DataFrame]) -> None:
    """Require identical ordered canonical key sets across target-free inputs."""
    canonical: pl.DataFrame | None = None
    for label, frame in frames.items():
        _require_columns(label, frame, KEY_COLUMNS)
        _assert_unique_origin_ids(label, frame)
        keys = frame.select(*KEY_COLUMNS).sort("origin_id")
        if canonical is None:
            canonical = keys
        elif not keys.equals(canonical):
            raise ValueError(f"TARGET_BLIND_V22_ORIGIN_KEY_MISMATCH:{label}")


def _require_utc_datetime(value: object, code: str) -> datetime:
    """Return a timezone-aware timestamp or fail closed."""
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError(code)
    return value


def _optional_int(value: object) -> int | None:
    """Coerce a scalar integer without accepting booleans."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    if isinstance(value, float) and math.isfinite(value) and value.is_integer():
        return int(value)
    return None


def _finite_float_or_none(value: object) -> float | None:
    """Return a finite float or ``None`` without imputation."""
    try:
        converted = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return converted if math.isfinite(converted) else None


def _positive_float_or_none(value: object) -> float | None:
    """Return a strictly positive finite float or ``None``."""
    converted = _finite_float_or_none(value)
    return converted if converted is not None and converted > 0 else None


def _term_values(value: object) -> dict[str, float | None]:
    """Extract documented term-structure slopes without imputation."""
    mapping = value if isinstance(value, Mapping) else {}
    return {
        "short_to_medium": _finite_float_or_none(mapping.get("short_to_medium")),
        "medium_to_long": _finite_float_or_none(mapping.get("medium_to_long")),
    }


def _difference(
    current: float | None,
    prior: Mapping[str, Any] | None,
    field: str,
) -> float | None:
    """Return a same-session difference only when both observations exist."""
    if current is None or prior is None:
        return None
    previous = _finite_float_or_none(prior.get(field))
    return current - previous if previous is not None else None


def _b1_missing_reason(
    *,
    source_pit_valid: bool,
    atm: float | None,
    atm_change_5: float | None,
    atm_change_30: float | None,
) -> str | None:
    """Classify the first B1a non-completion cause without outcomes."""
    if not source_pit_valid:
        return "B1Q_SOURCE_OR_PIT_INVALID"
    if atm is None:
        return "B1Q_ATM_IV_MISSING"
    if atm_change_5 is None:
        return "B1V2_ATM_5M_HISTORY_MISSING"
    if atm_change_30 is None:
        return "B1V2_ATM_30M_HISTORY_MISSING"
    return None
