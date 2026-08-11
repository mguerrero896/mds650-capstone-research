"""Tests for the target-blind v2.2 common predictor panel."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import polars as pl
import pytest

from mds650.target_blind_panel_v22 import (
    B2_PRIMARY_VARIANT,
    adapt_b1q_source_to_v22,
    apply_b2_availability_mask_v22,
    build_target_blind_b0_v22,
    build_target_blind_common_predictor_panel_v22,
    summarize_target_blind_common_predictor_panel_v22,
)


def _origin_rows() -> pl.DataFrame:
    """Return target-free origins with enough same-session B1 history."""
    start = datetime(2026, 1, 5, 14, 30, tzinfo=UTC)
    minutes = [0, 5, 25, 30, 35]
    return pl.DataFrame(
        {
            "origin_id": [f"AAPL-{index}" for index in range(1, 6)],
            "asset": ["AAPL"] * 5,
            "session_date": ["2026-01-05"] * 5,
            "forecast_origin_utc": [
                start + timedelta(minutes=minute) for minute in minutes
            ],
        }
    )


def _b0_rows(origins: pl.DataFrame) -> pl.DataFrame:
    """Return valid target-free B0 rows for the origin fixture."""
    return origins.with_columns(
        [
            pl.lit(1.0).alias("b0v2_log_spot"),
            pl.lit(0.1).alias("b0v2_underlying_return_5m"),
            pl.lit(0.1).alias("b0v2_underlying_rv_5m"),
            pl.lit(0.2).alias("b0v2_underlying_rv_30m"),
            pl.lit(1.0).alias("b0v2_log_dollar_volume_5m"),
            pl.lit(0.1).alias("b0v2_spy_return_5m"),
            pl.lit(0.2).alias("b0v2_spy_rv_30m"),
            pl.lit(0.1).alias("b0v2_qqq_return_5m"),
            pl.lit(0.2).alias("b0v2_qqq_rv_30m"),
            pl.lit(0.5).alias("b0v2_session_sine"),
            pl.lit(0.5).alias("b0v2_session_cosine"),
            pl.lit("AAPL").alias("b0v2_asset_identity"),
            pl.col("forecast_origin_utc").alias(
                "b0v2_max_predictor_available_at_utc"
            ),
            pl.lit(None, dtype=pl.String).alias("b0v2_predictor_missing_reason"),
        ]
    )


def _b1_source(origins: pl.DataFrame) -> pl.DataFrame:
    """Return a valid nested B1Q source fixture."""
    return origins.with_columns(
        [
            pl.lit(True).alias("b1a_complete"),
            pl.lit(True).alias("b1b_complete"),
            pl.lit(True).alias("b1c_complete"),
            pl.lit(True).alias("b1q_pit_evidence_valid"),
            pl.lit(True).alias("b1q_quote_not_after_origin"),
            pl.col("forecast_origin_utc").dt.epoch("ns").alias(
                "b1q_max_sip_timestamp_ns"
            ),
            pl.Series(
                "b1q_atm_iv",
                [0.20 + (index * 0.01) for index in range(origins.height)],
            ),
            pl.Series(
                "b1q_skew",
                [0.01 + (index * 0.01) for index in range(origins.height)],
            ),
            pl.Series(
                "b1q_term_structure",
                [
                    {
                        "short_to_medium": 0.01 + (index * 0.01),
                        "medium_to_long": 0.02 + (index * 0.01),
                        "short_to_long": 0.03 + (index * 0.01),
                    }
                    for index in range(origins.height)
                ],
            ),
        ]
    )


def _b2_rows(origins: pl.DataFrame) -> pl.DataFrame:
    """Return valid normalized B2 rows for the origin fixture."""
    return origins.with_columns(
        [
            pl.lit(0.1).alias("b2v2_z_log_trade_count"),
            pl.lit(0.1).alias("b2v2_z_unique_contract_share"),
            pl.lit(0.1).alias("b2v2_z_log_mean_trade_premium"),
            pl.lit(0.1).alias("b2v2_z_log_max_trade_premium"),
            pl.lit(0.1).alias("b2v2_deviation_call_put_premium_imbalance"),
            pl.lit(0.1).alias(
                "b2v2_deviation_execution_side_premium_imbalance"
            ),
            pl.lit(0.1).alias("b2v2_z_repeated_contract_premium_share"),
            pl.lit(0.1).alias("b2v2_z_strike_concentration"),
            pl.lit(0.1).alias("b2v2_z_expiry_concentration"),
            pl.lit(True).alias("b2v2_complete"),
            (pl.col("forecast_origin_utc") - pl.duration(seconds=60)).alias(
                "b2v2_cutoff_utc"
            ),
            (pl.col("forecast_origin_utc") - pl.duration(seconds=90)).alias(
                "b2v2_max_created_at_utc"
            ),
        ]
    )


def _availability_rows(origins: pl.DataFrame) -> pl.DataFrame:
    """Return a target-free v2.2 availability sidecar fixture."""
    return origins.with_columns(
        [
            pl.lit(B2_PRIMARY_VARIANT).alias("canonical_variant"),
            pl.lit(True).alias("eligible_for_corrected_pit_panel"),
            pl.lit("PIT_USABLE_ELIGIBLE_ACTIVITY").alias("row_status"),
        ]
    )


def _b0_raw_bars() -> pl.DataFrame:
    """Return one target-free FMP fixture for one asset and market controls."""
    start = datetime(2026, 1, 5, 14, 0, tzinfo=UTC)
    rows: list[dict[str, object]] = []
    for asset_index, asset in enumerate(("AAPL", "SPY", "QQQ"), start=1):
        for minute in range(100):
            timestamp = start + timedelta(minutes=minute)
            rows.append(
                {
                    "asset": asset,
                    "session_date": "2026-01-05",
                    "bar_timestamp_raw_utc": timestamp,
                    "available_at_utc": timestamp + timedelta(minutes=1),
                    "close": 100.0 + (asset_index * 10.0) + (minute * 0.05),
                    "volume": 1_000.0 + minute,
                }
            )
    return pl.DataFrame(rows)


def test_target_blind_b0_strips_internal_target_placeholder() -> None:
    """The B0 wrapper keeps only predictor fields after a target-free build."""
    origin = pl.DataFrame(
        {
            "origin_id": ["AAPL-B0"],
            "asset": ["AAPL"],
            "session_date": ["2026-01-05"],
            "forecast_origin_utc": [datetime(2026, 1, 5, 15, 5, tzinfo=UTC)],
        }
    )

    result = build_target_blind_b0_v22(_b0_raw_bars(), origin)

    assert result.height == 1
    assert "rv30" not in result.columns
    assert not any(column.startswith("target_") for column in result.columns)
    assert (
        result["b0v2_max_predictor_available_at_utc"].item()
        <= result["forecast_origin_utc"].item()
    )


def test_target_blind_panel_is_complete_without_target_or_metric_columns() -> None:
    """A fully valid target-free fixture yields complete nested predictor sets."""
    origins = _origin_rows()
    b1 = adapt_b1q_source_to_v22(origins, _b1_source(origins))
    b2 = apply_b2_availability_mask_v22(
        _b2_rows(origins), _availability_rows(origins)
    )

    panel, eligible = build_target_blind_common_predictor_panel_v22(
        origins, _b0_rows(origins), b1, b2
    )

    assert panel.height == 5
    assert eligible.height == 2
    assert panel["b0v2_predictor_complete"].to_list() == [True] * 5
    assert panel["b1v2a_predictor_complete"].to_list() == [False, False, False, True, True]
    assert panel["b2v2_predictor_complete"].to_list() == [False, False, False, True, True]
    assert not {
        column
        for column in panel.columns
        if column.lower() in {"rv30", "qlike", "target", "prediction", "outcome"}
        or column.lower().startswith("target_")
    }


def test_b2_delay_exclusion_clears_features_and_blocks_common_completion() -> None:
    """A delayed raw-activity incident cannot be encoded as a usable zero."""
    origins = _origin_rows()
    availability = _availability_rows(origins).with_columns(
        pl.when(pl.col("origin_id") == "AAPL-5")
        .then(pl.lit(False))
        .otherwise(pl.col("eligible_for_corrected_pit_panel"))
        .alias("eligible_for_corrected_pit_panel"),
        pl.when(pl.col("origin_id") == "AAPL-5")
        .then(pl.lit("PIT_EXCLUDED_DELAYED_RAW_WINDOW_TRADES"))
        .otherwise(pl.col("row_status"))
        .alias("row_status"),
    )
    b2 = apply_b2_availability_mask_v22(_b2_rows(origins), availability)
    b1 = adapt_b1q_source_to_v22(origins, _b1_source(origins))

    panel, eligible = build_target_blind_common_predictor_panel_v22(
        origins, _b0_rows(origins), b1, b2
    )

    excluded = panel.filter(pl.col("origin_id") == "AAPL-5")
    assert excluded["b2v2_predictor_complete"].item() is False
    assert excluded["b2v2_z_log_trade_count"].item() is None
    assert (
        excluded["predictor_exclusion_reason"].item()
        == "B2V2_DELAYED_OR_UNAVAILABLE_ACTIVITY"
    )
    assert eligible["origin_id"].to_list() == ["AAPL-4"]


def test_target_blind_panel_rejects_outcome_column() -> None:
    """The target-free constructor fails closed when an outcome field is supplied."""
    origins = _origin_rows().with_columns(pl.lit(0.01).alias("rv30"))
    b1 = adapt_b1q_source_to_v22(_origin_rows(), _b1_source(_origin_rows()))
    b2 = apply_b2_availability_mask_v22(
        _b2_rows(_origin_rows()), _availability_rows(_origin_rows())
    )

    with pytest.raises(ValueError, match="TARGET_BLIND_V22_FORBIDDEN_COLUMN"):
        build_target_blind_common_predictor_panel_v22(
            origins, _b0_rows(_origin_rows()), b1, b2
        )


def test_b1_adapter_preserves_nested_completion_invariant() -> None:
    """B1c/B1b cannot be complete when the ATM history required by B1a is absent."""
    origins = _origin_rows()
    source = _b1_source(origins).with_columns(
        pl.when(pl.col("origin_id") == "AAPL-1")
        .then(pl.lit(False))
        .otherwise(pl.col("b1a_complete"))
        .alias("b1a_complete")
    )

    adapted = adapt_b1q_source_to_v22(origins, source)

    assert adapted.filter(
        pl.col("b1v2b_complete") & ~pl.col("b1v2a_complete")
    ).height == 0
    assert adapted.filter(
        pl.col("b1v2c_complete") & ~pl.col("b1v2b_complete")
    ).height == 0


def test_target_blind_panel_is_deterministic() -> None:
    """Identical target-free inputs yield byte-stable logical rows."""
    origins = _origin_rows()
    b1 = adapt_b1q_source_to_v22(origins, _b1_source(origins))
    b2 = apply_b2_availability_mask_v22(
        _b2_rows(origins), _availability_rows(origins)
    )
    first, _ = build_target_blind_common_predictor_panel_v22(
        origins, _b0_rows(origins), b1, b2
    )
    second, _ = build_target_blind_common_predictor_panel_v22(
        origins, _b0_rows(origins), b1, b2
    )

    assert first.equals(second)


def test_summary_is_non_evaluative_and_reports_availability_state() -> None:
    """The summary reports predictor availability rather than a market result."""
    origins = _origin_rows()
    b1 = adapt_b1q_source_to_v22(origins, _b1_source(origins))
    b2 = apply_b2_availability_mask_v22(
        _b2_rows(origins), _availability_rows(origins)
    )
    panel, _ = build_target_blind_common_predictor_panel_v22(
        origins, _b0_rows(origins), b1, b2
    )

    summary = summarize_target_blind_common_predictor_panel_v22(panel)

    assert summary["no_target_or_metric_payload_read"] is True
    assert summary["model_fit_performed"] is False
    assert summary["completion_counts"]["common_predictor_complete"] == 2
    assert summary["b2_availability"]["excluded_row_count"] == 0


def test_adapter_rejects_future_massive_quote() -> None:
    """A Massive SIP timestamp after its origin cannot enter B1."""
    origins = _origin_rows()
    source = _b1_source(origins).with_columns(
        (pl.col("forecast_origin_utc").dt.epoch("ns") + 1).alias(
            "b1q_max_sip_timestamp_ns"
        )
    )

    with pytest.raises(ValueError, match="TARGET_BLIND_V22_B1_FUTURE_QUOTE"):
        adapt_b1q_source_to_v22(origins, source)


def test_b2_mask_rejects_absent_primary_variant() -> None:
    """The availability sidecar must explicitly cover the selected B2 variant."""
    origins = _origin_rows()
    availability = _availability_rows(origins).with_columns(
        pl.lit("other_variant").alias("canonical_variant")
    )

    with pytest.raises(ValueError, match="TARGET_BLIND_V22_B2_VARIANT_MISSING"):
        apply_b2_availability_mask_v22(_b2_rows(origins), availability)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda b0, b1, b2: (
                b0.with_columns(
                    (pl.col("forecast_origin_utc") + pl.duration(seconds=1)).alias(
                        "b0v2_max_predictor_available_at_utc"
                    )
                ),
                b1,
                b2,
            ),
            "TARGET_BLIND_V22_B0_AFTER_ORIGIN",
        ),
        (
            lambda b0, b1, b2: (
                b0,
                b1,
                b2.with_columns(
                    (pl.col("forecast_origin_utc") + pl.duration(seconds=1)).alias(
                        "b2v2_cutoff_utc"
                    )
                ),
            ),
            "TARGET_BLIND_V22_B2_CUTOFF_AFTER_ORIGIN",
        ),
        (
            lambda b0, b1, b2: (
                b0,
                b1,
                b2.with_columns(
                    pl.col("forecast_origin_utc").alias("b2v2_max_created_at_utc")
                ),
            ),
            "TARGET_BLIND_V22_B2_AFTER_CUTOFF",
        ),
    ],
)
def test_common_panel_fails_closed_on_pit_timestamp_violations(
    mutation: object,
    message: str,
) -> None:
    """Any predictor timestamp after its permitted cutoff fails closed."""
    origins = _origin_rows()
    b0 = _b0_rows(origins)
    b1 = adapt_b1q_source_to_v22(origins, _b1_source(origins))
    b2 = apply_b2_availability_mask_v22(
        _b2_rows(origins), _availability_rows(origins)
    )
    assert callable(mutation)
    mutated_b0, mutated_b1, mutated_b2 = mutation(b0, b1, b2)

    with pytest.raises(ValueError, match=message):
        build_target_blind_common_predictor_panel_v22(
            origins, mutated_b0, mutated_b1, mutated_b2
        )


@pytest.mark.parametrize(
    ("b1_column", "message"),
    [
        ("b1v2b_complete", "TARGET_BLIND_V22_B1_NESTED_INVARIANT_FAILURE"),
        ("b1v2c_complete", "TARGET_BLIND_V22_B1_NESTED_INVARIANT_FAILURE"),
    ],
)
def test_common_panel_rejects_non_nested_b1_flags(
    b1_column: str,
    message: str,
) -> None:
    """Nested B1 flags must imply all lower information sets."""
    origins = _origin_rows()
    b1 = adapt_b1q_source_to_v22(origins, _b1_source(origins))
    if b1_column == "b1v2b_complete":
        b1 = b1.with_columns(
            pl.lit(False).alias("b1v2a_complete"),
            pl.lit(True).alias("b1v2b_complete"),
        )
    else:
        b1 = b1.with_columns(
            pl.lit(False).alias("b1v2b_complete"),
            pl.lit(True).alias("b1v2c_complete"),
        )
    b2 = apply_b2_availability_mask_v22(
        _b2_rows(origins), _availability_rows(origins)
    )

    with pytest.raises(ValueError, match=message):
        build_target_blind_common_predictor_panel_v22(
            origins, _b0_rows(origins), b1, b2
        )


def test_common_panel_drops_unallowlisted_b2_metadata() -> None:
    """A benign but unregistered source field cannot propagate into the panel."""
    origins = _origin_rows()
    b1 = adapt_b1q_source_to_v22(origins, _b1_source(origins))
    b2 = apply_b2_availability_mask_v22(
        _b2_rows(origins), _availability_rows(origins)
    ).with_columns(pl.lit("legacy-sidecar-field").alias("legacy_b2_metadata"))

    panel, _ = build_target_blind_common_predictor_panel_v22(
        origins, _b0_rows(origins), b1, b2
    )

    assert "legacy_b2_metadata" not in panel.columns


def test_target_blind_panel_rejects_loss_like_column() -> None:
    """An unregistered loss field is forbidden even if its values are harmless."""
    origins = _origin_rows().with_columns(pl.lit(0.0).alias("loss"))
    b1 = adapt_b1q_source_to_v22(_origin_rows(), _b1_source(_origin_rows()))
    b2 = apply_b2_availability_mask_v22(
        _b2_rows(_origin_rows()), _availability_rows(_origin_rows())
    )

    with pytest.raises(ValueError, match="TARGET_BLIND_V22_FORBIDDEN_COLUMN"):
        build_target_blind_common_predictor_panel_v22(
            origins, _b0_rows(_origin_rows()), b1, b2
        )


def test_common_panel_rejects_excluded_b2_row_with_feature_value() -> None:
    """An excluded B2 row must not retain a numeric predictor by caller error."""
    origins = _origin_rows()
    b1 = adapt_b1q_source_to_v22(origins, _b1_source(origins))
    b2 = apply_b2_availability_mask_v22(
        _b2_rows(origins), _availability_rows(origins)
    ).with_columns(
        pl.when(pl.col("origin_id") == "AAPL-5")
        .then(pl.lit(False))
        .otherwise(pl.col("b2v2_availability_eligible"))
        .alias("b2v2_availability_eligible"),
        pl.when(pl.col("origin_id") == "AAPL-5")
        .then(pl.lit(False))
        .otherwise(pl.col("b2v2_corrected_pit_complete"))
        .alias("b2v2_corrected_pit_complete"),
        pl.when(pl.col("origin_id") == "AAPL-5")
        .then(pl.lit(0.1))
        .otherwise(pl.col("b2v2_z_log_trade_count"))
        .alias("b2v2_z_log_trade_count"),
    )

    with pytest.raises(ValueError, match="TARGET_BLIND_V22_B2_EXCLUDED_FEATURE_VALUE"):
        build_target_blind_common_predictor_panel_v22(
            origins, _b0_rows(origins), b1, b2
        )
