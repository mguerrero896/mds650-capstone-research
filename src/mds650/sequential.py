"""Sequential-multiplicity control for future campaigns (decision 64).

Within-campaign Holm cannot remove the bias of LAUNCHING campaign k+1 after
seeing campaign k. These primitives make that sequence explicitly costly:

- ``alpha_spending_schedule``: alpha_k = alpha_total / (k (k + 1)); the sum over
  an OPEN-ENDED sequence of campaigns is exactly alpha_total.
- ``e_value_from_likelihood_ratio`` / ``test_martingale``: multiplicative
  evidence that stays valid under optional stopping and optional continuation.
- ``always_valid_p_value``: p = 1 / max_k M_k, valid at every look simultaneously
  (Ville's inequality).

Every function is pure and deterministic; the binding usage rules live in
docs/sequential_multiplicity_policy_v1.md.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

__all__ = [
    "alpha_spending_schedule",
    "always_valid_p_value",
    "e_value_from_likelihood_ratio",
    "test_martingale",
]


def alpha_spending_schedule(alpha_total: float, campaigns: int) -> list[float]:
    """Per-campaign alpha budget ``alpha_total / (k (k + 1))`` for k = 1..n.

    The infinite series telescopes to ``alpha_total``, so family-wise error is
    controlled even if the sequence of campaigns never closes.

    Raises
    ------
    ValueError
        ``SEQUENTIAL_ALPHA_INVALID`` for alpha outside (0, 1);
        ``SEQUENTIAL_CAMPAIGNS_INVALID`` for a non-positive count.
    """
    if not 0.0 < alpha_total < 1.0 or not math.isfinite(alpha_total):
        raise ValueError("SEQUENTIAL_ALPHA_INVALID")
    if campaigns < 1:
        raise ValueError("SEQUENTIAL_CAMPAIGNS_INVALID")
    return [alpha_total / (k * (k + 1)) for k in range(1, campaigns + 1)]


def e_value_from_likelihood_ratio(
    log_likelihood_alt: float, log_likelihood_null: float
) -> float:
    """E-value = likelihood ratio of a PRE-REGISTERED alternative vs the null.

    Under the null its expectation is at most 1, so ``1/e`` bounds the p-value
    and e-values from independent campaigns MULTIPLY.
    """
    if not (math.isfinite(log_likelihood_alt) and math.isfinite(log_likelihood_null)):
        raise ValueError("SEQUENTIAL_LOGLIK_INVALID")
    return math.exp(log_likelihood_alt - log_likelihood_null)


def test_martingale(e_values: Sequence[float]) -> list[float]:
    """Running product ``M_k`` of per-campaign e-values (a test martingale).

    Valid under optional stopping: the sequence may be extended or stopped at
    any point without invalidating the evidence level.
    """
    if not e_values:
        raise ValueError("SEQUENTIAL_EVALUES_EMPTY")
    running: list[float] = []
    product = 1.0
    for value in e_values:
        if value <= 0.0 or not math.isfinite(value):
            raise ValueError("SEQUENTIAL_EVALUE_INVALID")
        product *= value
        running.append(product)
    return running


def always_valid_p_value(e_values: Sequence[float]) -> float:
    """Always-valid p-value ``min(1, 1 / max_k M_k)`` over the whole sequence.

    By Ville's inequality this is a valid p-value SIMULTANEOUSLY at every look,
    which is exactly the guarantee a post-hoc sequence of campaigns needs.
    """
    peak = max(test_martingale(e_values))
    return min(1.0, 1.0 / peak)
