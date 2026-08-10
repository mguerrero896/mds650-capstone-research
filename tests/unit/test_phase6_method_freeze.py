from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import polars as pl
import pytest

from mds650.phase6_evaluation import (
    estimate_training_mde,
    phase6_information_sets,
    training_mde_from_forecasts,
    training_only_oof_forecasts,
)

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import freeze_phase6_method as freezer  # noqa: E402


def test_training_mde_is_deterministic_and_positive() -> None:
    effects = [-0.03, -0.01, 0.0, 0.01, 0.02, 0.04] * 10

    first = estimate_training_mde(effects, draws=10_000, seed=650)
    second = estimate_training_mde(effects, draws=10_000, seed=650)

    assert first == second
    assert first > 0


def test_training_mde_from_frozen_forecasts_is_bitwise_deterministic() -> None:
    forecasts = pl.read_parquet(
        ROOT / "artifacts/phase6/training_mde_oof_forecasts.parquet"
    )

    estimates = {
        repr(training_mde_from_forecasts(forecasts, draws=10_000, seed=650))
        for _ in range(20)
    }

    assert len(estimates) == 1


@pytest.mark.parametrize("effects", [[], [0.1], [0.0] * 10])
def test_training_mde_rejects_uninformative_samples(effects: list[float]) -> None:
    with pytest.raises(ValueError, match="PHASE6_TRAINING_MDE_INPUT_INVALID"):
        estimate_training_mde(effects, draws=100, seed=650)


def test_training_oof_forecasts_never_read_registered_oos_dates() -> None:
    preregistration = json.loads(
        (ROOT / "artifacts/phase6/preregistration.json").read_text(
            encoding="utf-8"
        )
    )
    training_dates = preregistration["folds"][0]["train_dates"]
    rows = []
    features = phase6_information_sets()["B2v2"]
    for index, day in enumerate(training_dates):
        origin = datetime.fromisoformat(day).replace(tzinfo=UTC) + timedelta(
            hours=14, minutes=35
        )
        rows.append(
            {
                "origin_id": f"AAPL:{origin.isoformat()}",
                "asset": "AAPL",
                "session_date": day,
                "forecast_origin_utc": origin,
                "session_tercile": "first",
                "rv30": 0.001 + index / 1_000_000,
                **{
                    name: "AAPL"
                    if name == "b0v2_asset_identity"
                    else 0.1 + index / 100.0
                    for name in features
                },
            }
        )

    forecasts, ledger = training_only_oof_forecasts(
        pl.DataFrame(rows), preregistration
    )

    assert forecasts["origin_id"].n_unique() == 30
    assert forecasts.height == 90
    assert set(forecasts["information_set"]) == {"B0v2", "B1v2a", "B2v2"}
    assert set(forecasts["session_date"]).isdisjoint(
        preregistration["folds"][0]["test_dates"]
    )
    assert len(ledger) == 36
    mde = training_mde_from_forecasts(
        forecasts, draws=1_000, seed=650
    )
    assert set(mde) == {"delta_b1v2", "delta_b2v2"}
    assert all(value > 0 for value in mde.values())


def test_method_freeze_rejects_any_oos_read(tmp_path: Path) -> None:
    preregistration = json.loads(
        (ROOT / "artifacts/phase6/preregistration.json").read_text(
            encoding="utf-8"
        )
    )
    preregistration["oos_read_count"] = 1
    prereg_path = tmp_path / "preregistration.json"
    prereg_path.write_text(json.dumps(preregistration), encoding="utf-8")

    with pytest.raises(RuntimeError, match="OOS_ACCESSED_BEFORE_METHOD_FREEZE"):
        freezer.build_method_freeze(tmp_path / "missing.parquet", prereg_path)
