"""Contracts for the professor-readable canonical RV30 defense package."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "artifacts" / "canonical_validation_v1"
sys.path.insert(0, str(ROOT / "scripts"))

import build_canonical_defense_package as defense  # noqa: E402


def test_defense_package_is_evidence_bound_and_safe(tmp_path: Path) -> None:
    """The generated package must expose the canonical decision and portable sources."""

    manifest = defense.build_defense_package(SOURCE, tmp_path)

    assert manifest["status"] == "PASS_CANONICAL_DEFENSE_PACKAGE"
    assert manifest["claim_eligibility"] == {
        "delta_b1v2": "MODEL_FAMILY_DEPENDENT",
        "delta_b2v2": "MODEL_FAMILY_DEPENDENT",
    }
    assert (tmp_path / "MDS650_Canonical_RV30_Defense_Report.html").is_file()
    assert (tmp_path / "MDS650_Canonical_RV30_Defense_Slides.md").is_file()
    assert (tmp_path / "tables" / "canonical_registered_contrasts.csv").is_file()
    assert (tmp_path / "figures" / "canonical_qlike_contrasts.svg").is_file()
    assert all("C:\\Users\\" not in value for value in manifest["input_paths"])
    assert all("C:\\Users\\" not in value for value in manifest["output_paths"])


def test_defense_package_preserves_registered_signs_and_forbids_overclaim(
    tmp_path: Path,
) -> None:
    """A presentation artifact cannot erase the adverse registered robustness result."""

    defense.build_defense_package(SOURCE, tmp_path)
    report = (tmp_path / "MDS650_Canonical_RV30_Defense_Report.md").read_text(encoding="utf-8")
    table_rows = list(
        __import__("csv").DictReader(
            (tmp_path / "tables" / "canonical_registered_contrasts.csv").open(
                encoding="utf-8", newline=""
            )
        )
    )
    manifest = json.loads(
        (tmp_path / "MDS650_Defense_Package_Manifest.json").read_text(encoding="utf-8")
    )

    assert "MODEL_FAMILY_DEPENDENT" in report
    assert "universal positive edge" not in report.lower()
    assert "trading profit" not in report.lower()
    assert "-0.00180221" in report
    assert any(
        row["block"] == "independent_replication"
        and row["model_role"] == "lightgbm_robustness"
        and row["contrast"] == "delta_b2v2"
        and row["result_sign"] == "NEGATIVE"
        for row in table_rows
    )
    assert manifest["source_status"] == "PASS_CANONICAL_REPORT"


def test_defense_package_rerun_is_hash_stable(tmp_path: Path) -> None:
    """The same validated input must produce byte-identical portable output."""

    first = defense.build_defense_package(SOURCE, tmp_path)
    second = defense.build_defense_package(SOURCE, tmp_path)

    assert first["output_hashes"] == second["output_hashes"]
    assert second["status"] == "REUSED_HASH_VERIFIED"


def test_defense_package_rejects_unsanitized_source_manifest(tmp_path: Path) -> None:
    """A source that declares path or secret leakage cannot enter the package."""

    source = tmp_path / "source"
    shutil.copytree(SOURCE, source)
    manifest_path = source / "report_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["personal_paths_emitted"] = True
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(RuntimeError, match="CANONICAL_DEFENSE_INPUT_INVALID"):
        defense.build_defense_package(source, tmp_path / "output")
