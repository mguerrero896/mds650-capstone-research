"""Intraday HAR / HARQ feature construction and log-scale estimation.

Gate 3 machinery. Builds target-blind, availability-lagged heterogeneous
autoregressive components for the 30-minute realized-variance horizon from
one-minute underlying bars, plus the Bollerslev-Patton-Quaedvlieg realized
quarticity attenuation term, and fits ordinary least squares on the log scale
with lognormal smearing. Bar-label semantics are validated externally against
the frozen ``b0_rv_30m_lag`` panel column (empirical A001 evidence).
"""

from __future__ import annotations

import math

import numpy as np
import polars as pl
from numpy.typing import NDArray

type FloatArray = NDArray[np.float64]

HAR_COLUMNS = (
    "log_rv_30m",
    "log_rv_session",
    "log_rv_day",
    "log_rv_week",
    "minute_fraction",
    "minute_fraction_sq",
)
HARQ_COLUMN = "rq_attenuation"


def build_har_features(
    bars: pl.DataFrame,
    origins: pl.DataFrame,
    *,
    window_minutes: int = 30,
    week_sessions: int = 5,
    label_shift_minutes: int = 0,
    variance_floor: float = 1e-12,
) -> pl.DataFrame:
    """Attach HAR/HARQ regressors to forecast origins.

    Parameters
    ----------
    bars:
        One-minute bars with ``asset``, ``bar_start_utc`` and ``close``.
    origins:
        Forecast origins with ``origin_id``, ``asset``, ``session_date`` and
        ``forecast_origin_utc``.
    window_minutes:
        Short-horizon component window (matches the RV30 horizon).
    week_sessions:
        Sessions in the weekly component; earlier sessions are dropped.
    label_shift_minutes:
        Minutes added to the bar label before availability comparison, so both
        A001 candidate conventions can be evaluated externally.
    variance_floor:
        Floor applied inside logarithms.

    Returns
    -------
    polars.DataFrame
        Origins joined with the HAR columns and ``rq_30m``; origins without a
        complete component history are dropped.
    """
    required_bars = {"asset", "bar_start_utc", "close"}
    required_origins = {"origin_id", "asset", "session_date", "forecast_origin_utc"}
    if required_bars - set(bars.columns) or required_origins - set(origins.columns):
        raise ValueError("HAR_INPUT_COLUMNS_MISSING")
    returns = (
        bars.sort("asset", "bar_start_utc")
        .with_columns(
            pl.col("bar_start_utc")
            .dt.offset_by(f"{label_shift_minutes}m")
            .alias("effective_utc")
        )
        .with_columns(
            pl.col("effective_utc").dt.convert_time_zone("America/New_York").alias("effective_ny")
        )
        .with_columns(pl.col("effective_ny").dt.date().alias("bar_session"))
        .with_columns(
            (pl.col("close") / pl.col("close").shift(1).over("asset", "bar_session"))
            .log()
            .alias("log_return")
        )
        .drop_nulls("log_return")
        .with_columns((pl.col("log_return") ** 2).alias("squared"))
        .with_columns((pl.col("log_return") ** 4).alias("fourth"))
    )
    daily = (
        returns.group_by("asset", "bar_session")
        .agg(pl.col("squared").sum().alias("rv_full_session"))
        .sort("asset", "bar_session")
        .with_columns(
            pl.col("rv_full_session").shift(1).over("asset").alias("rv_day"),
            pl.col("rv_full_session")
            .shift(1)
            .rolling_mean(week_sessions)
            .over("asset")
            .alias("rv_week"),
        )
        .drop("rv_full_session")
    )
    origin_keys = origins.select(
        "origin_id", "asset", "session_date", "forecast_origin_utc"
    ).with_columns(pl.col("session_date").cast(pl.Date).alias("bar_session"))
    window_start = pl.col("forecast_origin_utc").dt.offset_by(f"-{window_minutes}m")
    joined = (
        returns.join(
            origin_keys,
            left_on=["asset", "bar_session"],
            right_on=["asset", "bar_session"],
            how="inner",
        )
        .filter(pl.col("effective_utc") < pl.col("forecast_origin_utc"))
        .with_columns(
            (pl.col("effective_utc") >= window_start).alias("in_window"),
        )
        .group_by("origin_id", "asset", "session_date", "forecast_origin_utc")
        .agg(
            pl.col("squared").filter(pl.col("in_window")).sum().alias("rv_30m"),
            pl.col("fourth").filter(pl.col("in_window")).sum().alias("sum_fourth"),
            pl.col("in_window").sum().alias("window_bars"),
            pl.col("squared").sum().alias("rv_session"),
        )
        .filter(pl.col("window_bars") >= window_minutes - 2)
    )
    features = (
        joined.with_columns(
            ((pl.col("window_bars") / 3.0) * pl.col("sum_fourth")).alias("rq_30m")
        )
        .with_columns(pl.col("session_date").cast(pl.Date).alias("bar_session"))
        .join(daily, on=["asset", "bar_session"], how="inner")
        .drop_nulls(["rv_day", "rv_week"])
        .with_columns(
            pl.col("rv_30m").clip(lower_bound=variance_floor).log().alias("log_rv_30m"),
            pl.col("rv_session").clip(lower_bound=variance_floor).log().alias("log_rv_session"),
            pl.col("rv_day").clip(lower_bound=variance_floor).log().alias("log_rv_day"),
            pl.col("rv_week").clip(lower_bound=variance_floor).log().alias("log_rv_week"),
            (
                (
                    pl.col("forecast_origin_utc")
                    .dt.convert_time_zone("America/New_York")
                    .dt.hour()
                    * 60
                    + pl.col("forecast_origin_utc")
                    .dt.convert_time_zone("America/New_York")
                    .dt.minute()
                    - 570
                )
                / 390.0
            ).alias("minute_fraction"),
        )
        .with_columns(
            (pl.col("minute_fraction") ** 2).alias("minute_fraction_sq"),
            (
                pl.col("rq_30m").clip(lower_bound=variance_floor).sqrt()
                / pl.col("rv_30m").clip(lower_bound=variance_floor)
                * pl.col("log_rv_30m")
            ).alias(HARQ_COLUMN),
        )
        .drop("bar_session")
    )
    return features


def fit_log_ols(design: FloatArray, log_target: FloatArray) -> dict[str, FloatArray | float]:
    """Least-squares fit of ``log_target`` on ``design`` with residual variance.

    Parameters
    ----------
    design:
        Two-dimensional design matrix including the intercept column.
    log_target:
        Log-scale targets.

    Returns
    -------
    dict
        Coefficients and residual variance ``sigma2``.
    """
    if design.ndim != 2 or log_target.ndim != 1 or design.shape[0] != log_target.size:
        raise ValueError("HAR_DESIGN_SHAPE_INVALID")
    if design.shape[0] <= design.shape[1] + 2:
        raise ValueError("HAR_DESIGN_UNDERDETERMINED")
    if not (np.isfinite(design).all() and np.isfinite(log_target).all()):
        raise ValueError("HAR_DESIGN_NONFINITE")
    coefficients, _, rank, _ = np.linalg.lstsq(design, log_target, rcond=None)
    if rank < design.shape[1]:
        raise ValueError("HAR_DESIGN_RANK_DEFICIENT")
    residuals = log_target - design @ coefficients
    sigma2 = float(residuals @ residuals / (log_target.size - design.shape[1]))
    return {"coefficients": coefficients, "sigma2": sigma2}


def predict_level(
    design: FloatArray,
    coefficients: FloatArray,
    sigma2: float,
    *,
    smearing: bool = True,
) -> FloatArray:
    """Level-scale forecasts ``exp(X beta [+ sigma2 / 2])``.

    Parameters
    ----------
    design, coefficients, sigma2:
        Fitted model pieces from :func:`fit_log_ols`.
    smearing:
        Apply the lognormal retransformation so forecasts target the mean.
    """
    if design.ndim != 2 or coefficients.ndim != 1 or design.shape[1] != coefficients.size:
        raise ValueError("HAR_DESIGN_SHAPE_INVALID")
    if sigma2 < 0 or not math.isfinite(sigma2):
        raise ValueError("HAR_SIGMA2_INVALID")
    adjustment = sigma2 / 2.0 if smearing else 0.0
    return np.exp(design @ coefficients + adjustment)
