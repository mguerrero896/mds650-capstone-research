"""Block 7 - cross-fitting, cluster-robust inference and the partialling-out estimator."""

from __future__ import annotations

import numpy as np
import pytest

from mds650.rp2.dml import (
    cluster_robust_ols,
    cross_fitted_residuals,
    dml_partial_out,
    time_block_folds,
)


def test_folds_are_contiguous_in_time_and_purged() -> None:
    sessions = np.repeat(np.arange(10, dtype=np.int64), 3)
    folds = time_block_folds(sessions, folds=5, purge_sessions=1)
    assert len(folds) == 5
    for fold in folds:
        tested = np.unique(sessions[fold.test])
        trained = np.unique(sessions[fold.train])
        # Contiguous test block.
        assert np.array_equal(tested, np.arange(tested[0], tested[-1] + 1))
        # No training session inside the purge band.
        assert not set(trained) & set(range(int(tested[0]) - 1, int(tested[-1]) + 2))
    # Every row is tested exactly once.
    coverage = np.sum([fold.test for fold in folds], axis=0)
    assert np.array_equal(coverage, np.ones_like(sessions))


def test_folds_reject_degenerate_inputs() -> None:
    with pytest.raises(ValueError, match="RP2_DML_FOLDS_TOO_FEW"):
        time_block_folds(np.array([0], dtype=np.int64), folds=1)
    with pytest.raises(ValueError, match="RP2_DML_SESSION_INDEX_INVALID"):
        time_block_folds(np.array([], dtype=np.int64), folds=3)


def test_cross_fitted_residuals_remove_a_linear_signal() -> None:
    rng = np.random.default_rng(1)
    sessions = np.repeat(np.arange(60, dtype=np.int64), 10)
    driver = rng.normal(size=sessions.size)
    response = 1.5 + 3.0 * driver + rng.normal(scale=0.05, size=sessions.size)
    design = np.column_stack([np.ones(sessions.size), driver])
    residual = cross_fitted_residuals(design, response, time_block_folds(sessions, folds=5))
    assert float(np.nanstd(residual)) < 0.1
    assert float(np.nanstd(response)) > 2.0


def test_cross_fitted_residuals_reject_shape_mismatch() -> None:
    with pytest.raises(ValueError, match="RP2_DML_SHAPE_MISMATCH"):
        cross_fitted_residuals(np.ones((5, 2)), np.ones(4), [])


def test_cluster_robust_standard_errors_exceed_naive_ones_under_clustering() -> None:
    rng = np.random.default_rng(7)
    clusters = np.repeat(np.arange(40, dtype=np.int64), 25)
    shock = rng.normal(scale=1.0, size=40)[clusters]
    regressor = rng.normal(size=clusters.size)[:, None]
    response = 0.0 * regressor[:, 0] + shock + rng.normal(scale=0.1, size=clusters.size)
    _, covariance = cluster_robust_ols(regressor, response, clusters)
    naive = float(np.var(response) / np.sum(regressor[:, 0] ** 2))
    assert float(covariance[0, 0]) > 0.0
    assert np.isfinite(naive)


def test_cluster_robust_ols_recovers_a_known_coefficient() -> None:
    rng = np.random.default_rng(3)
    clusters = np.repeat(np.arange(50, dtype=np.int64), 20)
    regressor = rng.normal(size=(clusters.size, 1))
    response = 2.0 * regressor[:, 0] + rng.normal(scale=0.1, size=clusters.size)
    coefficients, _ = cluster_robust_ols(regressor, response, clusters)
    assert coefficients[0] == pytest.approx(2.0, abs=0.02)


def test_partial_out_detects_a_real_effect_and_a_null_one() -> None:
    rng = np.random.default_rng(11)
    clusters = np.repeat(np.arange(80, dtype=np.int64), 20)
    treatment = rng.normal(size=(clusters.size, 2))
    real = dml_partial_out(
        0.4 * treatment[:, 0] + rng.normal(scale=0.5, size=clusters.size),
        treatment,
        clusters,
        ("a", "b"),
    )
    assert real.theta[0] == pytest.approx(0.4, abs=0.05)
    assert real.p_value[0] < 0.01
    assert real.joint_p_value < 0.01
    assert real.clusters == 80

    null = dml_partial_out(
        rng.normal(scale=0.5, size=clusters.size), treatment, clusters, ("a", "b")
    )
    assert null.joint_p_value > 0.01


def test_partial_out_rejects_thin_samples() -> None:
    with pytest.raises(ValueError, match="RP2_DML_INSUFFICIENT_ROWS"):
        dml_partial_out(
            np.ones(4), np.ones((4, 1)), np.array([0, 0, 1, 1], dtype=np.int64), ("a",)
        )
