"""Tests for the target-blind MDS650 current-research readiness ledger."""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Protocol, cast

import pytest

MODULE_NAME = "mds650.current_research_readiness_v1"
ROOT = Path(__file__).resolve().parents[2]


class _CurrentResearchReadiness(Protocol):
    """Public target-blind readiness surface covered by this test."""

    def build_current_research_readiness_v1(
        self, *, input_paths: Mapping[str, Path]
    ) -> dict[str, object]:
        """Bind current local evidence into a readiness-with-blockers record."""

    def validate_current_research_readiness_v1(self, ledger: Mapping[str, object]) -> None:
        """Reject a changed hash, evidence binding, or unsafe gate state."""

    def write_current_research_readiness_v1(
        self, *, input_paths: Mapping[str, Path], output_path: Path
    ) -> Path:
        """Write an immutable readiness ledger or preserve an identical replay."""


def _module() -> _CurrentResearchReadiness:
    """Load the production module after proving the desired API is absent/present."""
    assert importlib.util.find_spec(MODULE_NAME) is not None, (
        "current research readiness v1 is required"
    )
    return cast(_CurrentResearchReadiness, importlib.import_module(MODULE_NAME))


def _inputs() -> dict[str, Path]:
    """Return the five registered target-blind source artifacts."""
    return {
        "policy_gate": ROOT
        / "artifacts/provider_timing_v22/provider_timing_evidence_policy_gate_v1_20260812.json",
        "preflight": ROOT / "artifacts/preflight/date_level_pit_preflight_status_v2_1_current.json",
        "source_coverage": ROOT / "artifacts/corrected_development_v1/source_coverage_ledger.json",
        "fmp_docs_review": ROOT
        / "artifacts/provider_timing_v21/fmp_b1q_exogenous_docs_review_v1_20260812.json",
        "confirmation_readiness": ROOT
        / "artifacts/target_blind_v24_sourcebound_20260812/confirmation_readiness_v3.json",
    }


def _canonical_sha256(document: Mapping[str, object]) -> str:
    """Compute the semantic hash independently of production code."""
    rendered = json.dumps(
        document,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return "sha256:" + hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def test_current_ledger_binds_all_evidence_and_keeps_evaluation_blocked() -> None:
    """A historical-availability pass cannot be misreported as evaluation readiness."""
    ledger = _module().build_current_research_readiness_v1(input_paths=_inputs())

    assert ledger["status"] == "READY_FOR_CONFIRMATION_WITH_BLOCKERS"
    assert ledger["method_freeze_status"] == "FROZEN_TARGET_BLIND_ONLY"
    assert ledger["safe_to_build_b0_b1_b2_evaluation"] is False
    assert ledger["safe_to_reconcile_existing_results"] == "NO"
    assert ledger["safe_to_open_or_evaluate_oos"] == "NO"
    assert ledger["safe_to_acquire_new_historical_sample"] == "NO"
    assert ledger["b1q_exogenous_input_provenance"] == "UNRESOLVED"
    assert ledger["date_level_pit_preflight"] == "FAILED_CLOSED"
    assert ledger["current_blockers"] == [
        "B1Q_EXOGENOUS_INPUT_PROVENANCE_UNRESOLVED",
        "DATE_LEVEL_PIT_PREFLIGHT_FAILED_CLOSED",
        "SAFE_TO_RECONCILE_EXISTING_RESULTS_NO",
        "SAFE_TO_OPEN_OR_EVALUATE_OOS_NO",
    ]
    sources = cast(Mapping[str, object], ledger["bound_sources"])
    assert set(sources) == set(_inputs())
    assert all(
        isinstance(cast(Mapping[str, object], source)["file_sha256"], str)
        and len(cast(Mapping[str, object], source)["file_sha256"]) == 64
        for source in sources.values()
    )
    assert ledger["semantic_self_hash"] == _canonical_sha256(
        {key: value for key, value in ledger.items() if key != "semantic_self_hash"}
    )


def test_ledger_rejects_rehashed_gate_upgrade() -> None:
    """A caller cannot turn the static readiness evidence into model permission."""
    module = _module()
    ledger = module.build_current_research_readiness_v1(input_paths=_inputs())
    ledger["safe_to_build_b0_b1_b2_evaluation"] = True
    ledger["semantic_self_hash"] = _canonical_sha256(
        {key: value for key, value in ledger.items() if key != "semantic_self_hash"}
    )

    with pytest.raises(ValueError, match="CURRENT_RESEARCH_READINESS_SCHEMA_INVALID"):
        module.validate_current_research_readiness_v1(ledger)


def test_ledger_rejects_changed_bound_source_before_write(tmp_path: Path) -> None:
    """A different source byte identity must fail before a new readiness state exists."""
    module = _module()
    copied_inputs = {name: tmp_path / f"{name}.json" for name in _inputs()}
    for name, source in _inputs().items():
        copied_inputs[name].write_bytes(source.read_bytes())
    copied_inputs["source_coverage"].write_text("{}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="CURRENT_RESEARCH_READINESS_SOURCE_COVERAGE_INVALID"):
        module.build_current_research_readiness_v1(input_paths=copied_inputs)


def test_writer_is_idempotent_and_rejects_divergent_output(tmp_path: Path) -> None:
    """The status ledger has a deterministic immutable byte representation."""
    module = _module()
    output_path = tmp_path / "current_research_readiness_v1.json"

    assert (
        module.write_current_research_readiness_v1(input_paths=_inputs(), output_path=output_path)
        == output_path
    )
    expected = output_path.read_bytes()
    assert (
        module.write_current_research_readiness_v1(input_paths=_inputs(), output_path=output_path)
        == output_path
    )
    assert output_path.read_bytes() == expected

    output_path.write_text("{}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="CURRENT_RESEARCH_READINESS_OUTPUT_CONFLICT"):
        module.write_current_research_readiness_v1(input_paths=_inputs(), output_path=output_path)


def test_builder_requires_the_complete_registered_input_set() -> None:
    """Removing an evidence class cannot silently produce a less strict ledger."""
    input_paths = _inputs()
    input_paths.pop("fmp_docs_review")

    with pytest.raises(ValueError, match="CURRENT_RESEARCH_READINESS_INPUT_SET_INVALID"):
        _module().build_current_research_readiness_v1(input_paths=input_paths)


def test_validator_rejects_a_non_hash_self_hash() -> None:
    """A readiness record cannot claim integrity without the canonical hash format."""
    ledger = _module().build_current_research_readiness_v1(input_paths=_inputs())
    ledger["semantic_self_hash"] = "invalid"

    with pytest.raises(ValueError, match="CURRENT_RESEARCH_READINESS_SELF_HASH_INVALID"):
        _module().validate_current_research_readiness_v1(ledger)
