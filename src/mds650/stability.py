"""Frozen, target-blind transformations for Phase 5 stability checks."""

from __future__ import annotations

import polars as pl

from mds650.study_design import B2_FEATURE_NAMES

FMP_DELAYS_MINUTES = (1, 2)
B2_DELAYS_SECONDS = (60, 120, 300)
SESSION_TERCILE_BOUNDS = (130.0, 260.0)
B0_PLUS2_ALIASES = {
    "b0_plus2_spot": "b0_spot",
    "b0_plus2_rv_5m_lag": "b0_rv_5m_lag",
    "b0_plus2_rv_30m_lag": "b0_rv_30m_lag",
    "b0_plus2_return_5m_lag": "b0_return_5m_lag",
    "b0_plus2_volume_5m_lag": "b0_volume_5m_lag",
}


def b2_sensitivity_column(feature: str, delay_seconds: int) -> str:
    """Return the deterministic sidecar column for one B2 timing variant.

    Parameters
    ----------
    feature:
        One of the nine preregistered B2 feature names.
    delay_seconds:
        Registered operational delay in seconds.

    Returns
    -------
    str
        Sidecar column name.

    Raises
    ------
    ValueError
        If the feature or delay was not preregistered.
    """
    if feature not in B2_FEATURE_NAMES:
        raise ValueError(f"B2_FEATURE_NOT_PREREGISTERED:{feature}")
    if delay_seconds not in B2_DELAYS_SECONDS:
        raise ValueError(f"B2_DELAY_NOT_PREREGISTERED:{delay_seconds}")
    return f"{feature}__{delay_seconds}s"


def development_volatility_cutpoints(frame: pl.DataFrame) -> tuple[float, float]:
    """Derive pooled B0 lagged-RV tertiles from development predictors only.

    Parameters
    ----------
    frame:
        Frozen selected-asset development panel.

    Returns
    -------
    tuple[float, float]
        Linear-interpolation 1/3 and 2/3 quantiles.

    Raises
    ------
    ValueError
        If the B0 source is absent, non-finite or degenerate.
    """
    column = "b0_rv_30m_lag"
    if column not in frame.columns:
        raise ValueError("STABILITY_VOLATILITY_SOURCE_MISSING")
    values = frame.select(pl.col(column).cast(pl.Float64))
    if (
        values.is_empty()
        or values[column].null_count()
        or not values.select(pl.col(column).is_finite().all()).item()
    ):
        raise ValueError("STABILITY_VOLATILITY_SOURCE_INVALID")
    cuts = values.select(
        pl.col(column).quantile(1 / 3, interpolation="linear").alias("lower"),
        pl.col(column).quantile(2 / 3, interpolation="linear").alias("upper"),
    ).row(0)
    lower, upper = float(cuts[0]), float(cuts[1])
    if not lower < upper:
        raise ValueError("STABILITY_VOLATILITY_CUTPOINTS_DEGENERATE")
    return lower, upper


def add_stability_strata(
    frame: pl.DataFrame,
    *,
    lower: float,
    upper: float,
) -> pl.DataFrame:
    """Attach the frozen session-tercile and B0-volatility labels.

    Parameters
    ----------
    frame:
        Origin-level panel containing only the required B0 predictors plus any
        columns that must be carried through.
    lower, upper:
        Development-only lagged-RV tertile cutpoints.

    Returns
    -------
    polars.DataFrame
        Input rows with ``session_tercile`` and ``volatility_regime``.

    Raises
    ------
    ValueError
        If source columns or cutpoints are invalid.
    """
    required = {"b0_session_minute", "b0_rv_30m_lag"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"STABILITY_STRATA_COLUMNS_MISSING:{','.join(missing)}")
    if not lower < upper:
        raise ValueError("STABILITY_VOLATILITY_CUTPOINTS_DEGENERATE")
    first_end, middle_end = SESSION_TERCILE_BOUNDS
    return frame.with_columns(
        pl.when(pl.col("b0_session_minute") < first_end)
        .then(pl.lit("FIRST"))
        .when(pl.col("b0_session_minute") < middle_end)
        .then(pl.lit("MIDDLE"))
        .otherwise(pl.lit("LAST"))
        .alias("session_tercile"),
        pl.when(pl.col("b0_rv_30m_lag") <= lower)
        .then(pl.lit("LOW"))
        .when(pl.col("b0_rv_30m_lag") <= upper)
        .then(pl.lit("MIDDLE"))
        .otherwise(pl.lit("HIGH"))
        .alias("volatility_regime"),
    )


def apply_fmp_delay(frame: pl.DataFrame, *, delay_minutes: int) -> pl.DataFrame:
    """Select the registered FMP availability convention without using RV30.

    Parameters
    ----------
    frame:
        Panel containing canonical B0 columns and the +2-minute aliases.
    delay_minutes:
        Registered delay, either one or two minutes.

    Returns
    -------
    polars.DataFrame
        Same rows with canonical B0 columns representing the requested delay.

    Raises
    ------
    ValueError
        If the delay or required +2-minute columns are invalid.
    """
    if delay_minutes not in FMP_DELAYS_MINUTES:
        raise ValueError(f"FMP_DELAY_NOT_PREREGISTERED:{delay_minutes}")
    if delay_minutes == 1:
        return frame
    missing = sorted(set(B0_PLUS2_ALIASES) - set(frame.columns))
    if missing:
        raise ValueError(f"FMP_PLUS2_COLUMNS_MISSING:{','.join(missing)}")
    return frame.with_columns(
        [pl.col(source).alias(target) for source, target in B0_PLUS2_ALIASES.items()]
    )


def apply_b2_delay(frame: pl.DataFrame, *, delay_seconds: int) -> pl.DataFrame:
    """Select one registered B2 operational cutoff without using RV30.

    Parameters
    ----------
    frame:
        Panel containing the primary B2 columns and sensitivity sidecars.
    delay_seconds:
        Registered cutoff delay: 60, 120 or 300 seconds.

    Returns
    -------
    polars.DataFrame
        Same rows with canonical B2 features representing the requested delay.

    Raises
    ------
    ValueError
        If the delay or required sidecar columns are invalid.
    """
    if delay_seconds not in B2_DELAYS_SECONDS:
        raise ValueError(f"B2_DELAY_NOT_PREREGISTERED:{delay_seconds}")
    if delay_seconds == 60:
        return frame
    aliases = {
        b2_sensitivity_column(feature, delay_seconds): feature for feature in B2_FEATURE_NAMES
    }
    missing = sorted(set(aliases) - set(frame.columns))
    if missing:
        raise ValueError(f"B2_SENSITIVITY_COLUMNS_MISSING:{','.join(missing)}")
    return frame.with_columns([pl.col(source).alias(target) for source, target in aliases.items()])
