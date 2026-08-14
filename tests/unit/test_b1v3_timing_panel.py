"""Target-blind common-panel construction for registered timing variants."""

from __future__ import annotations

from datetime import UTC, datetime

import polars as pl
import pytest

from mds650.b1v3 import B1V3_FEATURES
from mds650.b1v3_timing_panel import (
    REGISTERED_TIMING_VARIANTS,
    build_registered_timing_panels,
)
from mds650.phase6 import B0V2_FEATURES
from mds650.study_design import B2_FEATURE_NAMES


def _components() -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    origins = pl.DataFrame(
        {
            "origin_id": ["AAPL:1", "MSFT:1"],
            "asset": ["AAPL", "MSFT"],
            "session_date": ["2024-08-02", "2024-08-02"],
            "forecast_origin_utc": [
                "2024-08-02T14:35:00+00:00",
                "2024-08-02T14:35:00+00:00",
            ],
            "forecast_origin_ns": [1_722_609_300_000_000_000] * 2,
            "role": ["development", "development"],
            "session_tercile": ["first", "first"],
        }
    )
    b0 = origins.select("origin_id").with_columns(
        *[
            pl.lit(1.0 if feature != "b0v2_asset_identity" else "asset").alias(feature)
            for feature in B0V2_FEATURES
        ],
        pl.lit(True).alias("b0_complete"),
        pl.lit(None, dtype=pl.String).alias("b0_missing_reason"),
    )
    b1 = origins.select("origin_id").with_columns(
        *[pl.lit(1.0).alias(feature) for feature in B1V3_FEATURES],
        pl.lit(True).alias("b1v3a_complete"),
        pl.lit(True).alias("b1v3b_complete"),
        pl.lit(True).alias("b1v3c_complete"),
    )
    b2 = origins.select("origin_id").with_columns(
        *[pl.lit(1.0).alias(feature) for feature in B2_FEATURE_NAMES],
        pl.lit(True).alias("b2v2_availability_eligible"),
        pl.lit("PASS").alias("b2v2_availability_status"),
        pl.lit(datetime(2024, 8, 2, 14, 34, tzinfo=UTC)).alias(
            "b2v2_max_created_at_utc"
        ),
        pl.lit(datetime(2024, 8, 2, 14, 34, tzinfo=UTC)).alias("b2v2_cutoff_utc"),
    )
    return origins, b0, b1, b2


def test_registered_timing_panels_preserve_origins_and_nested_completeness() -> None:
    origins, b0, b1, b2 = _components()
    overrides = {
        "FMP_DELAY_2_MINUTES": (b0, b1, None),
        "MASSIVE_CUTOFF_60_SECONDS": (None, b1, None),
        "MASSIVE_CUTOFF_300_SECONDS": (None, b1, None),
        "UW_CREATED_AT_120_SECONDS": (None, None, b2),
        "UW_CREATED_AT_300_SECONDS": (None, None, b2),
    }

    panels = build_registered_timing_panels(
        origins=origins,
        primary_b0=b0,
        primary_b1=b1,
        primary_b2=b2,
        overrides=overrides,
    )

    assert tuple(panels) == REGISTERED_TIMING_VARIANTS
    for variant, panel in panels.items():
        assert panel.height == origins.height
        assert panel["origin_id"].n_unique() == origins.height
        assert panel["timing_variant"].unique().to_list() == [variant]
        assert panel["b0_information_set_complete"].all()
        assert panel["b1v3a_information_set_complete"].all()
        assert panel["b2_information_set_complete"].all()


def test_timing_panels_fail_closed_on_variant_or_target_drift() -> None:
    origins, b0, b1, b2 = _components()
    incomplete = {
        variant: (None, None, None) for variant in REGISTERED_TIMING_VARIANTS[:-1]
    }
    with pytest.raises(ValueError, match="B1V3_TIMING_VARIANT_SET_INVALID"):
        build_registered_timing_panels(
            origins=origins,
            primary_b0=b0,
            primary_b1=b1,
            primary_b2=b2,
            overrides=incomplete,
        )
    with pytest.raises(ValueError, match="B1V3_TIMING_INPUT_NOT_TARGET_BLIND"):
        build_registered_timing_panels(
            origins=origins.with_columns(pl.lit(0.1).alias("rv30")),
            primary_b0=b0,
            primary_b1=b1,
            primary_b2=b2,
            overrides={
                variant: (None, None, None) for variant in REGISTERED_TIMING_VARIANTS
            },
        )
