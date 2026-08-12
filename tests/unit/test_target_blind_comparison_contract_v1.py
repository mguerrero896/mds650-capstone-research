"""Regression tests for the target-blind primary-comparison contract."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from collections.abc import Iterable, Mapping
from importlib import import_module
from pathlib import Path
from types import ModuleType
from typing import Protocol, cast

import pytest

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT_PATH = _REPOSITORY_ROOT / "scripts" / "seal_target_blind_comparison_contract_v1.py"
_PARENT_PATH = (
    _REPOSITORY_ROOT
    / "artifacts"
    / "target_blind_v24_sourcebound_20260812"
    / "next_confirmation_preregistration_v4.json"
)
_SCHEMA_PATH = (
    _REPOSITORY_ROOT
    / "specs"
    / "001-pit-options-rv30"
    / "contracts"
    / "target-blind-comparison-contract-v1.schema.json"
)
_SOURCE_COMMIT = "a" * 40


class _ComparisonContractSealer(Protocol):
    """Public surface required from the standalone comparison-contract sealer."""

    def seal_target_blind_comparison_contract(
        self,
        *,
        preregistration_v4_path: Path,
        output_dir: Path,
        source_commit: str,
    ) -> Path:
        """Seal a deterministic comparison contract without outcome access."""


class _JsonSchemaValidator(Protocol):
    """Minimal type boundary for the installed JSON Schema runtime."""

    def iter_errors(self, instance: object) -> Iterable[object]:
        """Yield validation errors for one instance."""


class _Draft202012ValidatorFactory(Protocol):
    """Minimal typed construction and schema-check interface."""

    def __call__(self, schema: Mapping[str, object]) -> _JsonSchemaValidator:
        """Create one validator from a JSON Schema mapping."""

    def check_schema(self, schema: Mapping[str, object]) -> None:
        """Raise if ``schema`` is invalid."""


def _load_sealer() -> _ComparisonContractSealer:
    """Load the standalone script without importing panel or evaluation modules."""
    specification = importlib.util.spec_from_file_location(
        "seal_target_blind_comparison_contract_v1", _SCRIPT_PATH
    )
    if specification is None or specification.loader is None:
        raise RuntimeError("COMPARISON_CONTRACT_V1_IMPORT_SPECIFICATION_INVALID")
    module = importlib.util.module_from_spec(specification)
    assert isinstance(module, ModuleType)
    specification.loader.exec_module(module)
    return cast(_ComparisonContractSealer, module)


@pytest.fixture(scope="module")
def sealer() -> _ComparisonContractSealer:
    """Load the target-blind sealer once for the focused test module."""
    return _load_sealer()


def _canonical_sha256(document: object) -> str:
    """Return the repository canonical JSON hash for a mapping-like document."""
    rendered = json.dumps(
        document,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def _draft202012_validator() -> _Draft202012ValidatorFactory:
    """Load the untyped installed package behind an explicit narrow protocol."""
    module = import_module("jsonschema")
    candidate = cast(object, getattr(module, "Draft202012Validator", None))
    if not callable(candidate) or not callable(getattr(candidate, "check_schema", None)):
        raise RuntimeError("COMPARISON_CONTRACT_V1_TEST_VALIDATOR_UNAVAILABLE")
    return cast(_Draft202012ValidatorFactory, candidate)


def _read_json(path: Path) -> dict[str, object]:
    """Read a JSON object without opening data panels or outcomes."""
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def _copy_parent(destination: Path) -> Path:
    """Copy metadata-only parent preregistration into a test-local source path."""
    destination.mkdir()
    copied = destination / _PARENT_PATH.name
    copied.write_bytes(_PARENT_PATH.read_bytes())
    return copied


def _replace_parent_self_hash(parent: dict[str, object]) -> None:
    """Recompute a deliberately altered parent hash for fail-closed tests."""
    unsigned = {key: value for key, value in parent.items() if key != "preregistration_sha256"}
    parent["preregistration_sha256"] = _canonical_sha256(unsigned)


def _seal(
    sealer: _ComparisonContractSealer,
    *,
    source_directory: Path,
    output_directory: Path,
) -> Path:
    """Run the sealer with a copied parent record and synthetic source commit."""
    return sealer.seal_target_blind_comparison_contract(
        preregistration_v4_path=_copy_parent(source_directory),
        output_dir=output_directory,
        source_commit=_SOURCE_COMMIT,
    )


def test_contract_freezes_primary_nested_comparisons_before_outcomes(
    sealer: _ComparisonContractSealer, tmp_path: Path
) -> None:
    """B1a-vs-B0 and B2-vs-B1a must be exact, directional, and target-blind."""
    first = _seal(
        sealer,
        source_directory=tmp_path / "first-source",
        output_directory=tmp_path / "first-output",
    )
    second = _seal(
        sealer,
        source_directory=tmp_path / "second-source",
        output_directory=tmp_path / "second-output",
    )
    assert first.read_bytes() == second.read_bytes()

    contract = _read_json(first)
    assert contract["target_definition"] == "RV30"
    assert contract["safe_to_open_or_evaluate_oos"] == "NO"
    assert contract["model_fit_performed"] is False
    assert contract["metric_evaluation_performed"] is False
    assert contract["primary_comparisons"] == [
        {
            "comparison_id": "B1A_VS_B0",
            "benchmark": "B0",
            "challenger": "B1a",
            "estimand": "MEAN_DAILY_QLIKE_B0_MINUS_B1A",
            "positive_direction": "FAVORS_B1A",
        },
        {
            "comparison_id": "B2_VS_B1A",
            "benchmark": "B1a",
            "challenger": "B2",
            "estimand": "MEAN_DAILY_QLIKE_B1A_MINUS_B2",
            "positive_direction": "FAVORS_B2",
        },
    ]
    assert contract["primary_b1_level"] == "B1a"
    assert contract["primary_benchmark_substitution"] == "PROHIBITED"
    assert contract["b1b_b1c_role"] == "PRE_SPECIFIED_ROBUSTNESS_ONLY"
    assert contract["comparison_contract_sha256"] == _canonical_sha256(
        {key: value for key, value in contract.items() if key != "comparison_contract_sha256"}
    )

    parent = _read_json(_PARENT_PATH)
    information_sets = parent["information_sets"]
    assert isinstance(information_sets, dict)
    expected_b0 = information_sets["B0"]
    expected_b1a = information_sets["B0"] + information_sets["B1a_addition"]
    expected_b2 = expected_b1a + information_sets["B2_addition"]
    assert contract["model_information_sets"] == {
        "B0": expected_b0,
        "B1a": expected_b1a,
        "B2": expected_b2,
    }


def test_contract_rejects_self_hashed_nonincremental_b2(
    sealer: _ComparisonContractSealer, tmp_path: Path
) -> None:
    """A self-consistent parent cannot smuggle a B2 duplicate into the challenger."""
    parent_path = _copy_parent(tmp_path / "source")
    parent = _read_json(parent_path)
    information_sets = parent["information_sets"]
    assert isinstance(information_sets, dict)
    b0 = information_sets["B0"]
    b2 = information_sets["B2_addition"]
    assert isinstance(b0, list)
    assert isinstance(b2, list)
    b0.append(b2[0])
    _replace_parent_self_hash(parent)
    parent_path.write_text(json.dumps(parent, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="COMPARISON_CONTRACT_V1_B2_NOT_STRICT_INCREMENT"):
        sealer.seal_target_blind_comparison_contract(
            preregistration_v4_path=parent_path,
            output_dir=tmp_path / "output",
            source_commit=_SOURCE_COMMIT,
        )


def test_contract_validates_against_its_json_schema(
    sealer: _ComparisonContractSealer, tmp_path: Path
) -> None:
    """The generated immutable record must satisfy the exact Draft 2020-12 schema."""
    contract_path = _seal(
        sealer,
        source_directory=tmp_path / "source",
        output_directory=tmp_path / "output",
    )
    schema = _read_json(_SCHEMA_PATH)
    validator = _draft202012_validator()
    validator.check_schema(schema)
    errors = list(validator(schema).iter_errors(_read_json(contract_path)))
    assert errors == []


def test_contract_rejects_parent_that_reopens_oos(
    sealer: _ComparisonContractSealer, tmp_path: Path
) -> None:
    """A parent record with an opened OOS gate must fail even when self-hashed."""
    parent_path = _copy_parent(tmp_path / "source")
    parent = _read_json(parent_path)
    parent["safe_to_open_or_evaluate_oos"] = "YES"
    _replace_parent_self_hash(parent)
    parent_path.write_text(json.dumps(parent, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="COMPARISON_CONTRACT_V1_PARENT_GATE_INVALID"):
        sealer.seal_target_blind_comparison_contract(
            preregistration_v4_path=parent_path,
            output_dir=tmp_path / "output",
            source_commit=_SOURCE_COMMIT,
        )


def test_contract_is_idempotent_and_rejects_nonidentical_replacement(
    sealer: _ComparisonContractSealer, tmp_path: Path
) -> None:
    """A sealed record can be repeated exactly but cannot be silently replaced."""
    parent_path = _copy_parent(tmp_path / "source")
    output_dir = tmp_path / "output"
    first = sealer.seal_target_blind_comparison_contract(
        preregistration_v4_path=parent_path,
        output_dir=output_dir,
        source_commit=_SOURCE_COMMIT,
    )
    original_bytes = first.read_bytes()
    repeated = sealer.seal_target_blind_comparison_contract(
        preregistration_v4_path=parent_path,
        output_dir=output_dir,
        source_commit=_SOURCE_COMMIT,
    )
    assert repeated == first
    assert repeated.read_bytes() == original_bytes

    with pytest.raises(ValueError, match="COMPARISON_CONTRACT_V1_OUTPUT_CONFLICT"):
        sealer.seal_target_blind_comparison_contract(
            preregistration_v4_path=parent_path,
            output_dir=output_dir,
            source_commit="b" * 40,
        )


def test_contract_rejects_self_hashed_method_or_b1a_changes(
    sealer: _ComparisonContractSealer, tmp_path: Path
) -> None:
    """Method and strict B1a nesting cannot be altered after the v4 freeze."""
    parent_path = _copy_parent(tmp_path / "method-source")
    parent = _read_json(parent_path)
    metrics = parent["metrics"]
    assert isinstance(metrics, dict)
    metrics["primary"] = "RMSE"
    _replace_parent_self_hash(parent)
    parent_path.write_text(json.dumps(parent, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="COMPARISON_CONTRACT_V1_PARENT_METHOD_INVALID"):
        sealer.seal_target_blind_comparison_contract(
            preregistration_v4_path=parent_path,
            output_dir=tmp_path / "method-output",
            source_commit=_SOURCE_COMMIT,
        )

    parent_path = _copy_parent(tmp_path / "b1a-source")
    parent = _read_json(parent_path)
    information_sets = parent["information_sets"]
    assert isinstance(information_sets, dict)
    b0 = information_sets["B0"]
    b1a = information_sets["B1a_addition"]
    assert isinstance(b0, list)
    assert isinstance(b1a, list)
    b1a[0] = b0[0]
    _replace_parent_self_hash(parent)
    parent_path.write_text(json.dumps(parent, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="COMPARISON_CONTRACT_V1_B1A_NOT_STRICT_INCREMENT"):
        sealer.seal_target_blind_comparison_contract(
            preregistration_v4_path=parent_path,
            output_dir=tmp_path / "b1a-output",
            source_commit=_SOURCE_COMMIT,
        )
