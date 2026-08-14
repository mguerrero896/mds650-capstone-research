"""Target-blind preregistration and one-read gates for B1v3 confirmation.

This module deliberately contains no provider transport and performs no target
read by itself.  It freezes the additive B0/B1v3a/B2 contract and validates the
single authorization that a later evaluation runner must consume.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any, Final

import polars as pl

from mds650.b1v3_confirmation_common import B1V3_PRIMARY_INFORMATION_SETS
from mds650.study_design import canonical_sha256

_SHA256_LENGTH: Final = 64
_OUTCOME_ASSETS: Final[tuple[str, ...]] = (
    "AAPL",
    "AMZN",
    "META",
    "MSFT",
    "NVDA",
    "TSLA",
)
_REQUIRED_PREREQUISITES: Final[tuple[str, ...]] = (
    "focused_tests",
    "full_tests",
    "ruff",
    "mypy",
    "coverage",
    "json_schema",
    "no_leakage",
    "hygiene",
    "deterministic_replay",
    "clean_install",
    "spec_kit",
    "disk_gate",
)


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == _SHA256_LENGTH
        and all(character in "0123456789abcdef" for character in value)
    )


def _self_hash_valid(document: Mapping[str, Any]) -> bool:
    stored = document.get("manifest_sha256")
    unsigned = {key: value for key, value in document.items() if key != "manifest_sha256"}
    return _is_sha256(stored) and stored == canonical_sha256(unsigned)


def _session_array(value: object, *, expected: int) -> list[str]:
    if not isinstance(value, list) or len(value) != expected:
        raise ValueError("B1V3_PREREG_DATE_SPLIT_INVALID")
    sessions = [str(item) for item in value]
    try:
        parsed = [date.fromisoformat(item) for item in sessions]
    except ValueError as exc:
        raise ValueError("B1V3_PREREG_DATE_SPLIT_INVALID") from exc
    if parsed != sorted(set(parsed)):
        raise ValueError("B1V3_PREREG_DATE_SPLIT_INVALID")
    return sessions


def b1v3_information_sets() -> dict[str, tuple[str, ...]]:
    """Return the exact nested B1v3 confirmation information sets.

    Returns
    -------
    dict[str, tuple[str, ...]]
        Frozen B0, B1v3a and B2 predictor names in contractual order.
    """
    return {
        name: tuple(features) for name, features in B1V3_PRIMARY_INFORMATION_SETS.items()
    }


def b1v3_method_contract() -> dict[str, Any]:
    """Return the owner-approved fixed model and inference contract.

    Returns
    -------
    dict[str, Any]
        Gamma confirmatory role, fixed LightGBM grid, metrics and inference.

    Notes
    -----
    These values are copied from the already preregistered Phase 5 contract;
    confirmation outcomes cannot alter them.
    """
    return {
        "confirmatory": {
            "name": "GammaRegressor",
            "role": "gamma_glm_confirmatory",
            "link": "log_fixed_by_estimator",
            "alpha_grid": [0.0, 0.01, 0.1, 1.0],
            "max_iter": 2000,
            "tolerance": 1e-8,
        },
        "robustness": {
            "name": "LGBMRegressor",
            "role": "lightgbm_robustness",
            "objective": "gamma",
            "grid": {
                "num_leaves": [7, 15],
                "max_depth": [3, 5],
                "learning_rate": [0.03, 0.05],
                "n_estimators": [200, 500],
                "min_child_samples": [50],
                "reg_lambda": [1.0],
            },
        },
        "metrics": {"primary": "QLIKE", "descriptive": ["MAE", "RMSE"]},
        "inference": {
            "bootstrap_unit": "XNYS_SESSION_DATE_WITH_ALL_ASSETS",
            "bootstrap_repetitions": 10_000,
            "multiplicity": "Holm",
            "confirmatory_family": ["delta_b1v3", "delta_b2"],
            "seed": 650,
        },
        "purge_minutes": 30,
        "embargo_minutes": 30,
        "feature_or_method_selection_from_confirmation": "PROHIBITED",
    }


def _validate_plan_and_common(
    plan: Mapping[str, Any], common_manifest: Mapping[str, Any]
) -> tuple[list[str], list[str]]:
    training = _session_array(plan.get("training_sessions"), expected=60)
    confirmation = _session_array(plan.get("confirmation_sessions"), expected=30)
    if (
        plan.get("status") != "PASS_PRISTINE_60_30_FROZEN"
        or plan.get("target_blind") is not True
        or plan.get("outcome_read_count") != 0
        or plan.get("safe_to_read_outcomes") is not False
        or plan.get("training_session_count") != 60
        or plan.get("confirmation_session_count") != 30
        or not _is_sha256(plan.get("plan_sha256"))
        or set(training) & set(confirmation)
        or max(training) >= min(confirmation)
    ):
        raise ValueError("B1V3_PREREG_DATE_SPLIT_INVALID")
    scope = common_manifest.get("scope")
    output = common_manifest.get("output")
    if (
        common_manifest.get("status") != "PASS_TARGET_BLIND_COMMON_PREDICTOR_PANEL"
        or common_manifest.get("target_blind") is not True
        or common_manifest.get("outcome_read_count") != 0
        or common_manifest.get("safe_to_read_outcomes") is not False
        or common_manifest.get("safe_to_evaluate_scientifically") is not False
        or common_manifest.get("plan_sha256") != plan.get("plan_sha256")
        or not _is_sha256(common_manifest.get("manifest_sha256"))
        or not isinstance(scope, Mapping)
        or scope.get("training_session_count") != 60
        or scope.get("confirmation_session_count") != 30
        or scope.get("assets") != list(_OUTCOME_ASSETS)
        or not isinstance(output, Mapping)
        or not _is_sha256(output.get("sha256"))
    ):
        raise ValueError("B1V3_PREREG_COMMON_INVALID")
    expected_sets = {
        name: {"feature_count": len(features), "features": list(features)}
        for name, features in b1v3_information_sets().items()
    }
    if common_manifest.get("information_sets") != expected_sets:
        raise ValueError("B1V3_PREREG_INFORMATION_SETS_INVALID")
    return training, confirmation


def build_b1v3_preregistration(
    plan: Mapping[str, Any],
    common_manifest: Mapping[str, Any],
    *,
    common_manifest_file_sha256: str,
    design_sha256: str,
    evaluation_code_sha256: str,
    uv_lock_sha256: str,
) -> dict[str, Any]:
    """Freeze B1v3 methods and bindings before any outcome access.

    Parameters
    ----------
    plan:
        Target-blind provider-passed 60/30 confirmation plan.
    common_manifest:
        Target-blind common predictor manifest.
    common_manifest_file_sha256, design_sha256, evaluation_code_sha256,
    uv_lock_sha256:
        Exact source and environment file identities.

    Returns
    -------
    dict[str, Any]
        Deterministic, self-hashed preregistration with evaluation still closed.

    Raises
    ------
    ValueError
        If dates, source bindings, feature sets or hashes drift.
    """
    hashes = (
        common_manifest_file_sha256,
        design_sha256,
        evaluation_code_sha256,
        uv_lock_sha256,
    )
    if not all(_is_sha256(value) for value in hashes):
        raise ValueError("B1V3_PREREG_HASH_INVALID")
    training, confirmation = _validate_plan_and_common(plan, common_manifest)
    output = common_manifest["output"]
    scope = common_manifest["scope"]
    assert isinstance(output, Mapping)
    assert isinstance(scope, Mapping)
    document: dict[str, Any] = {
        "schema_version": "1.0",
        "status": "FROZEN_BEFORE_CONFIRMATION",
        "target_blind": True,
        "safe_to_evaluate_b1v3": "NO",
        "outcome_read_count": 0,
        "confirmation_read_count": 0,
        "plan_sha256": str(plan["plan_sha256"]),
        "common_predictor_manifest_sha256": str(common_manifest["manifest_sha256"]),
        "common_predictor_manifest_file_sha256": common_manifest_file_sha256,
        "common_predictor_panel_sha256": str(output["sha256"]),
        "origin_identity_sha256": str(scope["origin_identity_sha256"]),
        "outcome_assets": list(_OUTCOME_ASSETS),
        "training_sessions": training,
        "confirmation_sessions": confirmation,
        "information_sets": {
            name: list(features) for name, features in b1v3_information_sets().items()
        },
        "method": b1v3_method_contract(),
        "estimands": {
            "delta_b1v3": "QLIKE(B0)-QLIKE(B1v3a)",
            "delta_b2": "QLIKE(B1v3a)-QLIKE(B2)",
            "positive_value_favors": "EXPANDED_INFORMATION_SET",
        },
        "mde_policy": "TRAINING_ONLY_DAILY_CLUSTERS_BEFORE_CONFIRMATION",
        "timing_sensitivities": {
            "fmp_minutes": [1, 2],
            "massive_cutoff_seconds": [0, 60, 300],
            "uw_created_at_cutoff_seconds": [60, 120, 300],
        },
        "stability_dimensions": [
            "asset",
            "session_tercile",
            "training_defined_volatility_regime",
            "provider_timing_assumption",
        ],
        "one_read_policy": "EXACTLY_ONE_ANALYTICAL_CONFIRMATION_READ",
        "retain_all_registered_signs": True,
        "source_hashes": {
            "design_sha256": design_sha256,
            "evaluation_code_sha256": evaluation_code_sha256,
            "uv_lock_sha256": uv_lock_sha256,
        },
    }
    document["manifest_sha256"] = canonical_sha256(document)
    return document


def b1v3_phase6_adapter_contract(
    preregistration: Mapping[str, Any],
) -> dict[str, Any]:
    """Adapt B1v3's frozen method to existing Phase 6 primitives.

    Parameters
    ----------
    preregistration:
        Self-hashed B1v3 preregistration.

    Returns
    -------
    dict[str, Any]
        The ``models``, ``inference`` and forecast-floor keys expected by
        ``select_phase6_parameters``, ``forecast_phase6_fold`` and
        ``phase6_contrast``.

    Raises
    ------
    ValueError
        If the preregistration is not the frozen zero-read contract.
    """
    if (
        not _self_hash_valid(preregistration)
        or preregistration.get("status") != "FROZEN_BEFORE_CONFIRMATION"
        or preregistration.get("confirmation_read_count") != 0
        or preregistration.get("safe_to_evaluate_b1v3") != "NO"
        or preregistration.get("information_sets")
        != {name: list(features) for name, features in b1v3_information_sets().items()}
        or preregistration.get("method") != b1v3_method_contract()
    ):
        raise ValueError("B1V3_PREREGISTRATION_INVALID")
    method = preregistration["method"]
    assert isinstance(method, Mapping)
    confirmatory = method["confirmatory"]
    robustness = method["robustness"]
    inference = method["inference"]
    assert isinstance(confirmatory, Mapping)
    assert isinstance(robustness, Mapping)
    assert isinstance(inference, Mapping)
    return {
        "models": {
            "purge_embargo_minutes": int(method["purge_minutes"]),
            "confirmatory": {
                "alpha_grid": list(confirmatory["alpha_grid"]),
                "max_iter": int(confirmatory["max_iter"]),
                "tolerance": float(confirmatory["tolerance"]),
            },
            "robustness": {"grid": dict(robustness["grid"])},
        },
        "inference": {
            "bootstrap_repetitions": int(inference["bootstrap_repetitions"]),
            "seed": int(inference["seed"]),
        },
        "forecast_floor": 1e-12,
    }


def build_b1v3_access_ledger(
    preregistration: Mapping[str, Any],
    *,
    common_panel_sha256: str,
    method_freeze_sha256: str,
    timing_panel_manifest_sha256: str,
    quality_report_sha256: str,
    confirmation_code_sha256: str,
    uv_lock_sha256: str,
    prerequisites: Mapping[str, bool],
) -> dict[str, Any]:
    """Seal confirmation access after training-only method freeze.

    Returns
    -------
    dict[str, Any]
        Self-hashed ledger recording one training read and authorizing exactly
        one later confirmation read.

    Raises
    ------
    ValueError
        If the preregistration, panel binding, or any prerequisite is invalid.
    """
    required = set(_REQUIRED_PREREQUISITES)
    if set(prerequisites) != required or not all(prerequisites.values()):
        raise ValueError("B1V3_PREREQUISITES_INCOMPLETE")
    if (
        not _self_hash_valid(preregistration)
        or preregistration.get("status") != "FROZEN_BEFORE_CONFIRMATION"
        or preregistration.get("safe_to_evaluate_b1v3") != "NO"
        or preregistration.get("outcome_read_count") != 0
        or preregistration.get("confirmation_read_count") != 0
        or preregistration.get("common_predictor_panel_sha256") != common_panel_sha256
        or not _is_sha256(common_panel_sha256)
        or not _is_sha256(method_freeze_sha256)
        or not _is_sha256(timing_panel_manifest_sha256)
        or not _is_sha256(quality_report_sha256)
        or not _is_sha256(confirmation_code_sha256)
        or not _is_sha256(uv_lock_sha256)
    ):
        raise ValueError("B1V3_PREREGISTRATION_INVALID")
    document: dict[str, Any] = {
        "schema_version": "1.0",
        "status": "METHOD_FROZEN_BEFORE_CONFIRMATION",
        "safe_to_evaluate_b1v3": "YES",
        "outcome_read_count": 1,
        "training_read_count": 1,
        "confirmation_read_count": 0,
        "evaluation_attempt_count": 0,
        "results_inspected": False,
        "common_panel_sha256": common_panel_sha256,
        "method_freeze_sha256": method_freeze_sha256,
        "timing_panel_manifest_sha256": timing_panel_manifest_sha256,
        "quality_report_sha256": quality_report_sha256,
        "confirmation_code_sha256": confirmation_code_sha256,
        "uv_lock_sha256": uv_lock_sha256,
        "preregistration_manifest_sha256": str(preregistration["manifest_sha256"]),
        "prerequisites": dict(sorted(prerequisites.items())),
    }
    document["manifest_sha256"] = canonical_sha256(document)
    return document


def authorize_b1v3_confirmation(
    ledger: Mapping[str, Any],
    *,
    common_panel_sha256: str,
    preregistration_manifest_sha256: str,
    results_exist: bool,
) -> dict[str, Any]:
    """Atomically consume the sole B1v3 confirmation authorization.

    Returns
    -------
    dict[str, Any]
        Self-hashed in-progress ledger with both counters equal to one.

    Raises
    ------
    ValueError
        If any binding drifted, output already exists or the read was consumed.
    """
    if (
        not _self_hash_valid(ledger)
        or ledger.get("status") != "METHOD_FROZEN_BEFORE_CONFIRMATION"
        or ledger.get("safe_to_evaluate_b1v3") != "YES"
        or ledger.get("outcome_read_count") != 1
        or ledger.get("training_read_count") != 1
        or ledger.get("confirmation_read_count") != 0
        or ledger.get("evaluation_attempt_count") != 0
        or ledger.get("results_inspected") is not False
        or ledger.get("common_panel_sha256") != common_panel_sha256
        or ledger.get("preregistration_manifest_sha256")
        != preregistration_manifest_sha256
        or results_exist
    ):
        raise ValueError("B1V3_CONFIRMATION_ACCESS_DENIED")
    unsigned = {key: value for key, value in ledger.items() if key != "manifest_sha256"}
    authorized: dict[str, Any] = {
        **unsigned,
        "status": "CONFIRMATION_EVALUATION_IN_PROGRESS",
        "outcome_read_count": 2,
        "confirmation_read_count": 1,
        "evaluation_attempt_count": 1,
    }
    authorized["manifest_sha256"] = canonical_sha256(authorized)
    return authorized


def _dates_match_role(
    frame: pl.DataFrame, preregistration: Mapping[str, Any]
) -> bool:
    training = set(str(value) for value in preregistration["training_sessions"])
    confirmation = set(str(value) for value in preregistration["confirmation_sessions"])
    observed = frame.select(
        pl.col("session_date").cast(pl.String), pl.col("role").cast(pl.String)
    )
    return all(
        (role == "development" and session in training)
        or (role == "confirmation" and session in confirmation)
        for session, role in observed.iter_rows()
    )


def validate_b1v3_evaluation_panel(
    panel: pl.DataFrame,
    *,
    preregistration: Mapping[str, Any],
    authorization: Mapping[str, Any],
) -> pl.DataFrame:
    """Validate the outcome-bound panel after the one-read gate is consumed.

    Parameters
    ----------
    panel:
        Common complete-case B0/B1v3a/B2 rows plus strictly positive RV30.
    preregistration:
        Frozen B1v3 preregistration.
    authorization:
        In-progress ledger returned by :func:`authorize_b1v3_confirmation`.

    Returns
    -------
    polars.DataFrame
        Deterministically sorted evaluation rows.

    Raises
    ------
    ValueError
        If access, keys, dates, features, completeness or targets drift.
    """
    features = b1v3_information_sets()["B2"]
    required = {
        "origin_id",
        "asset",
        "session_date",
        "forecast_origin_utc",
        "role",
        "rv30",
        "b0_information_set_complete",
        "b1v3a_information_set_complete",
        "b2_information_set_complete",
        *features,
    }
    authorization_valid = (
        _self_hash_valid(authorization)
        and authorization.get("status") == "CONFIRMATION_EVALUATION_IN_PROGRESS"
        and authorization.get("confirmation_read_count") == 1
        and authorization.get("outcome_read_count") == 2
        and authorization.get("training_read_count") == 1
        and authorization.get("evaluation_attempt_count") == 1
        and authorization.get("preregistration_manifest_sha256")
        == preregistration.get("manifest_sha256")
        and authorization.get("common_panel_sha256")
        == preregistration.get("common_predictor_panel_sha256")
    )
    if not authorization_valid:
        raise ValueError("B1V3_CONFIRMATION_ACCESS_DENIED")
    numeric = [feature for feature in features if feature != "b0v2_asset_identity"]
    invalid = (
        not _self_hash_valid(preregistration)
        or not required <= set(panel.columns)
        or panel.is_empty()
        or panel["origin_id"].null_count() > 0
        or panel["origin_id"].n_unique() != panel.height
        or not set(panel["asset"].cast(pl.String).unique()) <= set(_OUTCOME_ASSETS)
        or not set(panel["role"].cast(pl.String).unique())
        <= {"development", "confirmation"}
        or not _dates_match_role(panel, preregistration)
        or panel.filter(~pl.col("rv30").is_finite() | (pl.col("rv30") <= 0)).height > 0
        or panel.filter(
            ~pl.col("b0_information_set_complete")
            | ~pl.col("b1v3a_information_set_complete")
            | ~pl.col("b2_information_set_complete")
        ).height
        > 0
        or panel.select(
            pl.any_horizontal(
                [~pl.col(name).cast(pl.Float64, strict=False).is_finite() for name in numeric]
            ).any()
        ).item()
        or panel["b0v2_asset_identity"].null_count() > 0
    )
    if invalid:
        raise ValueError("B1V3_EVALUATION_PANEL_INVALID")
    return panel.sort(["session_date", "forecast_origin_utc", "asset"])


def registered_b1v3_contrasts() -> Sequence[tuple[str, str, str]]:
    """Return the two and only two confirmatory information-set contrasts."""
    return (
        ("delta_b1v3", "B0", "B1v3a"),
        ("delta_b2", "B1v3a", "B2"),
    )
