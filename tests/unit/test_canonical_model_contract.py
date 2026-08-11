from __future__ import annotations

from datetime import UTC, datetime, timedelta

import polars as pl
import pytest

from mds650.canonical_validation import (
    CANONICAL_MODEL_ROLES,
    canonical_model_parameters,
    forecast_canonical_fold,
)
from mds650.phase6_evaluation import phase6_information_sets


def _frame(start: datetime, rows: int) -> pl.DataFrame:
    features = phase6_information_sets()["B0v2"]
    data: list[dict[str, object]] = []
    for index in range(rows):
        origin = start + timedelta(minutes=5 * index)
        record: dict[str, object] = {
            "origin_id": f"AAPL:{origin.isoformat()}",
            "asset": "AAPL",
            "session_date": origin.date().isoformat(),
            "forecast_origin_utc": origin,
            "session_tercile": "first",
            "volatility_regime": "normal",
            "rv30": 0.001 + index / 500_000 + (index % 7) / 2_000_000,
        }
        for position, feature in enumerate(features):
            record[feature] = (
                "AAPL"
                if feature == "b0v2_asset_identity"
                else 0.01
                + ((index * (position + 3)) % 19) / 1_000
                + position / 10_000
            )
        data.append(record)
    return pl.DataFrame(data)


def _frozen_parameters() -> dict[str, object]:
    return {
        "gamma_glm_confirmatory": {"alpha": 0.1, "max_iter": 2_000, "tol": 1e-8},
        "lightgbm_robustness": {
            "learning_rate": 0.03,
            "max_depth": 3,
            "min_child_samples": 5,
            "n_estimators": 10,
            "num_leaves": 7,
            "reg_lambda": 1.0,
        },
    }


def test_all_five_roles_emit_positive_finite_forecasts() -> None:
    training = _frame(datetime(2025, 1, 2, 14, 30, tzinfo=UTC), 120)
    testing = _frame(datetime(2025, 1, 3, 14, 30, tzinfo=UTC), 10)

    for role in CANONICAL_MODEL_ROLES:
        result = forecast_canonical_fold(
            training,
            testing,
            role=role,
            information_set="B0v2",
            phase6_frozen=_frozen_parameters(),
            fold=1,
        )
        assert result.height == testing.height
        assert result.get_column("forecast").is_finite().all()
        assert (result.get_column("forecast") > 0).all()
        assert result.get_column("model_role").unique().to_list() == [role]


def test_fixed_extensions_cannot_select_from_testing_rows() -> None:
    frozen = _frozen_parameters()

    assert canonical_model_parameters("ridge_fixed_extension", phase6_frozen=frozen) == {
        "alpha": 1.0
    }
    assert canonical_model_parameters(
        "elastic_net_fixed_extension", phase6_frozen=frozen
    ) == {"alpha": 0.01, "l1_ratio": 0.5}


def test_canonical_fold_rejects_test_before_training() -> None:
    training = _frame(datetime(2025, 1, 3, 14, 30, tzinfo=UTC), 20)
    testing = _frame(datetime(2025, 1, 2, 14, 30, tzinfo=UTC), 5)

    with pytest.raises(ValueError, match="CANONICAL_FOLD_TEMPORAL_ORDER_INVALID"):
        forecast_canonical_fold(
            training,
            testing,
            role="ridge_fixed_extension",
            information_set="B0v2",
            phase6_frozen=_frozen_parameters(),
            fold=1,
        )
