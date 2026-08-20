"""Block 10 - the inference the program says is still missing.

Clark-West for nested predictive accuracy, Giacomini-White for *conditional* predictive
ability, and Hansen's SPA / White's Reality Check with a stationary bootstrap so that the
best of many transformations has to survive its own selection.

Everything here clusters or blocks by trading day: five-minute origins share overlapping
thirty-minute targets, so treating them as independent observations would understate every
standard error by roughly the square root of the origins per day.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

import numpy as np
import numpy.typing as npt
from scipy import stats

type FloatArray = npt.NDArray[np.float64]
type IntArray = npt.NDArray[np.int64]

DEFAULT_BOOTSTRAP: Final = 2000
#: Resamples for the family-matched SPA. Fewer than the interval bootstrap because the SPA
#: recentres and re-ranks every candidate on each draw; it is a separate setting, and the
#: digest records it separately rather than letting `DEFAULT_BOOTSTRAP` stand for both.
SPA_REPETITIONS: Final = 1000
#: Newey-West lags for the SPA's long-run variances. Equal to the session block length today
#: and not the same decision: one says how far dependence is carried when sessions are
#: resampled, the other how far it is carried when a variance is estimated. Leaving the SPA
#: reading the block-length constant would tie two settings that can move apart; leaving it
#: as a literal would move p-values without moving the digest.
SPA_HAC_LAGS: Final = 5
#: The frozen resampling seed. Every producer passes it; it is stated once here so the
#: inference configuration digest can cover it.
DEFAULT_SEED: Final = 650
DEFAULT_BLOCK_MEAN: Final = 5.0
#: Primary block length for the session bootstrap, fixed in advance.
SESSION_BLOCK_LENGTH: Final = 5
#: Test size and target power for every reported minimum detectable effect.
DEFAULT_ALPHA: Final = 0.05
DEFAULT_POWER: Final = 0.80
#: Equivalence margin, as a fraction of the base model's own loss level. Fixed in advance
#: and deliberately not a function of the observed dispersion: a margin that widens with
#: the noise would declare every noisy result equivalent to zero.
EQUIVALENCE_FRACTION: Final = 0.01


def clark_west_terms(
    actual: FloatArray,
    restricted: FloatArray,
    unrestricted: FloatArray,
    *,
    nested_linear: bool,
) -> FloatArray:
    """Per-observation Clark-West adjusted loss difference for nested LINEAR models.

    ``f_t = e_0t^2 - [e_1t^2 - (yhat_0t - yhat_1t)^2]``.  The final term removes the
    downward bias that plain Diebold-Mariano suffers when the larger model nests the
    smaller one and the extra parameters are estimated noise under the null.

    ``nested_linear`` must be asserted by the caller and is not a formality. The Clark-West
    adjustment is derived for a linear model whose restricted form is a parameter
    restriction of the unrestricted one. A boosted tree fitted on a larger feature set does
    not nest the tree fitted on the smaller one - the two are different function classes,
    not a parameter restriction - so the adjustment has no justification there and inflates
    the statistic. Applying it to a tree pair silently manufactures significance.
    """

    if not nested_linear:
        raise ValueError("RP2_CW_REQUIRES_NESTED_LINEAR")
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
    # Equal weight per session. Weighting by the number of origins would let a busy day
    # speak louder than a quiet one and an early close speak less than a full session,
    # which is a statement about liquidity, not about predictive accuracy.
    overall = float(np.mean(means))
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


def aggregate_by_session(values: FloatArray, sessions: IntArray) -> tuple[FloatArray, IntArray]:
    """Collapse per-origin values to one mean per session, in session order.

    Origins five minutes apart share overlapping thirty-minute targets, so they are not
    independent draws. Testing them as if they were understates every standard error by
    roughly the square root of the origins per day. Aggregating first makes the unit of
    observation the session, which is the level at which the blocks are actually
    exchangeable.
    """

    if values.shape != sessions.shape:
        raise ValueError("RP2_INFERENCE_SHAPE_MISMATCH")
    finite = np.isfinite(values)
    values, sessions = values[finite], sessions[finite]
    labels = np.unique(sessions)
    means = np.array([values[sessions == label].mean() for label in labels], dtype=np.float64)
    return means, labels


def session_block_draws(
    session_values: FloatArray,
    *,
    block_length: int = SESSION_BLOCK_LENGTH,
    repetitions: int = DEFAULT_BOOTSTRAP,
    seed: int = DEFAULT_SEED,
) -> FloatArray:
    """Circular block resamples of a session series, one row per repetition.

    Whole sessions travel in blocks of ``block_length`` so that the serial dependence in
    the loss differential survives the resample. Returned rather than reduced so that a
    caller - or a test - can check that every value in a resample is a session that
    actually occurred, and that consecutive sessions stayed together.
    """

    size = session_values.size
    if size < 3 or block_length < 1:
        raise ValueError("RP2_INFERENCE_BOOTSTRAP_PARAMS_INVALID")
    generator = np.random.default_rng(seed)
    blocks = int(np.ceil(size / block_length))
    starts = generator.integers(0, size, size=(repetitions, blocks))
    offsets = (starts[:, :, None] + np.arange(block_length)[None, None, :]) % size
    indices = offsets.reshape(repetitions, -1)[:, :size]
    return np.asarray(session_values[indices], dtype=np.float64)


def session_block_bootstrap(
    session_values: FloatArray,
    *,
    block_length: int = 5,
    repetitions: int = DEFAULT_BOOTSTRAP,
    seed: int = DEFAULT_SEED,
) -> dict[str, float]:
    """Circular block bootstrap over whole sessions.

    Blocks rather than individual sessions because the loss differential is serially
    correlated across days; resampling single sessions would destroy that dependence and
    return an interval that is too narrow.
    """

    draws = session_block_draws(
        session_values, block_length=block_length, repetitions=repetitions, seed=seed
    )
    size = session_values.size
    estimates = draws.mean(axis=1)
    lower, upper = np.quantile(estimates, [0.025, 0.975])
    nonpositive = (float(np.count_nonzero(estimates <= 0.0)) + 1.0) / (repetitions + 1.0)
    nonnegative = (float(np.count_nonzero(estimates >= 0.0)) + 1.0) / (repetitions + 1.0)
    return {
        "estimate": float(session_values.mean()),
        "ci_low": float(lower),
        "ci_high": float(upper),
        "p_value_two_sided": min(1.0, 2.0 * min(nonpositive, nonnegative)),
        "sessions": float(size),
        "block_length": float(block_length),
    }


def wild_cluster_bootstrap(
    session_values: FloatArray,
    *,
    repetitions: int = DEFAULT_BOOTSTRAP,
    seed: int = DEFAULT_SEED,
) -> float:
    """Two-sided p-value for a zero session mean under Rademacher wild weights.

    The null is imposed by centring the session series before the weights are applied, so
    the reference distribution is what the statistic would look like if the increment were
    exactly zero. With a few dozen sessions the asymptotic t-distribution is optimistic;
    this is not.
    """

    values = session_values[np.isfinite(session_values)]
    size = values.size
    if size < 3 or repetitions < 1:
        raise ValueError("RP2_INFERENCE_BOOTSTRAP_PARAMS_INVALID")
    centred = values - values.mean()
    spread = float(np.std(values, ddof=1))
    if spread <= 0.0:
        return 1.0
    observed = abs(float(values.mean()) / (spread / math.sqrt(size)))
    generator = np.random.default_rng(seed)
    weights = generator.choice(np.array([-1.0, 1.0]), size=(repetitions, size))
    samples = weights * centred[None, :]
    means = samples.mean(axis=1)
    spreads = np.std(samples, axis=1, ddof=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        statistics = np.abs(means / (spreads / math.sqrt(size)))
    exceed = int(np.count_nonzero(statistics >= observed))
    return (exceed + 1.0) / (repetitions + 1.0)


def minimum_detectable_effect(
    session_values: FloatArray,
    *,
    alpha: float = DEFAULT_ALPHA,
    power: float = DEFAULT_POWER,
    lags: int = SESSION_BLOCK_LENGTH,
) -> float:
    """The smallest mean this many sessions of this much noise could have detected.

    A null without one is uninterpretable: it does not distinguish "the increment is
    absent" from "the design could never have seen it".
    """

    values = session_values[np.isfinite(session_values)]
    size = values.size
    if size < 3 or not 0.0 < alpha < 1.0 or not 0.0 < power < 1.0:
        raise ValueError("RP2_INFERENCE_POWER_PARAMS_INVALID")
    # The same long-run variance the interval is built from. An IID standard error on a
    # series the block bootstrap treats as dependent would understate the effect this
    # design could detect, and so overstate how informative its nulls are.
    long_run = newey_west_variance(values, lags=lags)
    standard_error = math.sqrt(max(long_run, 0.0) / size)
    if standard_error <= 0.0:
        standard_error = float(np.std(values, ddof=1)) / math.sqrt(size)
    degrees = size - 1
    return float(
        (stats.t.ppf(1.0 - alpha / 2.0, df=degrees) + stats.t.ppf(power, df=degrees))
        * standard_error
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


def session_giacomini_white(
    loss_difference: FloatArray, conditioners: FloatArray, sessions: IntArray
) -> ConditionalTest:
    """Giacomini-White on one row per session.

    Cluster-robust standard errors correct the uncertainty of a per-origin regression;
    they do not correct its weighting. A session with more five-minute origins would still
    pull the coefficients, and so the Wald statistic, further than a quiet one. The
    difference and every conditioner are averaged within the session first, which leaves
    one observation per cluster and a heteroskedasticity-robust covariance over sessions.
    """

    if loss_difference.shape[0] != conditioners.shape[0]:
        raise ValueError("RP2_INFERENCE_SHAPE_MISMATCH")
    aggregated_difference, labels = aggregate_by_session(loss_difference, sessions)
    columns = [
        aggregate_by_session(conditioners[:, column], sessions)[0]
        for column in range(conditioners.shape[1])
    ]
    return giacomini_white(aggregated_difference, np.column_stack(columns), labels)


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
    #: Sessions, not origins. The sample size the p-value was computed on.
    observations: int


def model_family_of(name: str) -> str:
    """The family part of a ``family|information_set`` candidate label."""

    return name.split("|", 1)[0]


def assert_family_matched(names: Sequence[str]) -> None:
    """Every candidate in one SPA must belong to the same model family.

    A family compared against itself across information sets isolates the information. A
    family compared against a different family across information sets confounds the two,
    and the winner of that race is a statement about estimators, not about B1 or B2.
    """

    families = sorted({model_family_of(name) for name in names})
    if len(families) > 1:
        raise ValueError(f"RP2_INFERENCE_FAMILY_MISMATCH:{','.join(families)}")


def hansen_spa(
    benchmark_losses: FloatArray,
    candidate_losses: dict[str, FloatArray],
    *,
    sessions: IntArray,
    benchmark_name: str | None = None,
    repetitions: int = DEFAULT_BOOTSTRAP,
    block_mean: float = DEFAULT_BLOCK_MEAN,
    seed: int = DEFAULT_SEED,
) -> SuperiorPredictiveAbility:
    """Test whether *any* candidate genuinely beats the benchmark, after selection.

    ``d_k = L(benchmark) - L(candidate_k)``; positive favours the candidate.  Both the SPA
    (studentised, with Hansen's recentring) and the plain Reality Check statistic are
    returned, because they differ exactly when a poor candidate inflates the null.
    """

    if not candidate_losses:
        raise ValueError("RP2_INFERENCE_NO_CANDIDATES")
    names = sorted(candidate_losses)
    assert_family_matched([*names, *([benchmark_name] if benchmark_name else [])])
    differences = np.column_stack([benchmark_losses - candidate_losses[name] for name in names])
    if sessions.shape[0] != differences.shape[0]:
        raise ValueError("RP2_INFERENCE_SHAPE_MISMATCH")
    finite = np.isfinite(differences).all(axis=1)
    differences, session_labels = differences[finite], sessions[finite]
    # The unit of observation is the trading session. Five-minute origins share
    # overlapping thirty-minute targets, so a per-origin SPA would be testing a sample it
    # does not have.
    differences = np.column_stack(
        [
            aggregate_by_session(differences[:, column], session_labels)[0]
            for column in range(differences.shape[1])
        ]
    )
    size = differences.shape[0]
    if size < 20:
        raise ValueError("RP2_INFERENCE_TOO_FEW_OBSERVATIONS")
    means = differences.mean(axis=0)
    variances = np.array(
        [
            max(newey_west_variance(differences[:, k], lags=SPA_HAC_LAGS), 1e-18)
            for k in range(len(names))
        ]
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
        observations=size,
    )


@dataclass(frozen=True, slots=True)
class SessionContrast:
    """One nested contrast, measured at the session level, with what it took to measure it.

    The fields are the ones the plan requires an artifact to carry, and they are carried
    together on purpose: an estimate without the mask it was scored on, the family it came
    from, or the smallest effect the design could have detected is a number nobody can
    check.
    """

    estimate: float
    ci_low: float
    ci_high: float
    p_value: float
    sessions: int
    block_length: int
    common_mask_sha256: str
    model_family: str
    base_information_set: str
    expanded_information_set: str
    mde: float
    equivalence_bound: float
    newey_west_p_value: float
    wild_cluster_p_value: float
    equivalent: bool

    def as_record(self) -> dict[str, object]:
        """The artifact row, with every field the plan names."""

        return {
            "estimate": self.estimate,
            "ci_low": self.ci_low,
            "ci_high": self.ci_high,
            "p_value": self.p_value,
            "sessions": self.sessions,
            "block_length": self.block_length,
            "common_mask_sha256": self.common_mask_sha256,
            "model_family": self.model_family,
            "base_information_set": self.base_information_set,
            "expanded_information_set": self.expanded_information_set,
            "mde": self.mde,
            "equivalence_bound": self.equivalence_bound,
            "newey_west_p_value": self.newey_west_p_value,
            "wild_cluster_p_value": self.wild_cluster_p_value,
            "equivalent": self.equivalent,
        }


def newey_west_p_value(session_values: FloatArray, *, lags: int = SESSION_BLOCK_LENGTH) -> float:
    """Two-sided p-value for a zero mean using a Bartlett long-run variance."""

    size = session_values.size
    if size < 3:
        raise ValueError("RP2_INFERENCE_TOO_FEW_OBSERVATIONS")
    variance = newey_west_variance(session_values, lags=lags)
    if variance <= 0.0:
        return 1.0
    statistic = float(session_values.mean()) / math.sqrt(variance / size)
    return float(2.0 * stats.norm.sf(abs(statistic)))


def session_contrast(
    base_losses: FloatArray,
    expanded_losses: FloatArray,
    sessions: IntArray,
    *,
    model_family: str,
    base_information_set: str,
    expanded_information_set: str,
    common_mask_sha256: str,
    block_length: int = SESSION_BLOCK_LENGTH,
    repetitions: int = DEFAULT_BOOTSTRAP,
    seed: int = DEFAULT_SEED,
    alpha: float = DEFAULT_ALPHA,
    power: float = DEFAULT_POWER,
    equivalence_bound: float | None = None,
) -> SessionContrast:
    """Measure one nested increment on the session series and record what produced it.

    ``d_bar_d`` is the mean loss difference inside session ``d``; inference runs on the
    series of those means and on nothing else. Both losses must already have been computed
    on the same rows - the common evaluation mask whose digest is passed in - because a
    base model scored on rows the expanded model dropped is not a nested comparison.
    """

    if len(common_mask_sha256) != 64:
        raise ValueError("RP2_INFERENCE_MASK_DIGEST_INVALID")
    if base_losses.shape != expanded_losses.shape or base_losses.shape != sessions.shape:
        raise ValueError("RP2_INFERENCE_SHAPE_MISMATCH")
    difference = base_losses - expanded_losses
    session_values, labels = aggregate_by_session(difference, sessions)
    if labels.size < 3:
        raise ValueError("RP2_INFERENCE_TOO_FEW_CLUSTERS")
    blocked = session_block_bootstrap(
        session_values, block_length=block_length, repetitions=repetitions, seed=seed
    )
    detectable = minimum_detectable_effect(session_values, alpha=alpha, power=power)
    # The margin is a fraction of the base model's loss level, not of the spread of the
    # differences. Tying it to the spread would make a noisier sample easier to call
    # equivalent, which is the opposite of what the sample supports.
    bound = (
        float(equivalence_bound)
        if equivalence_bound is not None
        else EQUIVALENCE_FRACTION * float(np.mean(base_losses[np.isfinite(base_losses)]))
    )
    if not bound > 0.0:
        raise ValueError("RP2_INFERENCE_EQUIVALENCE_BOUND_INVALID")
    return SessionContrast(
        estimate=float(session_values.mean()),
        ci_low=float(blocked["ci_low"]),
        ci_high=float(blocked["ci_high"]),
        p_value=float(blocked["p_value_two_sided"]),
        sessions=int(labels.size),
        block_length=int(block_length),
        common_mask_sha256=common_mask_sha256,
        model_family=model_family,
        base_information_set=base_information_set,
        expanded_information_set=expanded_information_set,
        mde=detectable,
        equivalence_bound=bound,
        newey_west_p_value=newey_west_p_value(session_values),
        wild_cluster_p_value=wild_cluster_bootstrap(
            session_values, repetitions=repetitions, seed=seed
        ),
        # Equivalence in the TOST sense: the whole interval lies inside the smallest
        # effect this design could have detected, so the null is informative rather than
        # merely quiet.
        equivalent=bool(float(blocked["ci_low"]) > -bound and float(blocked["ci_high"]) < bound),
    )


def inference_config_digest() -> str:
    """A digest of the settings every contrast is computed under.

    Distinct from the model configuration and from the run's scientific hash: neither of
    those lets a reader ask whether two published contrasts were tested the same way. The
    block length, the number of bootstrap repetitions, the stationary block mean, the test
    size, the target power and the equivalence margin are what decide that.
    """

    return hashlib.sha256(inference_config_payload().encode("utf-8")).hexdigest()


def inference_config_payload() -> str:
    """The settings themselves, canonically encoded. Separated so a test can read them."""

    configuration = {
        "session_block_length": SESSION_BLOCK_LENGTH,
        # The seed decides which resamples the bootstrap draws, so two contrasts computed
        # under different seeds are not computed the same way even when every other setting
        # matches.
        "bootstrap_seed": DEFAULT_SEED,
        "bootstrap_repetitions": DEFAULT_BOOTSTRAP,
        "spa_repetitions": SPA_REPETITIONS,
        "spa_hac_lags": SPA_HAC_LAGS,
        "block_mean": DEFAULT_BLOCK_MEAN,
        "alpha": DEFAULT_ALPHA,
        "power": DEFAULT_POWER,
        "equivalence_fraction": EQUIVALENCE_FRACTION,
    }
    return json.dumps(configuration, sort_keys=True, separators=(",", ":"))
