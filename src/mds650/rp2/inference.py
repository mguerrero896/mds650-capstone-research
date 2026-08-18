"""Block 10 - the inference the program says is still missing.

Clark-West for nested predictive accuracy, Giacomini-White for *conditional* predictive
ability, and Hansen's SPA / White's Reality Check with a stationary bootstrap so that the
best of many transformations has to survive its own selection.

Everything here clusters or blocks by trading day: five-minute origins share overlapping
thirty-minute targets, so treating them as independent observations would understate every
standard error by roughly the square root of the origins per day.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Final

import numpy as np
import numpy.typing as npt
from scipy import stats

type FloatArray = npt.NDArray[np.float64]
type IntArray = npt.NDArray[np.int64]

DEFAULT_BOOTSTRAP: Final = 2000
DEFAULT_BLOCK_MEAN: Final = 5.0


def clark_west_terms(
    actual: FloatArray, restricted: FloatArray, unrestricted: FloatArray
) -> FloatArray:
    """Per-observation Clark-West adjusted loss difference for nested models.

    ``f_t = e_0t^2 - [e_1t^2 - (yhat_0t - yhat_1t)^2]``.  The final term removes the
    downward bias that plain Diebold-Mariano suffers when the larger model nests the
    smaller one and the extra parameters are estimated noise under the null.
    """

    if actual.shape != restricted.shape or actual.shape != unrestricted.shape:
        raise ValueError("RP2_CW_SHAPE_MISMATCH")
    error_restricted = actual - restricted
    error_unrestricted = actual - unrestricted
    adjustment = (restricted - unrestricted) ** 2
    return error_restricted**2 - (error_unrestricted**2 - adjustment)


@dataclass(frozen=True, slots=True)
class MeanTest:
    """A clustered mean with its standard error and one-sided significance."""

    mean: float
    standard_error: float
    t_statistic: float
    p_value_one_sided: float
    p_value_two_sided: float
    clusters: int


def clustered_mean_test(values: FloatArray, clusters: IntArray) -> MeanTest:
    """Test that a per-observation series has a positive mean, clustering by day."""

    if values.shape != clusters.shape:
        raise ValueError("RP2_INFERENCE_SHAPE_MISMATCH")
    finite = np.isfinite(values)
    values, clusters = values[finite], clusters[finite]
    labels = np.unique(clusters)
    if labels.size < 3:
        raise ValueError("RP2_INFERENCE_TOO_FEW_CLUSTERS")
    means = np.array([values[clusters == label].mean() for label in labels], dtype=np.float64)
    weights = np.array(
        [np.count_nonzero(clusters == label) for label in labels], dtype=np.float64
    )
    overall = float(np.sum(means * weights) / np.sum(weights))
    spread = float(np.std(means, ddof=1) / math.sqrt(labels.size))
    t_statistic = overall / spread if spread > 0.0 else float("nan")
    degrees = labels.size - 1
    return MeanTest(
        mean=overall,
        standard_error=spread,
        t_statistic=t_statistic,
        p_value_one_sided=float(stats.t.sf(t_statistic, df=degrees)),
        p_value_two_sided=float(2.0 * stats.t.sf(abs(t_statistic), df=degrees)),
        clusters=int(labels.size),
    )


def newey_west_variance(values: FloatArray, *, lags: int) -> float:
    """Long-run variance of a mean under serial dependence (Bartlett kernel)."""

    if lags < 0:
        raise ValueError("RP2_INFERENCE_LAGS_INVALID")
    centred = values - values.mean()
    size = centred.size
    total = float(centred @ centred) / size
    for lag in range(1, min(lags, size - 1) + 1):
        weight = 1.0 - lag / (lags + 1.0)
        total += 2.0 * weight * float(centred[lag:] @ centred[:-lag]) / size
    return max(total, 0.0)


@dataclass(frozen=True, slots=True)
class ConditionalTest:
    """Giacomini-White conditional predictive ability."""

    wald: float
    p_value: float
    degrees_of_freedom: int
    clusters: int


def giacomini_white(
    loss_difference: FloatArray, conditioners: FloatArray, clusters: IntArray
) -> ConditionalTest:
    """Test ``E[d_t | Z_t] = 0`` by regressing the loss difference on ``Z``.

    A significant result means the expanded model's advantage is *state dependent*: it
    works under some observable conditions and not others, which is a different claim from
    "it works on average" and is exactly what the program asks to detect.
    """

    if loss_difference.size != conditioners.shape[0]:
        raise ValueError("RP2_INFERENCE_SHAPE_MISMATCH")
    design = np.column_stack([np.ones(loss_difference.size), conditioners])
    finite = np.isfinite(design).all(axis=1) & np.isfinite(loss_difference)
    design, response, group = design[finite], loss_difference[finite], clusters[finite]
    labels = np.unique(group)
    if labels.size < design.shape[1] + 2:
        raise ValueError("RP2_INFERENCE_TOO_FEW_CLUSTERS")
    gram = np.linalg.pinv(design.T @ design)
    coefficients = gram @ (design.T @ response)
    residual = response - design @ coefficients
    meat = np.zeros((design.shape[1], design.shape[1]), dtype=np.float64)
    for label in labels:
        mask = group == label
        contribution = design[mask].T @ residual[mask]
        meat += np.outer(contribution, contribution)
    covariance = gram @ meat @ gram
    wald = float(coefficients @ np.linalg.pinv(covariance) @ coefficients)
    return ConditionalTest(
        wald=wald,
        p_value=float(stats.chi2.sf(wald, df=design.shape[1])),
        degrees_of_freedom=int(design.shape[1]),
        clusters=int(labels.size),
    )


def stationary_bootstrap_indices(
    size: int, *, block_mean: float, generator: np.random.Generator
) -> IntArray:
    """Politis-Romano stationary bootstrap index draw with geometric block lengths."""

    if size <= 0 or block_mean <= 1.0:
        raise ValueError("RP2_INFERENCE_BOOTSTRAP_PARAMS_INVALID")
    probability = 1.0 / block_mean
    indices = np.empty(size, dtype=np.int64)
    current = int(generator.integers(0, size))
    for position in range(size):
        indices[position] = current
        if generator.random() < probability:
            current = int(generator.integers(0, size))
        else:
            current = (current + 1) % size
    return indices


@dataclass(frozen=True, slots=True)
class SuperiorPredictiveAbility:
    """Hansen SPA and White Reality Check over a family of candidate models."""

    best_model: str
    best_mean_difference: float
    spa_p_value: float
    reality_check_p_value: float
    candidates: int
    blocks: int


def hansen_spa(
    benchmark_losses: FloatArray,
    candidate_losses: dict[str, FloatArray],
    *,
    repetitions: int = DEFAULT_BOOTSTRAP,
    block_mean: float = DEFAULT_BLOCK_MEAN,
    seed: int = 650,
) -> SuperiorPredictiveAbility:
    """Test whether *any* candidate genuinely beats the benchmark, after selection.

    ``d_k = L(benchmark) - L(candidate_k)``; positive favours the candidate.  Both the SPA
    (studentised, with Hansen's recentring) and the plain Reality Check statistic are
    returned, because they differ exactly when a poor candidate inflates the null.
    """

    if not candidate_losses:
        raise ValueError("RP2_INFERENCE_NO_CANDIDATES")
    names = sorted(candidate_losses)
    differences = np.column_stack(
        [benchmark_losses - candidate_losses[name] for name in names]
    )
    finite = np.isfinite(differences).all(axis=1)
    differences = differences[finite]
    size = differences.shape[0]
    if size < 20:
        raise ValueError("RP2_INFERENCE_TOO_FEW_OBSERVATIONS")
    means = differences.mean(axis=0)
    variances = np.array(
        [max(newey_west_variance(differences[:, k], lags=5), 1e-18) for k in range(len(names))]
    )
    scaled = math.sqrt(size) * means
    statistic = float(np.max(np.maximum(scaled / np.sqrt(variances), 0.0)))
    reality_statistic = float(np.max(scaled))

    # Hansen's recentring keeps candidates that are not significantly bad out of the null.
    threshold = -np.sqrt(variances / size) * math.sqrt(2.0 * math.log(math.log(size)))
    recentred = np.where(means >= threshold, means, 0.0)

    generator = np.random.default_rng(seed)
    spa_exceed = 0
    reality_exceed = 0
    for _ in range(repetitions):
        draw = stationary_bootstrap_indices(size, block_mean=block_mean, generator=generator)
        sample_means = differences[draw].mean(axis=0)
        centred_spa = math.sqrt(size) * (sample_means - recentred)
        centred_reality = math.sqrt(size) * (sample_means - means)
        if float(np.max(np.maximum(centred_spa / np.sqrt(variances), 0.0))) >= statistic:
            spa_exceed += 1
        if float(np.max(centred_reality)) >= reality_statistic:
            reality_exceed += 1
    best = int(np.argmax(means))
    return SuperiorPredictiveAbility(
        best_model=names[best],
        best_mean_difference=float(means[best]),
        spa_p_value=(spa_exceed + 1.0) / (repetitions + 1.0),
        reality_check_p_value=(reality_exceed + 1.0) / (repetitions + 1.0),
        candidates=len(names),
        blocks=int(round(size / block_mean)),
    )
