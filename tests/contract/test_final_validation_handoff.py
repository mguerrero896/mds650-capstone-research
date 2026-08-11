"""Contract checks for the evidence-bound final validation handoff."""

from __future__ import annotations

from pathlib import Path

REPORT = Path("reports/CODEX_FINAL_VALIDATION_HANDOFF.md")


def test_handoff_covers_required_validation_domains() -> None:
    assert REPORT.exists(), "final validation handoff is missing"
    text = REPORT.read_text(encoding="utf-8")
    required = (
        "TARGET HORIZON",
        "FMP TIMESTAMP SEMANTICS",
        "UNUSUAL WHALES created_at",
        "COMMON HISTORY",
        "EARNINGS POINT-IN-TIME CONTRACT",
        "CANONICAL FORECAST-ORIGIN TABLE",
        "METHODOLOGY STATUS",
        "TECHNICAL EVIDENCE",
        "SAFE TO PROCEED TO METHOD FREEZE",
        "MODEL_FAMILY_DEPENDENT",
    )
    for heading in required:
        assert heading in text
    assert "GLOBAL_EDGE" not in text.split("Canonical conclusion", 1)[-1]
    assert "NO-GO for modeling" in text


def test_handoff_has_evidence_path_and_command_for_critical_findings() -> None:
    text = REPORT.read_text(encoding="utf-8")
    assert "Evidence:" in text
    assert "Command/test:" in text
    assert "Consequence:" in text
    assert "artifacts/canonical_validation_v1/contrasts.json" in text
    assert "artifacts/canonical_validation_v1/phase6/causal_audit.parquet" in text
    assert "artifacts/provider_audit/2026-07-20/provider_audit_manifest.json" in text
