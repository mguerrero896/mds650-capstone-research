"""Fail-closed artifact controls for the B1v3 one-read access ledger."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from seal_b1v3_access_ledger import (  # noqa: E402
    _validated_quality_prerequisites,
    _write_json_if_identical,
)

from mds650.b1v3_evaluation import build_b1v3_access_ledger  # noqa: E402
from mds650.study_design import canonical_sha256  # noqa: E402

_SHA = "a" * 64
_GATES = (
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


def _quality() -> dict[str, Any]:
    document: dict[str, Any] = {
        "schema_version": "1.0",
        "status": "PASS_B1V3_PRE_CONFIRMATION_QUALITY",
        "target_blind": True,
        "outcome_read_count": 1,
        "training_read_count": 1,
        "confirmation_read_count": 0,
        "source_bindings": {
            "preregistration_manifest_sha256": "1" * 64,
            "method_freeze_manifest_sha256": "2" * 64,
            "common_panel_sha256": "3" * 64,
            "timing_panel_manifest_sha256": "4" * 64,
        },
        "gates": {
            name: {"status": "PASS", "evidence_sha256": _SHA} for name in _GATES
        },
        "security": {
            "secret_values_emitted": False,
            "personal_paths_emitted": False,
        },
    }
    document["manifest_sha256"] = canonical_sha256(document)
    return document


def test_quality_report_maps_exactly_to_access_prerequisites() -> None:
    prerequisites = _validated_quality_prerequisites(
        _quality(),
        preregistration_manifest_sha256="1" * 64,
        method_freeze_manifest_sha256="2" * 64,
        common_panel_sha256="3" * 64,
        timing_panel_manifest_sha256="4" * 64,
    )

    assert prerequisites == {name: True for name in _GATES}


@pytest.mark.parametrize(
    ("mutation", "error"),
    [
        (lambda document: document["gates"].pop("spec_kit"), "QUALITY_GATE_SET"),
        (
            lambda document: document["gates"]["mypy"].update(status="FAIL"),
            "QUALITY_GATE_FAILED",
        ),
        (
            lambda document: document["source_bindings"].update(
                common_panel_sha256="f" * 64
            ),
            "QUALITY_BINDING",
        ),
    ],
)
def test_quality_report_fails_closed_on_drift(mutation: Any, error: str) -> None:
    document = _quality()
    mutation(document)
    document["manifest_sha256"] = canonical_sha256(
        {key: value for key, value in document.items() if key != "manifest_sha256"}
    )

    with pytest.raises(ValueError, match=error):
        _validated_quality_prerequisites(
            document,
            preregistration_manifest_sha256="1" * 64,
            method_freeze_manifest_sha256="2" * 64,
            common_panel_sha256="3" * 64,
            timing_panel_manifest_sha256="4" * 64,
        )


def test_access_writer_is_idempotent_and_rejects_conflicts_and_paths(
    tmp_path: Path,
) -> None:
    output = tmp_path / "access.json"
    document = {"status": "PASS", "manifest_sha256": _SHA}

    first = _write_json_if_identical(output, document)

    assert _write_json_if_identical(output, document) == first
    with pytest.raises(ValueError, match="B1V3_ACCESS_OUTPUT_CONFLICT"):
        _write_json_if_identical(output, {"status": "FAIL"})
    with pytest.raises(ValueError, match="B1V3_ACCESS_OUTPUT_HYGIENE_INVALID"):
        _write_json_if_identical(
            tmp_path / "unsafe.json",
            {"path": "D:/MDS650/private", "apiKey": "never"},
        )


def test_expanded_access_contract_rejects_the_old_eight_gate_shape() -> None:
    preregistration: dict[str, Any] = {
        "status": "FROZEN_BEFORE_CONFIRMATION",
        "safe_to_evaluate_b1v3": "NO",
        "outcome_read_count": 0,
        "confirmation_read_count": 0,
        "common_predictor_panel_sha256": "3" * 64,
    }
    preregistration["manifest_sha256"] = canonical_sha256(preregistration)
    old = {name: True for name in _GATES[:7]}
    old["disk_gate"] = True

    with pytest.raises(ValueError, match="B1V3_PREREQUISITES_INCOMPLETE"):
        build_b1v3_access_ledger(
            preregistration,
            common_panel_sha256="3" * 64,
            method_freeze_sha256="2" * 64,
            timing_panel_manifest_sha256="4" * 64,
            quality_report_sha256="5" * 64,
            confirmation_code_sha256="6" * 64,
            uv_lock_sha256="7" * 64,
            prerequisites=old,
        )
