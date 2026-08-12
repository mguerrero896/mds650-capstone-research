"""Target-blind contracts for the nine frozen Phase 5 B2 features."""

from __future__ import annotations

import math

import polars as pl
import pytest

from mds650.phase5_features import add_compact_b2_features
from mds650.study_design import B2_FEATURE_NAMES


def _raw_row() -> dict[str, float]:
    return {
        "option_trade_count_5m": 4.0,
        "unique_contract_count_5m": 2.0,
        "total_premium_5m": 100.0,
        "max_trade_premium_5m": 50.0,
        "call_premium_5m": 70.0,
        "put_premium_5m": 30.0,
        "ask_side_premium_share": 0.60,
        "bid_side_premium_share": 0.25,
        "repeated_contract_premium": 40.0,
        "strike_concentration": 0.50,
        "expiry_concentration": 0.75,
    }


def test_compact_b2_formulas_match_hand_calculation() -> None:
    result = add_compact_b2_features(pl.DataFrame([_raw_row()])).row(0, named=True)

    assert result["b2_log_trade_count"] == pytest.approx(math.log1p(4.0))
    assert result["b2_unique_contract_share"] == pytest.approx(0.50)
    assert result["b2_log_mean_trade_premium"] == pytest.approx(math.log1p(25.0))
    assert result["b2_log_max_trade_premium"] == pytest.approx(math.log1p(50.0))
    assert result["b2_call_put_premium_imbalance_scaled"] == pytest.approx(0.40)
    assert result["b2_execution_side_premium_imbalance"] == pytest.approx(0.35)
    assert result["b2_repeated_contract_premium_share"] == pytest.approx(0.40)
    assert result["b2_strike_concentration"] == pytest.approx(0.50)
    assert result["b2_expiry_concentration"] == pytest.approx(0.75)


def test_compact_b2_zero_denominators_are_documented_zero() -> None:
    row = {key: 0.0 for key in _raw_row()}

    result = add_compact_b2_features(pl.DataFrame([row])).select(B2_FEATURE_NAMES)

    assert result.row(0) == (0.0,) * 9


def test_compact_b2_features_are_target_blind() -> None:
    low_target = pl.DataFrame([{**_raw_row(), "rv30": 0.000001}])
    high_target = pl.DataFrame([{**_raw_row(), "rv30": 1.0}])

    low = add_compact_b2_features(low_target).select(B2_FEATURE_NAMES)
    high = add_compact_b2_features(high_target).select(B2_FEATURE_NAMES)

    assert low.equals(high)


def test_compact_b2_rejects_impossible_raw_aggregates() -> None:
    invalid = {**_raw_row(), "option_trade_count_5m": -1.0}

    with pytest.raises(ValueError, match="B2_RAW_FEATURE_VALUES_INVALID"):
        add_compact_b2_features(pl.DataFrame([invalid]))
