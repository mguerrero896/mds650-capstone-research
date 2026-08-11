"""Contracts for the offline canonical-validation reproduction entrypoint."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "artifacts" / "canonical_validation_v1" / "reproduce.ps1"


def test_reproduction_script_fails_fast_and_reuses_frozen_evidence() -> None:
    """Native failures must stop before a later step can mask them."""
    source = SCRIPT.read_text(encoding="utf-8")

    assert "$ErrorActionPreference = 'Stop'" in source
    assert "$PSNativeCommandUseErrorActionPreference = $true" in source
    assert "audit_phase6_source_recovery.py" in source
    assert source.count("run_canonical_validation.py") == 2
    assert "report_canonical_validation.py" in source
    assert "build_canonical_evidence_index.py" in source
    assert "--no-create-refs" not in source
