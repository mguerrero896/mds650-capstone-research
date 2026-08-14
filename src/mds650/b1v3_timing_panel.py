"""Assemble the five registered target-blind B1v3 timing panels."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

import polars as pl

from mds650.b1v3_confirmation_common import build_common_predictor_frame

REGISTERED_TIMING_VARIANTS: Final[tuple[str, ...]] = (
    "FMP_DELAY_2_MINUTES",
    "MASSIVE_CUTOFF_60_SECONDS",
    "MASSIVE_CUTOFF_300_SECONDS",
    "UW_CREATED_AT_120_SECONDS",
    "UW_CREATED_AT_300_SECONDS",
)
_FORBIDDEN: Final[tuple[str, ...]] = (
    "rv30",
    "qlike",
    "prediction",
    "predicted",
    "outcome",
    "residual",
    "loss",
    "model_result",
)
TimingOverride = tuple[pl.DataFrame | None, pl.DataFrame | None, pl.DataFrame | None]


def _assert_target_blind(name: str, frame: pl.DataFrame) -> None:
    if any(
        token in column.lower()
        for column in frame.columns
        for token in _FORBIDDEN
    ):
        raise ValueError(f"B1V3_TIMING_INPUT_NOT_TARGET_BLIND:{name}")


def build_registered_timing_panels(
    *,
    origins: pl.DataFrame,
    primary_b0: pl.DataFrame,
    primary_b1: pl.DataFrame,
    primary_b2: pl.DataFrame,
    overrides: Mapping[str, TimingOverride],
) -> dict[str, pl.DataFrame]:
    """Build all timing panels while retaining every canonical origin.

    Parameters
    ----------
    origins:
        Frozen target-free origin grid.
    primary_b0, primary_b1, primary_b2:
        Primary source-bound components.
    overrides:
        Exact five-variant mapping.  Each tuple optionally replaces B0, B1 or
        B2; ``None`` means reuse the matching primary component.

    Returns
    -------
    dict[str, polars.DataFrame]
        Ordered variant frames with one row per origin and nested completeness.

    Raises
    ------
    ValueError
        If variants, source target-blindness, identities, nesting or origin
        preservation drift.
    """
    if set(overrides) != set(REGISTERED_TIMING_VARIANTS):
        raise ValueError("B1V3_TIMING_VARIANT_SET_INVALID")
    for name, frame in (
        ("ORIGINS", origins),
        ("PRIMARY_B0", primary_b0),
        ("PRIMARY_B1", primary_b1),
        ("PRIMARY_B2", primary_b2),
    ):
        _assert_target_blind(name, frame)
    if (
        origins.is_empty()
        or "origin_id" not in origins.columns
        or origins["origin_id"].n_unique() != origins.height
    ):
        raise ValueError("B1V3_TIMING_ORIGIN_IDENTITY_INVALID")
    expected_ids = set(str(value) for value in origins["origin_id"].to_list())
    panels: dict[str, pl.DataFrame] = {}
    for variant in REGISTERED_TIMING_VARIANTS:
        b0_override, b1_override, b2_override = overrides[variant]
        b0 = primary_b0 if b0_override is None else b0_override
        b1 = primary_b1 if b1_override is None else b1_override
        b2 = primary_b2 if b2_override is None else b2_override
        for component_name, component in (("B0", b0), ("B1", b1), ("B2", b2)):
            _assert_target_blind(f"{variant}_{component_name}", component)
        panel = build_common_predictor_frame(
            origins=origins,
            b0=b0,
            b1=b1,
            b2=b2,
        ).with_columns(pl.lit(variant).alias("timing_variant"))
        if (
            panel.height != origins.height
            or panel["origin_id"].n_unique() != origins.height
            or set(str(value) for value in panel["origin_id"].to_list())
            != expected_ids
        ):
            raise ValueError("B1V3_TIMING_ORIGIN_PRESERVATION_FAILURE")
        panels[variant] = panel
    return panels
