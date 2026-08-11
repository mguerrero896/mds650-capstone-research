from __future__ import annotations

import numpy as np
import polars as pl
import pytest

from mds650.development_models import (
    INFORMATION_SETS,
    candidate_parameter_grid,
    fit_development_candidate,
    persistence_forecast,
)


def _frame() -> pl.DataFrame:
    x = np.arange(1.0, 61.0)
    return pl.DataFrame(
        {
            "asset": ["AAPL", "MSFT"] * 30,
            "b0_spot": 100.0 + x,
            "b0_rv_5m_lag": 0.0001 + x / 1_000_000,
            "b0_rv_30m_lag": 0.0002 + x / 1_000_000,
            "b0_return_5m_lag": x / 100_000,
            "b0_volume_5m_lag": 10.0 + x,
            "b0_session_minute": x,
            "b1q_atm_iv": 0.2 + x / 1000,
            "b2_log_trade_count": 1.0 + x / 100,
            "b2_unique_contract_share": 0.2 + (x % 5) / 1_000,
            "b2_log_mean_trade_premium": 1.0 + (x % 7) / 100,
            "b2_log_max_trade_premium": 1.5 + (x % 11) / 100,
            "b2_call_put_premium_imbalance_scaled": (x % 9 - 4) / 100,
            "b2_execution_side_premium_imbalance": (x % 13 - 6) / 100,
            "b2_repeated_contract_premium_share": 0.1 + (x % 4) / 1_000,
            "b2_strike_concentration": 0.1 + (x % 6) / 1_000,
            "b2_expiry_concentration": 0.1 + (x % 8) / 1_000,
            "rv30": 0.01 + (x % 17) / 1_000 + (x % 11) / 2_000,
        }
    )


def test_information_sets_are_identical_to_phase5_contract() -> None:
    assert tuple(INFORMATION_SETS) == ("B0", "B1a", "B2")
    assert INFORMATION_SETS["B0"][0] == "asset"
    assert "b1q_atm_iv" in INFORMATION_SETS["B1a"]
    assert "b2_log_trade_count" in INFORMATION_SETS["B2"]
    assert all("rv30" not in name.lower() for names in INFORMATION_SETS.values() for name in names)


def test_persistence_uses_only_prior_30_minute_rv() -> None:
    frame = _frame()
    forecast = persistence_forecast(frame)
    assert np.array_equal(forecast, frame["b0_rv_30m_lag"].to_numpy())
    assert np.isfinite(forecast).all()
    assert (forecast > 0).all()


def test_candidate_grid_keeps_all_registered_variants() -> None:
    grid = candidate_parameter_grid("elastic_net")
    assert len(grid) == 1
    assert {float(row["l1_ratio"]) for row in grid} == {0.5}
    assert candidate_parameter_grid("ridge") == [{"alpha": 1.0}]
    assert candidate_parameter_grid("persistence") == [{}]


@pytest.mark.parametrize("model_name", ["har_rv", "ridge", "elastic_net"])
def test_log_linear_candidates_emit_positive_forecasts(model_name: str) -> None:
    frame = _frame()
    fitted = fit_development_candidate(
        frame.head(40),
        feature_columns=INFORMATION_SETS["B2"],
        model_name=model_name,
        parameters=candidate_parameter_grid(model_name)[0],
        seed=650,
    )
    predictions = fitted.predict(frame.tail(20))
    assert predictions.shape == (20,)
    assert np.isfinite(predictions).all()
    assert (predictions > 0).all()


def test_unknown_candidate_fails_closed() -> None:
    with pytest.raises(ValueError, match="UNKNOWN_DEVELOPMENT_MODEL"):
        fit_development_candidate(
            _frame(),
            feature_columns=INFORMATION_SETS["B0"],
            model_name="choose_best_result",
            parameters={},
            seed=650,
        )
