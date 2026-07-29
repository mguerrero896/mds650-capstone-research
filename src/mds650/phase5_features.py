"""Frozen, target-blind feature transformations for Phase 5."""

from __future__ import annotations

import polars as pl

from mds650.study_design import B2_FEATURE_NAMES

RAW_B2_COLUMNS = frozenset(
    {
        "option_trade_count_5m",
        "unique_contract_count_5m",
        "total_premium_5m",
        "max_trade_premium_5m",
        "call_premium_5m",
        "put_premium_5m",
        "ask_side_premium_share",
        "bid_side_premium_share",
        "repeated_contract_premium",
        "strike_concentration",
        "expiry_concentration",
    }
)


def add_compact_b2_features(frame: pl.DataFrame) -> pl.DataFrame:
    """Add the nine preregistered B2 features without reading any target.

    Parameters
    ----------
    frame:
        Per-origin locally reconstructed activity aggregates.

    Returns
    -------
    polars.DataFrame
        Input columns plus the nine frozen B2 features.

    Raises
    ------
    ValueError
        If a required raw activity aggregate is absent.
    """
    missing = sorted(RAW_B2_COLUMNS - set(frame.columns))
    if missing:
        raise ValueError(f"B2_RAW_FEATURES_MISSING:{','.join(missing)}")
    invalid = frame.select(
        pl.any_horizontal(
            [
                ~pl.col(column).cast(pl.Float64).is_finite()
                | (pl.col(column).cast(pl.Float64) < 0)
                for column in sorted(RAW_B2_COLUMNS)
            ]
        ).any()
    ).item()
    if invalid:
        raise ValueError("B2_RAW_FEATURE_VALUES_INVALID")

    count = pl.col("option_trade_count_5m").cast(pl.Float64)
    premium = pl.col("total_premium_5m").cast(pl.Float64)
    call_put_premium = (
        pl.col("call_premium_5m").cast(pl.Float64)
        + pl.col("put_premium_5m").cast(pl.Float64)
    )

    result = frame.with_columns(
        [
            count.log1p().alias(B2_FEATURE_NAMES[0]),
            pl.when(count > 0)
            .then(pl.col("unique_contract_count_5m") / count)
            .otherwise(0.0)
            .alias(B2_FEATURE_NAMES[1]),
            pl.when(count > 0)
            .then((premium / count).log1p())
            .otherwise(0.0)
            .alias(B2_FEATURE_NAMES[2]),
            pl.col("max_trade_premium_5m")
            .cast(pl.Float64)
            .log1p()
            .alias(B2_FEATURE_NAMES[3]),
            pl.when(call_put_premium > 0)
            .then(
                (
                    pl.col("call_premium_5m").cast(pl.Float64)
                    - pl.col("put_premium_5m").cast(pl.Float64)
                )
                / call_put_premium
            )
            .otherwise(0.0)
            .alias(B2_FEATURE_NAMES[4]),
            (
                pl.col("ask_side_premium_share").cast(pl.Float64)
                - pl.col("bid_side_premium_share").cast(pl.Float64)
            ).alias(B2_FEATURE_NAMES[5]),
            pl.when(premium > 0)
            .then(pl.col("repeated_contract_premium") / premium)
            .otherwise(0.0)
            .alias(B2_FEATURE_NAMES[6]),
            pl.col("strike_concentration")
            .cast(pl.Float64)
            .alias(B2_FEATURE_NAMES[7]),
            pl.col("expiry_concentration")
            .cast(pl.Float64)
            .alias(B2_FEATURE_NAMES[8]),
        ]
    )
    return result
