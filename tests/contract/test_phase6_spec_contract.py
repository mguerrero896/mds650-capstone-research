"""Contract checks for the owner-approved Phase 6 specification."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_phase6_design_is_present_in_all_spec_kit_artifacts() -> None:
    """Require the approved replication contract in every governing artifact."""
    required = {
        "specs/001-pit-options-rv30/spec.md": "Phase 6 — Mechanism-Aware Historical Replication",
        "specs/001-pit-options-rv30/plan.md": "Phase 6: Mechanism-Aware Historical Replication",
        "specs/001-pit-options-rv30/tasks.md": "Phase 12: Mechanism-Aware Historical Replication",
        "specs/001-pit-options-rv30/checklists/requirements.md": (
            "Phase 6 Mechanism-Aware Replication Requirements"
        ),
        "docs/methodology_decisions.md": "Mechanism-aware replication authority",
    }
    for relative, marker in required.items():
        assert marker in (ROOT / relative).read_text(encoding="utf-8"), relative


def test_phase6_spec_preserves_phase5_and_registered_outcomes() -> None:
    """Require immutable Phase 5 evidence and honest sign reporting."""
    spec = (ROOT / "specs/001-pit-options-rv30/spec.md").read_text(encoding="utf-8")
    assert "Phase 5 evidence MUST remain immutable" in spec
    assert "positive, negative and null" in spec
    assert "GLOBAL_EDGE_NOT_CONFIRMED" in spec
