"""Contract tests for Mincer-Zarnowitz calibration and recalibration."""

from __future__ import annotations

import numpy as np
import pytest

from mds650 import calibration
from mds650.metrics import qlike_losses


def test_mincer_zarnowitz_recovers_known_coefficients() -> None:
    rng = np.random.default_rng(11)
    truth = np.exp(rng.normal(-10.0, 1.0, size=5000))
    forecast = np.exp((np.log(truth) - 0.8) / 1.25 + rng.normal(0.0, 0.01, size=5000))
    fit = calibration.mincer_zarnowitz(truth, forecast)
    assert float(fit["slope"]) == pytest.approx(1.25, abs=0.02)
    assert float(fit["intercept"]) == pytest.approx(0.8, abs=0.05)
    assert float(fit["r_squared"]) > 0.98


def test_calibrated_forecast_passes_joint_test() -> None:
    rng = np.random.default_rng(12)
    forecast = np.exp(rng.normal(-10.0, 1.0, size=2000))
    truth = forecast * np.exp(rng.normal(0.0, 0.05, size=2000))
    fit = calibration.mincer_zarnowitz(truth, forecast)
    assert float(fit["slope"]) == pytest.approx(1.0, abs=0.02)
    assert float(fit["wald_joint"]) < 20.0


def test_recalibration_repairs_multiplicative_bias() -> None:
    rng = np.random.default_rng(13)
    truth = np.exp(rng.normal(-10.0, 0.8, size=4000))
    biased = truth * 7.0 * np.exp(rng.normal(0.0, 0.10, size=4000))
    train, evaluate = slice(0, 2000), slice(2000, 4000)
    fit = calibration.mincer_zarnowitz(truth[train], biased[train])
    corrected = calibration.recalibrate(
        biased[evaluate],
        intercept=float(fit["intercept"]),
        slope=float(fit["slope"]),
        sigma2=float(fit["sigma2"]),
    )
    raw_loss = float(qlike_losses(truth[evaluate], biased[evaluate]).mean())
    fixed_loss = float(qlike_losses(truth[evaluate], corrected).mean())
    assert fixed_loss < raw_loss / 2.0
    assert float(np.median(corrected / truth[evaluate])) == pytest.approx(1.0, abs=0.15)


def test_input_contracts() -> None:
    with pytest.raises(ValueError, match="CALIBRATION_REQUIRES_POSITIVE_VALUES"):
        calibration.mincer_zarnowitz([1.0, -1.0, 2.0], [1.0, 1.0, 1.0])
    with pytest.raises(ValueError, match="CALIBRATION_ARRAY_SHAPE_INVALID"):
        calibration.mincer_zarnowitz([1.0, 2.0], [1.0, 2.0])
    with pytest.raises(ValueError, match="CALIBRATION_DEGENERATE_FORECAST"):
        calibration.mincer_zarnowitz([1.0, 2.0, 3.0], [1.0, 1.0, 1.0])
    with pytest.raises(ValueError, match="CALIBRATION_COEFFICIENTS_INVALID"):
        calibration.recalibrate([1.0], intercept=0.0, slope=1.0, sigma2=-1.0)
