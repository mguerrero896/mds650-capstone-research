"""Tests for the v2.4 source-bound target-blind builder shell."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
builder = importlib.import_module("build_target_blind_common_panel_v24")


def test_v24_defaults_bind_promoted_evidence_and_new_output_version() -> None:
    """The successor defaults to the promoted records and never overwrites v2.3."""
    args = builder.parse_args([])

    assert args.massive_reselection.name == (
        "massive_reselection_sensitivity_v21_recomputed_20260812.json"
    )
    assert args.availability_manifest.name == "b2_availability_manifest_v22.json"
    assert args.reconciliation_gate.name == "pit_reconciliation_gate_v21_20260812.json"
    assert args.output_root.as_posix().endswith("target_blind_v24_sourcebound_20260812")
    assert args.output_manifest_schema.name == (
        "target-blind-common-predictor-manifest-v24.schema.json"
    )


def test_v24_refuses_to_build_from_uncommitted_builder_sources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A manifest cannot claim a clean source commit while this builder is dirty."""

    class Completed:
        """Minimum completed-process record for the scoped Git status call."""

        stdout = "?? scripts/build_target_blind_common_panel_v24.py\n"

    monkeypatch.setattr(builder.subprocess, "run", lambda *args, **kwargs: Completed())

    with pytest.raises(ValueError, match="TARGET_BLIND_V24_BUILDER_SOURCE_UNCOMMITTED"):
        builder.require_committed_builder_source()


def test_v24_accepts_clean_scoped_builder_sources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unrelated worktree changes remain outside the narrow source guard."""

    class Completed:
        """Minimum completed-process record for a clean scoped Git status call."""

        stdout = ""

    monkeypatch.setattr(builder.subprocess, "run", lambda *args, **kwargs: Completed())

    builder.require_committed_builder_source()


def test_v24_source_guard_covers_runtime_schemas_and_all_new_code() -> None:
    """Schema/hash validation cannot be separated from its committed runtime sources."""
    expected = {
        "pyproject.toml",
        "uv.lock",
        "scripts/build_target_blind_common_panel_v22.py",
        "scripts/build_target_blind_common_panel_v24.py",
        "src/mds650/phase6.py",
        "src/mds650/provider_timing_v21.py",
        "src/mds650/target_blind_panel_v22.py",
        "src/mds650/target_blind_provenance_v23.py",
        "src/mds650/target_blind_sourcebound_v24.py",
        "specs/001-pit-options-rv30/contracts/b2-availability-manifest-v22.schema.json",
        "specs/001-pit-options-rv30/contracts/pit-reconciliation-gate-v21.schema.json",
        "specs/001-pit-options-rv30/contracts/target-blind-common-predictor-manifest-v24.schema.json",
    }

    assert expected <= set(builder._BUILDER_SOURCE_PATHS)


def test_v24_source_commit_is_scoped_to_runtime_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Artifact-only commits cannot change the source identity of a replay."""
    calls: list[list[str]] = []

    class Completed:
        """Minimum completed-process record for the local Git history call."""

        stdout = "a" * 40 + "\n"

    def fake_run(args: list[str], **_: object) -> Completed:
        calls.append(args)
        return Completed()

    monkeypatch.setattr(builder.subprocess, "run", fake_run)

    assert builder.source_commit_v24() == "a" * 40
    assert calls == [["git", "log", "-1", "--format=%H", "--", *builder._BUILDER_SOURCE_PATHS]]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows drive-letter path semantics")
def test_v24_rejects_forbidden_path_before_preflight_or_predictor_read(tmp_path: Path) -> None:
    """Outcome-like paths are rejected before the builder can inspect any input bytes."""
    forbidden_path = tmp_path / "target_payload.parquet"

    with pytest.raises(ValueError, match="TARGET_BLIND_V24_FORBIDDEN_INPUT_PATH:origins"):
        builder.main(["--origins", str(forbidden_path)])
