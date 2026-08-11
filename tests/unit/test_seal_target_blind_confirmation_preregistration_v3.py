"""Tests for the target-blind preregistration v3 sealing command."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sealer = importlib.import_module("seal_target_blind_confirmation_preregistration_v3")


def test_v3_sealer_defaults_to_sourcebound_inputs_and_output() -> None:
    """The command cannot accidentally select the retained v2.2 panel."""
    args = sealer.parse_args([])

    assert args.panel_manifest.as_posix().endswith(
        "target_blind_v23_sourcebound_20260812/target_blind_common_predictor_manifest_v23.json"
    )
    assert args.template_preregistration.as_posix().endswith(
        "target_blind_v22/next_confirmation_preregistration_v2.json"
    )
    assert args.output.as_posix().endswith(
        "target_blind_v23_sourcebound_20260812/next_confirmation_preregistration_v3.json"
    )


def test_v3_sealer_refuses_uncommitted_runtime_sources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A seal cannot claim a commit that omits modified generator code."""

    class Completed:
        """Minimum completed-process record for a dirty source status."""

        stdout = " M src/mds650/target_blind_preregistration_v3.py\n"

    monkeypatch.setattr(sealer.subprocess, "run", lambda *args, **kwargs: Completed())

    with pytest.raises(ValueError, match="TARGET_BLIND_V3_SEALER_SOURCE_UNCOMMITTED"):
        sealer.require_committed_sealer_source()


def test_v3_sealer_writer_retains_identical_bytes_and_rejects_drift(tmp_path: Path) -> None:
    """The v3 registry output is immutable under deterministic replays."""
    output = tmp_path / "preregistration.json"

    sealer.write_if_new_or_identical(output, b"same")
    sealer.write_if_new_or_identical(output, b"same")

    with pytest.raises(FileExistsError, match="TARGET_BLIND_V3_OUTPUT_EXISTS_WITH_DIFFERENT_BYTES"):
        sealer.write_if_new_or_identical(output, b"different")
    assert output.read_bytes() == b"same"
