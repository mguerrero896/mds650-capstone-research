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

import json
import re
from functools import cache
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CONTRACT_DIR = REPO / "docs" / "rp2_v3"
SCORECARD_FIELDS = REPO / "configs" / "rp2_v3_scorecard_fields.json"

#: A scorecard field as the schema document declares it: a leading table cell in backticks.
DECLARED_FIELD = re.compile(r"^\| `([a-z0-9_]+)` \|", re.MULTILINE)

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


def test_scorecard_schema_declares_every_required_group() -> None:
    schema = _read("SCORECARD_SCHEMA.md")
    missing_groups = [group for group in SCORECARD_GROUPS if group not in schema]
    assert not missing_groups, f"SCORECARD_SCHEMA.md is missing metric groups: {missing_groups}"


def test_the_required_scorecard_fields_are_machine_readable() -> None:
    """The rebuild runner and this test must read one list, not two copies of one.

    A hand-maintained subset in the test is what let the earlier version pass while
    `provider_failures`, `model_config_sha256` and `artifact_sha256` could be deleted from
    the schema unnoticed.
    """

    assert SCORECARD_FIELDS.is_file(), f"missing machine-readable field list: {SCORECARD_FIELDS}"
    declared = json.loads(SCORECARD_FIELDS.read_text(encoding="utf-8"))
    assert declared["schema_version"].startswith("rp2-v3-scorecard-fields-")
    assert set(declared["groups"]) == {group.lower() for group in SCORECARD_GROUPS}
    assert all(fields for fields in declared["groups"].values()), "no group may be empty"


def test_every_required_field_and_only_those_appear_in_the_schema_document() -> None:
    """Both directions, so neither the document nor the field list can drift alone."""

    declared = json.loads(SCORECARD_FIELDS.read_text(encoding="utf-8"))
    required = {field for fields in declared["groups"].values() for field in fields}
    documented = set(DECLARED_FIELD.findall(_read("SCORECARD_SCHEMA.md")))
    assert not required - documented, (
        f"required fields the schema document does not declare: {sorted(required - documented)}"
    )
    assert not documented - required, (
        f"schema document declares fields nothing requires: {sorted(documented - required)}"
    )


def test_every_nested_contrast_carries_its_own_common_mask_hash() -> None:
    """An equal row count is not an equal mask.

    Two contrasts can score the same number of rows and not the same rows. Only a hash per
    contrast proves that a nested pair was compared on identical evidence.
    """

    declared = json.loads(SCORECARD_FIELDS.read_text(encoding="utf-8"))
    assert "common_mask_sha256" in declared["groups"]["forecast"], (
        "the forecast group must carry a per-contrast common_mask_sha256"
    )
    schema = _read("SCORECARD_SCHEMA.md")
    assert "per contrast" in schema, (
        "the schema document must state that the mask hash is recorded per contrast"
    )


def test_the_baseline_instruction_advances_with_each_merged_gate() -> None:
    """`origin/main` stopped being 8c01b0a the moment the first gate merged.

    The commit stays on the record as the provenance of the RP2-v2 baseline; it must not
    stay as a precondition every later gate would fail.
    """

    agents = (REPO / "AGENTS.md").read_text(encoding="utf-8")
    assert "debe devolver 8c01b0a0" not in agents, (
        "AGENTS.md still asserts a fixed origin/main tip; later gates branch from the "
        "current remote tip, not from the RP2-v2 baseline commit"
    )
    assert "8c01b0a" in agents, "the RP2-v2 baseline commit stays on the record"


def test_superseded_results_supersedes_rather_than_deletes() -> None:
    superseded = _read("SUPERSEDED_RESULTS.md")
    assert "SUPERSEDED_BY_RP2_V3" in superseded, (
        "superseded results carry an explicit marker, not an implicit one"
    )
    assert "never deleted" in superseded.lower(), (
        "the retention rule must be stated: a superseded artifact is retained, not removed"
    )
