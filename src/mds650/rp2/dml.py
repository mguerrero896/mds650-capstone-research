"""Block 7 - double machine learning: does B2 survive orthogonalisation against B0+B1?

The question is not whether a model containing B2 happens to score better, but whether B2
carries information that cannot be reconstructed from B0 and B1.  The estimator is the
partialling-out form of double machine learning:

``Y~ = Y - m(B0,B1)``, ``D~ = B2 - g(B0,B1)``, then ``Y~ = theta' D~ + e``.

Both nuisance functions are cross-fitted over *time blocks* with a purge, never over random
folds, and inference is clustered by session because origins inside a day overlap.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt
from scipy import stats

type FloatArray = npt.NDArray[np.float64]
type IntArray = npt.NDArray[np.int64]


@dataclass(frozen=True, slots=True)
class TimeFold:
    """One cross-fitting fold: a contiguous test block and its purged complement."""

    train: npt.NDArray[np.bool_]
    test: npt.NDArray[np.bool_]


def time_block_folds(
    session_index: IntArray, *, folds: int, purge_sessions: int = 1
) -> list[TimeFold]:
    """Contiguous-in-time folds with a purge band on both sides of the test block.

    ``session_index`` must be a non-negative integer rank of each row's session, so rows of
    the same session always fall in the same fold and the purge removes neighbouring
    sessions whose 30-minute targets could overlap the test block.
    """

    if folds < 2:
        raise ValueError("RP2_DML_FOLDS_TOO_FEW")
    if session_index.ndim != 1 or session_index.size == 0:
        raise ValueError("RP2_DML_SESSION_INDEX_INVALID")
    unique = np.unique(session_index)
    chunks = np.array_split(unique, folds)
    out: list[TimeFold] = []
    for chunk in chunks:
        if chunk.size == 0:
            continue
        low, high = int(chunk[0]), int(chunk[-1])
        test = (session_index >= low) & (session_index <= high)
        purged = (session_index >= low - purge_sessions) & (
            session_index <= high + purge_sessions
        )
        out.append(TimeFold(train=~purged, test=test))
    return out


def cross_fitted_residuals(
    design: FloatArray, response: FloatArray, folds: list[TimeFold], *, ridge: float = 1e-6
) -> FloatArray:
    """Out-of-fold residuals of a ridge-regularised linear projection on ``design``.

    A linear learner is deliberate: with a rich, already-engineered design the partialling
    out is what matters, and a linear nuisance keeps the estimator's own regularisation
    bias out of the reported theta.
    """

    if design.shape[0] != response.size:
        raise ValueError("RP2_DML_SHAPE_MISMATCH")
    fitted = np.full(response.size, np.nan, dtype=np.float64)
    for fold in folds:
        if fold.train.sum() <= design.shape[1] or not fold.test.any():
            continue
        train_design = design[fold.train]
        gram = train_design.T @ train_design + ridge * np.eye(design.shape[1])
        coefficients = np.linalg.solve(gram, train_design.T @ response[fold.train])
        fitted[fold.test] = design[fold.test] @ coefficients
    return response - fitted


def cluster_robust_ols(
    regressors: FloatArray, response: FloatArray, clusters: IntArray
) -> tuple[FloatArray, FloatArray]:
    """OLS with a cluster-robust (CR0) covariance matrix.

    Returns ``(coefficients, covariance)``.  Clustering is by session: origins five minutes
    apart share overlapping 30-minute targets, so treating them as independent would shrink
    every standard error by roughly the square root of the origins per day.
    """

    if regressors.ndim != 2 or regressors.shape[0] != response.size:
        raise ValueError("RP2_DML_SHAPE_MISMATCH")
    if clusters.size != response.size:
        raise ValueError("RP2_DML_CLUSTER_SHAPE_MISMATCH")
    gram = regressors.T @ regressors
    inverse = np.linalg.pinv(gram)
    coefficients = inverse @ (regressors.T @ response)
    residual = response - regressors @ coefficients
    meat = np.zeros_like(gram)
    for cluster in np.unique(clusters):
        mask = clusters == cluster
        contribution = regressors[mask].T @ residual[mask]
        meat += np.outer(contribution, contribution)
    unique_clusters = int(np.unique(clusters).size)
    parameters = regressors.shape[1]
    scale = unique_clusters / max(unique_clusters - 1, 1)
    scale *= (response.size - 1) / max(response.size - parameters, 1)
    return coefficients, scale * (inverse @ meat @ inverse)


@dataclass(frozen=True, slots=True)
class DmlResult:
    """Outcome of one partialling-out test of a treatment block."""

    theta: FloatArray
    standard_error: FloatArray
    t_statistic: FloatArray
    p_value: FloatArray
    joint_statistic: float
    joint_p_value: float
    clusters: int
    rows: int
    treatment_names: tuple[str, ...]


def dml_partial_out(
    response_residual: FloatArray,
    treatment_residual: FloatArray,
    clusters: IntArray,
    treatment_names: tuple[str, ...],
) -> DmlResult:
    """Regress the residualised outcome on the residualised treatments and test theta = 0.

    The joint test is a cluster-robust Wald statistic on all treatments at once, which is
    the honest question when B2 is a block of features rather than a single variable.
    """

    finite = np.isfinite(response_residual) & np.isfinite(treatment_residual).all(axis=1)
    y = response_residual[finite]
    d = treatment_residual[finite]
    group = clusters[finite]
    if y.size < d.shape[1] + 2 or np.unique(group).size < 3:
        raise ValueError("RP2_DML_INSUFFICIENT_ROWS")
    coefficients, covariance = cluster_robust_ols(d, y, group)
    standard_error = np.sqrt(np.maximum(np.diag(covariance), 0.0))
    with np.errstate(divide="ignore", invalid="ignore"):
        t_statistic = np.where(standard_error > 0.0, coefficients / standard_error, np.nan)
    degrees = max(int(np.unique(group).size) - 1, 1)
    p_value = 2.0 * stats.t.sf(np.abs(t_statistic), df=degrees)
    wald = float(coefficients @ np.linalg.pinv(covariance) @ coefficients)
    joint_p = float(stats.chi2.sf(wald, df=d.shape[1]))
    return DmlResult(
        theta=coefficients,
        standard_error=standard_error,
        t_statistic=np.asarray(t_statistic, dtype=np.float64),
        p_value=np.asarray(p_value, dtype=np.float64),
        joint_statistic=wald,
        joint_p_value=joint_p,
        clusters=int(np.unique(group).size),
        rows=int(y.size),
        treatment_names=treatment_names,
    )
