"""Block 11 - economic bridges: strategy P&L, performance statistics and risk utility."""

from __future__ import annotations

import math

import numpy as np
import pytest

from mds650.rp2.economics import (
    DeltaHedgedLeg,
    ExecutionCosts,
    apply_portfolio_constraints,
    break_even_cost,
    deflated_sharpe_ratio,
    delta_hedged_pnl,
    performance_metrics,
    risk_management_utility,
    variance_risk_strategy,
)


def test_strategy_trades_only_when_the_edge_clears_costs() -> None:
    implied = np.array([0.10, 0.10, 0.10])
    forecast = np.array([0.05, 0.10, 0.20])
    realized = np.array([0.06, 0.10, 0.18])
    cost = np.full(3, 0.01)
    run = variance_risk_strategy(implied, forecast, realized, cost_per_unit=cost, buffer=0.0)
    # Edge +0.05 -> short variance; edge 0 -> flat; edge -0.10 -> long variance.
    assert run.position.tolist() == [-1.0, 0.0, 1.0]
    assert run.gross_pnl[0] == pytest.approx(-(0.06 - 0.10))
    assert run.gross_pnl[1] == 0.0
    assert run.net_pnl[0] == pytest.approx(run.gross_pnl[0] - 0.01)
    assert run.turnover == pytest.approx(2.0)
    assert run.traded_share == pytest.approx(2 / 3)


def test_a_wider_buffer_reduces_trading() -> None:
    implied = np.full(50, 0.10)
    forecast = np.linspace(0.05, 0.15, 50)
    realized = np.full(50, 0.09)
    cost = np.full(50, 0.005)
    tight = variance_risk_strategy(implied, forecast, realized, cost_per_unit=cost, buffer=0.0)
    wide = variance_risk_strategy(implied, forecast, realized, cost_per_unit=cost, buffer=0.03)
    assert wide.turnover < tight.turnover


def test_strategy_validates_inputs() -> None:
    with pytest.raises(ValueError, match="RP2_ECON_SHAPE_MISMATCH"):
        variance_risk_strategy(
            np.ones(3), np.ones(2), np.ones(3), cost_per_unit=np.ones(3), buffer=0.0
        )
    with pytest.raises(ValueError, match="RP2_ECON_BUFFER_INVALID"):
        variance_risk_strategy(
            np.ones(3), np.ones(3), np.ones(3), cost_per_unit=np.ones(3), buffer=-1.0
        )


def test_performance_metrics_on_a_known_series() -> None:
    pnl = np.array([1.0, -1.0, 1.0, -1.0, 2.0], dtype=np.float64)
    stats_ = performance_metrics(pnl, periods_per_year=4.0)
    assert stats_.periods == 5
    assert stats_.mean == pytest.approx(0.4)
    assert stats_.hit_rate == pytest.approx(0.6)
    assert stats_.sharpe_annual == pytest.approx(2.0 * 0.4 / float(np.std(pnl, ddof=1)))
    assert stats_.max_drawdown < 0.0
    with pytest.raises(ValueError, match="RP2_ECON_SERIES_TOO_SHORT"):
        performance_metrics(np.array([1.0]))


def test_deflated_sharpe_falls_as_the_number_of_trials_grows() -> None:
    few = deflated_sharpe_ratio(0.1, trials=1, observations=500, skewness=0.0, kurtosis=3.0)
    many = deflated_sharpe_ratio(0.1, trials=500, observations=500, skewness=0.0, kurtosis=3.0)
    assert 0.0 <= many < few <= 1.0
    with pytest.raises(ValueError, match="RP2_ECON_DSR_PARAMS_INVALID"):
        deflated_sharpe_ratio(0.1, trials=0, observations=500, skewness=0.0, kurtosis=3.0)


def test_break_even_cost_is_gross_profit_per_unit_of_turnover() -> None:
    assert break_even_cost(np.array([1.0, 2.0, 3.0]), 4.0) == pytest.approx(1.5)
    assert math.isnan(break_even_cost(np.array([1.0]), 0.0))


def test_a_better_variance_forecast_improves_risk_management() -> None:
    rng = np.random.default_rng(31)
    size = 6000
    true_variance = np.exp(rng.normal(loc=-9.0, scale=0.6, size=size))
    realized_return = rng.normal(scale=np.sqrt(true_variance))
    realized_variance = realized_return**2
    good = risk_management_utility(
        true_variance,
        realized_variance,
        realized_return,
        target_variance=float(np.mean(true_variance)),
    )
    blind = risk_management_utility(
        np.full(size, float(np.mean(true_variance))),
        realized_variance,
        realized_return,
        target_variance=float(np.mean(true_variance)),
    )
    assert good.target_volatility_tracking_error < blind.target_volatility_tracking_error
    assert abs(good.var_breach_rate - 0.05) < abs(blind.var_breach_rate - 0.05)


def test_risk_utility_validates_inputs() -> None:
    with pytest.raises(ValueError, match="RP2_ECON_SHAPE_MISMATCH"):
        risk_management_utility(np.ones(3), np.ones(2), np.ones(3), target_variance=1.0)
    with pytest.raises(ValueError, match="RP2_ECON_TARGET_INVALID"):
        risk_management_utility(np.ones(3), np.ones(3), np.ones(3), target_variance=0.0)


# ------------------------------------------------------- forward contract-level economics


def _leg(**overrides: object) -> DeltaHedgedLeg:
    base: dict[str, object] = {
        "entry_option_mid": np.array([5.0]),
        "exit_option_mid": np.array([6.0]),
        "entry_spot": np.array([100.0]),
        "exit_spot": np.array([102.0]),
        "entry_delta": np.array([0.5]),
        "contracts": np.array([1.0]),
        "entry_half_spread": np.array([0.05]),
        "exit_half_spread": np.array([0.05]),
    }
    base.update(overrides)
    return DeltaHedgedLeg(**base)  # type: ignore[arg-type]


def _costs(**overrides: float) -> ExecutionCosts:
    base = {
        "half_spread_fraction": 0.0,
        "fee_per_contract": 0.65,
        "slippage_fraction_of_half_spread": 0.0,
    }
    base.update(overrides)
    return ExecutionCosts(**base)  # type: ignore[arg-type]


def test_the_hedge_removes_the_directional_move_from_the_option_leg() -> None:
    """A long call that rose only because spot rose must not book a profit.

    Option up 1.00 on a 2.00 spot move at delta 0.5 is exactly the hedge, so the gross
    delta-hedged result is zero and only costs remain.
    """

    result = delta_hedged_pnl(_leg(), _costs(fee_per_contract=0.0))
    assert result["gross_pnl"][0] == pytest.approx(0.0)
    # Both crossings are still paid.
    assert result["spread_cost"][0] == pytest.approx(0.10 * 100.0)
    assert result["net_pnl"][0] < 0.0


def test_a_move_beyond_the_hedge_is_kept() -> None:
    result = delta_hedged_pnl(_leg(exit_option_mid=np.array([7.0])), _costs(fee_per_contract=0.0))
    # One dollar of option move survives the hedge.
    assert result["gross_pnl"][0] == pytest.approx(100.0)


def test_the_spread_is_charged_on_both_legs_and_fees_on_both_sides() -> None:
    result = delta_hedged_pnl(_leg(contracts=np.array([4.0])), _costs())
    assert result["spread_cost"][0] == pytest.approx(4.0 * 0.10 * 100.0)
    assert result["fees"][0] == pytest.approx(2.0 * 4.0 * 0.65)


def test_slippage_scales_the_spread_cost() -> None:
    plain = delta_hedged_pnl(_leg(), _costs(fee_per_contract=0.0))
    slipped = delta_hedged_pnl(
        _leg(), _costs(fee_per_contract=0.0, slippage_fraction_of_half_spread=0.5)
    )
    assert slipped["spread_cost"][0] == pytest.approx(1.5 * plain["spread_cost"][0])


def test_a_short_position_reverses_the_sign_but_still_pays_costs() -> None:
    long = delta_hedged_pnl(_leg(exit_option_mid=np.array([7.0])), _costs(fee_per_contract=0.0))
    short = delta_hedged_pnl(
        _leg(exit_option_mid=np.array([7.0]), contracts=np.array([-1.0])),
        _costs(fee_per_contract=0.0),
    )
    assert short["gross_pnl"][0] == pytest.approx(-long["gross_pnl"][0])
    assert short["spread_cost"][0] == pytest.approx(long["spread_cost"][0])


def test_costs_and_shapes_are_validated() -> None:
    with pytest.raises(ValueError, match="RP2_ECON_COSTS_INVALID"):
        ExecutionCosts(-0.1, 0.0, 0.0)
    with pytest.raises(ValueError, match="RP2_ECON_SHAPE_MISMATCH"):
        delta_hedged_pnl(_leg(exit_spot=np.array([1.0, 2.0])), _costs())


def test_portfolio_constraints_cap_per_name_before_scaling_gross() -> None:
    """Scaling a concentrated book down to a gross limit leaves it just as concentrated."""

    signal = np.array([100.0, 5.0, 5.0])
    names = np.array(["AAPL", "MSFT", "NVDA"])
    out = apply_portfolio_constraints(
        signal, max_gross_contracts=20.0, max_position_per_name=10.0, names=names
    )
    assert abs(out[0]) <= 10.0 + 1e-9
    assert float(np.sum(np.abs(out))) <= 20.0 + 1e-9
    # The concentrated name no longer dominates the whole book.
    assert abs(out[0]) / float(np.sum(np.abs(out))) < 0.75


def test_portfolio_constraints_validate_their_limits() -> None:
    with pytest.raises(ValueError, match="RP2_ECON_CONSTRAINT_INVALID"):
        apply_portfolio_constraints(
            np.ones(2),
            max_gross_contracts=0.0,
            max_position_per_name=1.0,
            names=np.array(["A", "B"]),
        )
