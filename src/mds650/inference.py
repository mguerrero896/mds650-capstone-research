"""Studentized forecast-comparison inference on daily loss differentials.

Every registered contrast in this project was previously summarized only by the
whole-day sign bootstrap in :mod:`mds650.metrics`, whose p-values saturate at
``2 / (repetitions + 1)``. This module adds the studentized machinery required
by gate R-020 and roadmap 3.6: cluster t, Newey-West (Diebold-Mariano) t, wild
cluster bootstrap-t, moving-block bootstrap, Ljung-Box diagnostics, a Hansen-
Lunde-Nason Model Confidence Set, and Gelman-Carlin design analysis. All
functions consume per-day series derived from frozen forecast artifacts; no
data acquisition happens here.
"""

from __future__ import annotations

import math

import numpy as np
import polars as pl
from numpy.typing import NDArray
from scipy import stats

type FloatArray = NDArray[np.float64]

_WEBB_WEIGHTS = np.asarray(
    [
        -math.sqrt(1.5),
        -1.0,
        -math.sqrt(0.5),
        math.sqrt(0.5),
        1.0,
        math.sqrt(1.5),
    ],
    dtype=np.float64,
)


def _daily_series(values: object) -> FloatArray:
    array = np.asarray(values, dtype=np.float64)
    if array.ndim != 1 or array.size < 3:
        raise ValueError("INFERENCE_REQUIRES_THREE_DAYS")
    if not np.isfinite(array).all():
        raise ValueError("INFERENCE_NONFINITE_INPUT")
    return array


def paired_daily_differences(
    frame: pl.DataFrame,
    *,
    base_set: str,
    expanded_set: str,
    model: str,
    model_column: str = "model_role",
    set_column: str = "information_set",
    loss_column: str = "qlike_loss",
    key_columns: tuple[str, ...] = ("origin_id", "asset"),
    date_column: str = "session_date",
) -> pl.DataFrame:
    """Collapse paired origin-level losses to one mean difference per day.

    Parameters
    ----------
    frame:
        Long forecast frame with one row per origin x model x information set.
    base_set, expanded_set:
        Information-set labels; positive output favors ``expanded_set``.
    model:
        Model label evaluated on both sets.
    model_column, set_column, loss_column, key_columns, date_column:
        Column conventions of the frozen forecast artifacts.

    Returns
    -------
    polars.DataFrame
        ``date_column``, ``mean_difference``, ``origin_count`` sorted by day.

    Raises
    ------
    ValueError
        If either side is empty or origins do not pair exactly.
    """
    keys = [*key_columns, date_column]
    sides = []
    for label in (base_set, expanded_set):
        side = frame.filter(
            (pl.col(model_column) == model) & (pl.col(set_column) == label)
        ).select(*keys, pl.col(loss_column))
        if side.is_empty():
            raise ValueError(f"INFERENCE_EMPTY_SIDE:{model}:{label}")
        sides.append(side)
    paired = sides[0].join(
        sides[1],
        on=keys,
        how="inner",
        suffix="_expanded",
    )
    if paired.height != sides[0].height or paired.height != sides[1].height:
        raise ValueError("INFERENCE_UNPAIRED_ORIGINS")
    return (
        paired.with_columns(
            (pl.col(loss_column) - pl.col(f"{loss_column}_expanded")).alias("difference")
        )
        .group_by(date_column)
        .agg(
            pl.col("difference").mean().alias("mean_difference"),
            pl.len().alias("origin_count"),
        )
        .sort(date_column)
    )


def interaction_daily_differences(
    frame: pl.DataFrame,
    *,
    base_set: str,
    expanded_set: str,
    model_a: str,
    model_b: str,
    model_column: str = "model_role",
    **kwargs: str | tuple[str, ...],
) -> pl.DataFrame:
    """Per-day difference of two models' loss differentials on identical days.

    Parameters
    ----------
    frame:
        Long forecast frame shared by both models.
    base_set, expanded_set, model_a, model_b, model_column:
        Contrast definition; output is ``model_a`` minus ``model_b``.
    kwargs:
        Passed through to :func:`paired_daily_differences`.

    Returns
    -------
    polars.DataFrame
        ``session_date`` (or override), ``mean_difference``, ``origin_count``.
    """
    date_column = str(kwargs.get("date_column", "session_date"))
    left = paired_daily_differences(
        frame,
        base_set=base_set,
        expanded_set=expanded_set,
        model=model_a,
        model_column=model_column,
        **kwargs,  # type: ignore[arg-type]
    )
    right = paired_daily_differences(
        frame,
        base_set=base_set,
        expanded_set=expanded_set,
        model=model_b,
        model_column=model_column,
        **kwargs,  # type: ignore[arg-type]
    )
    joined = left.join(right, on=date_column, how="inner", suffix="_b")
    if joined.height != left.height or joined.height != right.height:
        raise ValueError("INFERENCE_INTERACTION_DAY_MISMATCH")
    return joined.select(
        pl.col(date_column),
        (pl.col("mean_difference") - pl.col("mean_difference_b")).alias("mean_difference"),
        pl.min_horizontal("origin_count", "origin_count_b").alias("origin_count"),
    ).sort(date_column)


def cluster_t_test(values: object) -> dict[str, float | int]:
    """Student-t test on the mean of a per-day loss-differential series.

    Parameters
    ----------
    values:
        One mean loss differential per trading day.

    Returns
    -------
    dict
        Estimate, standard error, t statistic, two-sided p, cluster count.
    """
    series = _daily_series(values)
    count = series.size
    estimate = float(series.mean())
    standard_error = float(series.std(ddof=1) / math.sqrt(count))
    if standard_error == 0.0:
        raise ValueError("INFERENCE_ZERO_VARIANCE")
    statistic = estimate / standard_error
    p_value = float(2.0 * stats.t.sf(abs(statistic), df=count - 1))
    return {
        "estimate": estimate,
        "standard_error": standard_error,
        "statistic": statistic,
        "p_value": p_value,
        "clusters": count,
    }


def newey_west_t_test(
    values: object,
    *,
    max_lag: int | None = None,
) -> dict[str, float | int]:
    """Diebold-Mariano style HAC t test on a daily loss-differential series.

    Parameters
    ----------
    values:
        One mean loss differential per trading day.
    max_lag:
        Bartlett truncation lag; defaults to ``floor(4 * (T / 100) ** (2 / 9))``.

    Returns
    -------
    dict
        Estimate, HAC standard error, t statistic, two-sided p, lag used.
    """
    series = _daily_series(values)
    count = series.size
    lag = max_lag if max_lag is not None else int(math.floor(4.0 * (count / 100.0) ** (2.0 / 9.0)))
    if lag < 0 or lag >= count:
        raise ValueError("INFERENCE_LAG_INVALID")
    centered = series - series.mean()
    variance = float(np.dot(centered, centered)) / count
    for j in range(1, lag + 1):
        weight = 1.0 - j / (lag + 1.0)
        variance += 2.0 * weight * float(np.dot(centered[j:], centered[:-j])) / count
    if variance <= 0.0:
        raise ValueError("INFERENCE_HAC_VARIANCE_NONPOSITIVE")
    standard_error = math.sqrt(variance / count)
    estimate = float(series.mean())
    statistic = estimate / standard_error
    p_value = float(2.0 * stats.t.sf(abs(statistic), df=count - 1))
    return {
        "estimate": estimate,
        "standard_error": standard_error,
        "statistic": statistic,
        "p_value": p_value,
        "max_lag": lag,
        "clusters": count,
    }


def wild_cluster_bootstrap(
    values: object,
    *,
    weights: str = "rademacher",
    repetitions: int = 9_999,
    seed: int = 650,
) -> dict[str, float | int | str]:
    """Wild cluster bootstrap-t inference on a per-day series.

    Parameters
    ----------
    values:
        One mean loss differential per trading day (one cluster per day).
    weights:
        ``"rademacher"`` or ``"webb"`` (six-point) auxiliary weights.
    repetitions, seed:
        Bootstrap replications and deterministic seed.

    Returns
    -------
    dict
        Symmetric bootstrap-t p-value and 95% bootstrap-t confidence interval.
    """
    series = _daily_series(values)
    if repetitions < 99:
        raise ValueError("INFERENCE_REPETITIONS_INVALID")
    base = cluster_t_test(series)
    estimate = float(base["estimate"])
    standard_error = float(base["standard_error"])
    statistic = float(base["statistic"])
    centered = series - estimate
    generator = np.random.default_rng(seed)
    if weights == "rademacher":
        draws = generator.choice(np.asarray([-1.0, 1.0]), size=(repetitions, series.size))
    elif weights == "webb":
        draws = generator.choice(_WEBB_WEIGHTS, size=(repetitions, series.size))
    else:
        raise ValueError("INFERENCE_WEIGHTS_INVALID")
    resampled = centered[None, :] * draws
    means = resampled.mean(axis=1)
    errors = resampled.std(axis=1, ddof=1) / math.sqrt(series.size)
    valid = errors > 0.0
    statistics = means[valid] / errors[valid]
    if statistics.size < repetitions // 2:
        raise ValueError("INFERENCE_BOOTSTRAP_DEGENERATE")
    exceedances = np.count_nonzero(np.abs(statistics) >= abs(statistic))
    p_value = float((exceedances + 1.0) / (statistics.size + 1.0))
    lower_q, upper_q = np.quantile(statistics, [0.975, 0.025])
    return {
        "estimate": estimate,
        "statistic": statistic,
        "p_value": p_value,
        "ci_low": estimate - float(lower_q) * standard_error,
        "ci_high": estimate - float(upper_q) * standard_error,
        "weights": weights,
        "repetitions": int(statistics.size),
        "clusters": series.size,
        "seed": seed,
    }


def autocorrelation(values: object, *, max_lag: int = 5) -> list[float]:
    """Sample autocorrelations of a daily series at lags ``1..max_lag``.

    Parameters
    ----------
    values:
        Daily series.
    max_lag:
        Highest lag; must be below the series length.

    Returns
    -------
    list[float]
        ``acf[k - 1]`` is the lag-``k`` autocorrelation.
    """
    series = _daily_series(values)
    if max_lag < 1 or max_lag >= series.size:
        raise ValueError("INFERENCE_LAG_INVALID")
    centered = series - series.mean()
    denominator = float(np.dot(centered, centered))
    if denominator == 0.0:
        raise ValueError("INFERENCE_ZERO_VARIANCE")
    return [
        float(np.dot(centered[lag:], centered[:-lag]) / denominator)
        for lag in range(1, max_lag + 1)
    ]


def ljung_box(values: object, *, max_lag: int = 5) -> dict[str, float | int]:
    """Ljung-Box portmanteau test for serial dependence.

    Parameters
    ----------
    values:
        Daily series.
    max_lag:
        Number of autocorrelations pooled into the statistic.

    Returns
    -------
    dict
        Statistic, chi-square p-value and degrees of freedom.
    """
    series = _daily_series(values)
    correlations = autocorrelation(series, max_lag=max_lag)
    count = series.size
    statistic = count * (count + 2.0) * math.fsum(
        correlation**2 / (count - lag)
        for lag, correlation in enumerate(correlations, start=1)
    )
    return {
        "statistic": float(statistic),
        "p_value": float(stats.chi2.sf(statistic, df=max_lag)),
        "degrees_of_freedom": max_lag,
        "clusters": count,
    }


def moving_block_bootstrap(
    values: object,
    *,
    block_length: int | None = None,
    repetitions: int = 9_999,
    seed: int = 650,
) -> dict[str, float | int]:
    """Circular moving-block bootstrap CI for the mean of a daily series.

    Parameters
    ----------
    values:
        Daily series.
    block_length:
        Block size in days; defaults to ``ceil(T ** (1 / 3))``.
    repetitions, seed:
        Bootstrap replications and deterministic seed.

    Returns
    -------
    dict
        Estimate, percentile 95% interval and the block length used.
    """
    series = _daily_series(values)
    count = series.size
    length = block_length if block_length is not None else int(math.ceil(count ** (1.0 / 3.0)))
    if length < 1 or length > count:
        raise ValueError("INFERENCE_BLOCK_LENGTH_INVALID")
    if repetitions < 99:
        raise ValueError("INFERENCE_REPETITIONS_INVALID")
    doubled = np.concatenate([series, series])
    blocks_needed = math.ceil(count / length)
    generator = np.random.default_rng(seed)
    starts = generator.integers(0, count, size=(repetitions, blocks_needed))
    offsets = np.arange(length)
    samples = doubled[(starts[:, :, None] + offsets[None, None, :])]
    means = samples.reshape(repetitions, -1)[:, :count].mean(axis=1)
    lower, upper = np.quantile(means, [0.025, 0.975])
    return {
        "estimate": float(series.mean()),
        "ci_low": float(lower),
        "ci_high": float(upper),
        "block_length": length,
        "repetitions": repetitions,
        "clusters": count,
        "seed": seed,
    }


def model_confidence_set(
    daily_losses: pl.DataFrame,
    *,
    date_column: str = "session_date",
    alpha: float = 0.10,
    repetitions: int = 9_999,
    seed: int = 650,
    block_length: int | None = None,
) -> dict[str, float | int | list[str] | dict[str, float]]:
    """Hansen-Lunde-Nason Model Confidence Set over daily mean losses.

    Parameters
    ----------
    daily_losses:
        One row per day; one column per model with that day's mean loss.
    date_column:
        Day column excluded from the loss matrix.
    alpha:
        Level of the set; models with MCS p-value above ``alpha`` survive.
    repetitions, seed:
        Bootstrap replications and deterministic seed.
    block_length:
        ``None`` resamples days IID (legacy; too liberal when daily loss
        differentials are autocorrelated). An integer uses a circular
        moving-block bootstrap over whole days — blocks of consecutive days are
        drawn jointly across ALL model columns, preserving both the
        cross-model pairing and the serial dependence within blocks.

    Returns
    -------
    dict
        Surviving models, per-model MCS p-values, the level and block length.
    """
    models = [column for column in daily_losses.columns if column != date_column]
    if len(models) < 2:
        raise ValueError("INFERENCE_MCS_REQUIRES_TWO_MODELS")
    losses = daily_losses.select(models).to_numpy().astype(np.float64)
    if not np.isfinite(losses).all() or losses.shape[0] < 3:
        raise ValueError("INFERENCE_MCS_INPUT_INVALID")
    count = losses.shape[0]
    generator = np.random.default_rng(seed)
    if block_length is None:
        samples = generator.integers(0, count, size=(repetitions, count))
    else:
        if block_length < 1 or block_length > count:
            raise ValueError("INFERENCE_BLOCK_LENGTH_INVALID")
        blocks_needed = math.ceil(count / block_length)
        starts = generator.integers(0, count, size=(repetitions, blocks_needed))
        offsets = np.arange(block_length)
        samples = (
            (starts[:, :, None] + offsets[None, None, :]) % count
        ).reshape(repetitions, -1)[:, :count]
    remaining = list(range(len(models)))
    p_values: dict[str, float] = {}
    running_max = 0.0
    while len(remaining) > 1:
        subset = losses[:, remaining]
        grand = subset.mean(axis=1, keepdims=True)
        relative = subset - grand
        observed_means = relative.mean(axis=0)
        boot = relative[samples].mean(axis=1)
        boot_centered = boot - observed_means[None, :]
        scale = boot_centered.std(axis=0, ddof=1)
        scale = np.where(scale > 0.0, scale, np.inf)
        observed_t = observed_means / scale
        boot_t = np.abs(boot_centered / scale[None, :]).max(axis=1)
        statistic = float(observed_t.max())
        p_value = float((np.count_nonzero(boot_t >= statistic) + 1.0) / (repetitions + 1.0))
        running_max = max(running_max, p_value)
        worst = remaining[int(np.argmax(observed_t))]
        p_values[models[worst]] = running_max
        if p_value >= alpha:
            for index in remaining:
                p_values.setdefault(models[index], max(running_max, p_value))
            break
        remaining.remove(worst)
    if len(remaining) == 1:
        p_values.setdefault(models[remaining[0]], 1.0)
    survivors = sorted(name for name, value in p_values.items() if value >= alpha)
    return {
        "survivors": survivors,
        "mcs_p_values": {name: p_values[name] for name in models},
        "alpha": alpha,
        "repetitions": repetitions,
        "seed": seed,
        "block_length": 0 if block_length is None else block_length,
    }


def type_s_type_m(
    true_effect: float,
    standard_error: float,
    *,
    alpha: float = 0.05,
) -> dict[str, float]:
    """Gelman-Carlin design analysis for a normal estimator.

    Parameters
    ----------
    true_effect:
        Hypothesized true effect size (nonzero).
    standard_error:
        Standard error of the estimator.
    alpha:
        Two-sided significance level.

    Returns
    -------
    dict
        Power, type-S error probability and exaggeration ratio (type-M).
    """
    if standard_error <= 0.0 or not math.isfinite(standard_error):
        raise ValueError("INFERENCE_SE_INVALID")
    if true_effect == 0.0 or not math.isfinite(true_effect):
        raise ValueError("INFERENCE_EFFECT_INVALID")
    critical = float(stats.norm.ppf(1.0 - alpha / 2.0))
    shift = abs(true_effect) / standard_error
    power_correct = float(stats.norm.sf(critical - shift))
    power_wrong = float(stats.norm.cdf(-critical - shift))
    power = power_correct + power_wrong
    upper_tail = float(
        stats.norm.pdf(critical - shift) + shift * stats.norm.sf(critical - shift)
    )
    lower_tail = float(
        stats.norm.pdf(critical + shift) - shift * stats.norm.sf(critical + shift)
    )
    expected_magnitude = standard_error * (upper_tail + lower_tail) / power
    return {
        "power": power,
        "type_s": power_wrong / power,
        "exaggeration_ratio": expected_magnitude / abs(true_effect),
        "alpha": alpha,
    }
