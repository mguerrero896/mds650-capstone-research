"""Frozen adapters and terminal decision rules for independent replication.

This module contains no file discovery and no provider or target reader.  It
adapts the independently preregistered contract to the already-tested Phase 6
forecasting primitives and freezes a sign-agnostic terminal taxonomy.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from mds650.b1v3_evaluation import (
    b1v3_method_contract,
    b1v3_phase6_adapter_contract,
)
from mds650.study_design import canonical_sha256


def _self_hash_valid(document: Mapping[str, Any]) -> bool:
    stored = document.get("manifest_sha256")
    unsigned = {key: value for key, value in document.items() if key != "manifest_sha256"}
    return isinstance(stored, str) and stored == canonical_sha256(unsigned)


def build_legacy_evaluation_adapters(
    preregistration: Mapping[str, Any],
    method_freeze: Mapping[str, Any],
    *,
    common_panel_sha256: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Adapt the new replication contracts to validated forecasting primitives.

    Parameters
    ----------
    preregistration, method_freeze:
        Self-hashed independent-replication contracts frozen before target read.
    common_panel_sha256:
        Exact target-blind primary panel identity.

    Returns
    -------
    tuple[dict[str, Any], dict[str, Any]]
        In-memory preregistration and method-freeze adapters. They are not new
        scientific specifications and are never used to relax a gate.

    Raises
    ------
    ValueError
        If methods, information sets, dates, hashes or read counters drift.
    """
    if (
        not _self_hash_valid(preregistration)
        or preregistration.get("status") != "FROZEN_BEFORE_PROVIDER_PAYLOAD"
        or preregistration.get("replication_target_reads") != 0
        or preregistration.get("result_sign_selection") != "PROHIBITED"
        or preregistration.get("method") != b1v3_method_contract()
        or not _self_hash_valid(method_freeze)
        or method_freeze.get("status") != "FROZEN_AFTER_TRAINING_BEFORE_REPLICATION"
        or method_freeze.get("replication_target_read_count") != 0
        or method_freeze.get("result_sign_selection") != "PROHIBITED"
        or method_freeze.get("preregistration_manifest_sha256")
        != preregistration.get("manifest_sha256")
        or len(str(common_panel_sha256)) != 64
    ):
        raise ValueError("B1_REPLICATION_EVALUATION_ADAPTER_SOURCE_INVALID")
    prereg_adapter: dict[str, Any] = {
        "schema_version": "b1-independent-replication-evaluation-adapter-1.0",
        "status": "FROZEN_BEFORE_CONFIRMATION",
        "target_blind": True,
        "safe_to_evaluate_b1v3": "NO",
        "outcome_read_count": 0,
        "confirmation_read_count": 0,
        "common_predictor_panel_sha256": common_panel_sha256,
        "training_sessions": list(preregistration["training_sessions"]),
        "confirmation_sessions": list(preregistration["replication_sessions"]),
        "information_sets": dict(preregistration["information_sets"]),
        "method": dict(preregistration["method"]),
    }
    prereg_adapter["manifest_sha256"] = canonical_sha256(prereg_adapter)
    b1v3_phase6_adapter_contract(prereg_adapter)
    method_adapter: dict[str, Any] = {
        "schema_version": "b1-independent-replication-method-adapter-1.0",
        "status": "FROZEN_AFTER_TRAINING_BEFORE_CONFIRMATION",
        "safe_to_read_confirmation": False,
        "training_read_count": 1,
        "confirmation_read_count": 0,
        "preregistration_manifest_sha256": prereg_adapter["manifest_sha256"],
        "selected_parameters": dict(method_freeze["selected_parameters"]),
        "training_mde": dict(method_freeze["training_mde"]),
        "volatility_regime_cutpoints": dict(
            method_freeze["volatility_regime_cutpoints"]
        ),
    }
    method_adapter["manifest_sha256"] = canonical_sha256(method_adapter)
    return prereg_adapter, method_adapter


def build_consumed_authorization_adapter(
    preregistration_adapter: Mapping[str, Any],
) -> dict[str, Any]:
    """Create the in-memory authorization expected after the durable token claim."""
    if not _self_hash_valid(preregistration_adapter):
        raise ValueError("B1_REPLICATION_AUTHORIZATION_ADAPTER_SOURCE_INVALID")
    document: dict[str, Any] = {
        "schema_version": "b1-independent-replication-authorization-adapter-1.0",
        "status": "CONFIRMATION_EVALUATION_IN_PROGRESS",
        "safe_to_evaluate_b1v3": "YES",
        "outcome_read_count": 2,
        "training_read_count": 1,
        "confirmation_read_count": 1,
        "evaluation_attempt_count": 1,
        "results_inspected": False,
        "preregistration_manifest_sha256": preregistration_adapter["manifest_sha256"],
        "common_panel_sha256": preregistration_adapter[
            "common_predictor_panel_sha256"
        ],
    }
    document["manifest_sha256"] = canonical_sha256(document)
    return document


def classify_b2_replication(
    evaluation: Mapping[str, Any],
    *,
    training_mde: float,
) -> dict[str, Any]:
    """Apply the frozen sign-agnostic B2 terminal rule.

    ``REPLICATED_MODEL_INDEPENDENT`` requires a positive, Holm-significant,
    training-MDE-sized Gamma result and a positive LightGBM estimate.
    ``REPLICATED_GAMMA_ONLY`` meets the Gamma rule but not the challenger-sign
    condition. Every other valid execution is ``NOT_REPLICATED``. Protocol or
    data failures are assigned ``INVALID_REPLICATION`` by the caller and cannot
    be manufactured from an observed result.
    """
    global_rows = evaluation.get("global")
    holm = evaluation.get("global_holm")
    if not isinstance(global_rows, Mapping) or not isinstance(holm, Mapping):
        raise ValueError("B1_REPLICATION_DECISION_INPUT_INVALID")
    gamma_role = global_rows.get("gamma_glm_confirmatory")
    challenger_role = global_rows.get("lightgbm_robustness")
    gamma = gamma_role.get("delta_b2") if isinstance(gamma_role, Mapping) else None
    challenger = (
        challenger_role.get("delta_b2")
        if isinstance(challenger_role, Mapping)
        else None
    )
    if not isinstance(gamma, Mapping) or not isinstance(challenger, Mapping):
        raise ValueError("B1_REPLICATION_DECISION_INPUT_INVALID")
    values = {
        "gamma_estimate": float(gamma["estimate"]),
        "gamma_ci_low": float(gamma["ci_low"]),
        "gamma_holm_p": float(holm["delta_b2"]),
        "challenger_estimate": float(challenger["estimate"]),
        "training_mde": float(training_mde),
    }
    if not all(math.isfinite(value) for value in values.values()) or training_mde <= 0:
        raise ValueError("B1_REPLICATION_DECISION_VALUE_INVALID")
    gamma_confirmed = (
        values["gamma_estimate"] > 0
        and values["gamma_ci_low"] > 0
        and values["gamma_holm_p"] < 0.05
        and values["gamma_estimate"] >= values["training_mde"]
    )
    challenger_positive = values["challenger_estimate"] > 0
    if gamma_confirmed and challenger_positive:
        state = "REPLICATED_MODEL_INDEPENDENT"
    elif gamma_confirmed:
        state = "REPLICATED_GAMMA_ONLY"
    else:
        state = "NOT_REPLICATED"
    return {
        "terminal_state": state,
        "rule_version": "b1-independent-replication-terminal-rule-1.0",
        "conditions": {
            "gamma_estimate_positive": values["gamma_estimate"] > 0,
            "gamma_interval_above_zero": values["gamma_ci_low"] > 0,
            "gamma_holm_p_below_0_05": values["gamma_holm_p"] < 0.05,
            "gamma_effect_meets_training_mde": (
                values["gamma_estimate"] >= values["training_mde"]
            ),
            "lightgbm_estimate_positive": challenger_positive,
        },
        "values": values,
        "positive_null_negative_retained": True,
    }
