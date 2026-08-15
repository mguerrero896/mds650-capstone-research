"""Frozen terminal rules for the independent B2 replication."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from mds650.b1_replication_evaluation import (
    build_consumed_authorization_adapter,
    build_legacy_evaluation_adapters,
    classify_b2_replication,
)
from mds650.b1v3_evaluation import b1v3_information_sets, b1v3_method_contract
from mds650.study_design import canonical_sha256


def _frozen_contracts() -> tuple[dict[str, object], dict[str, object]]:
    training_start = date(2024, 8, 1)
    replication_start = date(2025, 1, 1)
    preregistration: dict[str, object] = {
        "status": "FROZEN_BEFORE_PROVIDER_PAYLOAD",
        "replication_target_reads": 0,
        "result_sign_selection": "PROHIBITED",
        "training_sessions": [
            (training_start + timedelta(days=index)).isoformat() for index in range(60)
        ],
        "replication_sessions": [
            (replication_start + timedelta(days=index)).isoformat()
            for index in range(30)
        ],
        "information_sets": {
            name: list(features) for name, features in b1v3_information_sets().items()
        },
        "method": b1v3_method_contract(),
    }
    preregistration["manifest_sha256"] = canonical_sha256(preregistration)
    method: dict[str, object] = {
        "status": "FROZEN_AFTER_TRAINING_BEFORE_REPLICATION",
        "replication_target_read_count": 0,
        "result_sign_selection": "PROHIBITED",
        "preregistration_manifest_sha256": preregistration["manifest_sha256"],
        "selected_parameters": {
            role: {
                information_set: {"alpha": 0.1}
                for information_set in ("B0", "B1v3a", "B2")
            }
            for role in ("gamma_glm_confirmatory", "lightgbm_robustness")
        },
        "training_mde": {"delta_b1v3": 0.01, "delta_b2": 0.02},
        "volatility_regime_cutpoints": {"lower": 0.1, "upper": 0.2},
    }
    method["manifest_sha256"] = canonical_sha256(method)
    return preregistration, method


def _evaluation(
    *,
    gamma: float,
    ci_low: float,
    challenger: float,
    holm: float,
) -> dict[str, object]:
    return {
        "global": {
            "gamma_glm_confirmatory": {
                "delta_b2": {"estimate": gamma, "ci_low": ci_low}
            },
            "lightgbm_robustness": {
                "delta_b2": {"estimate": challenger, "ci_low": -1.0}
            },
        },
        "global_holm": {"delta_b2": holm},
    }


@pytest.mark.parametrize(
    ("gamma", "ci_low", "challenger", "holm", "expected"),
    [
        (0.02, 0.01, 0.004, 0.01, "REPLICATED_MODEL_INDEPENDENT"),
        (0.02, 0.01, -0.004, 0.01, "REPLICATED_GAMMA_ONLY"),
        (-0.02, -0.03, 0.004, 0.90, "NOT_REPLICATED"),
        (0.02, -0.001, 0.004, 0.20, "NOT_REPLICATED"),
        (0.005, 0.001, 0.004, 0.01, "NOT_REPLICATED"),
    ],
)
def test_terminal_rule_retains_every_sign(
    gamma: float,
    ci_low: float,
    challenger: float,
    holm: float,
    expected: str,
) -> None:
    decision = classify_b2_replication(
        _evaluation(gamma=gamma, ci_low=ci_low, challenger=challenger, holm=holm),
        training_mde=0.01,
    )
    assert decision["terminal_state"] == expected
    assert decision["positive_null_negative_retained"] is True


def test_terminal_rule_rejects_invalid_result() -> None:
    with pytest.raises(ValueError, match="B1_REPLICATION_DECISION_VALUE_INVALID"):
        classify_b2_replication(
            _evaluation(gamma=float("nan"), ci_low=0.1, challenger=0.1, holm=0.01),
            training_mde=0.01,
        )


def test_evaluation_adapters_preserve_frozen_methods_and_one_read_contract() -> None:
    preregistration, method = _frozen_contracts()
    prereg_adapter, method_adapter = build_legacy_evaluation_adapters(
        preregistration,
        method,
        common_panel_sha256="f" * 64,
    )
    authorization = build_consumed_authorization_adapter(prereg_adapter)
    assert prereg_adapter["confirmation_sessions"] == preregistration[
        "replication_sessions"
    ]
    assert method_adapter["selected_parameters"] == method["selected_parameters"]
    assert authorization["confirmation_read_count"] == 1
    assert authorization["results_inspected"] is False


def test_evaluation_adapters_fail_closed_on_contract_drift() -> None:
    preregistration, method = _frozen_contracts()
    method["result_sign_selection"] = "POSITIVE_ONLY"
    method["manifest_sha256"] = canonical_sha256(
        {key: value for key, value in method.items() if key != "manifest_sha256"}
    )
    with pytest.raises(
        ValueError, match="B1_REPLICATION_EVALUATION_ADAPTER_SOURCE_INVALID"
    ):
        build_legacy_evaluation_adapters(
            preregistration,
            method,
            common_panel_sha256="f" * 64,
        )
