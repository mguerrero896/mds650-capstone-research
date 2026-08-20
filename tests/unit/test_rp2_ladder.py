"""Block 8 - every ladder model must fit, predict positively, and stay out of sample."""

from __future__ import annotations

import numpy as np
import pytest

from mds650.rp2.ladder import (
    INDEPENDENT_FAMILIES,
    LADDER,
    PRIMARY_MODELS,
    partial_pooling,
)


def _panel(size: int = 900, seed: int = 17) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    driver = rng.normal(size=size)
    noise = rng.normal(scale=0.4, size=size)
    target = np.exp(-9.0 + 1.2 * driver + noise)
    design = np.column_stack([np.ones(size), driver, driver**2])
    train = np.arange(size) < int(size * 0.7)
    return design, target, train


@pytest.mark.parametrize("name", sorted(LADDER))
def test_every_model_predicts_a_positive_variance_for_all_rows(name: str) -> None:
    design, target, train = _panel()
    forecast = LADDER[name](design, target, train)
    assert forecast.shape == target.shape
    assert np.all(forecast > 0.0)
    assert np.isfinite(forecast).all()


@pytest.mark.parametrize("name", sorted(LADDER))
def test_every_model_beats_a_constant_out_of_sample(name: str) -> None:
    design, target, train = _panel()
    forecast = LADDER[name](design, target, train)
    test = ~train
    constant = np.full(target.size, float(np.mean(target[train])))
    model_error = float(np.mean((np.log(forecast[test]) - np.log(target[test])) ** 2))
    constant_error = float(np.mean((np.log(constant[test]) - np.log(target[test])) ** 2))
    assert model_error < constant_error


def test_the_ladder_spans_more_than_one_independent_family() -> None:
    families = {INDEPENDENT_FAMILIES[name] for name in LADDER}
    assert len(families) >= 3
    assert INDEPENDENT_FAMILIES["lightgbm"] != INDEPENDENT_FAMILIES["gamma_glm"]
    # Ridge and log-OLS are the same family: the program forbids counting them as two.
    assert INDEPENDENT_FAMILIES["ridge_log"] == INDEPENDENT_FAMILIES["log_ols"]


def test_partial_pooling_shrinks_noise_and_keeps_real_group_offsets() -> None:
    rng = np.random.default_rng(21)
    groups = np.repeat(np.arange(6, dtype=np.int64), 200)
    true_offset = np.array([0.8, -0.8, 0.0, 0.0, 0.4, -0.4])
    residuals = true_offset[groups] + rng.normal(scale=0.5, size=groups.size)
    train = np.ones(groups.size, dtype=bool)
    pooled = partial_pooling(residuals, groups, train)
    applied = pooled.apply(np.arange(6, dtype=np.int64))
    assert pooled.between_variance > 0.0
    # Shrunk toward zero but still ordered like the truth.
    assert np.all(np.abs(applied) <= np.abs(true_offset) + 0.15)
    assert applied[0] > applied[4] > applied[2] > applied[5] > applied[1]


def test_partial_pooling_collapses_to_zero_when_groups_are_indistinguishable() -> None:
    rng = np.random.default_rng(22)
    groups = np.repeat(np.arange(5, dtype=np.int64), 300)
    residuals = rng.normal(scale=1.0, size=groups.size)
    pooled = partial_pooling(residuals, groups, np.ones(groups.size, dtype=bool))
    assert float(np.max(np.abs(pooled.apply(np.arange(5, dtype=np.int64))))) < 0.2


def test_partial_pooling_validates_shapes_and_empty_training() -> None:
    with pytest.raises(ValueError, match="RP2_POOLING_SHAPE_MISMATCH"):
        partial_pooling(np.ones(3), np.zeros(2, dtype=np.int64), np.ones(3, dtype=bool))
    empty = partial_pooling(np.ones(3), np.zeros(3, dtype=np.int64), np.zeros(3, dtype=bool))
    assert empty.offsets == {}


def _heteroskedastic_panel(
    size: int = 1200, seed: int = 91
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Realized variance with a dispersion that changes across the state space.

    ``RV`` behaves like ``sigma^2 * chi2_k / k``: the multiplicative noise has mean one
    whatever ``k`` is, but its mean *in logs* moves with ``k``. A fit on log variance
    therefore needs a different retransformation constant in each regime, and it only has
    one. QLIKE targets the conditional mean of the variance directly and needs none.
    """

    rng = np.random.default_rng(seed)
    driver = rng.normal(size=size)
    degrees = np.where(driver < 0.0, 2, 40)
    multiplier = rng.chisquare(degrees) / degrees
    target = np.exp(-9.0 + 1.2 * driver) * multiplier
    design = np.column_stack([np.ones(size), driver, driver**2])
    train = np.arange(size) < int(size * 0.7)
    return design, target, train


def test_the_primary_models_are_frozen_and_registered() -> None:
    """The research contract names three families; all three must exist in the ladder."""

    assert PRIMARY_MODELS == ("gamma_glm", "ridge_log", "lightgbm_qlike")
    for name in PRIMARY_MODELS:
        assert name in LADDER, name
        assert name in INDEPENDENT_FAMILIES, name
    # The QLIKE booster and the log-MSE booster are the same family: reporting both as
    # independent evidence would double-count one tree ensemble.
    assert INDEPENDENT_FAMILIES["lightgbm_qlike"] == INDEPENDENT_FAMILIES["lightgbm"]


def test_the_qlike_booster_beats_the_log_mse_booster_on_qlike() -> None:
    """The reason this model exists, measured on rows neither model was fitted on."""

    from mds650.metrics import qlike_losses

    design, target, train = _heteroskedastic_panel()
    held_out = ~train
    aligned = float(
        qlike_losses(
            target[held_out], LADDER["lightgbm_qlike"](design, target, train)[held_out]
        ).mean()
    )
    log_mse = float(
        qlike_losses(target[held_out], LADDER["lightgbm"](design, target, train)[held_out]).mean()
    )
    assert aligned < log_mse, f"qlike={aligned:.6f} log_mse={log_mse:.6f}"


@pytest.mark.parametrize("name", sorted(LADDER))
def test_no_model_tunes_on_validation_sessions(name: str) -> None:
    """Corrupting the held-out targets beyond recognition must not move a single forecast.

    Any early stopping, any statistic taken over all rows, any smearing factor computed
    outside the training mask would show up here as a changed number.
    """

    design, target, train = _panel()
    baseline = LADDER[name](design, target, train)
    corrupted = target.copy()
    corrupted[~train] *= 1e6
    after = LADDER[name](design, corrupted, train)
    assert np.array_equal(baseline, after), name
