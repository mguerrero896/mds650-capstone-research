"""Regression contract for byte-bound research evidence line endings."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_byte_bound_evidence_has_explicit_cross_worktree_eol_contract() -> None:
    """A new Windows worktree must reproduce the registered file hashes."""
    observed = set(
        (ROOT / ".gitattributes").read_text(encoding="utf-8").splitlines()
    )
    required = {
        "*.json text eol=lf",
        "/artifacts/provider_timing_v21/** text eol=lf",
        (
            "/artifacts/provider_timing_v21/"
            "massive_reselection_sensitivity_v21_recomputed_20260812.json "
            "text eol=crlf"
        ),
        (
            "/artifacts/provider_timing_v22/b2_availability_manifest_v22.json "
            "text eol=crlf"
        ),
        (
            "/artifacts/target_blind_v23_sourcebound_20260812/** "
            "text eol=crlf"
        ),
        (
            "/artifacts/target_blind_v24_sourcebound_20260812/"
            "target_blind_common_predictor_manifest_v24.json text eol=crlf"
        ),
        (
            "/artifacts/corrected_development_v1/"
            "source_coverage_ledger.json text eol=crlf"
        ),
    }
    assert required <= observed
