"""Regression coverage for the metadata-only v4 confirmation package sealer."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Protocol, cast

import pytest

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT_PATH = _REPOSITORY_ROOT / "scripts" / "seal_target_blind_confirmation_package_v4.py"
_V24_MANIFEST_PATH = (
    _REPOSITORY_ROOT
    / "artifacts"
    / "target_blind_v24_sourcebound_20260812"
    / "target_blind_common_predictor_manifest_v24.json"
)
_POLICY_GATE_PATH = (
    _REPOSITORY_ROOT
    / "artifacts"
    / "provider_timing_v22"
    / "provider_timing_evidence_policy_gate_v1_20260812.json"
)
_V3_PREREGISTRATION_PATH = (
    _REPOSITORY_ROOT
    / "artifacts"
    / "target_blind_v23_sourcebound_20260812"
    / "next_confirmation_preregistration_v3.json"
)
_SOURCE_COMMIT = "a" * 40
_FROZEN_B2_FEATURES = [
    "b2v2_z_log_trade_count",
    "b2v2_z_unique_contract_share",
    "b2v2_z_log_mean_trade_premium",
    "b2v2_z_log_max_trade_premium",
    "b2v2_deviation_call_put_premium_imbalance",
    "b2v2_deviation_execution_side_premium_imbalance",
    "b2v2_z_repeated_contract_premium_share",
    "b2v2_z_strike_concentration",
    "b2v2_z_expiry_concentration",
]


class _ConfirmationPackageSealer(Protocol):
    def seal_confirmation_package(
        self,
        *,
        v24_manifest_path: Path,
        policy_gate_path: Path,
        preregistration_v3_path: Path,
        output_dir: Path,
        source_commit: str,
    ) -> dict[str, Path]:
        """Seal deterministic v4 preregistration and v3 readiness metadata."""


def _load_sealer() -> _ConfirmationPackageSealer:
    specification = importlib.util.spec_from_file_location(
        "seal_target_blind_confirmation_package_v4", _SCRIPT_PATH
    )
    if specification is None or specification.loader is None:
        raise RuntimeError("V4_SEALER_IMPORT_SPECIFICATION_INVALID")
    module = importlib.util.module_from_spec(specification)
    assert isinstance(module, ModuleType)
    specification.loader.exec_module(module)
    return cast(_ConfirmationPackageSealer, module)


@pytest.fixture(scope="module")
def sealer() -> _ConfirmationPackageSealer:
    """Load the standalone sealer without importing data-processing modules."""
    return _load_sealer()


def _copy_source_documents(destination: Path) -> tuple[Path, Path, Path]:
    destination.mkdir()
    copied_paths: list[Path] = []
    for source in (_V24_MANIFEST_PATH, _POLICY_GATE_PATH, _V3_PREREGISTRATION_PATH):
        copied = destination / source.name
        copied.write_bytes(source.read_bytes())
        copied_paths.append(copied)
    assert len(copied_paths) == 3
    return copied_paths[0], copied_paths[1], copied_paths[2]


def _canonical_sha256(document: object) -> str:
    rendered = json.dumps(
        document,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def _replace_self_hash(document: dict[str, object], field: str) -> None:
    unsigned = dict(document)
    unsigned.pop(field, None)
    document[field] = _canonical_sha256(unsigned)


def _read_json(path: Path) -> dict[str, object]:
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def _seal(
    sealer: _ConfirmationPackageSealer,
    *,
    source_directory: Path,
    output_directory: Path,
) -> dict[str, Path]:
    v24_path, policy_path, v3_path = _copy_source_documents(source_directory)
    return sealer.seal_confirmation_package(
        v24_manifest_path=v24_path,
        policy_gate_path=policy_path,
        preregistration_v3_path=v3_path,
        output_dir=output_directory,
        source_commit=_SOURCE_COMMIT,
    )


def test_sealer_is_deterministic_and_self_validating(
    sealer: _ConfirmationPackageSealer, tmp_path: Path
) -> None:
    """Identical source-bound metadata must produce byte-identical sealed records."""
    first = _seal(
        sealer,
        source_directory=tmp_path / "first-sources",
        output_directory=tmp_path / "first-output",
    )
    second = _seal(
        sealer,
        source_directory=tmp_path / "second-sources",
        output_directory=tmp_path / "second-output",
    )

    assert first.keys() == {"preregistration", "readiness"}
    assert second.keys() == first.keys()
    for key in first:
        assert first[key].read_bytes() == second[key].read_bytes()

    preregistration = _read_json(first["preregistration"])
    readiness = _read_json(first["readiness"])
    assert preregistration["preregistration_sha256"] == _canonical_sha256(
        {key: value for key, value in preregistration.items() if key != "preregistration_sha256"}
    )
    assert readiness["readiness_sha256"] == _canonical_sha256(
        {key: value for key, value in readiness.items() if key != "readiness_sha256"}
    )
    assert preregistration["safe_to_reconcile_existing_results"] == "NO"
    assert preregistration["safe_to_open_or_evaluate_oos"] == "NO"
    assert readiness["safe_to_acquire_new_historical_sample"] == "NO"
    assert readiness["safe_to_start_prospective_capture"] == "NO"


def test_sealer_freezes_registered_method_without_sign_selection(
    sealer: _ConfirmationPackageSealer, tmp_path: Path
) -> None:
    """The successor record must retain the registered method, not choose an edge."""
    sealed = _seal(
        sealer,
        source_directory=tmp_path / "sources",
        output_directory=tmp_path / "output",
    )
    preregistration = _read_json(sealed["preregistration"])

    information_sets = preregistration["information_sets"]
    assert isinstance(information_sets, dict)
    assert information_sets["B2_addition"] == _FROZEN_B2_FEATURES
    assert preregistration["target_definition"] == "RV30"
    assert preregistration["confirmatory_model"] == {
        "family": "Gamma",
        "estimator": "GLM",
        "link": "log",
        "role": "CONFIRMATORY_FIXED",
    }
    assert preregistration["robustness_model"] == {
        "estimator": "LightGBM",
        "role": "FIXED_ROBUSTNESS",
        "tuning": "NONE",
    }
    assert preregistration["metrics"] == {
        "primary": "QLIKE",
        "secondary": ["MAE", "RMSE"],
    }
    assert preregistration["inference"] == {
        "resampling": "PAIRED_DAY_CLUSTER_BOOTSTRAP",
        "cluster_unit": "TRADING_DAY",
        "multiplicity": "HOLM",
        "selection_by_sign": "PROHIBITED",
    }
    assert preregistration["preflight_workflow"]["execution_status"] == "NOT_EXECUTED"


def test_sealer_rejects_altered_sidecar_or_policy_binding(
    sealer: _ConfirmationPackageSealer, tmp_path: Path
) -> None:
    """A self-consistent but differently bound source record remains fail-closed."""
    v24_path, policy_path, v3_path = _copy_source_documents(tmp_path / "sources")
    v24 = _read_json(v24_path)
    source_hashes = v24["source_hashes"]
    assert isinstance(source_hashes, dict)
    source_hashes["b2_availability_sidecar_sha256"] = "0" * 64
    _replace_self_hash(v24, "manifest_sha256")
    v24_path.write_text(json.dumps(v24, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="B2_SIDECAR_POLICY_BINDING_INVALID"):
        sealer.seal_confirmation_package(
            v24_manifest_path=v24_path,
            policy_gate_path=policy_path,
            preregistration_v3_path=v3_path,
            output_dir=tmp_path / "sidecar-output",
            source_commit=_SOURCE_COMMIT,
        )

    v24_path, policy_path, v3_path = _copy_source_documents(tmp_path / "policy-sources")
    policy = _read_json(policy_path)
    evidence = policy["source_evidence"]
    assert isinstance(evidence, list)
    pit_evidence = next(
        item
        for item in evidence
        if isinstance(item, dict) and item.get("role") == "PIT_RECONCILIATION_GATE_V21"
    )
    pit_evidence["file_sha256"] = "0" * 64
    _replace_self_hash(policy, "policy_sha256")
    policy_path.write_text(json.dumps(policy, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="PIT_GATE_POLICY_BINDING_INVALID"):
        sealer.seal_confirmation_package(
            v24_manifest_path=v24_path,
            policy_gate_path=policy_path,
            preregistration_v3_path=v3_path,
            output_dir=tmp_path / "policy-output",
            source_commit=_SOURCE_COMMIT,
        )


def test_sealer_refuses_output_conflict(
    sealer: _ConfirmationPackageSealer, tmp_path: Path
) -> None:
    """Write-if-identical prevents a later invocation from replacing a sealed record."""
    source_directory = tmp_path / "sources"
    output_directory = tmp_path / "output"
    sealed = _seal(sealer, source_directory=source_directory, output_directory=output_directory)
    sealed["preregistration"].write_text("{}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="OUTPUT_CONFLICT"):
        sealer.seal_confirmation_package(
            v24_manifest_path=source_directory / _V24_MANIFEST_PATH.name,
            policy_gate_path=source_directory / _POLICY_GATE_PATH.name,
            preregistration_v3_path=source_directory / _V3_PREREGISTRATION_PATH.name,
            output_dir=output_directory,
            source_commit=_SOURCE_COMMIT,
        )


def test_sealer_source_has_no_forbidden_runtime_paths_or_suppressions() -> None:
    """The metadata sealer must not regain data, network, or type-ignore access."""
    source = _SCRIPT_PATH.read_text(encoding="utf-8")
    assert "type: ignore" not in source
    for forbidden in (
        "evaluation/",
        "holdout/",
        "predictions/",
        "models/",
        "reports/",
        "graphify",
        "gbrain",
        "urllib",
        "import requests",
        "from requests",
    ):
        assert forbidden not in source.lower()
