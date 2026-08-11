from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import polars as pl
import pytest

from mds650.phase6 import (
    B0V2_FEATURES,
    B1V2A_FEATURES,
    B2V2_FEATURES,
    build_phase6_preregistration,
)
from mds650.phase6_evaluation import (
    add_training_volatility_regime,
    authorize_phase6_oos,
    forecast_phase6_fold,
    phase6_contrast,
    phase6_fold_definitions,
    phase6_information_sets,
    replace_phase6_features,
    select_phase6_parameters,
    validate_phase6_evaluation_panel,
)
from mds650.temporal_validation import FoldDefinition


def _preregistration() -> dict[str, Any]:
    """Return a production-shaped contract without commercial evidence files."""
    hash_value = "0" * 64
    return build_phase6_preregistration(
        {
            "branch": "test-phase6-evaluation",
            "repository_commit": "0" * 40,
            "python_version": "3.12.0",
            "uv_lock_sha256": hash_value,
            "design_sha256": hash_value,
            "spec_sha256": hash_value,
            "plan_sha256": hash_value,
            "tasks_sha256": hash_value,
            "analysis_sha256": hash_value,
            "phase6_source_sha256": hash_value,
            "schema_sha256": hash_value,
            "worktree_dirty": False,
        }
    )


def _valid_panel(preregistration: dict[str, Any]) -> pl.DataFrame:
    dates = sorted(
        {
            str(day)
            for fold in preregistration["folds"]
            for key in ("train_dates", "test_dates")
            for day in fold[key]
        }
    )
    rows = []
    for day in dates:
        for asset in preregistration["outcome_assets"]:
            origin = datetime.fromisoformat(day).replace(tzinfo=UTC) + timedelta(
                hours=14, minutes=35
            )
            rows.append(
                {
                    "origin_id": f"{asset}:{origin.isoformat()}",
                    "asset": asset,
                    "session_date": day,
                    "forecast_origin_utc": origin,
                    "rv30": 0.001,
                    "common_complete": True,
                    **{
                        name: asset if name == "b0v2_asset_identity" else 0.1
                        for name in phase6_information_sets()["B2v2"]
                    },
                }
            )
    return pl.DataFrame(rows)


def test_phase6_information_sets_are_strictly_nested() -> None:
    sets = phase6_information_sets()

    assert sets["B0v2"] == B0V2_FEATURES
    assert sets["B1v2a"] == (*B0V2_FEATURES, *B1V2A_FEATURES)
    assert sets["B2v2"] == (
        *B0V2_FEATURES,
        *B1V2A_FEATURES,
        *B2V2_FEATURES,
    )
    assert all("rv30" not in name.lower() for names in sets.values() for name in names)


def test_phase6_folds_match_frozen_expanding_dates() -> None:
    folds = phase6_fold_definitions(_preregistration())

    assert len(folds) == 5
    assert [fold.fold for fold in folds] == [1, 2, 3, 4, 5]
    assert [fold.train_end.isoformat() for fold in folds] == [
        "2025-10-27",
        "2025-11-24",
        "2025-12-23",
        "2026-01-23",
        "2026-02-23",
    ]
    assert [fold.test_start.isoformat() for fold in folds] == [
        "2025-10-28",
        "2025-11-25",
        "2025-12-24",
        "2026-01-26",
        "2026-02-24",
    ]


def test_phase6_evaluation_guard_rejects_noncommon_or_duplicate_rows() -> None:
    preregistration = _preregistration()
    row = {
        "origin_id": "AAPL:2025-08-04T13:35:00Z",
        "asset": "AAPL",
        "session_date": "2025-08-04",
        "forecast_origin_utc": "2025-08-04T13:35:00Z",
        "rv30": 0.001,
        "common_complete": False,
        **{
            name: "AAPL" if name == "b0v2_asset_identity" else 0.1
            for name in phase6_information_sets()["B2v2"]
        },
    }
    frame = pl.DataFrame([row])

    with pytest.raises(ValueError, match="PHASE6_EVALUATION_PANEL_INVALID"):
        validate_phase6_evaluation_panel(frame, preregistration)

    duplicate = pl.concat(
        [frame.with_columns(pl.lit(True).alias("common_complete"))] * 2
    )
    with pytest.raises(ValueError, match="PHASE6_EVALUATION_PANEL_INVALID"):
        validate_phase6_evaluation_panel(duplicate, preregistration)


def test_phase6_evaluation_guard_accepts_exact_registered_sessions() -> None:
    preregistration = _preregistration()
    panel = _valid_panel(preregistration)

    validated = validate_phase6_evaluation_panel(panel, preregistration)

    assert validated.height == 960
    assert validated["session_date"].n_unique() == 160


def test_phase6_gamma_selection_and_forecast_are_positive() -> None:
    preregistration = _preregistration()
    features = phase6_information_sets()["B0v2"]
    rows = []
    for index in range(25):
        day = (datetime(2025, 8, 4, tzinfo=UTC) + timedelta(days=index)).date()
        origin = datetime.combine(day, datetime.min.time(), tzinfo=UTC) + timedelta(
            hours=14, minutes=35
        )
        rows.append(
            {
                "origin_id": f"AAPL:{origin.isoformat()}",
                "asset": "AAPL",
                "session_date": day.isoformat(),
                "forecast_origin_utc": origin,
                "session_tercile": "first",
                "volatility_regime": "normal",
                "rv30": 0.001 + index / 1_000_000,
                **{
                    name: "AAPL"
                    if name == "b0v2_asset_identity"
                    else 0.1 + index / 100.0
                    for name in features
                },
            }
        )
    frame = pl.DataFrame(rows)
    fold = FoldDefinition(
        fold=1,
        train_end=datetime(2025, 8, 26, tzinfo=UTC).date(),
        test_start=datetime(2025, 8, 27, tzinfo=UTC).date(),
        test_end=datetime(2025, 8, 28, tzinfo=UTC).date(),
    )

    selected, ledger = select_phase6_parameters(
        frame.head(23),
        fold=fold,
        information_set="B0v2",
        features=features,
        role="gamma_glm_confirmatory",
        preregistration=preregistration,
    )
    forecasts = forecast_phase6_fold(
        frame.head(23),
        frame.tail(2),
        fold=fold,
        information_set="B0v2",
        features=features,
        role="gamma_glm_confirmatory",
        parameters=selected,
        preregistration=preregistration,
    )

    assert len(ledger) == 4
    assert sum(bool(row["selected"]) for row in ledger) == 1
    assert forecasts.height == 2
    minimum_forecast = forecasts["forecast"].min()
    assert isinstance(minimum_forecast, int | float)
    assert minimum_forecast > 0
    assert forecasts["qlike_loss"].is_finite().all()
    assert forecasts["volatility_regime"].to_list() == ["normal", "normal"]


def test_phase6_contrast_is_paired_by_origin_and_day() -> None:
    preregistration = _preregistration()
    preregistration["inference"]["bootstrap_repetitions"] = 100
    rows = []
    for day_index, day in enumerate(("2025-10-28", "2025-10-29")):
        for information_set, loss in (("B0v2", 0.5), ("B1v2a", 0.3)):
            rows.append(
                {
                    "origin_id": f"AAPL:{day}",
                    "asset": "AAPL",
                    "session_date": day,
                    "fold": 1,
                    "model_role": "gamma_glm_confirmatory",
                    "information_set": information_set,
                    "qlike_loss": loss + day_index / 100.0,
                }
            )
    forecasts = pl.DataFrame(rows)

    result = phase6_contrast(
        forecasts,
        role="gamma_glm_confirmatory",
        name="delta_b1v2",
        baseline="B0v2",
        expanded="B1v2a",
        preregistration=preregistration,
    )

    assert result["estimate"] == pytest.approx(0.2)
    assert result["result_sign"] == "POSITIVE"
    assert result["observations"] == 2

    with pytest.raises(ValueError, match="PHASE6_UNPAIRED_CONTRAST"):
        phase6_contrast(
            forecasts.head(3),
            role="gamma_glm_confirmatory",
            name="delta_b1v2",
            baseline="B0v2",
            expanded="B1v2a",
            preregistration=preregistration,
        )


def test_volatility_regime_cutpoints_use_training_only() -> None:
    training = pl.DataFrame(
        {"b0v2_underlying_rv_30m": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]}
    )
    testing = pl.DataFrame(
        {
            "origin_id": ["low", "mid", "high"],
            "b0v2_underlying_rv_30m": [1.0, 3.5, 9.0],
            "rv30": [999.0, 999.0, 999.0],
        }
    )

    classified, cutpoints = add_training_volatility_regime(training, testing)
    changed, changed_cutpoints = add_training_volatility_regime(
        training, testing.with_columns(pl.lit(1e-12).alias("rv30"))
    )

    assert classified["volatility_regime"].to_list() == ["low", "normal", "high"]
    assert cutpoints == changed_cutpoints
    assert classified["volatility_regime"].equals(changed["volatility_regime"])


def test_phase6_oos_authorization_is_single_use_and_self_hashed() -> None:
    ledger = {
        "schema_version": "phase6-oos-access-1.0",
        "status": "SEALED_BEFORE_OOS",
        "oos_read_count": 0,
        "evaluation_attempt_count": 0,
        "common_panel_sha256": "panel",
        "preregistration_manifest_sha256": "prereg",
        "results_inspected": False,
    }
    from mds650.study_design import canonical_sha256

    ledger["manifest_sha256"] = canonical_sha256(ledger)

    authorized = authorize_phase6_oos(
        ledger,
        common_panel_sha256="panel",
        preregistration_manifest_sha256="prereg",
        results_exist=False,
    )

    assert authorized["status"] == "OOS_EVALUATION_IN_PROGRESS"
    assert authorized["oos_read_count"] == 1
    assert authorized["evaluation_attempt_count"] == 1

    with pytest.raises(ValueError, match="PHASE6_OOS_ACCESS_DENIED"):
        authorize_phase6_oos(
            authorized,
            common_panel_sha256="panel",
            preregistration_manifest_sha256="prereg",
            results_exist=False,
        )


def test_phase6_sensitivity_replaces_only_registered_columns() -> None:
    origin = datetime(2025, 10, 28, 14, 35, tzinfo=UTC)
    primary = pl.DataFrame(
        {
            "origin_id": ["AAPL:1"],
            "asset": ["AAPL"],
            "session_date": ["2025-10-28"],
            "forecast_origin_utc": [origin],
            "rv30": [0.001],
            "b0v2_log_spot": [4.5],
        }
    )
    sensitivity = pl.DataFrame(
        {
            "origin_id": ["AAPL:1"],
            "asset": ["AAPL"],
            "session_date": ["2025-10-28"],
            "forecast_origin_utc": [origin],
            "rv30": [0.001],
            "b0v2_log_spot": [4.4],
        }
    )

    replaced = replace_phase6_features(
        primary, sensitivity, columns=("b0v2_log_spot",)
    )

    assert replaced["b0v2_log_spot"].to_list() == [4.4]
    assert replaced["rv30"].to_list() == [0.001]

    with pytest.raises(ValueError, match="PHASE6_SENSITIVITY_TARGET_DRIFT"):
        replace_phase6_features(
            primary,
            sensitivity.with_columns(pl.lit(0.002).alias("rv30")),
            columns=("b0v2_log_spot",),
        )
