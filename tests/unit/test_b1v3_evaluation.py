"""Frozen contracts for the additive B1v3 evaluation adapter."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

import polars as pl
import pytest

from mds650.b1v3 import B1V3A_FEATURES
from mds650.b1v3_confirmation_common import B1V3_PRIMARY_INFORMATION_SETS
from mds650.b1v3_evaluation import (
    authorize_b1v3_confirmation,
    b1v3_information_sets,
    b1v3_method_contract,
    b1v3_phase6_adapter_contract,
    build_b1v3_access_ledger,
    build_b1v3_preregistration,
    validate_b1v3_evaluation_panel,
)
from mds650.study_design import B2_FEATURE_NAMES, canonical_sha256

_SHA_A = "a" * 64
_SHA_B = "b" * 64
_SHA_C = "c" * 64
_SHA_D = "d" * 64
_ASSETS = ("AAPL", "AMZN", "META", "MSFT", "NVDA", "TSLA")


def _plan() -> dict[str, Any]:
    # Synthetic dates need only be unique and ordered within each frozen array.
    training = [f"2024-{8 + index // 20:02d}-{index % 20 + 1:02d}" for index in range(60)]
    confirmation = [f"2024-{11 + index // 20:02d}-{index % 20 + 1:02d}" for index in range(30)]
    plan: dict[str, Any] = {
        "schema_version": "1.0",
        "status": "PASS_PRISTINE_60_30_FROZEN",
        "plan_sha256": _SHA_A,
        "target_blind": True,
        "outcome_read_count": 0,
        "safe_to_read_outcomes": False,
        "training_session_count": 60,
        "confirmation_session_count": 30,
        "training_sessions": training,
        "confirmation_sessions": confirmation,
    }
    return plan


def _common_manifest() -> dict[str, Any]:
    information_sets = {
        name: {"feature_count": len(features), "features": list(features)}
        for name, features in B1V3_PRIMARY_INFORMATION_SETS.items()
    }
    manifest: dict[str, Any] = {
        "schema_version": "1.0",
        "status": "PASS_TARGET_BLIND_COMMON_PREDICTOR_PANEL",
        "manifest_sha256": _SHA_B,
        "plan_sha256": _SHA_A,
        "target_blind": True,
        "outcome_read_count": 0,
        "safe_to_read_outcomes": False,
        "safe_to_evaluate_scientifically": False,
        "evaluation_blocker": "EVALUATION_TESTS_AND_PREREGISTRATION_PENDING",
        "scope": {
            "training_session_count": 60,
            "confirmation_session_count": 30,
            "asset_count": 6,
            "assets": list(_ASSETS),
            "origin_count": 38_664,
            "origin_identity_sha256": _SHA_C,
        },
        "information_sets": information_sets,
        "output": {
            "logical_path": "MDS650_B1V3_DATA_ROOT/predictors/common_predictor_panel.parquet",
            "sha256": _SHA_D,
            "bytes": 10,
            "row_count": 38_664,
            "columns": ["origin_id", *B1V3_PRIMARY_INFORMATION_SETS["B2"]],
        },
    }
    return manifest


def _preregistration() -> dict[str, Any]:
    return build_b1v3_preregistration(
        _plan(),
        _common_manifest(),
        common_manifest_file_sha256="e" * 64,
        design_sha256="f" * 64,
        evaluation_code_sha256="1" * 64,
        uv_lock_sha256="2" * 64,
    )


def _authorization(preregistration: dict[str, Any]) -> dict[str, Any]:
    ledger = build_b1v3_access_ledger(
        preregistration,
        common_panel_sha256=_SHA_D,
        prerequisites={
            "focused_tests": True,
            "full_tests": True,
            "ruff": True,
            "mypy": True,
            "coverage": True,
            "json_schema": True,
            "no_leakage": True,
            "disk_gate": True,
        },
    )
    return authorize_b1v3_confirmation(
        ledger,
        common_panel_sha256=_SHA_D,
        preregistration_manifest_sha256=str(preregistration["manifest_sha256"]),
        results_exist=False,
    )


def test_b1v3_information_sets_are_exact_and_strictly_nested() -> None:
    sets = b1v3_information_sets()

    assert sets == B1V3_PRIMARY_INFORMATION_SETS
    assert sets["B1v3a"] == (*sets["B0"], *B1V3A_FEATURES)
    assert sets["B2"] == (*sets["B1v3a"], *B2_FEATURE_NAMES)
    assert len(sets["B0"]) == 12
    assert len(sets["B1v3a"]) == 15
    assert len(sets["B2"]) == 24


def test_b1v3_method_contract_is_frozen_without_result_selection() -> None:
    method = b1v3_method_contract()

    assert method["confirmatory"] == {
        "name": "GammaRegressor",
        "role": "gamma_glm_confirmatory",
        "link": "log_fixed_by_estimator",
        "alpha_grid": [0.0, 0.01, 0.1, 1.0],
        "max_iter": 2000,
        "tolerance": 1e-8,
    }
    assert method["robustness"]["name"] == "LGBMRegressor"
    assert method["robustness"]["role"] == "lightgbm_robustness"
    assert method["robustness"]["objective"] == "gamma"
    assert method["metrics"] == {"primary": "QLIKE", "descriptive": ["MAE", "RMSE"]}
    assert method["inference"] == {
        "bootstrap_unit": "XNYS_SESSION_DATE_WITH_ALL_ASSETS",
        "bootstrap_repetitions": 10_000,
        "multiplicity": "Holm",
        "confirmatory_family": ["delta_b1v3", "delta_b2"],
        "seed": 650,
    }
    assert method["purge_minutes"] == 30
    assert method["embargo_minutes"] == 30
    assert method["feature_or_method_selection_from_confirmation"] == "PROHIBITED"


def test_preregistration_binds_exact_panel_dates_methods_and_self_hash() -> None:
    preregistration = _preregistration()
    unsigned = {
        key: value for key, value in preregistration.items() if key != "manifest_sha256"
    }

    assert preregistration["status"] == "FROZEN_BEFORE_CONFIRMATION"
    assert preregistration["safe_to_evaluate_b1v3"] == "NO"
    assert preregistration["outcome_read_count"] == 0
    assert preregistration["confirmation_read_count"] == 0
    assert len(preregistration["training_sessions"]) == 60
    assert len(preregistration["confirmation_sessions"]) == 30
    assert not set(preregistration["training_sessions"]) & set(
        preregistration["confirmation_sessions"]
    )
    assert preregistration["common_predictor_panel_sha256"] == _SHA_D
    assert preregistration["information_sets"] == {
        name: list(features) for name, features in B1V3_PRIMARY_INFORMATION_SETS.items()
    }
    assert preregistration["manifest_sha256"] == canonical_sha256(unsigned)
    assert preregistration["retain_all_registered_signs"] is True


def test_phase6_adapter_reuses_frozen_models_and_inference() -> None:
    preregistration = _preregistration()

    adapter = b1v3_phase6_adapter_contract(preregistration)

    assert adapter == {
        "models": {
            "purge_embargo_minutes": 30,
            "confirmatory": {
                "alpha_grid": [0.0, 0.01, 0.1, 1.0],
                "max_iter": 2000,
                "tolerance": 1e-8,
            },
            "robustness": {
                "grid": {
                    "num_leaves": [7, 15],
                    "max_depth": [3, 5],
                    "learning_rate": [0.03, 0.05],
                    "n_estimators": [200, 500],
                    "min_child_samples": [50],
                    "reg_lambda": [1.0],
                }
            },
        },
        "inference": {"bootstrap_repetitions": 10_000, "seed": 650},
        "forecast_floor": 1e-12,
    }


@pytest.mark.parametrize(
    ("mutation", "error"),
    [
        (lambda plan, common: common.update(status="FAIL"), "B1V3_PREREG_COMMON_INVALID"),
        (
            lambda plan, common: common["information_sets"]["B2"]["features"].append(
                "rv30"
            ),
            "B1V3_PREREG_INFORMATION_SETS_INVALID",
        ),
        (
            lambda plan, common: plan["confirmation_sessions"].__setitem__(
                0, plan["training_sessions"][-1]
            ),
            "B1V3_PREREG_DATE_SPLIT_INVALID",
        ),
    ],
)
def test_preregistration_fails_closed_on_source_or_scope_drift(
    mutation: Any, error: str
) -> None:
    plan = _plan()
    common = _common_manifest()
    mutation(plan, common)

    with pytest.raises(ValueError, match=error):
        build_b1v3_preregistration(
            plan,
            common,
            common_manifest_file_sha256="e" * 64,
            design_sha256="f" * 64,
            evaluation_code_sha256="1" * 64,
            uv_lock_sha256="2" * 64,
        )


def test_access_ledger_requires_every_gate_and_is_single_use() -> None:
    preregistration = _preregistration()
    prerequisites = {
        "focused_tests": True,
        "full_tests": True,
        "ruff": True,
        "mypy": True,
        "coverage": True,
        "json_schema": True,
        "no_leakage": True,
        "disk_gate": True,
    }
    ledger = build_b1v3_access_ledger(
        preregistration,
        common_panel_sha256=_SHA_D,
        prerequisites=prerequisites,
    )

    assert ledger["status"] == "SEALED_BEFORE_CONFIRMATION"
    assert ledger["safe_to_evaluate_b1v3"] == "YES"
    assert ledger["confirmation_read_count"] == 0
    assert ledger["evaluation_attempt_count"] == 0

    authorized = authorize_b1v3_confirmation(
        ledger,
        common_panel_sha256=_SHA_D,
        preregistration_manifest_sha256=str(preregistration["manifest_sha256"]),
        results_exist=False,
    )
    assert authorized["status"] == "CONFIRMATION_EVALUATION_IN_PROGRESS"
    assert authorized["confirmation_read_count"] == 1
    assert authorized["evaluation_attempt_count"] == 1

    with pytest.raises(ValueError, match="B1V3_CONFIRMATION_ACCESS_DENIED"):
        authorize_b1v3_confirmation(
            authorized,
            common_panel_sha256=_SHA_D,
            preregistration_manifest_sha256=str(preregistration["manifest_sha256"]),
            results_exist=False,
        )

    incomplete = dict(prerequisites, mypy=False)
    with pytest.raises(ValueError, match="B1V3_PREREQUISITES_INCOMPLETE"):
        build_b1v3_access_ledger(
            preregistration,
            common_panel_sha256=_SHA_D,
            prerequisites=incomplete,
        )


def test_evaluation_panel_requires_authorization_identical_complete_origins() -> None:
    preregistration = _preregistration()
    authorization = _authorization(preregistration)
    features = b1v3_information_sets()["B2"]
    rows: list[dict[str, Any]] = []
    for index, role in enumerate(("development", "confirmation")):
        row: dict[str, Any] = {
            "origin_id": f"AAPL|2024-11-0{index + 1}|15:00:00Z",
            "asset": "AAPL",
            "session_date": preregistration[
                "training_sessions" if role == "development" else "confirmation_sessions"
            ][0],
            "forecast_origin_utc": datetime(2024, 11, index + 1, 15, tzinfo=UTC),
            "role": role,
            "rv30": 0.0001,
            "b0_information_set_complete": True,
            "b1v3a_information_set_complete": True,
            "b2_information_set_complete": True,
        }
        for feature in features:
            row[feature] = "AAPL" if feature == "b0v2_asset_identity" else 0.1
        rows.append(row)
    panel = pl.DataFrame(rows)

    validated = validate_b1v3_evaluation_panel(
        panel,
        preregistration=preregistration,
        authorization=authorization,
    )
    assert validated["origin_id"].to_list() == [row["origin_id"] for row in rows]

    duplicate = pl.concat([panel, panel.head(1)])
    with pytest.raises(ValueError, match="B1V3_EVALUATION_PANEL_INVALID"):
        validate_b1v3_evaluation_panel(
            duplicate,
            preregistration=preregistration,
            authorization=authorization,
        )

    future_attempt = deepcopy(authorization)
    future_attempt["confirmation_read_count"] = 2
    future_attempt["manifest_sha256"] = canonical_sha256(
        {key: value for key, value in future_attempt.items() if key != "manifest_sha256"}
    )
    with pytest.raises(ValueError, match="B1V3_CONFIRMATION_ACCESS_DENIED"):
        validate_b1v3_evaluation_panel(
            panel,
            preregistration=preregistration,
            authorization=future_attempt,
        )
