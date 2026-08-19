"""RP2-v3 freezes what it is testing before it changes what it measures.

The failure this guards against is not hypothetical: a research programme that edits
its own target, loss, model family or comparison direction while the results come in
can always find a favourable reading. The contract below is written once, in Git, and
every later gate is judged against it rather than against whatever the code then does.

The documents are checked for content, not for existence alone. A `RESEARCH_CONTRACT.md`
that exists but no longer names QLIKE as the primary loss is worse than a missing one,
because it reads as a frozen contract while having quietly moved.
"""

from __future__ import annotations

from functools import cache
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CONTRACT_DIR = REPO / "docs" / "rp2_v3"

REQUIRED_DOCUMENTS: tuple[str, ...] = (
    "RP2_V3_MASTER_PLAN.md",
    "RESEARCH_CONTRACT.md",
    "IMPLEMENTATION_STATUS.md",
    "SCORECARD_SCHEMA.md",
    "SUPERSEDED_RESULTS.md",
)

#: The frozen specification, verbatim from the master plan's step 0.
FROZEN_SPECIFICATION: tuple[str, ...] = (
    "Primary target: RV30",
    "B0 vs B0+B1",
    "B0+B1 vs B0+B1+B2",
    "Primary loss:",
    "QLIKE",
    "Gamma GLM",
    "Ridge-log",
    "LightGBM-QLIKE",
    "Inference unit:",
    "Trading session",
    "Contemporaneous option-state snapshot",
    "Point-in-time option-flow activity",
    "No sealed confirmation cohort may be read during development.",
)

#: The twelve gate branches of the master plan's section 24, in their binding order.
GATE_BRANCHES: tuple[str, ...] = (
    "docs/rp2-v3-contract",
    "fix/rp2-v3-panel-contracts",
    "fix/rp2-v3-causal-b0",
    "feat/rp2-v3-contemporaneous-b1",
    "fix/rp2-v3-exact-clock-b2",
    "feat/rp2-v3-core-feature-registry",
    "feat/rp2-v3-fold-local-preprocessing",
    "feat/rp2-v3-qlike-models",
    "fix/rp2-v3-session-inference",
    "feat/rp2-v3-pipeline-runner",
    "db/rp2-v3-versioned-results",
    "results/rp2-v3-rebuild",
)

#: Every metric group the scorecard of section 12 must account for.
SCORECARD_GROUPS: tuple[str, ...] = ("Data", "B1", "B2", "Forecast", "Engineering")

#: Metrics whose absence would let a rebuild claim more than it measured.
SCORECARD_METRICS: tuple[str, ...] = (
    "common_evaluation_rows",
    "b1_core_coverage",
    "b1_median_quote_age_s",
    "b1_p95_quote_age_s",
    "b2_pit_violation_count",
    "b2_zero_dte_count",
    "qlike_b0",
    "qlike_b0_b1",
    "qlike_b0_b1_b2",
    "delta_b1",
    "delta_b2_given_b1",
    "mde",
    "feature_registry_sha256",
    "code_commit",
)


@cache
def _read(name: str) -> str:
    return (CONTRACT_DIR / name).read_text(encoding="utf-8")


def test_every_rp2_v3_contract_document_exists() -> None:
    missing = [name for name in REQUIRED_DOCUMENTS if not (CONTRACT_DIR / name).is_file()]
    assert not missing, f"RP2-v3 contract documents missing: {missing}"


def test_research_contract_freezes_the_primary_specification() -> None:
    contract = _read("RESEARCH_CONTRACT.md")
    missing = [line for line in FROZEN_SPECIFICATION if line not in contract]
    assert not missing, f"RESEARCH_CONTRACT.md no longer freezes: {missing}"


def test_research_contract_fixes_the_direction_of_both_deltas() -> None:
    """A sign convention decided after the numbers arrive is not a sign convention."""
    contract = _read("RESEARCH_CONTRACT.md")
    assert "L(B0) - L(B0+B1)" in contract, "delta_B1 must be defined as L(B0) - L(B0+B1)"
    assert "L(B0+B1) - L(B0+B1+B2)" in contract, (
        "delta_B2|B1 must be defined as L(B0+B1) - L(B0+B1+B2)"
    )
    assert "delta_B1 > 0" in contract and "delta_B2|B1 > 0" in contract, (
        "the contract must state that both deltas are expected to be positive"
    )


def test_implementation_status_tracks_the_twelve_gates_in_order() -> None:
    status = _read("IMPLEMENTATION_STATUS.md")
    positions = []
    for branch in GATE_BRANCHES:
        index = status.find(branch)
        assert index >= 0, f"IMPLEMENTATION_STATUS.md does not track gate {branch}"
        positions.append(index)
    assert positions == sorted(positions), (
        "the twelve gates must appear in the binding order of the master plan's section 24"
    )


def test_scorecard_schema_declares_every_required_metric() -> None:
    schema = _read("SCORECARD_SCHEMA.md")
    missing_groups = [group for group in SCORECARD_GROUPS if group not in schema]
    assert not missing_groups, f"SCORECARD_SCHEMA.md is missing metric groups: {missing_groups}"
    missing = [metric for metric in SCORECARD_METRICS if metric not in schema]
    assert not missing, f"SCORECARD_SCHEMA.md is missing metrics: {missing}"


def test_superseded_results_supersedes_rather_than_deletes() -> None:
    superseded = _read("SUPERSEDED_RESULTS.md")
    assert "SUPERSEDED_BY_RP2_V3" in superseded, (
        "superseded results carry an explicit marker, not an implicit one"
    )
    assert "never deleted" in superseded.lower(), (
        "the retention rule must be stated: a superseded artifact is retained, not removed"
    )
