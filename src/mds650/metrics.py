"""Deterministic Phase 5 forecast losses and paired-day inference."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import numpy as np
import polars as pl
from numpy.typing import NDArray

type FloatArray = NDArray[np.float64]


def _arrays(
    actual: Sequence[float] | FloatArray,
    forecast: Sequence[float] | FloatArray,
    floor: float,
) -> tuple[FloatArray, FloatArray]:
    observed = np.asarray(actual, dtype=np.float64)
    predicted = np.asarray(forecast, dtype=np.float64)
    if (
        observed.ndim != 1
        or predicted.shape != observed.shape
        or observed.size == 0
    ):
        raise ValueError("METRIC_ARRAY_SHAPE_INVALID")
    if floor <= 0 or not np.isfinite(observed).all() or not np.isfinite(
        predicted
    ).all():
        raise ValueError("METRIC_INPUT_INVALID")
    if (observed <= 0).any():
        raise ValueError("QLIKE_REQUIRES_POSITIVE_TARGET")
    return observed, np.maximum(predicted, floor)


def qlike_losses(
    actual: Sequence[float] | FloatArray,
    forecast: Sequence[float] | FloatArray,
    *,
    floor: float = 1e-12,
) -> FloatArray:
    """Compute observation-level QLIKE losses.

    Parameters
    ----------
    actual, forecast:
        Strictly positive observed RV30 and finite forecasts.
    floor:
        Positive forecast floor.

    Returns
    -------
    numpy.ndarray
        ``actual / forecast - log(actual / forecast) - 1`` per row.

    Raises
    ------
    ValueError
        If shapes, targets or forecasts violate the metric contract.
    """
    observed, predicted = _arrays(actual, forecast, floor)
    ratio = observed / predicted
    return ratio - np.log(ratio) - 1.0


def regression_metrics(
    actual: Sequence[float] | FloatArray,
    forecast: Sequence[float] | FloatArray,
    *,
    floor: float = 1e-12,
) -> dict[str, float]:
    """Return preregistered QLIKE, MAE and RMSE.

    Parameters
    ----------
    actual, forecast:
        Observed RV30 and forecasts.
    floor:
        Positive forecast floor used by QLIKE.

    Returns
    -------
    dict[str, float]
        Mean QLIKE, MAE and RMSE.
    """
    observed, predicted = _arrays(actual, forecast, floor)
    errors = observed - predicted
    return {
        "qlike": float(qlike_losses(observed, predicted, floor=floor).mean()),
        "mae": float(np.abs(errors).mean()),
        "rmse": float(np.sqrt(np.square(errors).mean())),
    }


def paired_day_bootstrap(
    frame: pl.DataFrame,
    *,
    date_column: str = "session_date",
    value_column: str = "loss_difference",
    repetitions: int = 10_000,
    seed: int = 650,
) -> dict[str, float | int]:
    """Bootstrap a paired loss difference by whole trading day.

    Parameters
    ----------
    frame:
        One paired loss difference per evaluated origin.
    date_column, value_column:
        Trading-day cluster and difference columns.
    repetitions:
        Number of whole-day resamples.
    seed:
        Frozen deterministic seed.

    Returns
    -------
    dict[str, float | int]
        Estimate, percentile interval, two-sided sign p-value and counts.

    Raises
    ------
    ValueError
        If inputs are empty, non-finite or contain too few clusters.
    """
    missing = {date_column, value_column} - set(frame.columns)
    if missing:
        raise ValueError(f"BOOTSTRAP_COLUMNS_MISSING:{','.join(sorted(missing))}")
    if repetitions < 1:
        raise ValueError("BOOTSTRAP_REPETITIONS_INVALID")
    if frame.is_empty() or frame[value_column].null_count():
        raise ValueError("BOOTSTRAP_INPUT_EMPTY_OR_NULL")
    values = np.asarray(frame[value_column].to_numpy(), dtype=np.float64)
    if not np.isfinite(values).all():
        raise ValueError("BOOTSTRAP_NONFINITE_DIFFERENCE")
    days = (
        frame.group_by(date_column)
        .agg(
            pl.col(value_column).sum().alias("_sum"),
            pl.len().alias("_count"),
        )
        .sort(date_column)
    )
    if days.height < 2:
        raise ValueError("BOOTSTRAP_REQUIRES_TWO_DAYS")
    day_sums = np.asarray(days["_sum"].to_numpy(), dtype=np.float64)
    day_counts = np.asarray(days["_count"].to_numpy(), dtype=np.float64)
    generator = np.random.default_rng(seed)
    samples = generator.integers(
        0,
        days.height,
        size=(repetitions, days.height),
    )
    estimates = day_sums[samples].sum(axis=1) / day_counts[samples].sum(axis=1)
    lower, upper = np.quantile(estimates, [0.025, 0.975])
    probability_nonpositive = (
        float(np.count_nonzero(estimates <= 0)) + 1.0
    ) / (repetitions + 1.0)
    probability_nonnegative = (
        float(np.count_nonzero(estimates >= 0)) + 1.0
    ) / (repetitions + 1.0)
    return {
        "estimate": float(values.mean()),
        "ci_low": float(lower),
        "ci_high": float(upper),
        "p_value_two_sided": min(
            1.0,
            2.0 * min(probability_nonpositive, probability_nonnegative),
        ),
        "clusters": days.height,
        "observations": frame.height,
        "repetitions": repetitions,
        "seed": seed,
    }


def holm_adjust(p_values: Mapping[str, float]) -> dict[str, float]:
    """Apply Holm's step-down family-wise-error adjustment.

    Parameters
    ----------
    p_values:
        Named raw p-values.

    Returns
    -------
    dict[str, float]
        Adjusted p-values under the original names.

    Raises
    ------
    ValueError
        If the mapping is empty or any p-value lies outside ``[0, 1]``.
    """
    if not p_values or any(
        not np.isfinite(value) or not 0 <= value <= 1
        for value in p_values.values()
    ):
        raise ValueError("HOLM_P_VALUES_INVALID")
    ordered = sorted(p_values.items(), key=lambda item: (item[1], item[0]))
    adjusted: dict[str, float] = {}
    running = 0.0
    count = len(ordered)
    for index, (name, value) in enumerate(ordered):
        running = max(running, min(1.0, (count - index) * value))
        adjusted[name] = running
    return {name: adjusted[name] for name in p_values}
